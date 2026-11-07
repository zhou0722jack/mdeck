#!/usr/bin/env python3
"""Check the native DroidDeck animation and optionally render review PNGs; no IPA."""
import argparse
import json
import math
import platform
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--render', type=Path)
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
source = APP / 'DeckSteamLoading.swift'
manifest = json.loads((ROOT / 'docs/droiddeck-steam-loading.json').read_text())
assert manifest['commit'] == '18c7d56409de4cf3b63b1b09e60e0fe97a633a7d'
assert len(manifest['sources']) == 3 and manifest['logoLoopSeconds'] == 1.9
project = (ROOT / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
assert project.count('/* DeckSteamLoading.swift in Sources */') == 2
native = (APP / 'Winios/Winios.m').read_text()
start = native.index('int winios_window_has_visible_frame(')
end = native.index('\n}', start) + 2
predicate = native[start:end]
for token in ['NSThread.isMainThread', 'g_compositor_view.hidden', '!g_compositor_view.window',
              'layer.hidden', '!layer.contents', 'CGRectIntersection']:
    assert token in predicate, token
assert 'metal' not in predicate and 'g_surface_present_count' not in predicate
library = (APP / 'Library.swift').read_text()
assert 'drawn: winios_window_has_visible_frame(window.hwnd) != 0' in library
assert 'steamLoading.observe(DeckSteamNativeFrames.snapshot())' in library
content = (APP / 'ContentView.swift').read_text()
assert 'if steamLoading.presented && !steamJIT.showSetup' in content
assert 'return JITCoordinator.shared.showSetup ? nil : super.hitTest(point, with: event)' in content
assert 'if let steamRequest, !steamPreparation.permitsLaunch(steamRequest)' in content

main = r'''
import SwiftUI
import AppKit
enum DeckSteamLaunchPreparation { enum Phase { case idle, components, starting, waitingForFrame, failed } }
enum ReviewStrings {
    static let values: [String:String] = {
        guard CommandLine.arguments.count > 2,
              let data = try? Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2])),
              let root = try? JSONSerialization.jsonObject(with:data) as? [String:Any],
              let strings = root["strings"] as? [String:[String:Any]] else { return [:] }
        return strings.reduce(into:[:]) { result, item in
            if let locales=item.value["localizations"] as? [String:Any],
               let zh=locales["zh-Hans"] as? [String:Any],
               let unit=zh["stringUnit"] as? [String:Any], let value=unit["value"] as? String { result[item.key]=value }
        }
    }()
}
func L(_ key: String) -> String { ReviewStrings.values[key] ?? key }
@main struct Check {
    @MainActor static func main() throws {
        var rows: [[Double]] = []
        for i in 0...100 {
            let p = Double(i) / 100, m = DeckSteamLogoGeometry.motion(p)
            let left = DeckSteamLogoGeometry.leftHalf(bend: m.bend)
            precondition(left.count == 82 && DeckSteamLogoGeometry.rightHalf.count == 80)
            for point in left + DeckSteamLogoGeometry.rightHalf {
                precondition(point.x.isFinite && point.y.isFinite)
            }
            rows.append([p,m.bend,m.turn,m.ballScale])
        }
        print(String(data: try JSONSerialization.data(withJSONObject: rows), encoding: .utf8)!)
        if CommandLine.arguments.count > 1 {
            let dir = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
            for (name, phase) in [("components",DeckSteamLaunchPreparation.Phase.components),
                                  ("starting",.starting),("first-frame",.waitingForFrame)] {
                let view = DeckSteamLoadingArtwork(phase: phase, installer: false, error: nil,
                    startedAt: Date().addingTimeInterval(-0.95), fraction: 0.42) { EmptyView() }
                    .frame(width: 960, height: 640)
                let renderer = ImageRenderer(content: view)
                renderer.scale = 1
                guard let image = renderer.cgImage else { preconditionFailure("native loading snapshot failed") }
                let bitmap = NSBitmapImageRep(cgImage: image)
                var greenPixels = 0
                for y in stride(from: 0, to: image.height, by: 4) {
                    for x in stride(from: 0, to: image.width, by: 4) {
                        if let color = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB),
                           color.greenComponent > 0.5 && color.redComponent < 0.4 { greenPixels += 1 }
                    }
                }
                precondition(greenPixels > 20, "loading content must be visible, not only its backdrop")
                guard let data = bitmap.representation(using: .png, properties: [:]) else {
                    preconditionFailure("native loading snapshot failed")
                }
                try data.write(to: dir.appendingPathComponent(name + ".png"))
            }
            for (index,p) in [0.0,0.18,0.5,0.82].enumerated() {
                let renderer = ImageRenderer(content: DeckSteamLogo(progress:p).padding(40)
                    .frame(width:320,height:320).background(.black))
                guard let image = renderer.cgImage,
                      let data = NSBitmapImageRep(cgImage:image).representation(using:.png,properties:[:]) else {
                    preconditionFailure("logo snapshot failed")
                }
                try data.write(to:dir.appendingPathComponent("logo-\(index).png"))
            }
        }
    }
}
'''


def ease(x, a, b):
    # Independent high-precision solution of the upstream cubic-Bezier curve.
    lo, hi = 0.0, 1.0
    for _ in range(60):
        t = (lo + hi) / 2
        at = 3*(1-t)**2*t*a + 3*(1-t)*t*t*b + t**3
        if at < x:
            lo = t
        else:
            hi = t
    return 3*(1-t)*t*t + t**3


def upstream_motion(p):
    settle = lambda x: ease(x, 0.5, 0.3)
    bend = (0 if p < .10 else settle((p-.10)/.14) if p < .24 else
            1 if p < .76 else 1-settle((p-.76)/.14) if p < .90 else 0)
    turn = 0 if p < .16 or p > .84 else ease((p-.16)/.68,.65,.35)*360
    scale = (1 if p < .12 else 1-.2*settle((p-.12)/.18) if p < .30 else
             .8 if p < .70 else .8+.2*settle((p-.70)/.18) if p < .88 else 1)
    return bend, turn, scale


with tempfile.TemporaryDirectory(prefix='mdeck-loading-art-') as directory:
    tmp = Path(directory)
    fixture = tmp / 'Check.swift'
    fixture.write_text(main)
    binary = tmp / 'check'
    subprocess.run(['xcrun','swiftc','-parse-as-library','-target',platform.machine()+'-apple-macos15.0',
                    str(source),str(fixture),'-o',str(binary)],check=True)
    command = [str(binary)]
    if args.render:
        args.render.mkdir(parents=True,exist_ok=True)
        command.append(str(args.render.resolve()))
        command.append(str(APP / 'Localizable.xcstrings'))
    result = subprocess.run(command,check=True,capture_output=True,text=True)
    rows = json.loads(result.stdout)
    for p,bend,turn,scale in rows:
        expected = upstream_motion(p)
        assert all(math.isclose(a,b,abs_tol=0.0001) for a,b in zip((bend,turn,scale),expected)),(p,expected)
    # Type-check the actual UIKit predicate, without building the app or Wine.
    objc = tmp / 'Frame.m'
    objc.write_text('#import <UIKit/UIKit.h>\n#import <QuartzCore/QuartzCore.h>\n'
                    'static UIView *g_compositor_view;\nstatic NSMutableDictionary *g_layers;\n'+predicate)
    subprocess.run(['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios18.0','-fobjc-arc',
                    '-fsyntax-only','-Wall','-Wextra','-Werror',str(objc)],check=True)
print('PASS: 101 animation samples match upstream bend/rotation/ball curves and finite original logo paths')
print('PASS: source attribution, Xcode source entry, target-window frame predicate and HUD/JIT interaction wiring')
print('PASS: actual UIKit frame predicate typechecked; no global/desktop/allocated-swapchain frame shortcut')
if args.render:
    print('Rendered native review PNGs: '+str(args.render.resolve()))
