// SPDX-License-Identifier: GPL-3.0-or-later
import SwiftUI

struct DeckPalette {
    var background = Color(red: 10 / 255, green: 11 / 255, blue: 13 / 255)
    var surface = Color(red: 18 / 255, green: 20 / 255, blue: 23 / 255)
    var raised = Color(red: 26 / 255, green: 29 / 255, blue: 34 / 255)
    var line = Color(red: 38 / 255, green: 42 / 255, blue: 49 / 255)
    var text = Color(red: 242 / 255, green: 244 / 255, blue: 247 / 255)
    var muted = Color(red: 154 / 255, green: 163 / 255, blue: 175 / 255)
    var accent = Color(red: 26 / 255, green: 159 / 255, blue: 1)
    var second = Color(red: 20 / 255, green: 135 / 255, blue: 219 / 255)
    var onAccent = Color(red: 3 / 255, green: 17 / 255, blue: 31 / 255)
}

private struct DeckPaletteKey: EnvironmentKey {
    static let defaultValue = DeckPalette()
}

extension EnvironmentValues {
    var deckPalette: DeckPalette {
        get { self[DeckPaletteKey.self] }
        set { self[DeckPaletteKey.self] = newValue }
    }
}

@MainActor final class DeckAppearance: ObservableObject {
    static let shared = DeckAppearance()
    @Published var theme: String { didSet { UserDefaults.standard.set(theme, forKey: "deck.theme") } }
    @Published var animations: Bool { didSet { UserDefaults.standard.set(animations, forKey: "deck.animations") } }
    @Published var railLabels: Bool { didSet { UserDefaults.standard.set(railLabels, forKey: "deck.railLabels") } }
    @Published var scale: Double { didSet { UserDefaults.standard.set(scale, forKey: "deck.scale") } }
    @Published var rgbSpeed: Double { didSet { UserDefaults.standard.set(rgbSpeed, forKey: "deck.rgbSpeed") } }
    @Published var gradientPrimary: Color { didSet { Self.saveColor(gradientPrimary, key: "deck.gradientPrimary") } }
    @Published var gradientSecondary: Color { didSet { Self.saveColor(gradientSecondary, key: "deck.gradientSecondary") } }

    private init() {
        let defaults = UserDefaults.standard
        theme = defaults.string(forKey: "deck.theme") ?? "graphite"
        animations = defaults.object(forKey: "deck.animations") as? Bool ?? true
        railLabels = defaults.object(forKey: "deck.railLabels") as? Bool ?? true
        scale = defaults.object(forKey: "deck.scale") as? Double ?? 1
        rgbSpeed = defaults.object(forKey: "deck.rgbSpeed") as? Double ?? 3
        gradientPrimary = Self.readColor(key: "deck.gradientPrimary", fallback: [0.55, 0.36, 0.96])
        gradientSecondary = Self.readColor(key: "deck.gradientSecondary", fallback: [0.13, 0.83, 0.93])
    }

    private static func readColor(key: String, fallback: [Double]) -> Color {
        let values = UserDefaults.standard.array(forKey: key) as? [Double] ?? fallback
        guard values.count == 3 else { return Color(red: fallback[0], green: fallback[1], blue: fallback[2]) }
        return Color(red: values[0], green: values[1], blue: values[2])
    }

    private static func saveColor(_ color: Color, key: String) {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        if UIColor(color).getRed(&r, green: &g, blue: &b, alpha: &a) {
            UserDefaults.standard.set([Double(r), Double(g), Double(b)], forKey: key)
        }
    }

