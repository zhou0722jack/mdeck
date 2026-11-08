// SPDX-License-Identifier: GPL-3.0-or-later
import SwiftUI

// MARK: - Entry JIT policy

@MainActor final class AppEntryJIT: ObservableObject {
    struct Services {
        var enable: (@escaping (Result<Void, Error>) -> Void) -> Void
        var preparePool: (@escaping (Result<Void, Error>) -> Void) -> Void = { $0(.success(())) }
        var ready: () -> Bool
        var canProbe: () -> Bool
        var probe: (@escaping (Int64) -> Void) -> Void
        var report: () -> [RegionResult] = { [] }
        var release: (@escaping (Int64) -> Void) -> Void
        var schedule: (TimeInterval, @escaping () -> Void) -> (() -> Void)
    }
    static let shared = AppEntryJIT(services: .live)
    static let interval: TimeInterval = 5
    static let probeBytes = 8
    struct RegionResult: Identifiable, Equatable {
        let name: String
        let available: Bool
        let tested: Bool
        let result: Int64
        var id: String { name }
        var description: String {
            if !available { return L("Region not allocated") }
            if !tested { return L("Not tested yet") }
            return result == 42 ? L("Probe passed") : LF("Probe returned %@", String(result))
        }
    }
    enum State: Equatable { case idle, requesting, waiting, monitoring, paused, failed, stopped }
    @Published private(set) var state = State.idle
    @Published private(set) var error: String?
    @Published private(set) var successfulProbes = 0
    @Published private(set) var lastProbeResult: Int64?
    @Published private(set) var lastProbeFinishedAt: Date?
    @Published private(set) var regionResults: [RegionResult] = []
    @Published private(set) var cycleStartedAt = Date()
    static func cycleProgress(at date: Date, since start: Date) -> Double {
        max(0, date.timeIntervalSince(start)).truncatingRemainder(dividingBy: interval) / interval
    }
    func probeIsHealthy(at date: Date) -> Bool {
        guard state == .monitoring, lastProbeResult == 42, let lastProbeFinishedAt else { return false }
        return date.timeIntervalSince(lastProbeFinishedAt) <= Self.interval * 2
    }
    private let services: Services
    private var entered = false
    private var foreground = false
    private var allowed = false
    private var stoppedForLaunch = false
    private var nativeFailed = false
    private var cleanupFailed = false
    private var enableInFlight = false
    private var enableWaiters: [(Result<Void, Error>) -> Void] = []
    private var cancelTimer: (() -> Void)?
    private var probing = false
    private var releasing = false
    private var releasedForLaunch = false
    private var pendingLaunch: (() -> Void)?
    private var pendingFailure: ((String) -> Void)?

    init(services: Services) { self.services = services }

    /// Called by App.init, before the startup movie or the root view exists.
    /// Scene visibility controls only the periodic probe, never attachment.
    func requestAtAppEntry() {
        guard !entered else { return }
        entered = true
        LogStore.shared.log("[jit-entry] requesting selected JIT method immediately at app entry")
        enable { _ in }
    }

    func sceneChanged(active: Bool, allowed: Bool) {
        foreground = active
        self.allowed = allowed
        guard active, allowed, !stoppedForLaunch else {
            stopTimer()
            if entered && !stoppedForLaunch { state = .paused }
            return
        }
        if !entered {
            requestAtAppEntry()
        } else {
            if nativeFailed { state = .failed; return }
            if enableInFlight { state = .requesting; return }
            armTimer()
            tick()
        }
    }

    /// Entry, Settings/Play callers share the same pending attachment. This
    /// prevents a cached-component Steam tap from launching a second helper.
    func enable(completion: @escaping (Result<Void, Error>) -> Void = { _ in }) {
        guard !cleanupFailed else {
            let message = error ?? L("The JIT probe could not restore the borrowed code. Close and reopen mdeck before starting Steam.")
            state = .failed
            completion(.failure(NSError(domain: "MadeiraEntryJIT", code: -4,
                                        userInfo: [NSLocalizedDescriptionKey: message])))
            return
        }
        enableWaiters.append(completion)
        guard !enableInFlight else { return }
        enableInFlight = true
        nativeFailed = cleanupFailed
        error = nil
        if !stoppedForLaunch { state = .requesting }
        services.enable { [weak self] result in
            guard let self else { return }
            if case .success = result {
                LogStore.shared.log("[jit-entry] debugger ready; preparing A/B/C now, before Steam")
                self.services.preparePool { [weak self] in self?.finishEnabling($0) }
            } else { self.finishEnabling(result) }
        }
    }

