// SPDX-License-Identifier: GPL-3.0-or-later
// Native SwiftUI port of DroidDeck LogoThrobber and LoadingOverlay.
// Source, pinned hashes and licence: docs/droiddeck-steam-loading.json.
import SwiftUI

enum DeckSteamLogoGeometry {
    static let left = -55.98, width = 239.92, height = 223.72
    static let cx = 63.98, cy = 111.86, ball = 55.98
    private static let outer = 111.86, inner = 71.81, squareX = -31.98
    private static let splitLeft = 56.055, splitRight = 71.885
    struct Motion { var bend: Double; var turn: Double; var ballScale: Double }

    static func easing(_ value: Double, x1: Double, x2: Double) -> Double {
        let x = min(1, max(0, value))
        var lo = 0.0, hi = 1.0
        for _ in 0..<24 {
            let t = (lo + hi) / 2, u = 1 - t
            let at = 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t
            if at < x { lo = t } else { hi = t }
        }
        let t = (lo + hi) / 2
        return 3 * (1 - t) * t * t + t * t * t
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
    var covers: [Image] = []
    @ViewBuilder var details: () -> Details
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduced
    private let background = Color(red: 10 / 255, green: 11 / 255, blue: 14 / 255)
    private let signal = Color(red: 61 / 255, green: 220 / 255, blue: 132 / 255)
    private var active: Int { phase == .components ? 0 : phase == .starting ? 1 : 2 }
    private var message: String {
        switch phase {
        case .components: return L("Downloading and verifying components…")
        case .starting: return L("Preparing JIT and starting Steam…")
        case .waitingForFrame:
            return error ?? (installer ? L("Waiting for the Steam installer's first frame…") : L("Waiting for Steam's first frame…"))
        case .failed: return error ?? L("Steam could not start. Check the log.")
        case .idle: return L("Ready")
        }
    }
    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 60, paused: scenePhase != .active || reduced || phase == .failed)) { timeline in
            let elapsed = max(0, timeline.date.timeIntervalSince(startedAt))
            let still = reduced || phase == .failed
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
