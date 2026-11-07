#!/usr/bin/env python3
"""Compile the production client route and exercise real filesystem state."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
client=(ROOT/'app/Madeira/SteamClient.swift').read_text().split('\nstruct SteamClientView:',1)[0]
assert '["c:", "madeira", "installers", "steambootstrap.exe"]' in (ROOT/'app/Madeira/GameRecommendations.swift').read_text()
build=(ROOT/'tools/build-ipa.sh').read_text()
assert build.index('setup-llvm-mingw.sh') < build.index('build/steam-bootstrap/build.sh') < build.index('package-ipa.sh')
startup=(ROOT/'app/Madeira/DeckStartup.swift').read_text()
status=startup[startup.index('struct DeckSteamSetupStatus {'):startup.index('/// One continuous loading layer:')]
fixture=r'''
import Foundation
func L(_ value:String)->String{value}
func LF(_ value:String,_ args:CVarArg...)->String{String(format:value,arguments:args)}
struct LibraryEntry {
    var id=UUID(); var title:String; var relativePath:String; var bits:Int
    var launchMode="",arguments="",startServices=false
}
final class LibraryModel {
    static let shared=LibraryModel();var entries:[LibraryEntry]=[]
    static var drive=URL(fileURLWithPath:"/tmp")
    static func inspect(_ url:URL)throws->(bits:Int,other:Int){(32,0)}
}
enum LibraryError:Error{case message(String)}
final class LogStore{static let shared=LogStore();func log(_ value:String){}}
func wine_process_is_running()->Int32{0}
func wineserver_is_running()->Int32{0}
struct winios_steam_setup_progress{var step:Int32=4;var percent:Int32=63;var blocked:Int32=0}
func winios_steam_setup_snapshot(_ value:UnsafeMutablePointer<winios_steam_setup_progress>){}
func winios_steam_setup_reset(){}
@main struct Check {
    static func main()throws{
        let fm=FileManager.default
        let root=fm.temporaryDirectory.appendingPathComponent("mdeck-routing-"+UUID().uuidString)
        try fm.createDirectory(at:root,withIntermediateDirectories:true)
        defer{try? fm.removeItem(at:root)}
        LibraryModel.drive=root
        precondition(SteamClient.windowsExecutable=="C:\\Program Files\\Steam Client\\Steam.exe")
        let folder=root.appendingPathComponent(SteamClient.clientDirectory)
        try fm.createDirectory(at:folder,withIntermediateDirectories:true)
        // Dock's separate client cannot satisfy the requested client path.
        let dock=root.appendingPathComponent("Program Files (x86)/Steam")
        try fm.createDirectory(at:dock,withIntermediateDirectories:true)
        try Data([1]).write(to:dock.appendingPathComponent("steam.exe"))
        precondition(!SteamClient.installed)
        let missing=SteamClient.entry(install:!SteamClient.installed)
        precondition(missing.id==SteamClient.installerID&&missing.relativePath==SteamClient.bootstrapPath&&missing.launchMode=="direct")
        // A directory named Steam.exe is not a client executable.
        let upper=folder.appendingPathComponent("Steam.exe")
        try fm.createDirectory(at:upper,withIntermediateDirectories:true)
        precondition(!SteamClient.installed);try fm.removeItem(at:upper)
        try Data([1,2]).write(to:upper)
        precondition(SteamClient.installed&&SteamClient.executableURL?.lastPathComponent=="Steam.exe")
        let present=SteamClient.entry(install:!SteamClient.installed)
        precondition(present.id==SteamClient.clientID&&present.relativePath.hasSuffix("/Steam.exe"))
        precondition(present.arguments.contains("-no-cef-sandbox")&&present.arguments.contains("-cef-disable-gpu"))
        try fm.moveItem(at:upper,to:folder.appendingPathComponent("steam.exe"))
        precondition(SteamClient.installed&&SteamClient.entry(install:false).relativePath.hasSuffix("/steam.exe"))
        var custom=present;custom.arguments="-console -language schinese"
        LibraryModel.shared.entries=[custom]
        precondition(SteamClient.entry(install:false).arguments.hasPrefix(custom.arguments))
        try fm.removeItem(at:folder.appendingPathComponent("steam.exe"))
        let external=root.appendingPathComponent("outside.exe");try Data([1]).write(to:external)
        try fm.createSymbolicLink(at:upper,withDestinationURL:external)
        precondition(!SteamClient.installed);try fm.removeItem(at:upper)
        let setup=root.appendingPathComponent("Madeira/Installers")
        try fm.createDirectory(at:setup,withIntermediateDirectories:true)
        let state=setup.appendingPathComponent("SteamBootstrap.state")
        try Data("v1\nstage=installer\nerror=0\n".utf8).write(to:state)
        precondition(SteamClient.preparationStatus()?.percent==63)
        try Data("garbage".utf8).write(to:state)
        precondition(SteamClient.preparationStatus()==nil)
        SteamClient.cancelPreparation()
        precondition(fm.fileExists(atPath:setup.appendingPathComponent("SteamBootstrap.cancel").path))
        print("PASS: production route finds Steam.exe/steam.exe only in the requested folder, ignores Dock/directories/escaping symlinks, preserves extra options and adds required flags; status/cancel files work")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-client-route-') as tmp:
    folder=Path(tmp)
    (folder/'Client.swift').write_text(client+'\n'+status)
    (folder/'Check.swift').write_text(fixture)
    subprocess.run(['xcrun','swiftc','-parse-as-library',str(folder/'Client.swift'),str(folder/'Check.swift'),'-o',str(folder/'check')],check=True)
    subprocess.run([str(folder/'check')],check=True)
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    subprocess.run(['xcrun','swiftc','-typecheck','-sdk',sdk,'-target','arm64-apple-ios18.0',str(folder/'Client.swift'),str(folder/'Check.swift')],check=True)
print('No Steam/installer execution or IPA build.')
