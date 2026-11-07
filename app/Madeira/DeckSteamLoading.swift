// SPDX-License-Identifier: GPL-3.0-or-later
// Native SwiftUI port of DroidDeck LogoThrobber and LoadingOverlay.
// Source, pinned hashes and licence: docs/droiddeck-steam-loading.json.
import SwiftUI
#if canImport(UIKit)
import UIKit
#else
import AppKit
#endif

/// UIHostingController in the non-key HUD window does not inherit the app's
/// SwiftUI scenePhase reliably. Observe the application lifecycle directly.
@MainActor final class DeckMotionActivity: ObservableObject {
    static let shared = DeckMotionActivity()
    @Published private(set) var active: Bool
    private var observers: [NSObjectProtocol] = []

    init() {
        #if canImport(UIKit)
        active = UIApplication.shared.applicationState == .active
        let foreground = UIApplication.didBecomeActiveNotification
        let background = UIApplication.willResignActiveNotification
        #else
        active = NSApplication.shared.isActive
        let foreground = NSApplication.didBecomeActiveNotification
        let background = NSApplication.willResignActiveNotification
        #endif
        observers = [(foreground, true), (background, false)].map { name, active in
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.active = active }
            }
        }
    }
}

enum DeckSteamLogoGeometry {
    static let left = -55.98, width = 239.92, height = 223.72
    static let cx = 63.98, cy = 111.86, ball = 55.98
    private static let outer = 111.86, inner = 71.81, squareX = -31.98
    private static let splitLeft = 56.055, splitRight = 71.885
    struct Motion { var bend: Double; var turn: Double; var ballScale: Double }

    static func easing(_ value: Double, x1: Double, x2: Double, y1: Double = 0, y2: Double = 1) -> Double {
        let x = min(1, max(0, value))
        var lo = 0.0, hi = 1.0
        for _ in 0..<24 {
            let t = (lo + hi) / 2, u = 1 - t
            let at = 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t
            if at < x { lo = t } else { hi = t }
        }
        let t = (lo + hi) / 2
        return 3 * (1 - t) * (1 - t) * t * y1 + 3 * (1 - t) * t * t * y2 + t * t * t
    }

    static func motion(_ progress: Double) -> Motion {
        let p = min(1, max(0, progress))
        func settle(_ x: Double) -> Double { easing(x, x1: 0.5, x2: 0.3) }
        let bend: Double
        if p < 0.10 { bend = 0 }
        else if p < 0.24 { bend = settle((p - 0.10) / 0.14) }
        else if p < 0.76 { bend = 1 }
        else if p < 0.90 { bend = 1 - settle((p - 0.76) / 0.14) }
        else { bend = 0 }
        let turn = p < 0.16 || p > 0.84 ? 0 : easing((p - 0.16) / 0.68, x1: 0.65, x2: 0.35) * 360
        let scale: Double
        if p < 0.12 { scale = 1 }
        else if p < 0.30 { scale = 1 - 0.2 * settle((p - 0.12) / 0.18) }
        else if p < 0.70 { scale = 0.8 }
        else if p < 0.88 { scale = 0.8 + 0.2 * settle((p - 0.70) / 0.18) }
        else { scale = 1 }
        return Motion(bend: bend, turn: turn, ballScale: scale)
    }

