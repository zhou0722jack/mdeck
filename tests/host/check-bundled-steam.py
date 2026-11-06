#!/usr/bin/env python3
"""Verify the bundled installer and project wiring without building or running it."""
import hashlib
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[2]
app = ROOT / "app/Madeira"
source = (app / "SteamClient.swift").read_text()
payload = (app / "BundledInstallers/SteamSetup.exe").read_bytes()
expected = re.search(r'installerSHA256 = "([0-9a-f]{64})"', source)[1]
assert hashlib.sha256(payload).hexdigest() == expected, "Installer checksum mismatch"
assert len(payload) == 2_380_800, "Review metadata when updating the bundled installer"
assert payload[:2] == b"MZ", "Expected Windows executable"
pe = struct.unpack_from("<I", payload, 0x3C)[0]
assert payload[pe:pe + 4] == b"PE\0\0", "Invalid PE header"
assert struct.unpack_from("<H", payload, pe + 4)[0] == 0x14C, "Expected i386 installer"
assert struct.unpack_from("<H", payload, pe + 24)[0] == 0x10B, "Expected PE32 format"
print("PASS: bundled Steam installer size, SHA-256 and PE32 headers")

project = (ROOT / "app/Madeira.xcodeproj/project.pbxproj").read_text()
for identifier in ("9F580A013E294829B675A101", "9F580A013E294829B675A201",
                   "9F580A013E294829B675A102", "9F580A013E294829B675A202"):
    assert len(re.findall(r'^\s*' + identifier + r' /\*.*?\*/ =', project, re.M)) == 1, identifier
resources = project.split("/* Begin PBXResourcesBuildPhase section */", 1)[1].split("/* End PBXResourcesBuildPhase section */", 1)[0]
sources = project.split("/* Begin PBXSourcesBuildPhase section */", 1)[1].split("/* End PBXSourcesBuildPhase section */", 1)[0]
assert "9F580A013E294829B675A102 /* BundledInstallers in Resources */" in resources
assert "9F580A013E294829B675A101 /* SteamClient.swift in Sources */" in sources
assert 'lastKnownFileType = folder; path = "BundledInstallers"' in project
print("PASS: installer folder and Swift source registered in Xcode project")

runtime = (app / "SteamRuntime.swift").read_text()
client = re.search(r'clientDirectory = "([^"]+)"', source)[1]
dock = re.search(r'relativeRoot = "([^"]+)"', runtime)[1]
assert client.casefold() != dock.casefold(), "Client must not overwrite the pinned Dock runtime"
print("PASS: interactive client and pinned Dock runtime use different directories")
print("Static checks only; no compiler, Wine, installer, or client was run.")
