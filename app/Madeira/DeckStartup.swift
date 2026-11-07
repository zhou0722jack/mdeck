// SPDX-License-Identifier: GPL-3.0-or-later
import SwiftUI
import AVFoundation
import UIKit

// MARK: - Startup policy

enum DeckSetupComponent: String, CaseIterable, Identifiable {
    case mono, visualCPP, gecko, dock
    var id: String { rawValue }
}

enum DeckStartupRules {
    static let choiceKey = "deck.startup.jitChoice"
    static let completeKey = "deck.startup.componentsReady"
    static let movieKey = "deck.startup.movie"
    static let soundKey = "deck.startup.sound"

    static func validChoice(_ value: String?) -> Bool {
        value == "externalScript" || value == "builtIn"
    }

    static func complete(_ ready: Set<DeckSetupComponent>) -> Bool {
        Set(DeckSetupComponent.allCases).isSubset(of: ready)
    }
}

// MARK: - Component preparation

@MainActor final class DeckComponentPreparation: ObservableObject {
    static let shared = DeckComponentPreparation()

    enum State: Equatable {
        case waiting
        case working(String, Double?)
        case ready
        case failed(String)
    }

    @Published private(set) var states: [DeckSetupComponent: State] = [:]
    @Published private(set) var running = false
    private let defaults: UserDefaults
    private var completions: [(Bool) -> Void] = []
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    var readyCount: Int { states.values.filter { $0 == .ready }.count }
    var complete: Bool { DeckStartupRules.complete(Set(states.compactMap { $0.value == .ready ? $0.key : nil })) }
    var available: Bool { DeckSetupComponent.allCases.allSatisfy { isReady($0) } }
    var loadingFraction: Double? {
        var total = 0.0
        for component in DeckSetupComponent.allCases {
            switch states[component] ?? .waiting {
            case .ready: total += 1
            case .working(_, let fraction):
                guard let fraction else { return nil }
                total += min(1, max(0, fraction))
            case .waiting: return nil
            case .failed: break
            }
        }
        return total / Double(DeckSetupComponent.allCases.count)
    }

    func prepare(completion: @escaping (Bool) -> Void = { _ in }) {
        if running { completions.append(completion); return }
        guard LibraryModel.shared.current == nil, wine_process_is_running() == 0, wineserver_is_running() == 0 else {
            for component in DeckSetupComponent.allCases {
                states[component] = .failed(L("End the current session before preparing components."))
            }
            completion(false)
            return
        }
        running = true
        completions.append(completion)
        states = Dictionary(uniqueKeysWithValues: DeckSetupComponent.allCases.map { ($0, .waiting) })
        LogStore.shared.log("[deck-components] concurrent preparation started")
        // Each installer owns a separate destination. Start every missing
        // component before awaiting any download; existing work is joined.
        for component in DeckSetupComponent.allCases {
            if isReady(component) { states[component] = .ready; continue }
            if !isBusy(component) { start(component) }
        }
        Task {
            var pending = Set(DeckSetupComponent.allCases.filter { states[$0] != .ready })
            while !pending.isEmpty {
                for component in pending {
                    if isBusy(component) {
                        states[component] = progress(component)
                    } else {
                        states[component] = isReady(component) ? .ready
                            : .failed(failure(component) ?? L("Component preparation did not finish. Try again."))
                        pending.remove(component)
                    }
                }
                if !pending.isEmpty {
                    try? await Task.sleep(nanoseconds: 150_000_000)
                }
            }
            running = false
            defaults.set(complete, forKey: DeckStartupRules.completeKey)
            LogStore.shared.log("[deck-components] preparation ready=\(readyCount)/4")
            let callbacks = completions
            completions.removeAll()
            let success = complete
            for callback in callbacks { callback(success) }
        }
    }

    private func isReady(_ component: DeckSetupComponent) -> Bool {
        switch component {
        case .mono: return WineMonoModel.available
        case .visualCPP:
            VCRedistModel.shared.refresh()
            return VCRedistModel.shared.complete
        case .gecko: return WineGeckoModel.available
        case .dock: return MadeiraDock.bundled && MadeiraDock.clientInstalled
        }
    }

    private func start(_ component: DeckSetupComponent) {
        switch component {
        case .mono: WineMonoModel.shared.install()
        case .visualCPP: VCRedistModel.shared.install()
        case .gecko: WineGeckoModel.shared.install()
        case .dock:
            if MadeiraDock.bundled { MadeiraDockModel.shared.prepareClient() }
        }
    }

