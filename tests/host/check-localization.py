#!/usr/bin/env python3
"""Check Chinese coverage, format arguments and the real compiled string bundle."""
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app/Madeira"
catalog = json.loads((APP / "Localizable.xcstrings").read_text())
strings = catalog["strings"]


def chinese(key):
    unit = strings[key]["localizations"]["zh-Hans"]["stringUnit"]
    assert unit["state"] == "translated" and unit["value"], key
    return unit["value"]


format_token = re.compile(r'%(?:(\d+)\$)?[-+#0]*(?:\d+|\*)?(?:\.\d+)?(ll|hh|[hlzjtL])?([@diuoxXfFeEgGaAcsp])')


def arguments(value):
    return [(int(m[1]) if m[1] else None, (m[2] or "") + m[3])
            for m in format_token.finditer(value.replace("%%", ""))]


for key in strings:
    translated = chinese(key)
    original = arguments(key)
    localized = arguments(translated)
    if any(position is not None for position, _ in localized):
        assert all(position is not None for position, _ in localized), (key, translated)
        for position, kind in localized:
            assert 0 < position <= len(original), (key, translated)
            assert kind == original[position - 1][1], (key, translated)
    else:
        assert [kind for _, kind in localized] == [kind for _, kind in original], (key, translated)
print(f"PASS: {len(strings)} translated entries preserve format argument types")

# Check all metadata displayed by All settings without rewriting generated keys.
generated = (APP / "ConfigCatalog.generated.swift").read_text()
literal = r'"(?:[^"\\]|\\.)*"'
fields = re.findall(r'\b(?:title|category|note): (' + literal + ')', generated)
for field in fields:
    key = json.loads(field)
    if key:
        assert key in strings, f"Missing setting translation: {key}"
        chinese(key)
print("PASS: all generated setting titles, categories and descriptions have Chinese translations")

# L and LF use ordinary string keys, so Xcode cannot discover missing entries itself.
for source in APP.rglob("*.swift"):
    for match in re.finditer(r'\bL(?:F)?\(\s*(' + literal + ')', source.read_text()):
        key = json.loads(match[1])
        assert key in strings, f"{source.name}: missing {key}"
        chinese(key)
print("PASS: every L/LF call resolves to a translated catalog entry")

if sys.platform != "darwin":
    print("SKIP: compiled Apple bundle check requires Xcode on macOS")
    sys.exit(0)

with tempfile.TemporaryDirectory(prefix="madeira-localization-") as directory:
    folder = Path(directory)
    resources = folder / "Check.app/Contents/Resources"
    executable = folder / "Check.app/Contents/MacOS/check"
    resources.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    subprocess.run(["xcrun", "xcstringstool", "compile", str(APP / "Localizable.xcstrings"),
                    "--output-directory", str(resources)], check=True)
    with (folder / "Check.app/Contents/Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleExecutable": "check", "CFBundleIdentifier": "app.madeira.localization-check",
                      "CFBundlePackageType": "APPL", "CFBundleDevelopmentRegion": "en"}, stream)
    main = folder / "main.swift"
    main.write_text('''import Foundation
precondition(AppLanguage.locale.identifier == "zh-Hans")
precondition(L("Library") == "游戏库")
precondition(L("Settings") == "设置")
precondition(L("All") == "全部")
precondition(L("Does not exist in the catalog") == "Does not exist in the catalog")
precondition(LF("Step %@ of %@", "2", "5") == "第 2 步，共 5 步")
precondition(LF("Paused at %@%%", "75") == "已暂停：75%")
precondition(LF("Could not write %@.", "C:\\\\Games\\\\测试.exe") == "无法写入 C:\\\\Games\\\\测试.exe。")
precondition(LF("%@ saves", "3") == "3 个存档")
print("PASS: compiled bundle returns Chinese with English system preferences; paths and percentages are preserved")
''')
    subprocess.run([os.environ.get("SWIFTC", "swiftc"), str(APP / "Localization.swift"),
                    str(main), "-o", str(executable)], check=True)
    subprocess.run([str(executable), "-AppleLanguages", "(en)"], check=True)
