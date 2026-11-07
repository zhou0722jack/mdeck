#!/usr/bin/env python3
"""Compile the production client route and exercise real filesystem state."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
def block(source, header):
    start = source.index(header)
    opening = source.index('{', start)
    end, depth = opening + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

client=(ROOT/'app/Madeira/SteamClient.swift').read_text().split('\n/// Global preferences',1)[0]
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
    var steamAppID:Int?; var steamClientAppID:Int?; var bigPicture:Bool?
    var workingDirectory:String?
    var resolution="1280x720"
}
final class LibraryModel {
    static let shared=LibraryModel();var entries:[LibraryEntry]=[]
    static var drive=URL(fileURLWithPath:"/tmp")
    static func inspect(_ url:URL)throws->(bits:Int,other:Int){(32,0)}
}
enum LibraryError:Error{case message(String)}
enum SteamRuntimeFiles { static let relativeRoot="Program Files (x86)/Steam" }
enum ExternalDrives { static var steamLibraries:[String]{[]} }
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
        let defaults=UserDefaults.standard
        let keys=[SteamClient.bigPictureKey,SteamClient.argumentsKey]
        let savedDefaults=keys.map{defaults.object(forKey:$0)}
        keys.forEach{defaults.removeObject(forKey:$0)}
        defer{for (key,value) in zip(keys,savedDefaults){defaults.set(value,forKey:key)}}
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
        precondition(present.arguments.contains("-gamepadui"))
        var original=LibraryEntry(title:"Fixture game",relativePath:"Games/Fixture",bits:64)
        original.steamAppID=570;original.arguments="-novid -language schinese"
        original.resolution="1920x1080";original.workingDirectory="C:\\Games\\Fixture"
        LibraryModel.shared.entries=[original]
        let game=SteamClient.entry(install:false,appID:570)
        precondition(game.steamClientAppID==570&&game.steamAppID==nil&&game.arguments.contains("-applaunch 570 -novid -language schinese"))
        precondition(game.title==original.title&&game.resolution==original.resolution&&game.workingDirectory==nil)
        precondition(!SteamClient.entry(install:false).arguments.contains("-applaunch"))
        defaults.set(false,forKey:SteamClient.bigPictureKey)
        precondition(!SteamClient.entry(install:false).arguments.contains("-gamepadui"))
        let installing=SteamClient.entry(install:true,appID:570)
        SteamClient.configureSession(installing)
        precondition(String(cString:getenv("MADEIRA_CHILD_ARGS")).contains("-applaunch 570 -novid"))
        SteamClient.configureSession(SteamClient.entry(install:false))
        precondition(!String(cString:getenv("MADEIRA_CHILD_ARGS")).contains("-applaunch"))
        precondition(!String(cString:getenv("MADEIRA_CHILD_ARGS")).contains("-novid"))
        defaults.set(#"-language schinese "a path with -bigpicture inside" -applaunch 999 "-bigpicture""#,forKey:SteamClient.argumentsKey)
        let clean=SteamClient.entry(install:false).arguments
        precondition(clean.contains(#""a path with -bigpicture inside""#) && !clean.contains("999") && !clean.contains(#""-bigpicture""#))
        defaults.removeObject(forKey:SteamClient.argumentsKey)
        LibraryModel.shared.entries=[]
        try SteamClient.registerLibraries()
        let vdf=try Data(contentsOf:folder.appendingPathComponent("config/libraryfolders.vdf"))
        var parser=try SteamKeyValues(vdf)
        let registered=try parser.read()
        precondition(registered["libraryfolders"]?.fields.count==2)
        // A native content download's production manifest is discovered by
        // mdeck, while the interactive client's actual VDF lists that library.
        let downloaded=root.appendingPathComponent(SteamRuntimeFiles.relativeRoot+"/steamapps")
        try fm.createDirectory(at:downloaded.appendingPathComponent("common/Fixture"),withIntermediateDirectories:true)
        try AppManifestWriter.writeManifest(appID:4242,name:"Downloaded fixture",installDir:"Fixture",buildID:7,steamID:0,
            steamAppsPath:downloaded.path,installedDepots:[.init(depotID:4243,manifestGID:123,size:20)])
        let clientApps=folder.appendingPathComponent("steamapps")
        try AppManifestWriter.writeManifest(appID:4244,name:"Client fixture",installDir:"Client",buildID:8,steamID:0,
            steamAppsPath:clientApps.path,installedDepots:[.init(depotID:4245,manifestGID:456,size:30)])
        try SteamClient.registerLibraries()
        let discovered=MadeiraDock.games(drive:root)
        precondition(Set(discovered.map(\.id))==[4242,4244]&&discovered.allSatisfy(\.installed))
        let manifest=try Data(contentsOf:downloaded.appendingPathComponent("appmanifest_4242.acf"))
        var manifestParser=try SteamKeyValues(manifest)
        let installState=try manifestParser.read()["AppState"]
        precondition(installState?["InstalledDepots"]?["4243"]?["manifest"]?.string=="123")
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
        print("PASS: exact client routing, global Big Picture and quoted arguments, game display profile and flags, installer/update handoff, stale request isolation, real VDF registration, status and cancellation")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-client-route-') as tmp:
    folder=Path(tmp)
    storage=(ROOT/'app/Madeira/ExternalStorage.swift').read_text()
    storage=storage[storage.index('enum ExternalStorageError:'):storage.index('enum ExternalInstallTarget')]
    # Real path/VDF implementation, not a fake success for registration.
    keyvalues=(ROOT/'app/Madeira/SteamKeyValues.swift').read_text()
    dock=(ROOT/'app/Madeira/MadeiraDock.swift').read_text()
    discovery=block(dock,'struct DockGame:')+'\nenum MadeiraDock {\n'
    for method in ['static func validAppID(', 'static func validFolderName(', 'static func game(manifest',
                   'static func depots(manifest', 'static func games(drive:', 'static func steamLibraries(drive:', 'static func libraryRelative(']:
        discovery+=block(dock,method)+'\n'
    discovery+='}\n'
    writer=(ROOT/'app/Madeira/SwiftSteam/Install/AppManifestWriter.swift').read_text()
    (folder/'Client.swift').write_text(client+'\n'+status+'\n'+storage+'\n'+keyvalues+'\n'+discovery+'\n'+writer)
    (folder/'Check.swift').write_text(fixture)
    subprocess.run(['xcrun','swiftc','-parse-as-library',str(folder/'Client.swift'),str(folder/'Check.swift'),'-o',str(folder/'check')],check=True)
    subprocess.run([str(folder/'check')],check=True)
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    subprocess.run(['xcrun','swiftc','-typecheck','-sdk',sdk,'-target','arm64-apple-ios18.0',str(folder/'Client.swift'),str(folder/'Check.swift')],check=True)
print('No Steam/installer execution or IPA build.')