    private static func at(_ angle: Double, _ radius: Double) -> CGPoint {
        CGPoint(x: cx + radius * cos(angle), y: cy + radius * sin(angle))
    }
    private static func span(_ a: Double, _ b: Double, _ count: Int) -> [Double] {
        (0..<count).map { a + (b - a) * Double($0) / Double(count - 1) }
    }
    private static let rays: [Double] = {
        func angle(_ x: Double, _ y: Double) -> Double { atan2(y - cy, x - cx) }
        func leftward(_ a: Double) -> Double { a < 0 ? a : a - 2 * .pi }
        return Array(span(angle(splitLeft, 0), angle(squareX, 0), 9).dropLast())
            + Array(span(angle(squareX, 0), leftward(angle(squareX, height)), 25).dropLast())
            + span(leftward(angle(squareX, height)), leftward(angle(splitLeft, height)), 9)
    }()
    private static let square: [CGPoint] = rays.enumerated().map { index, angle in
        if index == 0 { return CGPoint(x: splitLeft, y: 0) }
        if index == rays.count - 1 { return CGPoint(x: splitLeft, y: height) }
        let c = cos(angle), s = sin(angle)
        var hits = [Double]()
        if c < -1e-9 { hits.append((squareX - cx) / c) }
        if s < -1e-9 { hits.append(-cy / s) }
        if s > 1e-9 { hits.append((height - cy) / s) }
        let distance = hits.min() ?? 0
        return CGPoint(x: cx + distance * c, y: cy + distance * s)
    }
    private static let arc: [CGPoint] = rays.enumerated().map { index, angle in
        let dy = sqrt(outer * outer - pow(splitLeft - cx, 2))
        if index == 0 { return CGPoint(x: splitLeft, y: cy - dy) }
        if index == rays.count - 1 { return CGPoint(x: splitLeft, y: cy + dy) }
        return at(angle, outer)
    }
    private static let leftInner: [CGPoint] = {
        let dx = splitLeft - cx, dy = sqrt(inner * inner - dx * dx)
        return span(atan2(dy, dx), atan2(-dy, dx) + 2 * .pi, rays.count).map { at($0, inner) }
    }()
    static let rightHalf: [CGPoint] = {
        let dx = splitRight - cx
        let oy = sqrt(outer * outer - dx * dx), iy = sqrt(inner * inner - dx * dx)
        return span(atan2(-oy, dx), atan2(oy, dx), 40).map { at($0, outer) }
            + span(atan2(iy, dx), atan2(-iy, dx), 40).map { at($0, inner) }
    }()
    static func leftHalf(bend: Double) -> [CGPoint] {
        zip(square, arc).map { q, r in CGPoint(x: q.x + (r.x - q.x) * bend, y: q.y + (r.y - q.y) * bend) }
            + leftInner
    }
}

struct DeckSteamLogo: View {
    var progress: Double
    var ink: Color = .white
    var signal = Color(red: 61 / 255, green: 220 / 255, blue: 132 / 255)
    var body: some View {
        Canvas { context, size in
            let motion = DeckSteamLogoGeometry.motion(progress)
            let scale = size.width / DeckSteamLogoGeometry.width
            func point(_ p: CGPoint) -> CGPoint { CGPoint(x: (p.x - DeckSteamLogoGeometry.left) * scale, y: p.y * scale) }
            func polygon(_ points: [CGPoint]) -> Path {
                Path { path in
                    for (index, p) in points.enumerated() {
                        if index == 0 { path.move(to: point(p)) } else { path.addLine(to: point(p)) }
                    }
                    path.closeSubpath()
                }
            }
            let centre = point(CGPoint(x: DeckSteamLogoGeometry.cx, y: DeckSteamLogoGeometry.cy))
            var ring = context
            ring.translateBy(x: centre.x, y: centre.y)
            ring.rotate(by: .degrees(motion.turn))
            ring.translateBy(x: -centre.x, y: -centre.y)
            ring.fill(polygon(DeckSteamLogoGeometry.leftHalf(bend: motion.bend)), with: .color(ink))
            ring.fill(polygon(DeckSteamLogoGeometry.rightHalf), with: .color(ink))
            let radius = DeckSteamLogoGeometry.ball * scale * motion.ballScale
            context.fill(Path(ellipseIn: CGRect(x: centre.x - radius, y: centre.y - radius,
                                                width: radius * 2, height: radius * 2)), with: .color(signal))
        }.aspectRatio(DeckSteamLogoGeometry.width / DeckSteamLogoGeometry.height, contentMode: .fit)
            .accessibilityHidden(true)
    }
}

