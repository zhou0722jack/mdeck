#!/usr/bin/env python3
"""Test immediate entry scheduling, A/B/C reports and one-way Wine handoff with injected services."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
swift = (APP / 'AppEntryJIT.swift').read_text()
core = swift[swift.index('// MARK: - Entry JIT policy'):swift.index('// MARK: - Production adapter')]
content = (APP / 'ContentView.swift').read_text()
assert 'AppEntryJIT.shared.enable { result in' in content
wine = content[content.index('    private func runWineFullSequence('):]
assert wine.index('deferLaunchUntilProbeFinishes') < wine.index('StikJITHelper.allocatePool(')
root = (APP / 'DeckStartup.swift').read_text()
assert 'sceneChanged(active: entryScenePhase == .active, allowed: startup.phase == .ready)' in root
assert 'sceneChanged(active: phase == .active, allowed: startup.phase == .ready)' in root
assert 'static let interval: TimeInterval = 5' in swift and 'static let probeBytes = 8' in swift
project = (ROOT / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
app_entry = (APP / 'MadeiraApp.swift').read_text()
assert app_entry.index('AppEntryJIT.shared.requestAtAppEntry()') < app_entry.index('ProfileUnification.run()')
assert 'self.services.preparePool' in core and 'if case .success = result' in core
assert '!enableInFlight, !probing, !releasing, pendingLaunch != nil' in core
assert 'configuration: values' in swift and 'GameProfile(windowsPath: SteamClient.windowsExecutable).values' in swift
assert project.count('/* AppEntryJIT.swift in Sources */') == 2
assert project.count('/* AppEntryJITProbe.c in Sources */') == 2

harness = r'''
import SwiftUI
func L(_ key: String) -> String { key }
func LF(_ key: String, _ args: CVarArg...) -> String { String(format:key,arguments:args) }
@MainActor final class LogStore { static let shared=LogStore(); func log(_ value:String) {} }
extension AppEntryJIT.Services { static var live: Self { fatalError("live service is never used") } }
@MainActor final class Fake {
    var ready=false, attached=false, enableCalls=0, probes=0, cancels=0, releases=0, prepares=0
    var automaticPool=true
    var regionReports: [AppEntryJIT.RegionResult] = ["A", "B", "C"].map { .init(name:$0,available:true,tested:true,result:42) }
    var intervals:[TimeInterval]=[]
    var enables:[(Result<Void,Error>)->Void]=[]
    var executions:[(Int64)->Void]=[]
    var cleanups:[(Int64)->Void]=[]
    var pools:[(Result<Void,Error>)->Void]=[]
    var tick:(()->Void)?
    func services() -> AppEntryJIT.Services {
        .init(enable:{ self.enableCalls+=1; self.enables.append($0) },
              preparePool:{ completion in
                  self.prepares+=1
                  if self.automaticPool { completion(.success(())) } else { self.pools.append(completion) }
              },
              ready:{ self.ready }, canProbe:{ self.attached },
              probe:{ self.probes+=1; self.executions.append($0) },
              report:{ self.regionReports },
              release:{ self.releases+=1; self.cleanups.append($0) },
              schedule:{ interval,tick in self.intervals.append(interval); self.tick=tick
                  return { self.cancels+=1; self.tick=nil }
              })
    }
    func enabled() { ready=true; attached=true; let f=enables.removeFirst(); f(.success(())) }
    func completed(_ result:Int64) { let f=executions.removeFirst(); f(result) }
    func released(_ result:Int64=0) { let f=cleanups.removeFirst(); f(result) }
    func prepared(_ result: Result<Void,Error> = .success(())) { let f=pools.removeFirst(); f(result) }
}
@main struct Check {
    @MainActor static func main() {
        var fake=Fake()
        var model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:false)
        precondition(fake.enableCalls==0)
        model.sceneChanged(active:true,allowed:true)
        model.sceneChanged(active:true,allowed:true)
        var joined=0
        model.enable { _ in joined+=1 }
        precondition(fake.enableCalls==1 && fake.probes==0)
        fake.enabled()
        precondition(joined==1 && fake.intervals==[5] && fake.probes==1)
        model.tick(); model.tick()
        precondition(fake.probes==1)
        fake.completed(42)
        precondition(model.successfulProbes==1)
        precondition(model.lastProbeResult==42 && model.lastProbeFinishedAt != nil)
        precondition(model.probeIsHealthy(at:model.lastProbeFinishedAt!))
        precondition(!model.probeIsHealthy(at:model.lastProbeFinishedAt!.addingTimeInterval(11)))
        precondition(abs(AppEntryJIT.cycleProgress(at:Date(timeIntervalSince1970:2.5),since:Date(timeIntervalSince1970:0)) - 0.5)<0.001)
        precondition(AppEntryJIT.cycleProgress(at:Date(timeIntervalSince1970:5),since:Date(timeIntervalSince1970:0))==0)
        fake.tick?()
        precondition(fake.probes==2)
        model.sceneChanged(active:false,allowed:true)
        precondition(fake.tick==nil)
        fake.completed(42)
        model.tick()
        precondition(fake.probes==2 && model.state == .paused)
        model.sceneChanged(active:true,allowed:true)
        precondition(fake.probes==3 && fake.enableCalls==1)
        fake.completed(42)
        fake.attached=false; fake.tick?()
        precondition(fake.probes==3 && model.state == .waiting)
        fake.attached=true; fake.tick?()
        precondition(fake.probes==4)
        print("PASS: entry after choice, one shared JIT attachment, immediate/5-second probe, no overlap and background pause")

        var starts=0, failures=0
        let staleTimer=fake.tick
        precondition(model.deferLaunchUntilProbeFinishes({ starts+=1 },failed:{_ in failures+=1}))
        precondition(starts==0 && fake.tick==nil)
        staleTimer?(); model.sceneChanged(active:true,allowed:true)
        precondition(fake.probes==4)
        fake.completed(42)
        precondition(starts==0 && fake.releases==1)
        fake.released()
        precondition(starts==1 && failures==0 && model.state == .stopped)
        precondition(!model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        model.tick(); staleTimer?()
        precondition(fake.probes==4)
        print("PASS: launch stops timer, drains the in-flight native cleanup once and never resumes probes")

        fake=Fake(); model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:true)
        precondition(model.deferLaunchUntilProbeFinishes({ starts+=1 },failed:{_ in failures+=1}))
        precondition(fake.releases==0)
        fake.enabled()
        precondition(fake.releases==1)
        fake.released()
        precondition(fake.probes==0 && fake.intervals.isEmpty && model.state == .stopped)
        print("PASS: a late initial attachment cannot restart the loop after a launch handoff")

        fake=Fake(); model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:true); fake.enabled()
        fake.completed(-1)
        precondition(model.lastProbeResult == -1 && !model.probeIsHealthy(at:.now))
        precondition(fake.tick==nil && model.state == .failed)
        model.sceneChanged(active:false,allowed:true); model.sceneChanged(active:true,allowed:true)
        precondition(fake.probes==1 && model.state == .failed)
        model.enable { _ in }
        fake.enabled()
        precondition(fake.probes==2)
        precondition(model.deferLaunchUntilProbeFinishes({ starts+=1 },failed:{_ in failures+=1}))
        let before=starts
        fake.completed(-4)
        fake.released(-4)
        precondition(starts==before && failures==1 && model.state == .failed)
        var refused=false
        model.enable { result in if case .failure = result { refused=true } }
        precondition(refused && fake.enableCalls==2)
        print("PASS: failed native probes stop retries; failed byte restoration refuses launch and requests reopening")

        fake=Fake(); model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:true); fake.enabled()
        for _ in 0..<1000 { fake.completed(42); fake.tick?() }
        precondition(fake.probes==1001 && fake.enableCalls==1 && fake.releases==0)
        let launchCount=starts
        precondition(model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        fake.completed(42)
        precondition(starts==launchCount && fake.releases==1)
        model.tick(); precondition(fake.probes==1001)
        fake.released()
        precondition(starts==launchCount+1)
        print("PASS: 1000 scheduled rounds do not reattach or release early; startup waits for original-byte restoration and probe sealing")

        fake=Fake(); model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:true); fake.enabled(); fake.completed(42)
        let beforeReleaseFailure=starts
        precondition(model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        precondition(model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        precondition(fake.releases==1)
        fake.released(-4)
        precondition(starts==beforeReleaseFailure && model.state == .failed)
        model.tick(); precondition(fake.probes==1)
        print("PASS: duplicate handoffs share one release; failure blocks startup after a successful last probe")

        fake=Fake(); fake.automaticPool=false; model=AppEntryJIT(services:fake.services())
        model.requestAtAppEntry(); model.requestAtAppEntry()
        precondition(fake.enableCalls==1 && fake.prepares==0 && fake.probes==0)
        fake.enabled()
        precondition(fake.prepares==1 && fake.probes==0 && fake.intervals.isEmpty)
        var poolJoined=0
        model.enable { result in if case .success = result { poolJoined+=1 } }
        precondition(fake.enableCalls==1)
        model.sceneChanged(active:true,allowed:true)
        model.tick()
        precondition(fake.probes==0 && poolJoined==0)
        let beforePool=starts
        precondition(model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        precondition(fake.releases==0 && starts==beforePool)
        fake.prepared()
        precondition(poolJoined==1 && fake.prepares==1 && fake.probes==0 && fake.releases==1)
        fake.released()
        precondition(starts==beforePool+1)
        print("PASS: App.init requests JIT without a scene or movie; fast Play joins A/B/C preparation before handoff")

        fake=Fake(); fake.automaticPool=false; model=AppEntryJIT(services:fake.services())
        model.requestAtAppEntry(); fake.enabled()
        let beforePoolFailure=starts, previousFailures=failures
        precondition(model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        fake.prepared(.failure(NSError(domain:"PoolFixture",code:1)))
        precondition(starts==beforePoolFailure && failures==previousFailures+1 && fake.probes==0 && fake.releases==0)
        model.tick()
        precondition(model.state == .failed && fake.probes==0)
        print("PASS: pool failure refuses both periodic execution and queued Steam startup")

        fake=Fake();model=AppEntryJIT(services:fake.services())
        fake.regionReports = [
            .init(name:"A",available:true,tested:true,result:42),
            .init(name:"B",available:false,tested:false,result:0),
            .init(name:"C",available:false,tested:false,result:0)]
        model.sceneChanged(active:true,allowed:true);fake.enabled();fake.completed(1)
        precondition(model.state == .monitoring && model.successfulProbes==0 && !model.probeIsHealthy(at:.now))
        precondition(model.regionResults.count==3 && model.regionResults[0].description=="Probe passed")
        precondition(model.regionResults[1].description=="Region not allocated")
        fake.tick?();precondition(fake.probes==2)
        print("PASS: missing B/C are visible as unallocated, never green, and do not become execution failures")

        fake=Fake();model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:true);fake.enabled()
        let beforeExecutionFailure=starts, failuresBeforeExecution=failures
        precondition(model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        fake.completed(-3);fake.released()
        precondition(starts==beforeExecutionFailure && failures==failuresBeforeExecution+1 && model.state == .failed)
        print("PASS: an A/B/C execution failure during a queued launch is restored/sealed but refuses Wine startup")
    }
}
'''

with tempfile.TemporaryDirectory(prefix='mdeck-entry-jit-') as directory:
    tmp=Path(directory)
    production=tmp/'Entry.swift';production.write_text('import SwiftUI\n'+core)
    fixture=tmp/'Check.swift';fixture.write_text(harness)
    binary=tmp/'check'
    subprocess.run(['xcrun','swiftc','-parse-as-library',str(production),str(fixture),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print('Host policy tests with fake services; native A/B/C execution is checked by check-abc-jit-probe.py.')