    private func isBusy(_ component: DeckSetupComponent) -> Bool {
        switch component {
        case .mono: return WineMonoModel.shared.busy
        case .visualCPP: return VCRedistModel.shared.busy
        case .gecko: return WineGeckoModel.shared.busy
        case .dock: return MadeiraDockModel.shared.preparing
        }
    }

    private func progress(_ component: DeckSetupComponent) -> State {
        switch component {
        case .mono:
            switch WineMonoModel.shared.phase {
            case .downloading(let value): return .working(L("Downloading Wine Mono…"), value)
            case .installing(let value): return .working(L("Unpacking and verifying…"), value)
            case .idle: return .waiting
            }
        case .visualCPP:
            switch VCRedistModel.shared.phase {
            case .downloading(let value): return .working(L("Downloading Visual C++…"), value)
            case .installing(let value): return .working(L("Unpacking and verifying…"), value)
            case .idle: return .waiting
            }
        case .gecko: return .working(L("Downloading Wine Gecko…"), WineGeckoModel.shared.progress)
        case .dock: return .working(MadeiraDockModel.shared.progress, nil)
        }
    }

    private func failure(_ component: DeckSetupComponent) -> String? {
        switch component {
        case .mono: return WineMonoModel.shared.error
        case .visualCPP: return VCRedistModel.shared.error
        case .gecko: return WineGeckoModel.shared.error
        case .dock:
            return MadeiraDock.bundled ? MadeiraDockModel.shared.error : L("This build is missing Madeira Dock. Install a complete IPA and try again.")
        }
    }
}

@MainActor final class DeckStartupModel: ObservableObject {
    static let shared = DeckStartupModel()
    enum Phase { case chooseJIT, ready }
    @Published private(set) var phase: Phase
    private let defaults: UserDefaults
    var blocking: Bool { phase != .ready }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        phase = DeckStartupRules.validChoice(defaults.string(forKey: DeckStartupRules.choiceKey)) ? .ready : .chooseJIT
    }

    func choose(_ method: JITMethod) {
        guard phase == .chooseJIT, JITMethod.launcherChoices.contains(method) else { return }
        guard method != .builtIn || MadeiraBuiltInJIT.isAvailable else { return }
        JITCoordinator.shared.method = method
        defaults.set(method.rawValue, forKey: DeckStartupRules.choiceKey)
        phase = .ready
    }
}

struct DeckSteamFrame: Equatable {
    var image: String
    var width: Int
    var height: Int
    var visible: Bool
    var drawn: Bool
}

enum DeckSteamFrameRules {
    static func path(_ value: String) -> String {
        var result = value.lowercased().replacingOccurrences(of: "/", with: "\\")
        if result.hasPrefix("\\??\\") || result.hasPrefix("\\\\?\\") { result.removeFirst(4) }
        return result
    }

    static func accepts(_ frame: DeckSteamFrame, target: String, installer: Bool) -> Bool {
        guard frame.visible, frame.drawn, frame.width >= 160, frame.height >= 100 else { return false }
        let image = path(frame.image), expected = path(target)
        guard !image.isEmpty, !expected.isEmpty else { return false }
        if image == expected { return true }
        guard !installer, let slash = expected.lastIndex(of: "\\") else { return false }
        let directory = String(expected[...slash])
        return image.hasPrefix(directory) && !image.hasPrefix(directory + "steamapps\\")
            && image.split(separator: "\\").last == "steamwebhelper.exe"
    }
}

struct DeckSteamSetupStatus {
    enum Stage: String { case installer, checking, starting, waiting, failed }
    var stage: Stage
    var code: UInt32
    var step: Int
    var percent: Int
    var blocked: Int
    static func decode(_ text: String, step: Int, percent: Int, blocked: Int) -> Self? {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        guard lines.count == 4, lines[0] == "v1", lines[3].isEmpty,
              lines[1].hasPrefix("stage="), lines[2].hasPrefix("error="),
              let stage = Stage(rawValue: String(lines[1].dropFirst(6))),
              let code = UInt32(lines[2].dropFirst(6)), stage == .failed || code == 0 else { return nil }
        return Self(stage: stage, code: code, step: step, percent: percent, blocked: blocked)
    }
    var failure: String? {
        if stage == .failed { return LF("Steam preparation failed (%@). Check the log.", String(code)) }
        guard stage == .installer else { return nil }
        switch blocked {
        case 1: return L("Steam setup reached an unknown page. Check the log.")
        case 2: return L("Steam setup is not using the expected installation folder. Check the log.")
        case 3: return L("Steam setup controls could not be updated. Check the log.")
        default: return nil
        }
    }
    var message: String {
        switch stage {
        case .installer:
            if step >= 5 { return L("Finishing Steam setup…") }
            if step == 4 { return L("Installing Steam files…") }
            return L("Preparing the Steam installation…")
        case .checking: return L("Steam setup closed. Checking the client…")
        case .starting: return L("Starting Steam with compatibility options…")
        case .waiting: return L("Waiting for Steam's first frame…")
        case .failed: return failure ?? L("Steam could not start. Check the log.")
        }
    }
}