struct DeckSteamLoadingArtwork<Details: View>: View {
    var phase: DeckSteamLaunchPreparation.Phase
    var installer: Bool
    var error: String?
    var startedAt: Date
    var fraction: Double?
    var motionEnabled = true
    var covers: [Image] = []
    @ViewBuilder var details: () -> Details
    @ObservedObject private var activity = DeckMotionActivity.shared
    @Environment(\.accessibilityReduceMotion) private var reduced
    private let background = Color(red: 10 / 255, green: 11 / 255, blue: 14 / 255)
    private let signal = Color(red: 61 / 255, green: 220 / 255, blue: 132 / 255)
    private var active: Int { phase == .components ? 0 : phase == .starting ? 1 : 2 }
    private var message: String {
        switch phase {
        case .components: return L("Downloading and verifying components…")
        case .starting: return L("Preparing JIT and starting Steam…")
        case .waitingForFrame, .revealing:
            return error ?? (installer ? L("Waiting for the Steam installer's first frame…") : L("Waiting for Steam's first frame…"))
        case .failed: return error ?? L("Steam could not start. Check the log.")
        case .idle: return L("Ready")
        }
    }
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60, paused: !activity.active || reduced || !motionEnabled || phase == .failed)) { timeline in
            let elapsed = max(0, timeline.date.timeIntervalSince(startedAt))
            let still = reduced || !motionEnabled || phase == .failed
            ZStack {
                background.ignoresSafeArea()
                DeckSteamCapsuleWall(covers: covers, progress: still ? 0 : elapsed.truncatingRemainder(dividingBy: 65) / 65)
                    .opacity(0.3).ignoresSafeArea()
                GeometryReader { geometry in
                    RadialGradient(stops: [.init(color: background.opacity(0.94), location: 0),
                                           .init(color: background.opacity(0.72), location: 0.6),
                                           .init(color: background.opacity(0.55), location: 1)],
                                   center: UnitPoint(x: 0.5, y: 0.46), startRadius: 0,
                                   endRadius: max(geometry.size.width, geometry.size.height) * 0.55)
                }.ignoresSafeArea()
                LinearGradient(stops: [.init(color: .clear, location: 0.7),
                                       .init(color: background.opacity(0.95), location: 1)],
                               startPoint: .top, endPoint: .bottom).ignoresSafeArea()
                ViewThatFits(in: .vertical) {
                    panel(elapsed: elapsed, still: still).fixedSize(horizontal: false, vertical: true)
                    ScrollView { panel(elapsed: elapsed, still: still) }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            }.foregroundStyle(.white)
        }
    }
    private func panel(elapsed: Double, still: Bool) -> some View {
        VStack(spacing: 0) {
            DeckSteamLogo(progress: still ? 0 : elapsed.truncatingRemainder(dividingBy: 1.9) / 1.9)
                .frame(width: phase == .failed ? 88 : 110).padding(.bottom, 30)
            Text(phase == .failed ? L("Steam could not start") : installer ? L("Starting Steam installer") : L("Starting Steam"))
                .font(.system(size: 20, weight: .semibold)).foregroundStyle(.white).multilineTextAlignment(.center)
            Text(message).font(.system(size: 14)).foregroundStyle(.white.opacity(0.65))
                .multilineTextAlignment(.center).padding(.top, 6).frame(maxWidth: 520)
            if phase != .failed {
                HStack(spacing: 6) {
                    ForEach(0..<3) { segment in
                        GeometryReader { geometry in
                            ZStack(alignment: .leading) {
                                Color.white.opacity(0.12)
                                if segment < active { signal }
                                else if segment == active {
                                    if phase == .components, let fraction {
                                        signal.frame(width: geometry.size.width * min(1, max(0, fraction)))
                                    } else if still { signal.opacity(0.5) }
                                    else {
                                        signal.frame(width: geometry.size.width * 0.4)
                                            .offset(x: geometry.size.width * (DeckSteamLogoGeometry.easing(
                                                elapsed.truncatingRemainder(dividingBy: 1.3) / 1.3, x1: 0.4, x2: 0.2) * 1.4 - 0.4))
                                    }
                                }
                            }.clipShape(RoundedRectangle(cornerRadius: 2))
                        }.frame(width: 44, height: 3)
                    }
                }.padding(.top, 18)
                HStack(spacing: 16) {
                    Text(L("Components")); Text(L("Start Steam")); Text(L("First frame"))
                }.font(.caption2).foregroundStyle(.white.opacity(0.6)).padding(.top, 12)
                    .accessibilityLabel(Text([L("Components"), L("Start Steam"), L("First frame")][active]))
            }
            details()
            Text(String(format: "%02d:%02d", Int(elapsed) / 60, Int(elapsed) % 60))
                .font(.caption.monospacedDigit()).foregroundStyle(.white.opacity(0.4)).padding(.top, 26)
        }.padding(.horizontal, 28).padding(.vertical, 36).frame(maxWidth: .infinity)
    }
}

