#!/usr/bin/env python3
"""Build the app's compact patch resource from the verified paired experiment."""
import argparse
import base64
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("originals", type=Path)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    patches = []
    for name, manifest_name in [("libcef.dll", "libcef-patch-manifest.json"),
                                ("chrome_elf.dll", "patch-manifest.json")]:
        manifest = json.loads((args.experiment / manifest_name).read_text())
        source = (args.originals / name).read_bytes()
        expected = (args.experiment / name).read_bytes()
        digest = lambda data: hashlib.sha256(data).hexdigest()
        if digest(source) != manifest["source_sha256"] or digest(expected) != manifest["output_sha256"]:
            raise ValueError(f"Hash mismatch for {name}")
        edits = [(entry["offset"], bytes.fromhex(entry["before"]), bytes.fromhex(entry["after"]))
                 for entry in manifest["edits"]]
        headers = manifest["pe_header_edits"]
        security = headers["security_directory_file_offset"]
        checksum = headers["checksum_file_offset"]
        edits.extend([(security, source[security:security + 8], b"\0" * 8),
                      (checksum, source[checksum:checksum + 4], struct.pack("<I", headers["checksum"]))])
        generated = bytearray(source[:len(expected)])
        groups = defaultdict(list)
        previous_end = 0
        for offset, before, after in sorted(edits):
            if offset < previous_end or len(before) != len(after) or source[offset:offset + len(before)] != before:
                raise ValueError(f"Invalid edit for {name} at {offset}")
            previous_end = offset + len(before)
            if previous_end > len(generated):
                raise ValueError("Edit exceeds output")
            generated[offset:previous_end] = after
            groups[(before, after)].append(offset)
        if generated != expected:
            raise ValueError(f"Patch does not reproduce the verified {name}")
        patches.append({"name": name, "sourceSHA256": digest(source), "outputSHA256": digest(expected),
                        "sourceSize": len(source), "outputSize": len(expected),
                        "groups": [{"before": base64.b64encode(before).decode(),
                                    "after": base64.b64encode(after).decode(), "offsets": offsets}
                                   for (before, after), offsets in groups.items()]})
    payload = json.dumps({"version": 1, "patches": patches}, separators=(",", ":")).encode() + b"\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(f"Verified paired app patch resource: {len(payload)} bytes, SHA256 {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