/// One continuous loading layer: components -> Steam/JIT startup -> a real
/// visible frame from this client's window. No movie-duration or global-frame
/// counter can complete a request, and stale JIT completions cannot launch it.
@MainActor final class DeckSteamLaunchPreparation: ObservableObject {
    static let shared = DeckSteamLaunchPreparation()
    enum Phase: Equatable { case idle, components, starting, installing, waitingForFrame, revealing, failed }
    @Published private(set) var presented = false
    @Published private(set) var phase: Phase = .idle
    @Published private(set) var error: String?
    @Published private(set) var installer = false
    @Published private(set) var startedAt = Date()
    @Published private(set) var closing = false
    @Published private(set) var slow = false
    @Published private(set) var setupMessage: String?
    @Published private(set) var setupFraction: Double?
    private let preparation: DeckComponentPreparation
    private var launch: ((UUID) -> Void)?
    private var requestID: UUID?
    private var preparationStarted = false
    private var target = ""
    private var session: UUID?
    private var waitingSince = Date()
    private var waitingVisibleSince: Date?
    private var firstFrameSeenAt: Date?
    var revealID: UUID? { phase == .revealing ? requestID : nil }
    // Keep the waiting stage visible after both its view and a real target
    // frame arrive. The main JIT pool can suspend the whole process, so elapsed
    // time since session startup cannot establish that this stage was painted.
    static let minimumVisibleWait: TimeInterval = 0.7
    static let revealDuration: TimeInterval = 0.45
    static let frameSlowAfter: TimeInterval = 120

    init(preparation: DeckComponentPreparation? = nil) {
        self.preparation = preparation ?? .shared
    }

    func request(target: String, installer: Bool, launch: @escaping (UUID) -> Void) {
        guard !presented else { return }
        requestID = UUID()
        self.target = target
        self.installer = installer
        self.launch = launch
        error = nil
        closing = false
        slow = false
        setupMessage = nil; setupFraction = nil
        startedAt = Date()
        session = nil
        waitingVisibleSince = nil
        firstFrameSeenAt = nil
        preparationStarted = false
        phase = .components
        presented = true
    }

    func beginPreparation() {
        guard presented, phase == .components, !preparationStarted else { return }
        preparationStarted = true
        prepare()
    }

    func retry() {
        guard presented, phase == .failed, session == nil, !preparation.running else { return }
        requestID = UUID()
        error = nil
        slow = false
        closing = false
        phase = .components
        prepare()
    }

    private func prepare() {
        let id = requestID
        preparation.prepare { [weak self] success in
            guard let self, self.presented, self.phase == .components, self.requestID == id else { return }
            if success {
                self.phase = .starting
                LogStore.shared.log("[steam-loading] components ready; starting Steam")
                if let id { self.launch?(id) }
            } else {
                self.fail(L("Some components could not be prepared. Retry the missing downloads."))
            }
        }
    }

    func permitsLaunch(_ id: UUID) -> Bool {
        presented && phase == .starting && requestID == id
    }

    func resolvedRoute(installer: Bool) {
        guard presented, phase == .starting else { return }
        self.installer = installer
    }

    @discardableResult func sessionStarted(_ id: UUID, at date: Date = .now) -> Bool {
        guard presented, phase == .starting else { return false }
        session = id
        waitingSince = date
        waitingVisibleSince = nil
        firstFrameSeenAt = nil
        phase = installer ? .installing : .waitingForFrame
        LogStore.shared.log(installer ? "[steam-loading] setup controller started; installer remains covered" : "[steam-loading] waiting for target window first frame")
        return true
    }