/// DroidDeck Rise: 450ms fade/slide, staggered by 60ms per item.
struct DeckHomeRise: ViewModifier {
    var index: Int
    var enabled: Bool
    @Environment(\.accessibilityReduceMotion) private var reduced
    @State private var shown = false
    func body(content: Content) -> some View {
        content.opacity(shown || reduced || !enabled ? 1 : 0)
            .offset(y: shown || reduced || !enabled ? 0 : 18)
            .task {
                withAnimation(reduced || !enabled ? nil : .timingCurve(0.2, 0.8, 0.2, 1, duration: 0.45).delay(Double(index) * 0.06)) {
                    shown = true
                }
            }
    }
}

enum DeckHomeMotion {
    static func ease(_ p: Double, _ a: Double, _ b: Double, _ c: Double, _ d: Double) -> Double {
        DeckSteamLogoGeometry.easing(p, x1: a, x2: c, y1: b, y2: d)
    }
    static func out(_ p: Double) -> Double { ease(p, 0, 0, 0.58, 1) }
    static func span(_ p: Double, _ a: Double, _ b: Double, _ from: Double, _ to: Double,
                     _ curve: (Double) -> Double) -> Double { from + (to - from) * curve((p - a) / (b - a)) }
    static func fan(_ elapsed: Double, index: Int) -> Double {
        let duration = [9.0, 11, 13][index]
        let p = max(0, elapsed).truncatingRemainder(dividingBy: duration * 2) / duration
        return ease(p <= 1 ? p : 2 - p, 0.4, 0, 0.2, 1)
    }
    static func bounce(_ position: Double, low: Double, high: Double) -> Double {
        let length = max(1, high - low)
        let p = ((position - low).truncatingRemainder(dividingBy: length * 2) + length * 2)
            .truncatingRemainder(dividingBy: length * 2)
        return low + (p <= length ? p : length * 2 - p)
    }
    static func placement(elapsed: Double, size: CGSize, still: Bool) -> (height: Double, centre: CGPoint) {
        let h = min(size.height * 0.3, size.width * 0.28 * DeckSteamLogoGeometry.height / DeckSteamLogoGeometry.width)
        let halfWidth = (DeckSteamLogoGeometry.cx - DeckSteamLogoGeometry.left) * h / DeckSteamLogoGeometry.height
        let centre = CGPoint(x: bounce(size.width * 0.64 + (still ? 0 : elapsed * 51.2),
                                       low: max(halfWidth + 10, size.width * 0.3), high: size.width - halfWidth - 10),
                             y: bounce(size.height * 0.42 - (still ? 0 : elapsed * 38.4),
                                       low: h / 2 + 16, high: max(h / 2 + 17, size.height * 0.7 - h / 2)))
        return (h, centre)
    }
    struct Mark {
        var fill: Double; var trace: Double; var traceAlpha: Double; var shown: Double
        var pop: Double; var rise: Double; var turn: Double; var squashX: Double; var squashY: Double
        var ripple: Double; var rippleAlpha: Double; var shake: Double
    }
    static func mark(intro: Double, ball: Double) -> Mark {
        func inOut(_ p: Double) -> Double { ease(p, 0.42, 0, 0.58, 1) }
        func popEase(_ p: Double) -> Double { ease(p, 0.15, 0.8, 0.3, 1) }
        func drop(_ p: Double) -> Double { ease(p, 0.6, 0, 0.9, 0.5) }
        let p = (ball - 0.9) / 1.3
        var pop = 1.0, rise = 0.0
        if p > 0 && p < 1 {
            if p < 0.11 {
                pop = span(p, 0, 0.11, 1, 0.92, inOut); rise = span(p, 0, 0.11, 0, 7, inOut)
            } else if p < 0.31 {
                pop = span(p, 0.11, 0.31, 0.92, 1.6, popEase); rise = span(p, 0.11, 0.31, 7, -42, popEase)
            } else if p < 0.88 {
                pop = span(p, 0.31, 0.88, 1.6, 1.54, inOut); rise = span(p, 0.31, 0.88, -42, -34, inOut)
            } else {
                pop = span(p, 0.88, 1, 1.54, 1, drop); rise = span(p, 0.88, 1, -34, 0, drop)
            }
        }
        var sx = 1.0, sy = 1.0
        let impact = ball - 2.2
        if impact >= 0 && impact < 0.28 {
            let q = impact / 0.28
            if q < 0.3 { sx = span(q, 0, 0.3, 1, 1.1, out); sy = span(q, 0, 0.3, 1, 0.88, out) }
            else if q < 0.65 { sx = span(q, 0.3, 0.65, 1.1, 0.97, out); sy = span(q, 0.3, 0.65, 0.88, 1.04, out) }
            else { sx = span(q, 0.65, 1, 0.97, 1, out); sy = span(q, 0.65, 1, 1.04, 1, out) }
        }
        let rp = min(1, max(0, impact / 1.25))
        let rippleAlpha = impact < 0 || impact > 1.25 ? 0 : rp < 0.7 ? 0.9 - 0.55 * rp / 0.7 : 0.35 * (1 - (rp - 0.7) / 0.3)
        var shake = 0.0
        if impact >= 0 && impact < 0.23 {
            let q = impact / 0.23
            shake = q < 0.25 ? span(q, 0, 0.25, 0, 7, out)
                : q < 0.55 ? span(q, 0.25, 0.55, 7, -3, out) : span(q, 0.55, 1, -3, 0, out)
        }
        if ball > 3.6 { rise -= 4 * (0.5 - 0.5 * cos(2 * .pi * (ball - 3.6) / 5.2)) }
        return Mark(fill: out((intro - 0.45) / 0.45), trace: ease(intro / 0.775, 0.45, 0, 0.25, 1),
                    traceAlpha: intro < 0.775 ? 1 : max(0, 1 - (intro - 0.775) / 0.475),
                    shown: out((intro - 0.65) / 0.3), pop: pop, rise: rise,
                    turn: 720 * ease((ball - 1.29) / 0.76, 0.25, 0.7, 0.35, 1), squashX: sx, squashY: sy,
                    ripple: ease(rp, 0.2, 0.6, 0.35, 1), rippleAlpha: rippleAlpha, shake: shake)
    }
}

