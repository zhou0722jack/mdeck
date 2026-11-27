#!/usr/bin/env python3
"""Check production auto replacement, optionally with the actual Valve DLLs."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app/Madeira"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--originals", type=Path)
parser.add_argument("--helper", type=Path)
args = parser.parse_args()
if bool(args.originals) != bool(args.helper):
    parser.error("--originals and --helper must be supplied together")
process = (ROOT / "build/ntdll-unix/process_ios.c").read_text()
start = process.index("    /* Steam downloads CEF after NSIS exits.")
end = process.index("\n#endif", start)
hook = process[start:end]
assert start < process.index("if ((status = spawn_process(")
assert "machine == IMAGE_FILE_MACHINE_AMD64" in hook
assert '"steamwebhelper.exe"' in hook
project = (ROOT / "app/Madeira.xcodeproj/project.pbxproj").read_text()
assert "SteamCEFPoolPatch.swift in Sources" in project
assert "BundledInstallers in Resources" in project
resource = APP / "BundledInstallers/SteamCEF4GiB.json"
assert resource.is_file() and resource.stat().st_size < 512 * 1024
with tempfile.TemporaryDirectory(prefix="mdeck-cef-auto-") as temporary:
    work = Path(temporary)
    # Compile the production spawn hook with both weak-symbol states. This
    # checks the normal Win64 helper route and exclusion of other child images.
    c = work / "hook.c"
    c.write_text('''#include <assert.h>
#include <stddef.h>
#include <string.h>
#define IMAGE_FILE_MACHINE_AMD64 0x8664
#define STATUS_UNSUCCESSFUL 1
typedef unsigned short WCHAR;
struct string { WCHAR *Buffer; unsigned int Length; };
struct params { struct string ImagePathName; };
static int ios_image_name_is(WCHAR *path, unsigned int count, const char *name) {
    return count == 1 && *path == 'h' && !strcmp(name,"steamwebhelper.exe");
}
#ifdef WITH_CALLBACK
extern int calls, result;
#endif
static int run(unsigned int machine, WCHAR name) {
    struct params value = {{&name, sizeof(name)}}, *params = &value;
    const char *unix_name = "helper";
    int status = 0;
''' + hook + '''
done: return status;
}
int main(void) {
    assert(!run(0x14c,'h')); assert(!run(0x8664,'x')); assert(!run(0x8664,'h'));
#ifdef WITH_CALLBACK
    assert(calls == 1); result = -1; assert(run(0x8664,'h') == STATUS_UNSUCCESSFUL); assert(calls == 2);
#endif
}
''')
    provider = work / "provider.c"
    provider.write_text('#include <assert.h>\n#include <string.h>\nint calls, result;\n'
                        'int madeira_steam_cef_prepare(const char *path) { assert(!strcmp(path,"helper")); calls++; return result; }\n')
    for callback in [False, True]:
        binary = work / ("hook-present" if callback else "hook-absent")
        subprocess.run(["xcrun", "clang", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                        *(["-DWITH_CALLBACK", str(provider)] if callback else ["-Wl,-U,_madeira_steam_cef_prepare"]),
                        str(c), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
    subprocess.run(["xcrun", "clang", "-arch", "arm64", "-isysroot", sdk,
                    "-miphoneos-version-min=17.0", "-Wall", "-Wextra", "-Werror",
                    "-c", str(c), "-o", str(work / "hook-ios.o")], check=True)
    binary = work / "patch-check"
    subprocess.run(["xcrun", "swiftc", "-parse-as-library", str(APP / "SteamCEFPoolPatch.swift"),
                    str(APP / "SteamClient64Bootstrap.swift"), str(APP / "SteamRuntime.swift"),
                    str(APP / "Localization.swift"), str(APP / "SteamKeyValues.swift"),
                    str(ROOT / "tests/host/fixtures/SteamCEFPoolPatchCheck.swift"), "-o", str(binary)], check=True)
    subprocess.run(["xcrun", "swiftc", "-typecheck", "-parse-as-library", "-target", "arm64-apple-ios17.0",
                    "-sdk", sdk, str(APP / "SteamCEFPoolPatch.swift"), str(APP / "SteamClient64Bootstrap.swift"),
                    str(APP / "SteamRuntime.swift"), str(APP / "Localization.swift"), str(APP / "SteamKeyValues.swift"),
                    str(ROOT / "tests/host/fixtures/SteamCEFPoolPatchCheck.swift")], check=True)
    originals, helper = args.originals, args.helper
    if originals is None:
        # CI exercises the complete transaction with small deterministic inputs.
        # --originals additionally checks the hash-pinned, real Valve pair.
        originals = work / "originals"
        originals.mkdir()
        patches = []
        for index, name in enumerate(["libcef.dll", "chrome_elf.dll"]):
            source = bytes((value * 37 + index) & 255 for value in range(8192))
            output = bytearray(source[:-16])
            output[256:260] = b"POOL"
            (originals / name).write_bytes(source)
            patches.append({"name": name, "sourceSHA256": hashlib.sha256(source).hexdigest(),
                            "outputSHA256": hashlib.sha256(output).hexdigest(),
                            "sourceSize": len(source), "outputSize": len(output), "groups": [{
                                "before": base64.b64encode(source[256:260]).decode(),
                                "after": base64.b64encode(output[256:260]).decode(), "offsets": [256]}]})
        resource = work / "recipe.json"
        resource.write_text(json.dumps({"version": 1, "patches": patches}))
        helper = work / "steamwebhelper.exe"
        image = bytearray(512)
        image[:2] = b"MZ"
        struct.pack_into("<I", image, 60, 128)
        image[128:134] = b"PE\0\0\x64\x86"
        struct.pack_into("<H", image, 152, 0x20b)
        helper.write_bytes(image)
    arguments = [str(work / "install"), str(originals.resolve()), str(resource), str(helper.resolve())]
    for action in ["normal", "partial-update", "cache", "rollback", "crash", "recover", "unknown", "scope", "bad-backup"]:
        result = subprocess.run([str(binary), action, *arguments], check=False)
        assert result.returncode == (77 if action == "crash" else 0), (action, result.returncode)
    subprocess.run([str(binary), "concurrent-setup", *arguments], check=True)
    children = [subprocess.Popen([str(binary), "prepare", *arguments]) for _ in range(2)]
    for child in children:
        assert child.wait(timeout=120) == 0
print("PASS: production child-spawn hook, app resource wiring and Swift compile")