    func observeSetup(_ status: DeckSteamSetupStatus?, at date: Date = .now) {
        guard presented, phase == .installing, let status else { return }
        if let failure = status.failure { fail(failure); return }
        setupMessage = status.message
        setupFraction = status.stage == .installer && status.step == 4 && (0...100).contains(status.percent)
            ? Double(status.percent) / 100 : nil
        if status.stage == .waiting {
            installer = false
            setupMessage = nil; setupFraction = nil
            waitingSince = date; waitingVisibleSince = nil; firstFrameSeenAt = nil
            phase = .waitingForFrame
            LogStore.shared.log("[steam-loading] installer exited; client launched; waiting for Steam image")
        }
    }

    func waitingStageShown(at date: Date = .now) {
        guard presented, phase == .waitingForFrame, waitingVisibleSince == nil else { return }
        waitingVisibleSince = date
    }

    func observe(_ frames: [DeckSteamFrame], at date: Date = .now) {
        guard presented, phase == .waitingForFrame else { return }
        if frames.contains(where: { DeckSteamFrameRules.accepts($0, target: target, installer: installer) }) {
            if firstFrameSeenAt == nil { firstFrameSeenAt = date }
            guard let waitingVisibleSince, let firstFrameSeenAt,
                  date.timeIntervalSince(max(waitingVisibleSince, firstFrameSeenAt)) >= Self.minimumVisibleWait else { return }
            error = nil
            phase = .revealing
            LogStore.shared.log("[steam-loading] target first frame received; revealing Steam beneath loading layer")
        } else if !slow && date.timeIntervalSince(waitingSince) >= Self.frameSlowAfter {
            slow = true
            error = L("Steam is taking longer than expected. Still waiting for its first frame…")
        }
    }

    func completeReveal(_ id: UUID) {
        guard presented, revealID == id else { return }
        LogStore.shared.log("[steam-loading] reveal fade completed; loading layer closed")
        finish()
    }

    func fail(_ message: String) {
        guard presented else { return }
        error = message
        phase = .failed
    }

    func sessionEnded(_ message: String?) {
        guard presented, session != nil else { return }
        if closing { finish(); return }
        session = nil
        fail(message ?? L("Steam closed before its first frame appeared. Check the session log."))
    }

    func closeRequested() {
        closing = true
        fail(L("Closing the Steam session…"))
    }

    func returnToLibrary() {
        guard !preparation.running, session == nil else { return }
        finish()
    }

    private func finish() {
        requestID = nil
        launch = nil
        preparationStarted = false
        session = nil
        waitingVisibleSince = nil
        firstFrameSeenAt = nil
        phase = .idle
        setupMessage = nil; setupFraction = nil
        presented = false
    }
}

// MARK: - Startup views

struct DeckStartupRoot<Content: View>: View {
    @ObservedObject private var startup = DeckStartupModel.shared
    @Environment(\.accessibilityReduceMotion) private var reduced
    @Environment(\.scenePhase) private var entryScenePhase
    @AppStorage(DeckStartupRules.movieKey) private var movieEnabled = true
    @AppStorage(DeckStartupRules.soundKey) private var soundEnabled = true
    @State private var movieFinished = false
    @ViewBuilder var content: () -> Content

    var body: some View {
        Group {
            if startup.phase == .chooseJIT {
                DeckJITChoiceView(choose: startup.choose)
            } else if startup.phase == .ready && (movieFinished || !movieEnabled || reduced) {
                content()
            } else {
                ZStack {
                    Color.black.ignoresSafeArea()
                    if !movieFinished && movieEnabled && !reduced {
                        DeckBootMovie(sound: soundEnabled) { movieFinished = true }
                            .ignoresSafeArea()
                            .contentShape(Rectangle())
                            .onTapGesture(count: 2) { movieFinished = true }
                            .accessibilityLabel(Text("Startup animation"))
                            .accessibilityHint(Text("Double-tap to skip the animation."))
                            .accessibilityAction(named: Text("Skip animation")) { movieFinished = true }
                    } else {
                        VStack(spacing: 16) {
                            DeckMark().frame(width: 80, height: 80)
                            Text("mdeck").font(.system(size: 36, weight: .bold, design: .rounded))
                        }.frame(maxHeight: .infinity, alignment: .top).padding(.top, 44)
                    }
                }.foregroundStyle(.white)
            }
        }
        .onAppear { AppEntryJIT.shared.sceneChanged(active: entryScenePhase == .active, allowed: startup.phase == .ready) }
        .onChange(of: entryScenePhase) { _, phase in
            AppEntryJIT.shared.sceneChanged(active: phase == .active, allowed: startup.phase == .ready)
        }
        .onChange(of: startup.phase) { _, phase in
            AppEntryJIT.shared.sceneChanged(active: entryScenePhase == .active, allowed: phase == .ready)
        }
    }
}