struct DeckSteamHomeBackground: View {
    var covers: [Image]
    var enabled: Bool
    var ink: Color
    var signal: Color
    var background: Color
    @ObservedObject private var activity = DeckMotionActivity.shared
    @Environment(\.accessibilityReduceMotion) private var reduced
    @State private var began = Date()
    @State private var pokeAt: Date?
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60, paused: !activity.active || reduced || !enabled)) { timeline in
            let still = reduced || !enabled
            let elapsed = still ? 3.6 : max(0, timeline.date.timeIntervalSince(began))
            let ball = still ? 3.6 : pokeAt.map { max(0, timeline.date.timeIntervalSince($0)) + 0.88 } ?? elapsed
            ZStack {
                if covers.isEmpty || covers.count >= 4 {
                    DeckSteamCapsuleWall(covers: covers, progress: still ? 0 : elapsed.truncatingRemainder(dividingBy: covers.isEmpty ? 75 : 40) / (covers.isEmpty ? 75 : 40))
                } else {
                    DeckSteamHomeFan(covers: covers, elapsed: elapsed, still: still)
                }
                LinearGradient(stops: [.init(color: background.opacity(0.97), location: 0),
                                       .init(color: background.opacity(0.86), location: 0.34),
                                       .init(color: background.opacity(0.25), location: 0.68),
                                       .init(color: background.opacity(0.1), location: 1)], startPoint: .leading, endPoint: .trailing)
                LinearGradient(stops: [.init(color: .clear, location: 0.55), .init(color: background.opacity(0.9), location: 1)],
                               startPoint: .top, endPoint: .bottom)
                if covers.isEmpty {
                    GeometryReader { geometry in
                        DeckSteamHomeMark(elapsed: elapsed, ball: ball, still: still, ink: ink, signal: signal)
                            .contentShape(Rectangle())
                            .onTapGesture { location in
                                let placement = DeckHomeMotion.placement(elapsed: elapsed, size: geometry.size, still: still)
                                let radius = DeckSteamLogoGeometry.ball * placement.height / DeckSteamLogoGeometry.height
                                if !still && ball >= 3.45 && hypot(location.x - placement.centre.x, location.y - placement.centre.y) <= radius * 1.4 {
                                    pokeAt = timeline.date
                                }
                            }
                    }
                }
            }
        }.accessibilityHidden(true)
    }
}

