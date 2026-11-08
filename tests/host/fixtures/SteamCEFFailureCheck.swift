import Foundation
func L(_ value:String)->String{value}
struct LibraryEntry { var desktop:Bool?;var steam=true }
@MainActor final class LibraryModel {
    static let shared=LibraryModel()
    var current:UUID?;var activeEntry:LibraryEntry?;var error:String?
}
enum SteamClient { static func owns(_ entry:LibraryEntry)->Bool{entry.steam} }
@MainActor final class LogStore {static let shared=LogStore();func log(_ text:String){}}
@MainActor final class DeckSteamLaunchPreparation {
    static let shared=DeckSteamLaunchPreparation()
    var calls=0,lastSession:UUID?
    var awaitingClientImage=true
    func runtimeFailure(_ text:String,session:UUID){calls+=1;lastSession=session;awaitingClientImage=false}
}
// PRODUCTION_RUNTIME_FAILURE
@main struct Check {
    @MainActor static func settle() async { for _ in 0..<10 { try? await Task.sleep(nanoseconds:1_000_000) } }
    @MainActor static func main() async {
        let defaults=UserDefaults.standard, saved=UserDefaults.standard.object(forKey:SteamClientRuntimeFailure.runKey)
        defer{defaults.set(saved,forKey:SteamClientRuntimeFailure.runKey)}
        SteamClientRuntimeFailure.beginRun()
        let old=defaults.string(forKey:SteamClientRuntimeFailure.runKey)!
        SteamClientRuntimeFailure.beginRun()
        let run=defaults.string(forKey:SteamClientRuntimeFailure.runKey)!
        precondition(old != run && !SteamClientRuntimeFailure.matchesActiveRun(old) && SteamClientRuntimeFailure.matchesActiveRun(run))
        precondition(!SteamClientRuntimeFailure.matchesActiveRun("invalid"))
        let model=LibraryModel.shared,overlay=DeckSteamLaunchPreparation.shared,session=UUID()
        model.current=session;model.activeEntry=LibraryEntry(desktop:false)
        old.withCString{madeiraSteamCEFAddressFailure($0)}
        "bad".withCString{madeiraSteamCEFAddressFailure($0)}
        madeiraSteamCEFAddressFailure(nil);await settle()
        precondition(model.error == nil && overlay.calls==0)
        run.withCString{madeiraSteamCEFAddressFailure($0)};await settle()
        precondition(model.error?.contains("address space") == true && overlay.calls==1 && overlay.lastSession==session)
        model.error=nil;model.activeEntry=LibraryEntry(desktop:false,steam:false)
        run.withCString{madeiraSteamCEFAddressFailure($0)};await settle()
        precondition(model.error == nil && overlay.calls==1)
        model.activeEntry=LibraryEntry(desktop:true,steam:false)
        run.withCString{madeiraSteamCEFAddressFailure($0)};await settle()
        precondition(overlay.calls==2)
        model.error=nil;model.current=nil
        run.withCString{madeiraSteamCEFAddressFailure($0)};await settle()
        precondition(model.error == nil && overlay.calls==2)
        model.current=session;model.activeEntry=LibraryEntry(desktop:false)
        overlay.awaitingClientImage=true
        old.withCString{madeiraSteamInitialWindowFailure($0)}
        madeiraSteamInitialWindowFailure(nil);await settle()
        precondition(model.error==nil && overlay.calls==2)
        run.withCString{madeiraSteamInitialWindowFailure($0)};await settle()
        precondition(model.error?.contains("(-104)")==true && overlay.calls==3 && overlay.lastSession==session)
        model.error=nil
        run.withCString{madeiraSteamInitialWindowFailure($0)};await settle()
        precondition(model.error==nil && overlay.calls==3) // Already failed/revealed/closing: no startup wait remains.
        overlay.awaitingClientImage=true
        model.activeEntry=LibraryEntry(desktop:false,steam:false)
        run.withCString{madeiraSteamInitialWindowFailure($0)};await settle()
        precondition(model.error==nil && overlay.calls==3)
        model.current=nil;model.activeEntry=LibraryEntry(desktop:true,steam:false)
        run.withCString{madeiraSteamInitialWindowFailure($0)};await settle()
        precondition(model.error==nil && overlay.calls==3)
        print("PASS: production Swift callback copies launch identity, ignores stale/ended/unrelated sessions and reports only the active Steam/desktop session")
        print("PASS: Steam -104 stops only the current startup first-frame wait, once; stale, ended, unrelated and post-reveal callbacks are ignored")
    }
}
