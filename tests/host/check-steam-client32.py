#!/usr/bin/env python3
"""Execute Win32 client preparation with synthetic and optional official archives; no Wine."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[2]
APP=ROOT/'app/Madeira'
parser=argparse.ArgumentParser()
parser.add_argument('--official-packages',type=Path)
args=parser.parse_args()
env=os.environ.copy()
if not env.get('DEVELOPER_DIR') and Path('/Applications/Xcode-beta.app/Contents/Developer').exists():
    env['DEVELOPER_DIR']='/Applications/Xcode-beta.app/Contents/Developer'

def block(source,header):
    start=source.index(header);at=source.index('{',start);depth=1;end=at+1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]

def pe(machine,magic):
    data=bytearray(512);data[:2]=b'MZ';struct.pack_into('<I',data,60,128)
    data[128:132]=b'PE\0\0';struct.pack_into('<H',data,132,machine);struct.pack_into('<H',data,152,magic)
    return bytes(data)

source=(APP/'SteamClient32Bootstrap.swift').read_text()
project=(ROOT/'app/Madeira.xcodeproj/project.pbxproj').read_text()
assert 'SteamClient32Bootstrap.swift in Sources' in project
assert 'delegate: SteamRuntimeRedirects()' in source
assert 'guard selected == architecture' in (APP/'SteamClient.swift').read_text()
assert 'case x86 = "32", x64 = "64"' in (APP/'SteamClient.swift').read_text()
with tempfile.TemporaryDirectory(prefix='mdeck-client32-') as directory:
    folder=Path(directory)
    critical=['steam.exe','steamclient.dll','steamui.dll','bin/cef/cef.win7/steamwebhelper.exe',
              'bin/cef/cef.win7/libcef.dll','bin/cef/cef.win7/chrome_elf.dll']
    for name,files in [('good',[(p,pe(0x14c,0x10b)) for p in critical]),
                       ('wrong',[(p,pe(0x8664,0x20b)) for p in critical]),
                       ('traversal',[('../escape.exe',b'x')]),('protected',[('config/loginusers.vdf',b'x')])]:
        with zipfile.ZipFile(folder/(name+'.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
            for path,data in files:archive.writestr(path,data)
    swift=r'''
import Foundation
import CryptoKit
func wine_process_is_running()->Int32{0}
func wineserver_is_running()->Int32{0}
func madeira_seed_prefix_if_needed(_ path:String){}
@main struct Check {
    static func reject(_ action:()throws->Void){do{try action();fatalError("invalid accepted")}catch{}}
    static func main()async throws{
        let fm=FileManager.default,root=URL(fileURLWithPath:CommandLine.arguments[1])
        func unpack(_ name:String,_ stage:URL)throws->[String:String]{
            let archive=try Data(contentsOf:root.appendingPathComponent(name+".zip"))
            let p=SteamRuntimeFiles.Package(file:name,bytes:archive.count,sha256:SteamClient32Bootstrap.digest(archive))
            var names=Set<String>(),hashes:[String:String]=[:]
            try SteamClient32Bootstrap.unpack(archive,package:p,into:stage,names:&names,hashes:&hashes)
            return hashes
        }
        let drive=root.appendingPathComponent("drive"),stage=root.appendingPathComponent("stage")
        try fm.createDirectory(at:drive,withIntermediateDirectories:true)
        let legacy=drive.appendingPathComponent("Program Files/Steam Client/config/fixture.txt")
        try fm.createDirectory(at:legacy.deletingLastPathComponent(),withIntermediateDirectories:true)
        let preserved=Data("Win64 account/game fixture retained".utf8);try preserved.write(to:legacy)
        var hashes=try unpack("good",stage)
        try SteamClient32Bootstrap.activate(stage:stage,drive:drive,hashes:hashes)
        precondition(SteamClient32Bootstrap.ready(drive:drive))
        let installed=drive.appendingPathComponent(SteamClient32Bootstrap.directory)
        precondition(try Data(contentsOf:legacy)==preserved)
        try await SteamClient32Bootstrap.prepare(drive:drive){_,_ in fatalError("cached install downloaded again")}
        let other=root.appendingPathComponent("other-stage");let otherHashes=try unpack("good",other)
        reject{try SteamClient32Bootstrap.activate(stage:other,drive:drive,hashes:otherHashes)}
        precondition(SteamClient32Bootstrap.ready(drive:drive))
        try Data("corrupt".utf8).write(to:installed.appendingPathComponent("steam.exe"))
        precondition(!SteamClient32Bootstrap.ready(drive:drive))
        reject{try SteamClient32Bootstrap.validate(folder:installed,expected:hashes)}
        let wrong=root.appendingPathComponent("wrong-stage");let wrongHashes=try unpack("wrong",wrong)
        reject{try SteamClient32Bootstrap.validate(folder:wrong,expected:wrongHashes)}
        for name in ["traversal","protected"]{reject{_ = try unpack(name,root.appendingPathComponent(name+"-stage"))}}
        let cancelledDrive=root.appendingPathComponent("cancelled-drive")
        let task=Task{
            withUnsafeCurrentTask{$0?.cancel()}
            do{try SteamClient32Bootstrap.activate(stage:other,drive:cancelledDrive,hashes:otherHashes);fatalError("cancelled activation")}
            catch is CancellationError{}catch{fatalError("wrong cancellation error")}
        };await task.value
        precondition(!fm.fileExists(atPath:cancelledDrive.path))
        print("PASS: PE32 client/CEF, pinned archive hashes, complete activation, cached reuse, wrong-arch/corrupt/traversal/protected/conflict/cancellation rejection; Win64 files preserved")
        if CommandLine.arguments.count>2{
            let packages=URL(fileURLWithPath:CommandLine.arguments[2]),actual=root.appendingPathComponent("official-stage")
            var names=Set<String>();hashes=[:]
            for p in SteamClient32Bootstrap.packages{
                let archive=try Data(contentsOf:packages.appendingPathComponent(p.file),options:.mappedIfSafe)
                do { try SteamClient32Bootstrap.unpack(archive,package:p,into:actual,names:&names,hashes:&hashes) }
                catch { fputs("FAILED official package: \(p.file): \(error)\n",stderr);throw error }
            }
            let officialDrive=root.appendingPathComponent("official-drive")
            try SteamClient32Bootstrap.activate(stage:actual,drive:officialDrive,hashes:hashes)
            precondition(SteamClient32Bootstrap.ready(drive:officialDrive))
            print("PASS: all 19 actual Valve archives checked/extracted with production code; matching Steam, steamui, steamclient, WebHelper, libcef and chrome_elf are i386")
        }
    }
}
'''
    # Swift's precondition does not accept a throwing autoclosure.
    swift=swift.replace('precondition(try Data(contentsOf:legacy)==preserved)',
                        'let legacyData=try Data(contentsOf:legacy);precondition(legacyData==preserved)')
    main=folder/'Check.swift';main.write_text(swift)
    inputs=[APP/'SteamClient32Bootstrap.swift',APP/'SteamRuntime.swift',APP/'SteamKeyValues.swift',APP/'Localization.swift',main]
    binary=folder/'check'
    subprocess.run(['xcrun','swiftc','-parse-as-library',*[str(p)for p in inputs],'-o',str(binary)],env=env,check=True)
    command=[str(binary),str(folder)]
    if args.official_packages:command.append(str(args.official_packages.resolve()))
    subprocess.run(command,env=env,check=True,timeout=180)
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],env=env,text=True).strip()
    subprocess.run(['xcrun','swiftc','-typecheck','-sdk',sdk,'-target','arm64-apple-ios18.0',*[str(p)for p in inputs]],env=env,check=True)
    print('PASS: production Win32 preparation typechecks against arm64/iOS SDK')
    library=(APP/'Library.swift').read_text()
    actions=block(library,'    var deckSteamActions:')
    selector=block(library,'    private func steamArchitectureButton(')
    assert 'Text("Experimental feature")' in actions
    assert 'steamArchitecture == SteamClient.Architecture.x64.rawValue' in actions
    assert 'architecture == .x64 ? palette.muted : palette.text' in selector
    assert 'steamArchitecture = architecture.rawValue' in selector and '.disabled(' not in selector
    assert 'steamLaunchPreparation.presented' in actions
    design=(APP/'DeckDesign.swift').read_text()
    ui=folder/'UI.swift'
    ui.write_text(r'''
import SwiftUI
func L(_ text:String)->String{text}
struct LibraryEntry{}
enum SteamClient {
    enum Architecture:String{case x86="32",x64="64"}
    static let installed=true
    static func entry(install:Bool)->LibraryEntry{LibraryEntry()}
}
enum Page{case steam}
struct DeckSettingsRoute{let page:Page}
class LaunchState:ObservableObject{@Published var launching=false;@Published var current:UUID?}
class PreparationState:ObservableObject{@Published var presented=false}
@MainActor class DeckAppearance{static let shared=DeckAppearance();var animations=true}
private struct PaletteKey:EnvironmentKey{static let defaultValue=DeckPalette()}
extension EnvironmentValues{var deckPalette:DeckPalette{get{self[PaletteKey.self]}set{self[PaletteKey.self]=newValue}}}
''' + block(design,'struct DeckPalette {')+'\n'+block(design,'struct DeckButtonStyle:')+r'''
struct Check:View {
    let palette=DeckPalette()
    @State var steamArchitecture="32"
    @State var deckSettingsPage:DeckSettingsRoute?
    @ObservedObject var model=LaunchState()
    @ObservedObject var steamLaunchPreparation=PreparationState()
    var play:(LibraryEntry)->Void={_ in}
    var body:some View{deckSteamActions}
''' + actions+'\n'+selector+'\n}\n')
    subprocess.run(['xcrun','swiftc','-typecheck','-sdk',sdk,'-target','arm64-apple-ios18.0',str(ui)],env=env,check=True)
    print('PASS: actual SwiftUI actions/selector and button style typecheck; gray x64 remains clickable and shows the experimental hint below launch')
print('No Steam/Wine execution or IPA build; real-device startup remains UNRUN.')