struct DeckJITChoiceView: View {
    var choose: (JITMethod) -> Void
    @State private var selection: JITMethod = .externalScript
    @State private var showSetup = false
    @Environment(\.deckPalette) private var palette

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                DeckMark().frame(width: 56, height: 56)
                Text("Choose how to start JIT").font(.largeTitle.bold())
                Text("Choose once. You can change it later in Settings → JIT.").foregroundStyle(palette.muted)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 16)], spacing: 16) {
                    choice(.externalScript, title: "Script JIT", symbol: "curlybraces",
                           detail: "Run madeira-jit.js in StikDebug, then return here and start Steam.")
                    choice(.builtIn, title: "Built-in JIT", symbol: "bolt.shield",
                           detail: "Madeira starts its own JIT helper. Pair this device and connect LocalDevVPN first.")
                }
                if selection == .externalScript {
                    if let url = StikJITHelper.scriptURL {
                        ShareLink(item: url) { Label("Export Madeira JIT script", systemImage: "square.and.arrow.up") }
                            .buttonStyle(DeckButtonStyle())
                    }
                } else {
                    Button("Configure built-in JIT") {
                        JITCoordinator.shared.method = .builtIn
                        showSetup = true
                    }.buttonStyle(DeckButtonStyle())
                }
                Button("Continue") { choose(selection) }
                    .buttonStyle(DeckButtonStyle(primary: true))
                Text("Wine Mono, Visual C++, Wine Gecko and Madeira Dock are checked and downloaded together when you start Steam.")
                    .font(.footnote).foregroundStyle(palette.muted)
            }.padding(28).frame(maxWidth: 760).frame(maxWidth: .infinity, minHeight: 520)
        }
        .background(palette.background.ignoresSafeArea()).foregroundStyle(palette.text)
        .sheet(isPresented: $showSetup) { JITSetupView() }
    }

    private func choice(_ method: JITMethod, title: LocalizedStringKey, symbol: String, detail: LocalizedStringKey) -> some View {
        let available = method != .builtIn || MadeiraBuiltInJIT.isAvailable
        return Button { selection = method } label: {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Image(systemName: symbol).font(.title2)
                    Spacer()
                    Image(systemName: selection == method ? "checkmark.circle.fill" : "circle")
                }.foregroundStyle(selection == method ? palette.accent : palette.muted)
                Text(title).font(.title3.bold())
                Text(detail).font(.subheadline).foregroundStyle(palette.muted)
                if !available, let reason = MadeiraBuiltInJIT.unavailableReason {
                    Text(reason).font(.caption).foregroundStyle(.orange)
                }
            }.padding(20).frame(maxWidth: .infinity, minHeight: 190, alignment: .topLeading)
                .background(selection == method ? palette.accent.opacity(0.1) : palette.surface, in: RoundedRectangle(cornerRadius: 18))
                .overlay(RoundedRectangle(cornerRadius: 18).stroke(selection == method ? palette.accent : palette.line, lineWidth: 1))
                .contentShape(RoundedRectangle(cornerRadius: 18))
        }.buttonStyle(.plain).disabled(!available)
            .accessibilityAddTraits(selection == method ? .isSelected : [])
    }
}