    private func finishEnabling(_ result: Result<Void, Error>) {
        enableInFlight = false
        switch result {
        case .success:
            error = nil
            if !stoppedForLaunch { state = foreground ? .monitoring : .paused }
        case .failure(let failure) where failure is CancellationError:
            error = nil
            if !stoppedForLaunch { state = foreground ? .waiting : .paused }
        case .failure(let failure):
            nativeFailed = true
            error = failure.localizedDescription
            if !stoppedForLaunch { state = .failed }
        }
        let callbacks = enableWaiters
        enableWaiters.removeAll()
        // Success means the production pool exists, not just CS_DEBUGGED.
        callbacks.forEach { $0(result) }
        if pendingLaunch != nil {
            if case .success = result { releaseBeforeLaunch() }
            else {
                let failed = pendingFailure
                pendingLaunch = nil; pendingFailure = nil
                state = .failed
                failed?(error ?? L("The JIT memory pool could not be prepared. Close and reopen mdeck, then enable JIT again."))
            }
        }
        armTimer()
        tick()
    }

    private func armTimer() {
        guard entered, foreground, allowed, !stoppedForLaunch, !nativeFailed, cancelTimer == nil else { return }
        cancelTimer = services.schedule(Self.interval) { [weak self] in self?.tick() }
    }

    private func stopTimer() { cancelTimer?(); cancelTimer = nil }

    func tick() {
        guard entered, foreground, allowed, !stoppedForLaunch, !nativeFailed, !probing, !releasing, !enableInFlight else { return }
        guard services.ready(), services.canProbe() else {
            state = .waiting
            return
        }
        probing = true
        cycleStartedAt = Date()
        state = .monitoring
        LogStore.shared.log("[jit-entry] probe round begin: \(successfulProbes + 1)")
        services.probe { [weak self] result in
            guard let self else { return }
            self.probing = false
            self.lastProbeResult = result
            self.lastProbeFinishedAt = Date()
            self.regionResults = self.services.report()
            let details = self.regionResults.map { "\($0.name)=\($0.available ? ($0.tested ? String($0.result) : "untested") : "not allocated")" }.joined(separator: " ")
            if !details.isEmpty { LogStore.shared.log("[jit-entry-probe] \(details); original bytes restored=\(result != -4)") }
            if result == -4 {
                self.cleanupFailed = true
                self.error = L("The JIT probe could not restore the borrowed code. Close and reopen mdeck before starting Steam.")
                LogStore.shared.log("[jit-entry] original-byte restoration failed; launch handoff refused")
            }
            if result < 0 && result != -2 {
                self.nativeFailed = true
                if result != -4 { self.error = LF("The A/B/C JIT probe failed (%@). Check the log before retrying JIT.", String(result)) }
            }
            if !self.stoppedForLaunch {
                if result == 42 || result == 1 {
                    if result == 42 { self.successfulProbes += 1 }
                    self.error = nil
                    self.state = self.foreground ? .monitoring : .paused
                    LogStore.shared.log("[jit-entry] A/B/C probe result=\(result); borrowed bytes restored; no allocation or debugger request")
                } else if result == -2 {
                    self.state = self.foreground ? .waiting : .paused
                    LogStore.shared.log("[jit-entry] probe skipped: JIT signing status unavailable")
                } else {
                    self.nativeFailed = true
                    if result != -4 { self.error = LF("The A/B/C JIT probe failed (%@). Check the log before retrying JIT.", String(result)) }
                    self.state = .failed
                    self.stopTimer()
                    LogStore.shared.log("[jit-entry] probe failed result=\(result); periodic execution stopped")
                }
            }
            if self.pendingLaunch != nil { self.releaseBeforeLaunch() }
        }
    }

