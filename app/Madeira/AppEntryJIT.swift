// SPDX-License-Identifier: GPL-3.0-or-later
import SwiftUI

// MARK: - Entry JIT policy

@MainActor final class AppEntryJIT: ObservableObject {
    struct Services {
        var enable: (@escaping (Result<Void, Error>) -> Void) -> Void
        var ready: () -> Bool
        var attached: () -> Bool
        var probe: (@escaping (Int64) -> Void) -> Void
        var schedule: (TimeInterval, @escaping () -> Void) -> (() -> Void)
    }
    static let shared = AppEntryJIT(services: .live)
    static let interval: TimeInterval = 5
    static let probeBytes = 16 * 1024
    enum State: Equatable { case idle, requesting, waiting, monitoring, paused, failed, stopped }
    @Published private(set) var state = State.idle
    @Published private(set) var error: String?
    @Published private(set) var successfulProbes = 0
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
        guard entered, foreground, allowed, !stoppedForLaunch, !nativeFailed, !probing, !enableInFlight else { return }
        guard services.ready(), services.attached() else {
            state = .waiting
            return
        }
        probing = true
        state = .monitoring
        services.probe { [weak self] result in
            guard let self else { return }
            self.probing = false
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
                    LogStore.shared.log("[jit-entry] probe \(self.successfulProbes): result=42; independent 16KiB mappings cleared")
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
            let launch = self.pendingLaunch
            let failed = self.pendingFailure
            self.pendingLaunch = nil
            self.pendingFailure = nil
            if self.cleanupFailed, launch != nil {
                self.state = .failed
                failed?(self.error ?? L("The JIT probe could not release its temporary memory. Close and reopen Madeira before starting Steam."))
            } else {
                if launch != nil { LogStore.shared.log("[jit-entry] active probe drained; continuing Wine startup") }
                launch?()
            }
        }
    }

    /// Returns true only when the caller must defer Wine startup. The native
    /// completion is delivered after wiping and unmapping both probe views.
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
        guard probing else { return false }
        if pendingLaunch == nil { pendingLaunch = launch; pendingFailure = failed }
        return true
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