struct DeckComponentProgress: View {
    @ObservedObject private var preparation = DeckComponentPreparation.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text("Preparing components").font(.title3.bold())
                Spacer()
                Text("\(preparation.readyCount) / 4").font(.subheadline.monospacedDigit()).foregroundStyle(.secondary)
            }
            ForEach(DeckSetupComponent.allCases) { component in
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: preparation.states[component] == .ready ? "checkmark.circle.fill" : "shippingbox")
                        .foregroundStyle(preparation.states[component] == .ready ? Color.green : Color.secondary)
                        .frame(width: 24)
                    VStack(alignment: .leading, spacing: 5) {
                        Text(title(component)).font(.subheadline.weight(.semibold))
                        switch preparation.states[component] ?? .waiting {
                        case .waiting: Text("Waiting").font(.caption).foregroundStyle(.secondary)
                        case .ready: Text("Ready").font(.caption).foregroundStyle(.secondary)
                        case .working(let detail, let fraction):
                            Text(detail).font(.caption).foregroundStyle(.secondary)
                            if let fraction { ProgressView(value: min(1, max(0, fraction))) }
                            else { ProgressView().controlSize(.small) }
                        case .failed(let message): Text(message).font(.caption).foregroundStyle(.orange).textSelection(.enabled)
                        }
                    }
                    Spacer(minLength: 0)
                }
            }
        }
    }

    private func title(_ component: DeckSetupComponent) -> String {
        switch component {
        case .mono: return "Wine Mono"
        case .visualCPP: return "Microsoft Visual C++"
        case .gecko: return "Wine Gecko"
        case .dock: return "Madeira Dock"
        }
    }
}

struct DeckSteamPreparationView: View {
    @ObservedObject private var preparation = DeckComponentPreparation.shared
    @ObservedObject private var launch = DeckSteamLaunchPreparation.shared
    @ObservedObject private var library = LibraryModel.shared
    @ObservedObject private var appearance = DeckAppearance.shared
    @State private var covers: [Image] = []
    @State private var layerOpacity = 1.0
    var body: some View {
        DeckSteamLoadingArtwork(phase: launch.phase, installer: launch.installer, error: launch.error,
                               startedAt: launch.startedAt, fraction: launch.phase == .installing ? launch.setupFraction : preparation.loadingFraction,
                               setupMessage: launch.setupMessage,
                               motionEnabled: appearance.animations, covers: covers) {
            if launch.phase == .components || (launch.phase == .failed && !preparation.complete) {
                DisclosureGroup("Component details") { DeckComponentProgress().padding(.top, 12) }
                    .font(.footnote).frame(maxWidth: 520).padding(.top, 20)
            }
            if launch.phase == .failed {
                HStack(spacing: 14) {
                    if library.current == nil && !preparation.running {
                        Button(preparation.complete ? L("Try again") : L("Retry downloads")) {
                            clearLaunchAlerts(); launch.retry()
                        }.buttonStyle(DeckButtonStyle(primary: true))
                    }
                    ShareLink(item: LogStore.shared.logURL) { Label("Share log", systemImage: "square.and.arrow.up") }
                        .buttonStyle(DeckButtonStyle())
                    if library.current != nil {
                        Button("Close session") { launch.closeRequested(); library.requestQuit() }
                            .buttonStyle(DeckButtonStyle()).disabled(launch.closing)
                    } else if !preparation.running {
                        Button("Return to library") { clearLaunchAlerts(); launch.returnToLibrary() }.buttonStyle(DeckButtonStyle())
                    }
                }.padding(.top, 22)
            } else if launch.phase != .components {
                HStack(spacing: 14) {
                    ShareLink(item: LogStore.shared.logURL) { Label("Share log", systemImage: "square.and.arrow.up") }
                        .buttonStyle(DeckButtonStyle())
                    Button("Cancel") {
                        if library.current != nil { launch.closeRequested(); library.requestQuit() }
                        else { launch.returnToLibrary() }
                    }.buttonStyle(DeckButtonStyle())
                }.padding(.top, 22)
            }
        }
        .opacity(layerOpacity)
        .onChange(of: launch.phase, initial: true) { _, phase in
            guard phase == .revealing, let id = launch.revealID else {
                layerOpacity = 1
                return
            }
            withAnimation(.easeOut(duration: DeckSteamLaunchPreparation.revealDuration), completionCriteria: .removed) {
                layerOpacity = 0
            } completion: {
                // A late animation callback must not dismiss a failed/retried launch.
                launch.completeReveal(id)
            }
        }
        .task(id: launch.phase) {
            if launch.phase == .waitingForFrame { launch.waitingStageShown() }
        }
        .task {
            covers = DeckSteamLocalCovers.images()
            LogStore.shared.log("[steam-loading] artwork motion=\(appearance.animations) application-active=\(DeckMotionActivity.shared.active)")
            launch.beginPreparation()
        }
    }

    private func clearLaunchAlerts() {
        library.error = nil
        library.jitNotice = nil
        library.restartNotice = nil
    }
}