    /// Restore borrowed bytes and seal the probe before Wine consumes the pool.
    /// No production mapping is released and no new probe may start afterwards.
    /// No new probe can start after this handoff, including late JIT callbacks.
    func deferLaunchUntilProbeFinishes(_ launch: @escaping () -> Void, failed: @escaping (String) -> Void) -> Bool {
        stoppedForLaunch = true
        stopTimer()
        state = .stopped
        if cleanupFailed {
            state = .failed
            failed(error ?? L("The JIT probe could not restore the borrowed code. Close and reopen mdeck before starting Steam."))
            return true
        }
        if releasedForLaunch { return false }
        if pendingLaunch == nil { pendingLaunch = launch; pendingFailure = failed }
        if !probing { releaseBeforeLaunch() }
        return true
    }

    private func releaseBeforeLaunch() {
        guard !enableInFlight, !probing, !releasing, pendingLaunch != nil else { return }
        releasing = true
        services.release { [weak self] result in
            guard let self else { return }
            self.releasing = false
            let launch = self.pendingLaunch
            let failed = self.pendingFailure
            self.pendingLaunch = nil
            self.pendingFailure = nil
            if result != 0 || self.cleanupFailed {
                self.cleanupFailed = true
                self.state = .failed
                self.error = L("The JIT probe could not restore the borrowed code. Close and reopen mdeck before starting Steam.")
                LogStore.shared.log("[jit-entry] probe handoff failed result=\(result); Wine startup refused")
                failed?(self.error!)
            } else if self.nativeFailed {
                self.state = .failed
                failed?(self.error ?? L("The JIT memory pool could not be prepared. Close and reopen mdeck, then enable JIT again."))
            } else {
                self.releasedForLaunch = true
                LogStore.shared.log("[jit-entry] A/B/C original bytes restored and probing sealed; continuing Wine startup")
                launch?()
            }
        }
    }
}

// MARK: - Production adapter

extension AppEntryJIT.Services {
    @MainActor static var live: Self {
        Self(enable: { JITCoordinator.shared.enable(completion: $0) },
             preparePool: { completion in
                 // Attachment is requested synchronously by App.init. Defer only
                 // the settings snapshot to the next main-queue turn, after that
                 // initializer has installed the persisted Steam/global defaults.
                 DispatchQueue.main.async {
                     let values = MadeiraConfig.all().merging(GameProfile(windowsPath: SteamClient.windowsExecutable).values) { _, game in game }
                     let mb = StikJITHelper.requestedPoolMB(in: values)
                     LogStore.shared.log("[jit-entry-pool] allocating A/B/C immediately after attachment; target A+B=\(mb)MB")
                     DispatchQueue.global(qos: .userInitiated).async {
                         let pool = StikJITHelper.allocatePool(poolSize: mb * 1024 * 1024, configuration: values)
                         let binding = pool == nil ? -6 : StikJITHelper.bindEntryProbe()
                         let reason: String?
                         if pool == nil {
                             reason = StikJITHelper.poolFailure ?? L("The JIT memory pool could not be prepared. Close and reopen mdeck, then enable JIT again.")
                         } else if binding != 0 {
                             reason = LF("The A/B/C JIT probe failed (%@). Check the log before retrying JIT.", String(binding))
                         } else { reason = nil }
                         DispatchQueue.main.async {
                             if let reason {
                                 completion(.failure(NSError(domain: "MadeiraEntryJIT", code: -6,
                                                             userInfo: [NSLocalizedDescriptionKey: reason])))
                             } else { completion(.success(())) }
                         }
                     }
                 }
             },
             ready: { StikJITHelper.ready && wine_process_is_running() == 0 && wineserver_is_running() == 0 },
             canProbe: { StikJITHelper.poolTaken },
             probe: { completion in
                 DispatchQueue.global(qos: .utility).async {
                     let result = jit_entry_probe_once()
                     DispatchQueue.main.async { completion(result) }
                 }
             }, report: {
                 var report = JITEntryProbeReport()
                 jit_entry_probe_copy_report(&report)
                 return zip(["A", "B", "C"], [report.a, report.b, report.c]).enumerated().map { index, item in
                     AppEntryJIT.RegionResult(name: item.0, available: report.available_mask & (1 << index) != 0,
                         tested: report.tested_mask & (1 << index) != 0, result: item.1)
                 }
             }, release: { completion in
                 DispatchQueue.global(qos: .utility).async {
                     let result = jit_entry_probe_release()
                     DispatchQueue.main.async { completion(result) }
                 }
             }, schedule: { seconds, tick in
                 let timer = Timer(timeInterval: seconds, repeats: true) { _ in
                     MainActor.assumeIsolated { tick() }
                 }
                 RunLoop.main.add(timer, forMode: .common)
                 return { timer.invalidate() }
             })
    }
}

