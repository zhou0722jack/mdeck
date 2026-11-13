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
prefix_check=block(client,'    static func registerClientPath(')
assert 'LibraryModel.prefix' in prefix_check and 'drive.deletingLastPathComponent()' not in prefix_check
prepare=block(client,'    @MainActor static func prepareSelectedClient(')
assert prepare.index('try prepareWindowsPrefix()') < prepare.index('if selected == .x64')
assert 'static var prefix: URL { documents.appendingPathComponent("wine", isDirectory: true) }' in (ROOT/'app/Madeira/Library.swift').read_text()
assert '["c:", "madeira", "installers", "steambootstrap.exe"]' in (ROOT/'app/Madeira/GameRecommendations.swift').read_text()
build=(ROOT/'tools/build-ipa.sh').read_text()
assert build.index('setup-llvm-mingw.sh') < build.index('build/steam-bootstrap/build.sh') < build.index('package-ipa.sh')
startup=(ROOT/'app/Madeira/DeckStartup.swift').read_text()
status=startup[startup.index('struct DeckSteamSetupStatus {'):startup.index('/// One continuous loading layer:')]
fixture=r'''
import Foundation
import zlib
func L(_ value:String)->String{value}
func LF(_ value:String,_ args:CVarArg...)->String{String(format:value,arguments:args)}
struct LibraryEntry: Codable {
    var id=UUID(); var title:String; var relativePath:String; var bits:Int
    var launchMode="",arguments="",startServices=false
    var steamAppID:Int?; var steamClientAppID:Int?; var bigPicture:Bool?
    var workingDirectory:String?; var desktop:Bool?; var config:String?
    var steamUseGlobalSettings:Bool?; var steamSettingsPath:String?
    var windowsPath:String { "C:\\"+relativePath.replacingOccurrences(of:"/",with:"\\") }
    var resolution="1280x720"
    // The production LibraryEntry copy routine is executed with all fields by
    // check-frontend.py. This route fixture needs its resolution surface only.
    mutating func inheritRuntimeSettings(from source:LibraryEntry){resolution=source.resolution}
}
final class LibraryModel {
    static let shared=LibraryModel();var entries:[LibraryEntry]=[]
    var current:UUID?;var activeEntry:LibraryEntry?;var error:String?
    static var drive=URL(fileURLWithPath:"/tmp")
    static var prefix=URL(fileURLWithPath:"/tmp/unused-prefix")
    static func inspect(_ url:URL)throws->(bits:Int,other:Int){(try SteamClient64Bootstrap.is64BitExecutable(at:url) ? 64 : 32,0)}
}
enum LibraryError:Error{case message(String)}
// RUNTIME_UNPACKER
enum ExternalDrives { static var steamLibraries:[String]{[]} }
final class LogStore{static let shared=LogStore();var messages:[String]=[];func log(_ value:String){messages.append(value)}}
@MainActor final class DeckSteamLaunchPreparation {
    static let shared=DeckSteamLaunchPreparation()
    var awaitingClientImage = false
    func runtimeFailure(_ message:String,session:UUID){}
    func clientPreparationProgress(_ message:String,fraction:Double){}
}
var fixtureRunning:Int32=0
var fixtureSeedCalls=0
var fixtureSeedFails=false
func wine_process_is_running()->Int32{fixtureRunning}
func wineserver_is_running()->Int32{0}
func madeira_seed_prefix_if_needed(_ path:String){
    fixtureSeedCalls+=1
    if fixtureSeedFails{return}
    let prefix=URL(fileURLWithPath:path),fm=FileManager.default
    try! fm.createDirectory(at:prefix.appendingPathComponent("drive_c"),withIntermediateDirectories:true)
    for name in ["system.reg","user.reg"]{
        try! "WINE REGISTRY Version 2\n\n".write(to:prefix.appendingPathComponent(name),atomically:true,encoding:.utf8)
    }
    try! Data().write(to:prefix.appendingPathComponent(".update-timestamp"))
}
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
        let keys=[SteamClient.bigPictureKey,SteamClient.argumentsKey,SteamClient.architectureKey,SteamClientRuntimeFailure.runKey]
        let savedDefaults=keys.map{defaults.object(forKey:$0)}
        keys.forEach{defaults.removeObject(forKey:$0)}
        precondition(SteamClient.architecture == .x86)
        precondition(SteamClient.clientDirectory == SteamClient32Bootstrap.directory)
        precondition(SteamClient.launchArguments().contains("-cef-force-32bit"))
        precondition(SteamClient.launchArguments().contains("-nobootstrapperupdate"))
        // Build 29's first Win32 snapshot could create drive_c before Wine
        // ever seeded its hives. Initializing that prefix must retain the client.
        let fresh=root.appendingPathComponent("fresh-prefix")
        let freshDownloaded=fresh.appendingPathComponent("drive_c/Program Files/Steam Client32/fixture.bin")
        try fm.createDirectory(at:freshDownloaded.deletingLastPathComponent(),withIntermediateDirectories:true)
        try Data("download retained".utf8).write(to:freshDownloaded)
        LibraryModel.prefix=fresh
        try SteamClient.prepareWindowsPrefix()
        precondition(fixtureSeedCalls==1)
        precondition(fm.fileExists(atPath:fresh.appendingPathComponent("system.reg").path))
        let retained=try Data(contentsOf:freshDownloaded)
        precondition(retained==Data("download retained".utf8))
        try SteamClient.prepareWindowsPrefix();precondition(fixtureSeedCalls==1)
        fixtureRunning=1
        do{try SteamClient.prepareWindowsPrefix();preconditionFailure("running session accepted")}
        catch SteamRuntimeFiles.Failure.activeSession{}
        fixtureRunning=0
        // A damaged existing prefix must never be replaced by the full template.
        try fm.removeItem(at:fresh.appendingPathComponent("user.reg"))
        do{try SteamClient.prepareWindowsPrefix();preconditionFailure("missing stamped hive accepted")}
        catch SteamRuntimeFiles.Failure.prefixMissing{}
        precondition(fixtureSeedCalls==1)
        precondition(LogStore.shared.messages.contains{$0.contains("registry missing after initialization: user.reg")})
        let brokenHive=fresh.appendingPathComponent("user.reg")
        try Data("invalid registry fixture".utf8).write(to:brokenHive)
        do{try SteamClient.prepareWindowsPrefix();preconditionFailure("invalid hive header accepted")}
        catch SteamRuntimeFiles.Failure.prefixMissing{}
        let brokenPreserved=try Data(contentsOf:brokenHive)
        precondition(brokenPreserved==Data("invalid registry fixture".utf8) && fixtureSeedCalls==1)
        let unstamped=root.appendingPathComponent("unstamped-prefix")
        try fm.createDirectory(at:unstamped,withIntermediateDirectories:true)
        let userHive=unstamped.appendingPathComponent("user.reg")
        let userContent="WINE REGISTRY Version 2\n\n[Fixture]\n\"account\"=\"synthetic-preserved\"\n"
        try userContent.write(to:userHive,atomically:true,encoding:.utf8)
        LibraryModel.prefix=unstamped
        do{try SteamClient.prepareWindowsPrefix();preconditionFailure("existing unstamped hive overwritten")}
        catch SteamRuntimeFiles.Failure.conflict{}
        let preservedHive=try String(contentsOf:userHive,encoding:.utf8)
        precondition(preservedHive==userContent && fixtureSeedCalls==1)
        LibraryModel.prefix=root.appendingPathComponent("failed-seed")
        fixtureSeedFails=true
        do{try SteamClient.prepareWindowsPrefix();preconditionFailure("failed seeding accepted")}
        catch SteamRuntimeFiles.Failure.prefixMissing{}
        fixtureSeedFails=false
        precondition(fixtureSeedCalls==2)
        let registryPrefix=root.appendingPathComponent("registry-fixture")
        let registryDrive=registryPrefix.appendingPathComponent("drive_c")
        try fm.createDirectory(at:registryDrive,withIntermediateDirectories:true)
        let initialHive="WINE REGISTRY Version 2\n\n[Fixture] 1\n\"keep\"=\"unchanged\"\n"
        for name in ["system.reg","user.reg"] { try initialHive.write(to:registryPrefix.appendingPathComponent(name),atomically:true,encoding:.utf8) }
        try Data().write(to:registryPrefix.appendingPathComponent(".update-timestamp"))
        LibraryModel.prefix=registryPrefix
        LibraryModel.drive=registryDrive
        try SteamClient.registerClientPath()
        let x86Hive=try String(contentsOf:registryPrefix.appendingPathComponent("user.reg"),encoding:.utf8)
        precondition(x86Hive.contains("Steam Client32")&&x86Hive.contains("unchanged"))
        defaults.set("64",forKey:SteamClient.architectureKey)
        // A resolved C: drive can live outside the real prefix. Do not open
        // registry hives beside that drive, or seed its parent by mistake.
        let externalVolume=root.appendingPathComponent("external-volume")
        LibraryModel.drive=externalVolume.appendingPathComponent("windows-drive")
        try fm.createDirectory(at:LibraryModel.drive,withIntermediateDirectories:true)
        let foreignHive=externalVolume.appendingPathComponent("user.reg")
        try Data("unrelated volume".utf8).write(to:foreignHive)
        try SteamClient.registerClientPath()
        let foreign=try Data(contentsOf:foreignHive)
        precondition(foreign==Data("unrelated volume".utf8) && fixtureSeedCalls==2)
        let x64Hive=try String(contentsOf:registryPrefix.appendingPathComponent("user.reg"),encoding:.utf8)
        precondition(!x64Hive.contains("Steam Client32")&&x64Hive.contains("unchanged"))
        let registryFiles=try fm.contentsOfDirectory(atPath:registryPrefix.path)
        precondition(registryFiles.filter{$0.hasSuffix(".bak")}.count==4)
        print("PASS: fresh prefix initialized before client registration; downloaded client retained; failed/stamped/unstamped/running prefixes protected; redirected drive never supplies registry location")
        LibraryModel.drive=root
        defer{for (key,value) in zip(keys,savedDefaults){defaults.set(value,forKey:key)}}
        precondition(SteamClient.windowsExecutable=="C:\\Program Files\\Steam Client\\Steam.exe")
        let folder=root.appendingPathComponent(SteamClient.clientDirectory)
        try SteamClient.registerLibraries()
        precondition(!fm.fileExists(atPath:folder.path),"native downloads must not populate an uninstalled client's directory")
        try fm.createDirectory(at:folder,withIntermediateDirectories:true)
        // Reproduce Build 20: registration left only two VDFs in the target.
        let metadata=Data(#""libraryfolders" { "0" { "path" "C:\\Games" "keep" "original" } }"#.utf8)
        for section in ["config","steamapps"] {
            let directory=folder.appendingPathComponent(section)
            try fm.createDirectory(at:directory,withIntermediateDirectories:true)
            try metadata.write(to:directory.appendingPathComponent("libraryfolders.vdf"))
        }
        try SteamClient.stageInstallationLibraries()
        try SteamClient.prepareInstallationDirectory()
        let emptyTarget=try fm.contentsOfDirectory(atPath:folder.path)
        precondition(emptyTarget.isEmpty)
        let controllerFolder=root.appendingPathComponent("Madeira/Installers")
        let backups=try fm.contentsOfDirectory(at:controllerFolder,includingPropertiesForKeys:nil).filter{$0.lastPathComponent.hasPrefix("SteamClient-metadata-")}
        precondition(backups.count==1)
        for section in ["config","steamapps"] {
            let restored=try Data(contentsOf:backups[0].appendingPathComponent(section+"/libraryfolders.vdf"))
            precondition(restored==metadata)
            let staged=try Data(contentsOf:root.appendingPathComponent(SteamClient.stagedLibrariesPath(section)))
            var stagedParser=try SteamKeyValues(staged)
            let snapshot=try stagedParser.read()
            precondition(snapshot["libraryfolders"]?["0"]?["keep"]?.string=="original")
        }
        // Unknown/game files must never be removed to make NSIS happy.
        let preserved=folder.appendingPathComponent("steamapps/common/Fixture/game.bin")
        try fm.createDirectory(at:preserved.deletingLastPathComponent(),withIntermediateDirectories:true)
        let gameBytes=Data([9,8,7]);try gameBytes.write(to:preserved)
        var refused=false
        do { try SteamClient.prepareInstallationDirectory() } catch { refused=true }
        precondition(refused)
        let preservedBytes=try Data(contentsOf:preserved);precondition(preservedBytes==gameBytes)
        try fm.removeItem(at:folder.appendingPathComponent("steamapps"))
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
        precondition(present.arguments.contains("-language schinese"))
        precondition(present.arguments.contains("-gamepadui"))
        var original=LibraryEntry(title:"Fixture game",relativePath:"Games/Fixture",bits:64)
        original.steamAppID=570;original.arguments="-novid -language schinese"
        original.resolution="1920x1080";original.workingDirectory="C:\\Games\\Fixture"
        var shared=SteamClient.settingsEntry;shared.resolution="1600x900"
        shared.config="swap-min-mb = 1\nenv.MADEIRA_SWAP_COVERAGE = broad\ndonor-pool-mb = 4096\n"
        original.config="env.CUSTOM_GAME_SETTING = 1"
        LibraryModel.shared.entries=[original,shared]
        let game=SteamClient.entry(install:false,appID:570)
        precondition(game.steamClientAppID==570&&game.steamAppID==nil&&game.arguments.contains("-applaunch 570 -novid -language schinese"))
        precondition(game.title==original.title&&game.resolution==shared.resolution&&game.workingDirectory==nil)
        precondition(SteamClient.entry(install:false).resolution==shared.resolution)
        precondition(SteamClient.entry(install:true).resolution==shared.resolution)
        precondition(game.steamSettingsPath==SteamClient.windowsExecutable)
        precondition(game.config==nil && SteamClient.settingsEntry.config==nil)
        precondition(SteamClient.entry(install:true).config==nil)
        original.steamUseGlobalSettings=false
        LibraryModel.shared.entries=[original,shared]
        let customized=SteamClient.entry(install:false,appID:570)
        precondition(customized.resolution==original.resolution&&customized.steamSettingsPath==original.windowsPath)
        precondition(customized.config==original.config)
        precondition(SteamClient.entry(install:false).resolution==shared.resolution)
        original.steamUseGlobalSettings=true
        LibraryModel.shared.entries=[original,shared]
        try SteamClient.stageClientLaunch(SteamClient.entry(install:true,appID:570))
        let desktopData=try Data(contentsOf:root.appendingPathComponent("Madeira/Installers/SteamDesktop.command"))
        let desktopCommand=String(data:desktopData,encoding:.utf16LittleEndian)!
        precondition(desktopCommand.hasPrefix("\"C:\\windows\\system32\\explorer.exe\" /desktop=shell,1600x900 cmd /c "))
        precondition(desktopCommand.last=="\0")
        let services=try String(contentsOf:root.appendingPathComponent("madeira-games/"+SteamClient.clientID.uuidString+".bat"),encoding:.utf8)
        precondition(services.contains("services.exe")&&services.contains("Steam.exe")&&services.contains("-language schinese"))
        let session=SteamTuningFixture();session.entries=[original,shared];session.begin(game)
        session.saveCurrentProfile();precondition(session.saves.isEmpty)
        session.desiredResolution="1024x768";session.saveCurrentProfile()
        precondition(session.saves.count==1&&session.saves[0].steamUseGlobalSettings==false)
        precondition(session.saves[0].resolution=="1024x768")
        session.entries[0].steamUseGlobalSettings=false
        session.saveCurrentProfile()
        precondition(session.saves.count==2&&session.saves[1].steamUseGlobalSettings==false)
        precondition(!SteamClient.entry(install:false).arguments.contains("-applaunch"))
        defaults.set(false,forKey:SteamClient.bigPictureKey)
        precondition(!SteamClient.entry(install:false).arguments.contains("-gamepadui"))
        let installing=SteamClient.entry(install:true,appID:570)
        SteamClient.configureSession(installing)
        precondition(String(cString:getenv("MADEIRA_CHILD_ARGS")).contains("-applaunch 570 -novid"))
        SteamClient.configureSession(SteamClient.entry(install:false))
        precondition(!String(cString:getenv("MADEIRA_CHILD_ARGS")).contains("-applaunch"))
        precondition(!String(cString:getenv("MADEIRA_CHILD_ARGS")).contains("-novid"))
        var desktop=LibraryEntry(title:"Desktop",relativePath:"windows/explorer.exe",bits:64)
        desktop.desktop=true;desktop.resolution="1920x1080";desktop.steamClientAppID=570
        SteamClient.configureSession(desktop)
        let desktopArgs=String(cString:getenv("MADEIRA_CHILD_ARGS"))
        precondition(desktopArgs.hasPrefix("steam.exe ")&&desktopArgs.contains("-no-cef-sandbox"))
        precondition(desktopArgs.contains("-language schinese") && !desktopArgs.contains("-applaunch"))
        precondition(String(cString:getenv("MADEIRA_STEAM_AUTOINSTALL"))=="0")
        precondition(String(cString:getenv("MADEIRA_CHILD_ARGS_FIRST"))=="1")
        precondition(getenv("MADEIRA_STEAM_CONTROLLED_SETUP")==nil&&desktop.resolution=="1920x1080")
        setenv("MADEIRA_CHILD_ARGS","custom.exe -test",1)
        SteamClient.configureSession(original)
        precondition(String(cString:getenv("MADEIRA_CHILD_ARGS"))=="custom.exe -test")
        precondition(getenv("MADEIRA_CHILD_ARGS_FIRST")==nil)
        defaults.set(#"-language schinese "a path with -bigpicture inside" -applaunch 999 "-bigpicture""#,forKey:SteamClient.argumentsKey)
        let clean=SteamClient.entry(install:false).arguments
        precondition(clean.contains(#""a path with -bigpicture inside""#) && !clean.contains("999") && !clean.contains(#""-bigpicture""#))
        defaults.removeObject(forKey:SteamClient.argumentsKey)
        defaults.set("-console -language \"english\"",forKey:SteamClient.argumentsKey)
        let english=SteamClient.entry(install:false).arguments
        precondition(english.contains("-language \"english\"") && !english.contains("-language schinese"))
        defaults.removeObject(forKey:SteamClient.argumentsKey)
        defaults.set("-console -cef-force-32bit",forKey:SteamClient.argumentsKey)
        precondition(!SteamClient.entry(install:false).arguments.contains("-cef-force-32bit"))
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
        print("PASS: empty first-install target, Build 20 metadata backup, staged VDF preservation, game files protected; exact routing, flags, real VDF registration, status and cancellation")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-client-route-') as tmp:
    folder=Path(tmp)
    runtime=(ROOT/'app/Madeira/SteamRuntime.swift').read_text()
    runtime_fixture='enum SteamRuntimeFiles { static let relativeRoot="Program Files (x86)/Steam"\nstatic let windowsRoot="C:\\\\Program Files (x86)\\\\Steam"\nnonisolated(unsafe) static var lastConflict:String?\n'
    for signature in ['enum Failure:', 'struct UnpackLimits', 'static func validPath(', 'static func destination(', 'static func unpack(', 'static func stringValue(']:
        runtime_fixture+=block(runtime,signature)+'\n'
    registry_start=runtime.index('    static func registry(')
    runtime_fixture+=runtime[registry_start:runtime.index('\n    }',registry_start)+6]+'\n'
    runtime_fixture+='}\n'
    runtime_fixture+='enum SteamClient32Bootstrap { static let directory="Program Files/Steam Client32"\nstatic func ready(drive:URL)->Bool{false}\nstatic func prepare(drive:URL,progress:@escaping @Sendable (Int,Int) async -> Void)async throws{fatalError("32-bit preparation tested separately")}\n}\n'
    fixture=fixture.replace('// RUNTIME_UNPACKER',runtime_fixture)
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
    library=(ROOT/'app/Madeira/Library.swift').read_text()
    launch=r'''
