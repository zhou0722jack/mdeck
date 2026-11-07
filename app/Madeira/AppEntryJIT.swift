// SPDX-License-Identifier: GPL-3.0-or-later
import SwiftUI

// MARK: - Entry JIT policy

@MainActor final class AppEntryJIT: ObservableObject {
    struct Services {
        var enable: (@escaping (Result<Void, Error>) -> Void) -> Void
        var ready: () -> Bool
        var attached: () -> Bool
        var probe: (@escaping (Int64) -> Void) -> Void
        var release: (@escaping (Int64) -> Void) -> Void
        var schedule: (TimeInterval, @escaping () -> Void) -> (() -> Void)
    }
    static let shared = AppEntryJIT(services: .live)
    static let interval: TimeInterval = 5
    static let probeBytes = 16 * 1024
    enum State: Equatable { case idle, requesting, waiting, monitoring, paused, failed, stopped }
    @Published private(set) var state = State.idle
    @Published private(set) var error: String?
    @Published private(set) var successfulProbes = 0
    @Published private(set) var lastProbeResult: Int64?
    @Published private(set) var lastProbeFinishedAt: Date?
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

    func sceneChanged(active: Bool, allowed: Bool) {
        foreground = active
        self.allowed = allowed
        guard active, allowed, !stoppedForLaunch else {
            stopTimer()
            if entered && !stoppedForLaunch { state = .paused }
            return
        }
        if !entered {
            entered = true
            LogStore.shared.log("[jit-entry] requesting selected JIT method at app entry")
            enable { _ in }
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
            let message = error ?? L("The JIT probe could not release its temporary memory. Close and reopen Madeira before starting Steam.")
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
            self.enableInFlight = false
            switch result {
            case .success:
                self.error = nil
                if !self.stoppedForLaunch { self.state = self.foreground ? .monitoring : .paused }
            case .failure(let failure) where failure is CancellationError:
                self.error = nil
                if !self.stoppedForLaunch { self.state = self.foreground ? .waiting : .paused }
            case .failure(let failure):
                self.error = failure.localizedDescription
                if !self.stoppedForLaunch { self.state = .failed }
            }
            let callbacks = self.enableWaiters
            self.enableWaiters.removeAll()
            // Waiters may start Wine and permanently stop entry probes.
            callbacks.forEach { $0(result) }
            self.armTimer()
            self.tick()
        }
    }

    private func armTimer() {
        guard entered, foreground, allowed, !stoppedForLaunch, !nativeFailed, cancelTimer == nil else { return }
        cancelTimer = services.schedule(Self.interval) { [weak self] in self?.tick() }
    }

    private func stopTimer() { cancelTimer?(); cancelTimer = nil }

    func tick() {
        guard entered, foreground, allowed, !stoppedForLaunch, !nativeFailed, !probing, !releasing, !enableInFlight else { return }
        guard services.ready(), services.attached() else {
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
            if result == -4 {
                self.cleanupFailed = true
                self.error = L("The JIT probe could not release its temporary memory. Close and reopen Madeira before starting Steam.")
                LogStore.shared.log("[jit-entry] temporary mapping cleanup failed; launch handoff refused")
            }
            if !self.stoppedForLaunch {
                if result == 42 {
                    self.successfulProbes += 1
                    self.error = nil
                    self.state = self.foreground ? .monitoring : .paused
                    LogStore.shared.log("[jit-entry] probe \(self.successfulProbes): result=42; 16KiB code wiped; scratch reused without debugger request")
                } else if result == -2 {
                    self.state = self.foreground ? .waiting : .paused
                    LogStore.shared.log("[jit-entry] probe skipped: debugger no longer attached")
                } else {
                    self.nativeFailed = true
                    if result != -4 { self.error = LF("The independent JIT probe failed (%@). Check the log before retrying JIT.", String(result)) }
                    self.state = .failed
                    self.stopTimer()
                    LogStore.shared.log("[jit-entry] probe failed result=\(result); periodic execution stopped")
                }
            }
            if self.pendingLaunch != nil { self.releaseBeforeLaunch() }
        }
    }

    /// Release the retained scratch pair after the last probe and before the
    /// production pool. The native release performs no debugger transaction.
    /// No new probe can start after this handoff, including late JIT callbacks.
    func deferLaunchUntilProbeFinishes(_ launch: @escaping () -> Void, failed: @escaping (String) -> Void) -> Bool {
        stoppedForLaunch = true
        stopTimer()
        state = .stopped
        if cleanupFailed {
            state = .failed
            failed(error ?? L("The JIT probe could not release its temporary memory. Close and reopen Madeira before starting Steam."))
            return true
        }
        if releasedForLaunch { return false }
        if pendingLaunch == nil { pendingLaunch = launch; pendingFailure = failed }
        if !probing { releaseBeforeLaunch() }
        return true
    }

    private func releaseBeforeLaunch() {
        guard !probing, !releasing, pendingLaunch != nil else { return }
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
                self.error = L("The JIT probe could not release its temporary memory. Close and reopen Madeira before starting Steam.")
                LogStore.shared.log("[jit-entry] scratch release failed result=\(result); launch handoff refused")
                failed?(self.error!)
            } else {
                self.releasedForLaunch = true
                LogStore.shared.log("[jit-entry] scratch mappings released; continuing Wine startup")
                launch?()
            }
        }
    }
}

// MARK: - Production adapter

extension AppEntryJIT.Services {
    @MainActor static var live: Self {
        Self(enable: { JITCoordinator.shared.enable(completion: $0) },
             ready: { StikJITHelper.ready && wine_process_is_running() == 0 && wineserver_is_running() == 0 },
             attached: { isDebuggerAttached() },
             probe: { completion in
                 DispatchQueue.global(qos: .utility).async {
                     let result = jit_entry_probe_once()
                     DispatchQueue.main.async { completion(result) }
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
        case .monitoring: return L("JIT is ready. A separate 16 KiB probe runs every 5 seconds until Steam starts.")
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
                            LabeledContent(L("Probe buffer"), value: "16 KiB")
                            LabeledContent(L("Successful probes"), value: String(model.successfulProbes))
                            LabeledContent(L("Last probe result"), value: model.lastProbeResult.map(String.init) ?? L("Not tested yet"))
                            if let date = model.lastProbeFinishedAt {
                                LabeledContent(L("Last probe time"), value: date.formatted(date: .omitted, time: .standard))
                            }
                        }
                        Section {
                            Text("The ring completes one cycle every 5 seconds. Green means the latest probe returned 42; red means untested, unavailable, failed or stale. Animation alone does not prove JIT is working.")
                            Text("The probe reuses a separate 16 KiB buffer, wipes its code each round and releases its mappings before Steam starts.")
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
            return result == 42 && model.probeIsHealthy(at: .now) ? L("Probe passed") : L("Probe failed or result expired")
        }
    }
}