struct AppEntryJITStatus: View {
    @ObservedObject private var model = AppEntryJIT.shared
    private var message: String? {
        if let error = model.error, model.state == .failed || model.state == .waiting { return error }
        switch model.state {
        case .idle, .stopped: return nil
        case .requesting: return L("JIT requested at app entry. Waiting for the selected method…")
        case .waiting: return L("Waiting for JIT. Run Madeira's script in StikDebug if using external mode.")
        case .monitoring: return L("JIT is ready. Existing A/B/C memory is probed every 5 seconds until Steam starts.")
        case .paused: return L("The entry JIT probe is paused while the app is inactive.")
        case .failed: return L("The entry JIT probe stopped. Check JIT settings and the log.")
        }
    }
    var body: some View {
        if let message { Text(message).font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center) }
    }
}

enum EntryJITIndicatorKind: String, Identifiable {
    case jit, memory, activity
    var id: String { rawValue }
    var title: String {
        switch self {
        case .jit: return "JIT"
        case .memory: return "Memory+"
        case .activity: return L("JIT activity")
        }
    }
}

/// This small timeline redraws only the indicators, never the homepage or its
/// entitlement reader. Progress is elapsed time, not a fabricated JIT result.
struct EntryJITIndicatorStrip: View {
    var jitEnabled: Bool
    var memoryEnabled: Bool
    var healthy: Bool
    var progress: Double
    var select: (EntryJITIndicatorKind) -> Void
    private let green = Color(red: 61 / 255, green: 220 / 255, blue: 132 / 255)
    var body: some View {
        HStack(spacing: 22) {
            indicator(.jit, enabled: jitEnabled, symbol: "bolt.fill")
            indicator(.memory, enabled: memoryEnabled, symbol: "memorychip")
            indicator(.activity, enabled: healthy, symbol: "waveform.path.ecg")
        }
        .padding(.horizontal, 22).padding(.vertical, 12)
        .background(.black.opacity(0.24), in: Capsule())
        .overlay(Capsule().stroke(.white.opacity(0.9), lineWidth: 1.4))
        .fixedSize(horizontal: true, vertical: true)
    }

    private func indicator(_ kind: EntryJITIndicatorKind, enabled: Bool, symbol: String) -> some View {
        let color = enabled ? green : Color.red
        return Button { select(kind) } label: {
            VStack(spacing: 6) {
                ZStack {
                    Circle().fill(color.opacity(0.17)).padding(5)
                    Circle().stroke(color.opacity(kind == .activity ? 0.25 : 0.85), lineWidth: 2)
                    if kind == .activity {
                        Circle().trim(from: 0, to: min(1, max(0, progress)))
                            .stroke(color, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                            .rotationEffect(.degrees(-90))
                    }
                    Image(systemName: symbol).font(.system(size: 16, weight: .semibold)).foregroundStyle(color)
                }.frame(width: 38, height: 38)
                Text(kind.title).font(.system(size: 10, weight: .medium)).foregroundStyle(.white.opacity(0.9))
                    .lineLimit(1).minimumScaleFactor(0.8)
            }.frame(minWidth: 48, minHeight: 62).contentShape(Rectangle())
        }.buttonStyle(.plain)
            .accessibilityLabel(Text(kind.title))
            .accessibilityValue(Text(enabled ? L("Enabled") : L("Unavailable")))
            .accessibilityHint(Text("View status details"))
    }
}

struct AppEntryJITIndicators: View {
    @ObservedObject private var model = AppEntryJIT.shared
    @ObservedObject private var activity = DeckMotionActivity.shared
    @ObservedObject private var appearance = DeckAppearance.shared
    @Environment(\.accessibilityReduceMotion) private var reduced
    @State private var jitEnabled = false
    @State private var memoryEnabled = false
    @State private var selected: EntryJITIndicatorKind?