extension LibraryEntry {
    var usesLaunchOptions:Bool{true}
    var runsInDesktop:Bool{launchMode=="desktop"}
    var isBatch:Bool{false}
    var programArguments:String{arguments}
    var launchWindowsPath:String{windowsPath}
    var launchDirectory:String{"C:\\Program Files\\Steam Client"}
    var launchArguments:String{launchCommand(parent:nil).args}
    static func gogSetup(for id:UUID)->String?{nil}
'''+block(library,'    var servicesScriptPath:')+'\n'+block(library,'    var servicesScript:')+'\n'+block(library,'    private func launchCommand(parent:')+'\n}\n'
    session=r'''
final class SteamTuningFixture {
    var activeEntry:LibraryEntry?;var current:UUID?;var entries:[LibraryEntry]=[]
    var initialSteamSessionProfile:Data?;var saves:[LibraryEntry]=[];var desiredResolution=""
    func sessionProfile(_ original:LibraryEntry)->LibraryEntry{var next=original;next.resolution=desiredResolution;return next}
    func save(_ entry:LibraryEntry){saves.append(entry)}
    func begin(_ entry:LibraryEntry){activeEntry=entry;current=entry.id;desiredResolution=entry.resolution;initialSteamSessionProfile=encodedSessionProfile(sessionProfile(entry))}
'''+block(library,'    private func encodedSessionProfile(')+'\n'+block(library,'    func saveCurrentProfile()')+'\n}\n'
    (folder/'Client.swift').write_text(client+'\n'+status+'\n'+storage+'\n'+keyvalues+'\n'+discovery+'\n'+writer+'\n'+session+'\n'+launch)
    (folder/'Check.swift').write_text(fixture)
    bootstrap=ROOT/'app/Madeira/SteamClient64Bootstrap.swift'
    runtime_failure=ROOT/'app/Madeira/SteamClientRuntimeFailure.swift'
    subprocess.run(['xcrun','swiftc','-parse-as-library',str(folder/'Client.swift'),str(bootstrap),str(runtime_failure),str(folder/'Check.swift'),'-o',str(folder/'check')],check=True)
    subprocess.run([str(folder/'check')],check=True)
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    subprocess.run(['xcrun','swiftc','-typecheck','-sdk',sdk,'-target','arm64-apple-ios18.0',str(folder/'Client.swift'),str(bootstrap),str(runtime_failure),str(folder/'Check.swift')],check=True)
print('No Steam/installer execution or IPA build.')