    func palette(at date: Date = .now) -> DeckPalette {
        var p = DeckPalette()
        switch theme {
        case "paper":
            p.background = .black; p.surface = Color(white: 0.06); p.raised = Color(white: 0.1)
            p.accent = Color(white: 0.98); p.second = Color(white: 0.85); p.onAccent = .black
        case "blue":
            p.background = Color(red: 0.02, green: 0.025, blue: 0.035)
            p.accent = Color(red: 0.075, green: 0.42, blue: 0.88)
            p.second = Color(red: 0.045, green: 0.31, blue: 0.69); p.onAccent = .white
        case "electric":
            p.background = Color(red: 0.027, green: 0.04, blue: 0.065)
            p.surface = Color(red: 0.06, green: 0.08, blue: 0.13)
            p.accent = Color(red: 0.18, green: 0.53, blue: 1)
        case "gradient":
            p.background = Color(red: 0.045, green: 0.025, blue: 0.075)
            p.surface = Color(red: 0.075, green: 0.055, blue: 0.11)
            p.accent = gradientPrimary
            p.second = gradientSecondary; p.onAccent = .white
        case "innerGamer":
            let hue = animations ? (date.timeIntervalSinceReferenceDate * rgbSpeed / 30).truncatingRemainder(dividingBy: 1) : 0.3
            p.accent = Color(hue: hue, saturation: 0.85, brightness: 1)
            p.second = Color(hue: (hue + 1 / 6).truncatingRemainder(dividingBy: 1), saturation: 0.8, brightness: 1)
        default: break
        }
        return p
    }
}

struct DeckThemeHost<Content: View>: View {
    @ObservedObject private var appearance = DeckAppearance.shared
    @ObservedObject private var session = LibraryModel.shared
    @Environment(\.accessibilityReduceMotion) private var reduced
    @Environment(\.scenePhase) private var scenePhase
    @ViewBuilder var content: () -> Content

    var body: some View {
        TimelineView(.animation(minimumInterval: 0.1, paused: appearance.theme != "innerGamer" || !appearance.animations || reduced || session.current != nil || scenePhase != .active)) { context in
            let palette = appearance.palette(at: context.date)
            content()
                .environment(\.deckPalette, palette)
                .tint(palette.accent)
                .preferredColorScheme(.dark)
                .font(.system(size: 15 * min(1.3, max(0.8, appearance.scale))))
                .transaction { if !appearance.animations || reduced { $0.disablesAnimations = true } }
        }
    }
}

enum DeckDestination: String, CaseIterable, Identifiable {
    case steam, library, stores, desktop, components, apps, settings, updates, diagnostics
    static let allCases: [DeckDestination] = [.steam, .library, .stores, .desktop, .components, .apps, .settings, .updates]
    var id: String { rawValue }
    var title: String {
        switch self {
        case .steam: return L("Steam")
        case .library: return L("Library")
        case .stores: return L("Stores")
        case .desktop: return L("Desktop")
        case .components: return L("Components")
        case .apps: return L("Apps")
        case .settings: return L("Settings")
        case .updates: return L("Updates")
        case .diagnostics: return L("Diagnostics")
        }
    }
    var icon: String {
        switch self {
        case .steam: return "gamecontroller"
        case .library: return "rectangle.stack"
        case .stores: return "bag"
        case .desktop: return "desktopcomputer"
        case .components: return "square.3.layers.3d"
        case .apps: return "square.grid.2x2"
        case .settings: return "slider.horizontal.3"
        case .updates: return "arrow.down.app"
        case .diagnostics: return "waveform.path.ecg"
        }
    }
}

struct DeckNavigation: View {
    @Binding var selection: DeckDestination
    var horizontal: Bool
    @Environment(\.deckPalette) private var palette
    @Environment(\.accessibilityReduceMotion) private var reduced
    @ObservedObject private var appearance = DeckAppearance.shared
    @Namespace private var highlight