    var body: some View {
        TimelineView(.animation(minimumInterval: reduced || !appearance.animations ? 1 : 1.0 / 30,
                                paused: !activity.active || model.state != .monitoring)) { timeline in
            EntryJITIndicatorStrip(jitEnabled: jitEnabled, memoryEnabled: memoryEnabled,
                                   healthy: jitEnabled && model.probeIsHealthy(at: timeline.date),
                                   progress: model.state == .monitoring ? AppEntryJIT.cycleProgress(at: timeline.date, since: model.cycleStartedAt) : 0) {
                selected = $0
            }
        }
        .task {
            memoryEnabled = EntitlementStatus.check().increasedMemory
            while !Task.isCancelled {
                jitEnabled = StikJITHelper.ready
                do { try await Task.sleep(nanoseconds: 1_000_000_000) } catch { return }
            }
        }
        .sheet(item: $selected) { kind in
            NavigationStack {
                Form {
                    Section {
                        LabeledContent("JIT", value: jitEnabled ? L("Enabled") : L("Unavailable"))
                        LabeledContent("Memory+", value: memoryEnabled ? L("Enabled") : L("Unavailable"))
                        LabeledContent(L("JIT activity"), value: activityDescription)
                    }
                    if kind == .jit {
                        Section { Text("JIT status uses the same runtime check as Settings. It does not use the allow-jit signing flag.") }
                    } else if kind == .memory {
                        Section {
                            Text("Memory+ requires the Increased Memory Limit entitlement in this signed copy of Madeira. Enabling JIT does not grant it. Check that your signing tool enables this capability for Madeira, then sign and install the updated app without deleting your existing installation.")
                        }
                    } else {
                        Section {
                            LabeledContent(L("Probe interval"), value: L("5 seconds"))
                            LabeledContent(L("Code per region"), value: L("8 bytes"))
                            ForEach(model.regionResults) { region in
                                LabeledContent(LF("JIT region %@", region.name), value: region.description)
                            }
                            LabeledContent(L("Successful probes"), value: String(model.successfulProbes))
                            LabeledContent(L("Last probe result"), value: model.lastProbeResult.map(String.init) ?? L("Not tested yet"))
                            if let date = model.lastProbeFinishedAt {
                                LabeledContent(L("Last probe time"), value: date.formatted(date: .omitted, time: .standard))
                            }
                        }
                        Section {
                            Text("The ring completes one cycle every 5 seconds. Green means the latest probe returned 42; red means untested, unavailable, failed or stale. Animation alone does not prove JIT is working.")
                            Text("Each round borrows 8 bytes in existing A/B/C memory, executes code and restores the original bytes. No probe memory is allocated or reserved; probing stops before Steam starts.")
                            Text("Unallocated regions remain untested. Green requires A, B and C to return 42.")
                        }
                    }
                    if let error = model.error { Section { Text(error).foregroundStyle(.red).textSelection(.enabled) } }
                    Section { AppEntryJITStatus() }
                }
                .navigationTitle(kind.title)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { selected = nil } } }
            }.presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
        }
    }

    private var activityDescription: String {
        switch model.state {
        case .idle, .requesting: return L("Not tested yet")
        case .waiting: return L("Waiting for JIT")
        case .paused: return L("Probe paused")
        case .failed: return L("Probe failed")
        case .stopped: return L("Probe stopped before Steam startup")
        case .monitoring:
            guard let result = model.lastProbeResult else { return L("Not tested yet") }
            if result == 1 { return L("Allocated regions passed; some regions are unavailable") }
            return result == 42 && model.probeIsHealthy(at: .now) ? L("Probe passed") : L("Probe failed or result expired")
        }
    }
}