struct DeckSteamHomeFan: View {
    var covers: [Image]
    var elapsed: Double
    var still: Bool
    var body: some View {
        Canvas { context, size in
            let slots = [(0.54, 0.14, 0.62, -9.0), (0.70, 0.24, 0.56, 5.0), (0.40, 0.30, 0.50, -17.0)]
            for index in covers.prefix(3).indices.reversed() {
                let (x, y, height, lean) = slots[index]
                let t = still ? 0 : DeckHomeMotion.fan(elapsed, index: index)
                let h = size.height * height, w = h * 2 / 3
                var tile = context
                tile.translateBy(x: size.width * x + w / 2, y: size.height * y + h / 2 - 12 * t)
                tile.rotate(by: .degrees(lean + 2 * t))
                let rect = CGRect(x: -w / 2, y: -h / 2, width: w, height: h)
                tile.addFilter(.shadow(color: .black.opacity(0.45), radius: 16, y: 12))
                tile.clip(to: Path(roundedRect: rect, cornerRadius: 14))
                let image = tile.resolve(covers[index])
                if image.size.width > 0 && image.size.height > 0 {
                    let scale = max(w / image.size.width, h / image.size.height)
                    tile.draw(image, in: CGRect(x: -image.size.width * scale / 2, y: -image.size.height * scale / 2,
                                               width: image.size.width * scale, height: image.size.height * scale))
                }
            }
        }.accessibilityHidden(true)
    }
}

