#!/usr/bin/env python3
"""Check native frontend integration and conservation of existing controls; no build."""
import collections
import json
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app/Madeira"
inventory = json.loads((ROOT / "docs/native-ui-inventory.json").read_text())
count = 0
for record in inventory["files"]:
    source = (ROOT / record["file"]).read_text()
    for name in record["views"]:
        assert re.search(r"\b(?:struct|class)\s+" + re.escape(name) + r"\b", source), (record["file"], name)
        count += 1
    for label in record["controlLabels"]:
        assert '"' + label + '"' in source, (record["file"], "Missing original control", label)
print(f"PASS: {count} existing native view types and their literal control labels retained")

project = (ROOT / "app/Madeira.xcodeproj/project.pbxproj").read_text()
assert "DroidDeckShell.swift" not in project
assert "DroidDeckUI" not in project
assert "DroidDeckInfo.plist" not in project
assert "DeckDesign.swift in Sources" in project
for name in ["ContentView.swift", "Library.swift", "JITSetup.swift", "SteamGames.swift", "SettingsPages.swift", "SteamClient.swift"]:
    assert name + " in Sources" in project, name
ids = re.findall(r"^\s*([A-F0-9]+) /\*.*?\*/ = \{", project, re.M)
assert not [key for key, count in collections.Counter(ids).items() if count > 1]
scheme = ET.parse(ROOT / "app/Madeira.xcodeproj/xcshareddata/xcschemes/Madeira.xcscheme")
for ref in scheme.findall(".//BuildableReference"):
    assert ref.attrib["BlueprintIdentifier"] == "A5000001"
if sys.platform == "darwin":
    objects = plistlib.loads(subprocess.check_output(["plutil", "-convert", "xml1", "-o", "-", str(ROOT / "app/Madeira.xcodeproj/project.pbxproj")]))["objects"]
    paths = [objects[objects[key]["fileRef"]]["path"] for key in objects["A3000002"]["files"]]
    assert paths.count("DeckDesign.swift") == 1
    for record in inventory["files"]:
        name = Path(record["file"]).name
        assert any(Path(path).name == name for path in paths), (name, "not in app target")
print("PASS: restored native app target, existing UI sources and matching scheme")

app = (APP / "MadeiraApp.swift").read_text()
library = (APP / "Library.swift").read_text()
design = (APP / "DeckDesign.swift").read_text()
assert "DeckThemeHost { ContentView() }" in app
assert "DroidDeckShell()" not in app
assert "WebKit" not in design and "WKWebView" not in design
for route in ["steam", "library", "stores", "desktop", "components", "apps", "settings", "updates", "diagnostics"]:
    assert "case ." + route + ":" in library
for page in [".steam", ".gog", ".itch", ".epic", ".ea", ".graphics", ".display", ".memory", ".jit", ".signing", ".saves", ".drives", ".advanced", ".credits"]:
    assert page in (APP / "SettingsPages.swift").read_text()
assert "SteamClient.entry(install: false)" in library and "SteamClient.entry(install: true)" in library
assert "pageSections(selection)" in library and "SteamWorkshopSections(appID:" in library
assert "GameSetupShareSheet(entry:" in library and "GameSetupApplySheet(setup:" in library
assert "DeckSetupTabs(selected: $deckSetupTab)" in library
assert "session.current != nil || scenePhase != .active" in design
for label in ["Flathub", "Boot animation", "Smart glasses", "Head tracking", "Calibration", "Spatial setup", "Check for updates"]:
    assert 'DeckPendingFeatureButton(title: L("' + label + '")' in library, label
assert "case .workshop:" in library and "case .iniFiles:" in library
print("PASS: native routes retain Steam, JIT, Workshop, cloud and shared-setup actions")
print("No Swift compilation, native build, packaging or device test performed.")