struct DeckComponentSetupView: View {
    @ObservedObject private var preparation = DeckComponentPreparation.shared
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    DeckComponentProgress()
                    if !preparation.running {
                        Button("Prepare missing components") { preparation.prepare() }.buttonStyle(DeckButtonStyle(primary: true))
                    }
                }.padding(24).frame(maxWidth: 640).frame(maxWidth: .infinity)
            }
            .navigationTitle("Components")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() }.disabled(preparation.running) } }
            .task { preparation.prepare() }
        }.interactiveDismissDisabled(preparation.running)
    }
}

struct DeckBootSettings: View {
    @AppStorage(DeckStartupRules.movieKey) private var enabled = true
    @AppStorage(DeckStartupRules.soundKey) private var sound = true
    @State private var preview = false
    var body: some View {
        Section("Boot animation") {
            Toggle("Play DroidDeck startup animation", isOn: $enabled)
            Toggle("Startup sound", isOn: $sound).disabled(!enabled)
            Button("Preview startup animation") { preview = true }
        }
        .fullScreenCover(isPresented: $preview) {
            ZStack(alignment: .topTrailing) {
                Color.black.ignoresSafeArea()
                DeckBootMovie(sound: sound) { preview = false }.ignoresSafeArea()
                Button("Done") { preview = false }.buttonStyle(DeckButtonStyle()).padding(24)
            }
        }
    }
}

// MARK: - Native movie playback

struct DeckBootMovie: UIViewRepresentable {
    var sound: Bool
    var finished: () -> Void
    @Environment(\.scenePhase) private var scenePhase

    func makeCoordinator() -> Coordinator { Coordinator(finished: finished) }
    func makeUIView(context: Context) -> Surface {
        let surface = Surface()
        surface.backgroundColor = .black
        surface.movieLayer.videoGravity = .resizeAspect
        context.coordinator.start(surface: surface, sound: sound, active: scenePhase == .active)
        return surface
    }
    func updateUIView(_ view: Surface, context: Context) {
        context.coordinator.player?.isMuted = !sound
        context.coordinator.setActive(scenePhase == .active)
    }
    static func dismantleUIView(_ view: Surface, coordinator: Coordinator) {
        coordinator.stop()
        view.movieLayer.player = nil
    }

    final class Surface: UIView {
        override class var layerClass: AnyClass { AVPlayerLayer.self }
        var movieLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }

    @MainActor final class Coordinator {
        var player: AVPlayer?
        private var observation: NSKeyValueObservation?
        private var notifications: [NSObjectProtocol] = []
        private var watchdog: Task<Void, Never>?
        private var active = false
        private var ended = false
        private let finished: () -> Void
        init(finished: @escaping () -> Void) { self.finished = finished }

        func start(surface: Surface, sound: Bool, active: Bool) {
            guard let url = Bundle.main.url(forResource: "droiddeck-startup", withExtension: "mp4", subdirectory: "BootAnimation") else {
                Task { finish() }
                return
            }
            let item = AVPlayerItem(url: url)
            let player = AVPlayer(playerItem: item)
            self.player = player
            player.isMuted = !sound
            surface.movieLayer.player = player
            observation = item.observe(\.status, options: [.initial, .new]) { [weak self] item, _ in
                if item.status == .failed { Task { @MainActor in self?.finish() } }
            }
            for name in [AVPlayerItem.didPlayToEndTimeNotification, AVPlayerItem.failedToPlayToEndTimeNotification] {
                notifications.append(NotificationCenter.default.addObserver(forName: name, object: item, queue: .main) { [weak self] _ in
                    Task { @MainActor in self?.finish() }
                })
            }
            setActive(active)
            watchdog = Task { [weak self] in
                var activeTicks = 0
                while !Task.isCancelled {
                    do { try await Task.sleep(nanoseconds: 250_000_000) } catch { return }
                    guard let self, !self.ended else { return }
                    if self.active { activeTicks += 1 }
                    if activeTicks >= 64 { self.finish(); return }
                }
            }
        }

        func setActive(_ value: Bool) {
            guard active != value else { return }
            active = value
            if value && !ended { player?.play() } else { player?.pause() }
        }
        func finish() {
            guard !ended else { return }
            ended = true
            stop()
            finished()
        }
        func stop() {
            player?.pause()
            observation?.invalidate(); observation = nil
            notifications.forEach(NotificationCenter.default.removeObserver)
            notifications.removeAll()
            watchdog?.cancel(); watchdog = nil
        }
    }
}
