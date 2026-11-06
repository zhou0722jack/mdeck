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
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    var readyCount: Int { states.values.filter { $0 == .ready }.count }
    var complete: Bool { DeckStartupRules.complete(Set(states.compactMap { $0.value == .ready ? $0.key : nil })) }

    func prepare(completion: @escaping (Bool) -> Void = { _ in }) {
        guard !running else { return }
        guard LibraryModel.shared.current == nil, wine_process_is_running() == 0, wineserver_is_running() == 0 else {
            for component in DeckSetupComponent.allCases {
                states[component] = .failed(L("End the current session before preparing components."))
            }
            completion(false)
            return
        }
        running = true
        states = Dictionary(uniqueKeysWithValues: DeckSetupComponent.allCases.map { ($0, .waiting) })
        LogStore.shared.log("[deck-startup] component preparation started")
        Task {
            for component in DeckSetupComponent.allCases {
                if isReady(component) { states[component] = .ready; continue }
                start(component)
                while isBusy(component) {
                    states[component] = progress(component)
                    try? await Task.sleep(nanoseconds: 150_000_000)
                }
                if isReady(component) {
                    states[component] = .ready
                } else {
                    states[component] = .failed(failure(component) ?? L("Component preparation did not finish. Try again."))
                }
            }
            running = false
            if complete { defaults.set(true, forKey: DeckStartupRules.completeKey) }
            LogStore.shared.log("[deck-startup] component preparation ready=\(readyCount)/4")
            completion(complete)
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
    enum Phase { case chooseJIT, preparing, ready }
    @Published private(set) var phase: Phase
    private var started = false
    private let defaults: UserDefaults
    private let preparation: DeckComponentPreparation
    var blocking: Bool { phase != .ready }

    init(defaults: UserDefaults = .standard, preparation: DeckComponentPreparation? = nil) {
        self.defaults = defaults
        self.preparation = preparation ?? .shared
        if !DeckStartupRules.validChoice(defaults.string(forKey: DeckStartupRules.choiceKey)) {
            phase = .chooseJIT
        } else {
            phase = defaults.bool(forKey: DeckStartupRules.completeKey) ? .ready : .preparing
        }
    }

    func begin() {
        guard !started else { return }
        started = true
        if phase == .preparing { prepare() }
    }

    func choose(_ method: JITMethod) {
        guard phase == .chooseJIT, JITMethod.launcherChoices.contains(method) else { return }
        guard method != .builtIn || MadeiraBuiltInJIT.isAvailable else { return }
        JITCoordinator.shared.method = method
        defaults.set(method.rawValue, forKey: DeckStartupRules.choiceKey)
        prepare()
    }

    func prepare() {
        phase = .preparing
        preparation.prepare { [weak self] success in
            if success { self?.phase = .ready }
        }
    }

    func deferFailedDownloads() {
        guard !preparation.running else { return }
        phase = .ready
        LogStore.shared.log("[deck-startup] incomplete components deferred; retry on next launch")
    }
}

// MARK: - Startup views

struct DeckStartupRoot<Content: View>: View {
    @ObservedObject private var startup = DeckStartupModel.shared
    @ObservedObject private var preparation = DeckComponentPreparation.shared
    @Environment(\.accessibilityReduceMotion) private var reduced
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
                    VStack {
                        Spacer(minLength: 16)
                        if startup.phase == .preparing {
                            ScrollView {
                                DeckComponentProgress()
                                if !preparation.running && !preparation.complete {
                                    HStack(spacing: 14) {
                                        Button("Retry downloads") { startup.prepare() }.buttonStyle(DeckButtonStyle(primary: true))
                                        Button("Download later") { startup.deferFailedDownloads() }.buttonStyle(DeckButtonStyle())
                                    }.padding(.top, 12)
                                }
                            }.frame(maxHeight: 350)
                                .padding(20).background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 22))
                                .frame(maxWidth: 620)
                        }
                    }.padding(20)
                }.foregroundStyle(.white)
            }
        }
        .task { startup.begin() }
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
                Button("Continue and prepare components") { choose(selection) }
                    .buttonStyle(DeckButtonStyle(primary: true))
                Text("The first launch downloads Wine Mono, Visual C++, Wine Gecko and Madeira Dock components. Keep this app open until preparation finishes.")
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
                Text("Preparing first launch").font(.title3.bold())
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
