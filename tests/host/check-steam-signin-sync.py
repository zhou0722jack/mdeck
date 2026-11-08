#!/usr/bin/env python3
"""Synthetic Windows-to-App authorization tests. Never reads a real Steam cache or token."""
from pathlib import Path
import base64
import json
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
sync = (APP / 'SteamClientSignInSync.swift').read_text()
native = (ROOT / 'build/crypto-unix/crypt32_unixlib_ios.c').read_text()
patch = ROOT / 'build/windows-runtime/patches/0003-steam-signin-sync.patch'


def block(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    end, depth = brace + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


rules = sync.split('#if canImport(UIKit)', 1)[0]
model = block(sync, '@MainActor final class SteamClientSignInSync: ObservableObject')
project = (ROOT / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
assert project.count('/* SteamClientSignInSync.swift in Sources */') == 2
assert 'SteamClientSignInSync.shared.start()' in (APP / 'MadeiraApp.swift').read_text()
assert 'SteamClientSignInSync.shared.beginSteamSession()' in (APP / 'ContentView.swift').read_text()
assert 'addObserver(forName: SteamSignIn.didChange' in (APP / 'SwiftSteam/SteamSignIn.swift').read_text()
assert 'SecItemUpdate' in (APP / 'SwiftSteam/Auth/SteamTokenStore.swift').read_text()
assert 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly' in sync
assert 'kSecAttrSynchronizable' not in sync
assert 'C:\\' not in rules  # no guessed cache decryption or hard-coded account data
assert 'GenerateAccessTokenForApp' not in sync, 'client refresh validation must use CM, not the web endpoint'
assert 'SteamSession(automaticallyReconnect: false)' in sync
assert sync.index('guard !windowsRunning else') < sync.index('try await cm.connectAndLogin(')
assert sync.index('await SteamOwnedLibrary.shared.prepareClientSignInVerification()') < sync.index('try await cm.connectAndLogin(')
assert sync.index('await cm.suspend()') < sync.index('guard SteamSignIn.store(')
assert 'deferWindowsLaunch' in (APP / 'ContentView.swift').read_text()
assert 'self.account(for: candidate) == account' in model and 'revision == attempt' in model
assert 'SteamSignIn.credentialsForDock()?.refreshToken == before' in model
assert 'FileManager.default.createFile' not in sync and 'setenv(' not in sync
for line in sync.splitlines():
    if any(x in line for x in ['SteamLog.event(', 'print(', 'LogStore.', 'NSLog(']):
        assert '\\(' not in line, 'authorization logs must contain no interpolated data'
library = (APP / 'SteamOwnedLibrary.swift').read_text()
refresh = block(library, '    func refreshLibrary(interactive:')
assert refresh.index('accountRevision == requestRevision') < refresh.index('owned = games')
assert 'accountRevision = UUID()' in block(library, '    private func signInChanged()')
assert 'if signedIn && libraryUpdated == nil' in block(library, '    func sessionChanged(active')
playtime = block(library, '    func refreshPlaytime()')
assert playtime.index('accountRevision == requestRevision') < playtime.index('playtime = parsed')

with tempfile.TemporaryDirectory(prefix='mdeck-signin-sync-') as temporary:
    temp = Path(temporary)
    rules_file = temp / 'Rules.swift'
    rules_file.write_text(rules)
    fixture = (ROOT / 'tests/host/fixtures/SteamSignInSyncCheck.swift').read_text()
    harness = temp / 'Checks.swift'
    account_fixture = r'''
struct SteamAppInfo { var appID: UInt32; var name: String; var installableOnWindows = true }
struct SteamOwnedGame {
    var name: String
    init(_ app: SteamAppInfo, ownedDLC: [UInt32: SteamAppInfo]) { name=app.name }
}
@MainActor final class AccountFetcherCheck {
    var first=true
    var waiting: CheckedContinuation<[SteamAppInfo],Never>?
    var ownedDLC:[SteamAppInfo]=[]
    func fetchOwnedApps() async throws -> [SteamAppInfo] {
        if first { first=false;return await withCheckedContinuation { waiting=$0 } }
        return [.init(appID:2,name:"new fixture")]
    }
}
@MainActor final class AccountSessionCheck { var logoffs=0;func logoff(){logoffs+=1} }
@MainActor final class AccountLibraryCheck {
    static let enabled=true,dlcEnabled=false
    var signedIn=true,inSession=false,refreshing=false
    var cachedAccount:String?="old_fixture"
    var accountRevision=UUID(),lastLibraryRefreshAttempt:Date?,libraryUpdated:Date?
    var owned:[SteamOwnedGame]=[],playtime:[Int:Int]=[:],downloads=[1:1],queue=[1],resumeAfterSession:Set<Int>=[1]
    let session=AccountSessionCheck(),fetcher=AccountFetcherCheck()
    var paused:[Int]=[],writes:[[String]]=[]
    static func accountKey(_ name:String?)->String?{name}
    func pause(_ id:Int){paused.append(id)}
    func clearCaches(){cachedAccount=nil}
    func writeCache(){writes.append(owned.map(\.name))}
    func refreshPlaytime() async {}
    func handleSessionError(_ error:Error,context:String,report:Bool){}
    func testAccountChanged(){signInChanged()}
''' + block(library, '    private func signInChanged()') + '\n' + refresh + '\n}\n'
    harness.write_text(fixture.replace('// PRODUCTION_MODEL', model).replace('// PRODUCTION_LIBRARY_ACCOUNT_TEST', account_fixture))
    dependencies = [APP / 'SteamKeyValues.swift', APP / 'SwiftSteam/Proto/SteamProtoMessages.swift',
                    APP / 'SwiftSteam/Core/SteamError.swift', APP / 'Localization.swift']
    binary = temp / 'check'
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library', str(rules_file), *map(str, dependencies), str(harness), '-o', str(binary)], check=True)
    subprocess.run([str(binary), str(temp / 'drive')], check=True)

    # Real UIKit/Security imports are typechecked, not replaced by the host fakes.
    ios_stubs = temp / 'IOSDependencies.swift'
    ios_stubs.write_text('''import Foundation
@MainActor final class LibraryModel { static let shared=LibraryModel();static var drive=URL(fileURLWithPath:"/tmp");var current:Int? }
func wine_process_is_running()->Int32{0}
func wineserver_is_running()->Int32{0}
enum SteamClient { static let clientDirectory="Program Files/Steam Client" }
enum SteamLog { static func event(_ value:String){}; static func trace(_ value:String){} }
@MainActor final class SteamOwnedLibrary {
    static let shared=SteamOwnedLibrary()
    func prepareClientSignInVerification() async {}
    func finishClientSignInVerification(imported:Bool){}
}
enum SteamConnectionState { case disconnected,authenticated }
@MainActor final class SteamSession {
    var steamID:UInt64=0;var connectionState=SteamConnectionState.disconnected
    init(automaticallyReconnect:Bool=true){}
    func connectAndLogin(credentialsOverride:(accountName:String,refreshToken:String)?=nil) async throws {}
    func suspend() async {}
}
enum SteamSignIn {
    static let didSignOut=Notification.Name("out"), didChange=Notification.Name("changed")
    static func flag(_ name:String,default value:Bool)->Bool{value}
    static func credentialsForDock()->(accountName:String,refreshToken:String)?{nil}
    static func store(accountName:String,refreshToken:String,accessToken:String)->Bool{true}
}
''')
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    subprocess.run(['xcrun', 'swiftc', '-typecheck', '-sdk', sdk, '-target', 'arm64-apple-ios18.0',
                    str(APP / 'SteamClientSignInSync.swift'), *map(str, dependencies),
                    str(APP / 'SwiftSteam/Auth/SteamAuthAPI.swift'), str(APP / 'SwiftSteam/Auth/SteamTokenStore.swift'), str(ios_stubs)], check=True)
    full_stubs = temp / 'IOSFullSigninDependencies.swift'
    full_stubs.write_text('''import Foundation
@MainActor final class LibraryModel { static let shared=LibraryModel();static var drive=URL(fileURLWithPath:"/tmp");var current:Int? }
func wine_process_is_running()->Int32{0}
func wineserver_is_running()->Int32{0}
enum SteamClient { static let clientDirectory="Program Files/Steam Client" }
enum MadeiraConfig { static func get(_ key:String)->String?{nil} }
enum SteamLog { static func event(_ value:String){}; static func trace(_ value:@autoclosure ()->String){} }
@MainActor final class SteamOwnedLibrary {
    static let shared=SteamOwnedLibrary()
    func prepareClientSignInVerification() async {}
    func finishClientSignInVerification(imported:Bool){}
}
''')
    actual_signin = [APP / 'SwiftSteam' / path for path in [
        'SteamSignIn.swift', 'SteamSignInView.swift', 'Auth/SteamAuthAPI.swift', 'Auth/SteamTokenStore.swift',
        'Auth/SteamQRAuth.swift', 'Auth/SteamCredentialAuth.swift', 'Helpers/SteamDevice.swift']]
    actual_cm = [APP / 'SwiftSteam/Core' / name for name in [
        'SteamSession.swift', 'SteamConnection.swift', 'SteamCMSession.swift', 'CMServerList.swift',
        'SteamProtocol.swift', 'SteamMessageCodec.swift', 'LicenseListBox.swift']]
    actual_cm.append(APP / 'SwiftSteam/Content/SteamLANPeer.swift')
    actual_cm.append(APP / 'SwiftSteam/Content/ContentDecryptor.swift')
    bridge_header = temp / 'SteamContentBridge.h'
    bridge_header.write_text('#include "' + str(APP / 'SwiftSteam/lzma_shim.h') + '"\n')
    subprocess.run(['xcrun', 'swiftc', '-typecheck', '-sdk', sdk, '-target', 'arm64-apple-ios18.0',
                    '-import-objc-header', str(bridge_header),
                    str(APP / 'SteamClientSignInSync.swift'), *map(str, dependencies),
                    *map(str, actual_signin), *map(str, actual_cm), str(full_stubs)], check=True)
    print('PASS: complete importer, actual CM transport/session, Keychain and sign-in UI typecheck together for iOS')

    # Execute the production primary Keychain writer against an in-memory
    # Security API. No real device/macOS Keychain item is read or changed.
    store_source = (APP / 'SwiftSteam/Auth/SteamTokenStore.swift').read_text().replace('import Security', 'import CoreFoundation')
    keychain = temp / 'Keychain.swift'
    keychain.write_text(r'''
import Foundation
import CoreFoundation
let kSecClass="class",kSecClassGenericPassword="password",kSecAttrService="service",kSecAttrAccount="account"
let kSecValueData="data",kSecAttrAccessible="accessible",kSecAttrAccessibleWhenUnlockedThisDeviceOnly="device"
let kSecReturnData="return",kSecMatchLimit="limit",kSecMatchLimitOne="one"
let errSecSuccess:Int32=0,errSecItemNotFound:Int32 = -25300
enum SecurityFixture { static var data:Data?;static var fail=false;static var deletes=0 }
enum SteamLog { static func trace(_ value:@autoclosure ()->String){} }
func SecItemUpdate(_ query:CFDictionary,_ attributes:CFDictionary)->Int32 {
    if SecurityFixture.fail{return -34018}
    guard SecurityFixture.data != nil else{return errSecItemNotFound}
    SecurityFixture.data=(attributes as NSDictionary)[kSecValueData] as? Data;return errSecSuccess
}
func SecItemAdd(_ query:CFDictionary,_ result:UnsafeMutablePointer<CFTypeRef?>?)->Int32 {
    if SecurityFixture.fail{return -34018}
    SecurityFixture.data=(query as NSDictionary)[kSecValueData] as? Data;return errSecSuccess
}
func SecItemCopyMatching(_ query:CFDictionary,_ result:UnsafeMutablePointer<AnyObject?>?)->Int32 {
    guard let data=SecurityFixture.data else{return errSecItemNotFound};result?.pointee=data as NSData;return errSecSuccess
}
@discardableResult func SecItemDelete(_ query:CFDictionary)->Int32 {SecurityFixture.deletes+=1;SecurityFixture.data=nil;return errSecSuccess}
''' + store_source + r'''
@main struct Check {
    static func main() {
        let store=SteamTokenStore()
        store.saveTokens(accountName:"fixture",refreshToken:"old_fixture",accessToken:"",steamID:0)
        precondition(store.loadTokens()?.refreshToken=="old_fixture")
        SecurityFixture.fail=true
        store.saveTokens(accountName:"fixture",refreshToken:"new_fixture",accessToken:"",steamID:0)
        precondition(store.loadTokens()?.refreshToken=="old_fixture" && SecurityFixture.deletes==0)
        SecurityFixture.fail=false
        store.saveTokens(accountName:"fixture",refreshToken:"new_fixture",accessToken:"",steamID:0)
        precondition(store.loadTokens()?.refreshToken=="new_fixture" && SecurityFixture.deletes==0)
        store.clearTokens();precondition(store.loadTokens()==nil && SecurityFixture.deletes==1)
    }
}
''')
    keychain_binary = temp / 'keychain'
    subprocess.run(['xcrun','swiftc','-parse-as-library',str(keychain),'-o',str(keychain_binary)],check=True)
    subprocess.run([str(keychain_binary)],check=True)
    print('PASS: production Keychain writer replaces atomically; failed updates preserve the old authorization')

    # Apply the Wine patch in a disposable checkout only.
    wine = temp / 'wine'; wine.mkdir()
    subprocess.run(['git', 'init', '-q', str(wine)], check=True)
    originals = {}
    for name in ['dlls/crypt32/crypt32_private.h', 'dlls/crypt32/main.c', 'dlls/crypt32/protectdata.c', 'dlls/crypt32/unixlib.c']:
        text = subprocess.check_output(['git', '-C', str(ROOT / 'wine'), 'show', 'HEAD:' + name], text=True)
        originals[name] = text
        target = wine / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text)
    subprocess.run(['git', '-C', str(wine), 'apply', '--check', str(patch)], check=True)
    subprocess.run(['git', '-C', str(wine), 'apply', str(patch)], check=True)
    protect = (wine / 'dlls/crypt32/protectdata.c').read_text()
    dllmain = block((wine / 'dlls/crypt32/main.c').read_text(), 'BOOL WINAPI DllMain(')
    assert dllmain.index('__wine_init_unix_call()') < dllmain.index('mdeck_steam_auth_probe();')
    assert dllmain.index('CRYPT32_CALL( process_attach, NULL );') < dllmain.index('mdeck_steam_auth_probe();')
    for signature, blob, event in [('BOOL WINAPI CryptProtectData(', 'pDataIn', 'PROTECT'), ('BOOL WINAPI CryptUnprotectData(', 'pDataOut', 'UNPROTECT')]:
        method = block(protect, signature)
        success = block(method, '    if (rc)')
        scoped = block(success, 'if (mdeck_steam_process())')
        assert f'mdeck_publish_token( {blob} );' in scoped
        assert f'mdeck_steam_event( MDECK_STEAM_{event}_SUCCEEDED );' in scoped
        assert f'if (mdeck_steam_process()) mdeck_steam_event( MDECK_STEAM_{event}_ENTERED );' in method
        assert method.index(f'mdeck_publish_token( {blob} );') < method.rindex('SetLastError(ERROR_SUCCESS)')
        assert 'if (!mdeck_steam_process()) report(' in method
        assert 'if (!mdeck_steam_process()) TRACE_DATA_BLOB(pDataOut)' in method
    bridge = block(native, 'static NTSTATUS mdeck_steam_token(')
    wow = block(native, 'static NTSTATUS wow64_mdeck_steam_token(')
    private = (wine / 'dlls/crypt32/crypt32_private.h').read_text()
    definitions = block(private, 'enum mdeck_steam_auth_event') + ';\n' + block(private, 'struct mdeck_steam_token_params') + ';\n'
    handlers = protect[protect.index("/* Only the user's interactive Steam client participates."):protect.index('#define CRYPT32_PROTECTDATA_PROV')]
    # This is a synthetic JWT with no cryptographic signature or real account.
    def encoded(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')
    body = encoded({'iss': 'steam', 'sub': str(0x0110000100000001), 'aud': ['client', 'derive'], 'exp': 4102444800})
    header_variants = [
        ('compact JSON', '{"alg":"RS256","typ":"JWT"}'),
        ('space after opening brace', '{ "typ": "JWT", "alg": "RS256" }'),
        ('leading whitespace', '  {"typ":"JWT","alg":"RS256"}'),
        ('leading newline and reordered fields', '\n{\n"kid":"fixture", "alg":"RS256", "typ":"JWT"\n}'),
    ]
    c = temp / 'bridge.c'
    cbinary = temp / 'bridge'
    for label, header in header_variants:
        jwt = base64.urlsafe_b64encode(header.encode()).decode().rstrip('=') + '.' + body + '.synthetic_signature'
        bridge_fixture = (ROOT / 'tests/host/fixtures/SteamSignInBridgeCheck.c').read_text()
        for marker, production in [('PRODUCTION_DEFINITIONS', definitions), ('PRODUCTION_NATIVE', bridge),
                                    ('PRODUCTION_HANDLERS', handlers), ('PRODUCTION_WOW64', wow),
                                    ('SYNTHETIC_TOKEN', 'static const char jwt[] = ' + json.dumps(jwt) + ';')]:
            assert bridge_fixture.count('// ' + marker) == 1
            bridge_fixture = bridge_fixture.replace('// ' + marker, production)
        c.write_text(bridge_fixture)
        print('Checking production Windows bridge with synthetic header format: ' + label, flush=True)
        subprocess.run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', str(c), '-o', str(cbinary)], check=True)
        subprocess.run([str(cbinary)], check=True)
    print('PASS: JWT header whitespace/order variants, raw/wrapped UTF-8 and UTF-16 slices, process scope, bounds, grammar, candidate cap and metadata/WOW64 conversion (ASan/UBSan)')
    event_names = re.findall(r'^    (MDECK_STEAM_[A-Z_]+)(?: = 1)?,?$', block(private, 'enum mdeck_steam_auth_event'), re.M)
    assert len(event_names) == 12
    assert [int(value) for value in re.findall(r'^    case \w+ = (\d+)$', block(sync, 'enum SteamClientAuthProbe'), re.M)] == list(range(1, len(event_names) + 1))
    for table in ['__wine_unix_call_funcs', '__wine_unix_call_wow64_funcs']:
        name = 'mdeck_steam_token' if table.endswith('call_funcs') else 'wow64_mdeck_steam_token'
        assert name in block(native, 'const unixlib_entry_t ' + table + '[] =')
    # Compile the full patched PE source when the pinned cross compiler is
    # available; CI's runtime build remains responsible for full DLL linkage.
    compiler_root = ROOT / 'toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin'
    checked_arches = []
    for arch in ['i686', 'aarch64', 'arm64ec']:
        compiler = compiler_root / (arch + '-w64-mingw32-clang')
        if compiler.exists():
            subprocess.run([str(compiler), '-target', ('i386' if arch == 'i686' else arch) + '-windows',
                            '-fsyntax-only', '-D__WINESRC__', '-D_CRYPT32_',
                            '-I' + str(wine / 'dlls/crypt32'), '-I' + str(ROOT / 'wine/include'),
                            '-I' + str(ROOT / 'wine/include/msvcrt'),
                            '-I' + str(ROOT / 'wine/dlls/crypt32'),
                            str(wine / 'dlls/crypt32/protectdata.c'), str(wine / 'dlls/crypt32/main.c')], check=True)
            checked_arches.append(arch)
    print('PASS: full patched DPAPI and DLL attach sources syntax-checked for ' + ', '.join(checked_arches) if checked_arches else 'SKIP: full PE syntax check requires the pinned cross compilers')
    # Source drift is a build failure rather than silently omitting the hook.
    target = wine / 'dlls/crypt32/protectdata.c'
    target.write_text(originals['dlls/crypt32/protectdata.c'].replace('WINE_DEFAULT_DEBUG_CHANNEL(crypt);', 'SOURCE_DRIFT;'))
    for name in ['dlls/crypt32/crypt32_private.h', 'dlls/crypt32/main.c', 'dlls/crypt32/unixlib.c']:
        (wine / name).write_text(originals[name])
    assert subprocess.run(['git', '-C', str(wine), 'apply', '--check', str(patch)], capture_output=True).returncode != 0
print('PASS: real UIKit/Security importer and CM verification typecheck for iOS; privacy, ABI tables and fail-on-drift wiring checked')
print('No real credentials, Steam API call, Wine execution, IPA build or physical-device test.')