    var body: some View {
        Group {
            if horizontal {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 3) { items }.padding(.horizontal, 5).padding(.vertical, 5)
                }.frame(height: 67)
            } else {
                VStack(spacing: 4) {
                    ScrollView(showsIndicators: false) { VStack(spacing: 4) { items } }
                    DeckMark().frame(width: 28, height: 28).padding(.bottom, 16)
                }.padding(.top, 12).frame(width: appearance.railLabels ? 92 : 64)
            }
        }
        .background(palette.surface)
        .overlay(alignment: horizontal ? .top : .trailing) {
            Rectangle().fill(palette.line).frame(width: horizontal ? nil : 1, height: horizontal ? 1 : nil)
        }
    }

    private var items: some View {
        ForEach(DeckDestination.allCases) { destination in
            Button {
                withAnimation(reduced || !appearance.animations ? nil : .spring(response: 0.38, dampingFraction: 0.78)) {
                    selection = destination
                }
            } label: {
                VStack(spacing: 5) {
                    Image(systemName: destination.icon).font(.system(size: 21, weight: .medium))
                    if horizontal || appearance.railLabels { Text(destination.title).font(.system(size: 10, weight: .medium)).lineLimit(1) }
                }
                .foregroundStyle(selection == destination ? palette.accent : palette.muted)
                .frame(width: horizontal ? 69 : appearance.railLabels ? 82 : 54, height: horizontal ? 55 : 61)
                .background {
                    if selection == destination {
                        RoundedRectangle(cornerRadius: 14).fill(palette.accent.opacity(0.14))
                            .matchedGeometryEffect(id: "deck-navigation", in: highlight)
                    }
                }
                .contentShape(RoundedRectangle(cornerRadius: 14))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(destination.title)
            .accessibilityAddTraits(selection == destination ? .isSelected : [])
        }
    }
}

struct DeckMark: View {
    @Environment(\.deckPalette) private var palette
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                Circle().stroke(palette.text, lineWidth: geometry.size.width * 0.14)
                Rectangle().fill(palette.background).frame(width: geometry.size.width * 0.09).rotationEffect(.degrees(8))
                Circle().fill(palette.accent).padding(geometry.size.width * 0.26)
            }.padding(geometry.size.width * 0.08)
        }.accessibilityHidden(true)
    }
}

struct DeckButtonStyle: ButtonStyle {
    var primary = false
    @Environment(\.deckPalette) private var palette
    @Environment(\.isEnabled) private var enabled
    @Environment(\.accessibilityReduceMotion) private var reduced

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: primary ? 16 : 14, weight: .semibold))
            .padding(.horizontal, primary ? 22 : 15).frame(minHeight: primary ? 50 : 43)
            .foregroundStyle(primary ? palette.onAccent : palette.text)
            .background {
                if primary {
                    Capsule().fill(LinearGradient(colors: [palette.accent, palette.second], startPoint: .leading, endPoint: .trailing))
                } else {
                    Capsule().fill(palette.raised.opacity(configuration.isPressed ? 1 : 0.75))
                }
            }
            .overlay(Capsule().stroke(primary ? Color.clear : palette.line, lineWidth: 1))
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .opacity(enabled ? 1 : 0.42)
            .animation(reduced || !DeckAppearance.shared.animations ? nil : .easeOut(duration: 0.15), value: configuration.isPressed)
    }
}

struct DeckIconButton: View {
    let title: String
    let symbol: String
    var action: () -> Void
    @Environment(\.deckPalette) private var palette
    var body: some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 19, weight: .medium))
                .frame(width: 42, height: 42).contentShape(RoundedRectangle(cornerRadius: 10))
        }.buttonStyle(.plain).foregroundStyle(palette.muted).accessibilityLabel(title)
    }
}

struct DeckPageHeading<Trailing: View>: View {
    var title: String
    var subtitle: String? = nil
    @ViewBuilder var trailing: () -> Trailing
    @Environment(\.deckPalette) private var palette
    var body: some View {
        HStack(spacing: 10) {
            Text(title).font(.system(size: 25, weight: .bold)).foregroundStyle(palette.text)
            if let subtitle { Text(subtitle).font(.caption).foregroundStyle(palette.muted) }
            Spacer(minLength: 2)
            trailing()
        }.padding(.horizontal, 20).padding(.vertical, 10)
    }
}

struct DeckFormSkin: ViewModifier {
    @Environment(\.deckPalette) private var palette
    func body(content: Content) -> some View {
        content
            .scrollContentBackground(.hidden)
            .background(palette.background)
            .tint(palette.accent)
    }
}

struct DeckSettingsRoute: Identifiable {
    let page: SettingsPages.Page
    var id: SettingsPages.Page { page }
}

enum DeckSetupTab: String, CaseIterable, Identifiable {
    case overview, controller, launcher, storage, diagnostics, glasses
    var id: String { rawValue }
    var title: String {
        switch self {
        case .overview: return L("Overview")
        case .controller: return L("Controller")
        case .launcher: return L("Launcher")
        case .storage: return L("Storage")
        case .diagnostics: return L("Diagnostics")
        case .glasses: return L("Smart glasses")
        }
    }
}