struct DeckSteamHomeMark: View {
    var elapsed: Double
    var ball: Double
    var still: Bool
    var ink: Color
    var signal: Color
    var body: some View {
        Canvas { context, size in
            let (h, centre) = DeckHomeMotion.placement(elapsed: elapsed, size: size, still: still)
            let scale = h / DeckSteamLogoGeometry.height, k = h / 460
            let m = DeckHomeMotion.mark(intro: elapsed, ball: ball)
            let radius = DeckSteamLogoGeometry.ball * scale
            if m.rippleAlpha > 0 {
                let reach = radius + (hypot(size.width, size.height) * 1.05 - radius) * m.ripple
                context.stroke(Path(ellipseIn: CGRect(x: centre.x - reach, y: centre.y - reach, width: reach * 2, height: reach * 2)),
                               with: .color(signal.opacity(m.rippleAlpha)), lineWidth: max(1.5, 2.5 * k))
            }
            func path(_ points: [CGPoint], lift: Double = 0) -> Path {
                Path { p in
                    for (i, q) in points.enumerated() {
                        let point = CGPoint(x: centre.x + (q.x - DeckSteamLogoGeometry.cx) * scale,
                                            y: centre.y + (q.y - DeckSteamLogoGeometry.cy) * scale + lift + m.shake * k)
                        if i == 0 { p.move(to: point) } else { p.addLine(to: point) }
                    }
                    p.closeSubpath()
                }
            }
            for points in [DeckSteamLogoGeometry.leftHalf(bend: 0), DeckSteamLogoGeometry.rightHalf] {
                context.fill(path(points, lift: 5 * scale + 8 * k * (1 - m.fill)), with: .color(ink.opacity(0.4 * m.fill)))
                context.fill(path(points, lift: 8 * k * (1 - m.fill)), with: .color(ink.opacity(m.fill)))
                if m.traceAlpha > 0 {
                    context.stroke(path(points).trimmedPath(from: 0, to: m.trace), with: .color(signal.opacity(m.traceAlpha)), lineWidth: max(1, 2 * scale))
                }
            }
            let grow = (0.6 + 0.4 * m.shown) * m.pop
            let r = radius * grow
            let angle = m.turn * .pi / 180
            let rx = max(0.25, r * abs(cos(angle)) * m.squashX)
            let ry = r * m.squashY
            let cy = centre.y + (m.rise + m.shake) * k
            let half = r * 0.061 * sin(angle)
            context.fill(Path(ellipseIn: CGRect(x: centre.x - r * 0.93, y: centre.y - r * 0.4, width: r * 1.86, height: r * 0.8)),
                         with: .color(.black.opacity(0.25 * m.shown)))
            context.fill(Path(ellipseIn: CGRect(x: centre.x - rx - abs(half), y: cy - ry, width: rx * 2 + abs(half) * 2, height: ry * 2)),
                         with: .color(signal.opacity(0.55 * m.shown)))
            context.fill(Path(ellipseIn: CGRect(x: centre.x - rx + (cos(angle) >= 0 ? half : -half), y: cy - ry, width: rx * 2, height: ry * 2)),
                         with: .color(signal.opacity(m.shown)))
        }.accessibilityHidden(true)
    }
}

/// DroidDeck TiltedWall geometry (112x168 cards, 14-point gap, -13 degrees,
/// alternating columns, 65-second drift). Cached local covers only; no artwork
/// download competes with the four runtime downloads.
struct DeckSteamCapsuleWall: View {
    var covers: [Image]
    var progress: Double
    var body: some View {
        Canvas { context, size in
            let angle = 13.0 * .pi / 180
            let wallW = (size.width * cos(angle) + size.height * sin(angle)) * 1.1
            let wallH = max(size.height * 2.4, (size.width * sin(angle) + size.height * cos(angle)) * 1.1)
            let columns = Int((wallW + 14) / 126) + 1
            let rows = Int((wallH + 14) / 182) + 1
            let run = Double(rows) * 182
            var wall = context
            wall.translateBy(x: size.width / 2, y: size.height / 2)
            wall.rotate(by: .degrees(-13))
            wall.translateBy(x: -wallW / 2, y: -wallH / 2)
            for column in 0..<columns {
                let shift = column.isMultiple(of: 2) ? -run * progress : run * progress - run
                for row in 0..<(rows * 2) {
                    let rect = CGRect(x: Double(column) * 126, y: Double(row) * 182 + shift, width: 112, height: 168)
                    let outline = Path(roundedRect: rect, cornerRadius: 10)
                    var tile = wall
                    tile.clip(to: outline)
                    tile.fill(outline, with: .linearGradient(Gradient(colors: [Color.white.opacity(0.055), .black.opacity(0.08)]),
                                                            startPoint: rect.origin, endPoint: CGPoint(x: rect.maxX, y: rect.maxY)))
                    if !covers.isEmpty {
                        let image = tile.resolve(covers[(column * 5 + (row % rows) * 3) % covers.count])
                        if image.size.width > 0 && image.size.height > 0 {
                            let scale = max(rect.width / image.size.width, rect.height / image.size.height)
                            let w = image.size.width * scale, h = image.size.height * scale
                            tile.draw(image, in: CGRect(x: rect.midX - w / 2, y: rect.midY - h / 2, width: w, height: h))
                        }
                    }
                    wall.stroke(outline, with: .color(.white.opacity(0.045)), lineWidth: 1)
                }
            }
        }.accessibilityHidden(true)
    }
}