struct DeckSetupTabs: View {
    @Binding var selected: DeckSetupTab
    @Environment(\.deckPalette) private var palette
    @Environment(\.accessibilityReduceMotion) private var reduced
    @Namespace private var indicator
    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 7) {
                ForEach(DeckSetupTab.allCases) { tab in
                    Button {
                        withAnimation(reduced ? nil : .spring(response: 0.35, dampingFraction: 0.78)) { selected = tab }
                    } label: {
                        Text(tab.title).font(.system(size: 12, weight: .medium))
                            .padding(.horizontal, 15).padding(.vertical, 11)
                            .foregroundStyle(selected == tab ? palette.text : palette.muted)
                            .background {
                                if selected == tab { Capsule().fill(palette.accent.opacity(0.16)).matchedGeometryEffect(id: "setup-tab", in: indicator) }
                            }
                            .overlay(Capsule().stroke(selected == tab ? palette.accent.opacity(0.7) : palette.line, lineWidth: 1))
                    }.buttonStyle(.plain).accessibilityAddTraits(selected == tab ? .isSelected : [])
                }
            }.padding(2)
        }
    }
}

struct DeckPendingFeatureButton: View {
    var title: String
    var symbol: String
    @State private var notice = false
    var body: some View {
        Button { notice = true } label: {
            HStack {
                Label(title, systemImage: symbol)
                Spacer()
                Text("Not connected").font(.caption).foregroundStyle(.secondary)
            }
        }
        .alert(title, isPresented: $notice) { Button("OK", role: .cancel) {} } message: {
            Text("This control is retained. Its mdeck integration is not implemented yet.")
        }
    }
}

struct DeckSettingsTiles: View {
    let pages: [SettingsPages.Page]
    var focused: SettingsPages.Page? = nil
    var select: (SettingsPages.Page) -> Void
    @Environment(\.deckPalette) private var palette
    var body: some View {
        VStack(spacing: 0) {
            ForEach(pages.filter(\.shown), id: \.self) { page in
                Button { select(page) } label: {
                    HStack(spacing: 13) {
                        Image(systemName: page.symbol).foregroundStyle(palette.accent).frame(width: 24)
                        Text(page.title).foregroundStyle(palette.text).font(.system(size: 14, weight: .medium))
                        Spacer()
                        Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(palette.muted)
                    }.padding(16).frame(minHeight: 58).contentShape(Rectangle())
                        .background(focused == page ? palette.accent.opacity(0.12) : .clear)
                }.buttonStyle(.plain)
                if page != pages.filter(\.shown).last { Divider().overlay(palette.line).padding(.leading, 53) }
            }
        }
        .background(palette.surface, in: RoundedRectangle(cornerRadius: 13))
        .overlay(RoundedRectangle(cornerRadius: 13).stroke(palette.line, lineWidth: 1))
    }
}

struct DeckAppearanceControls: View {
    @ObservedObject private var appearance = DeckAppearance.shared
    var body: some View {
        Section("Appearance") {
            Picker("Theme", selection: $appearance.theme) {
                Text("Graphite").tag("graphite")
                Text("Paper").tag("paper")
                Text("Blue").tag("blue")
                Text("Electric").tag("electric")
                Text("Gradient").tag("gradient")
                Text("Inner Gamer").tag("innerGamer")
            }
            Toggle("Animations", isOn: $appearance.animations)
            Toggle("Sidebar labels", isOn: $appearance.railLabels)
            LabeledContent("Interface scale") { Slider(value: $appearance.scale, in: 0.8...1.3, step: 0.05) }
            if appearance.theme == "innerGamer" { LabeledContent("RGB speed") { Slider(value: $appearance.rgbSpeed, in: 1...10, step: 1) } }
            if appearance.theme == "gradient" {
                ColorPicker("Primary color", selection: $appearance.gradientPrimary, supportsOpacity: false)
                ColorPicker("Secondary color", selection: $appearance.gradientSecondary, supportsOpacity: false)
            }
        }
    }
}
