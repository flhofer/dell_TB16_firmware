#!/usr/bin/env python3
"""Experimental native macOS TB16 MST updater. No NVM or ASMedia writer."""
import argparse
import hashlib
import json
import plistlib
from pathlib import Path
import sys
import subprocess

from mst import Mst, MstError, validate_image
from native import AuxError, IodpNative, Native

DEFAULT_IMAGE = Path(__file__).resolve().parents[2] / "bins/bme-ie-03.12.002.eeprom"


def device_id(value):
    try:
        result = int(value, 0)
        if not 0 < result < 2**64:
            raise ValueError
        return result
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected a nonzero 64-bit IORegistry ID (e.g. 0x100001234)") from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list interfaces; no bus transactions")
    listing.add_argument("--backend", choices=("ioi2c", "iodp"), default="ioi2c")
    listing.add_argument("--experimental", action="store_true")
    commands.add_parser("diagnose", help="filtered, read-only dock/display report; no native bridge required")
    inspect = commands.add_parser("inspect-image", help="validate the bundled raw MST image offline")
    inspect.add_argument("image", nargs="?", type=Path, default=DEFAULT_IMAGE)
    for name in ("probe", "backup", "flash", "read-dpcd"):
        command = commands.add_parser(name)
        command.add_argument("--backend", choices=("ioi2c", "iodp"), default="ioi2c")
        command.add_argument("--experimental", action="store_true", help="enable unvalidated experimental functionality")
        command.add_argument("--device", type=device_id, required=True,
                             help="exact IORegistry interface ID from list; IDs can change after replug")
        if name == "read-dpcd":
            command.add_argument("--address", type=lambda s: int(s, 0), default=0)
            command.add_argument("--length", type=int, default=16, help="1 to 256 bytes")
        if name == "backup":
            command.add_argument("--output", type=Path, required=True)
        if name == "flash":
            command.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
            command.add_argument("--write", action="store_true", help="perform a real EEPROM update")
            command.add_argument("--backup", type=Path, help="new file for a mandatory pre-write backup")
    args = parser.parse_args(argv)
    if args.command == "flash" and args.write and (not args.experimental or args.backup is None):
        parser.error("--write requires --experimental and --backup NEW_FILE")
    if getattr(args, "backend", None) == "iodp":
        if not args.experimental:
            parser.error("--backend iodp requires --experimental (private, read-only API)")
        if args.command == "backup" or (args.command == "flash" and args.write):
            parser.error("The IODP backend is read-only; backup and firmware writes are unavailable")
    if args.command == "read-dpcd" and (not 1 <= args.length <= 256 or args.address < 0 or
                                        args.address + args.length > 0x100000):
        parser.error("DPCD address must be 20-bit and length must be 1 to 256 bytes")
    try:
        if args.command == "diagnose":
            from diagnostics import collect
            print(json.dumps(collect(), indent=2))
            return 0
        # Validate before loading IOKit, allowing offline use on any OS.
        if args.command in ("inspect-image", "flash"):
            image = args.image.read_bytes()
            validate_image(image)
        if args.command == "inspect-image":
            print(json.dumps({"image": str(args.image), "size": len(image), "board_id": "0x0112",
                              "version": "03.12.002", "sha256": hashlib.sha256(image).hexdigest()}, indent=2))
            return 0
        native = IodpNative() if args.backend == "iodp" else Native()
        if args.command == "list":
            endpoints = native.endpoints()
            print(json.dumps(endpoints, indent=2))
            if args.backend == "iodp" and not any(entry["external"] for entry in endpoints):
                print("No External IODP device exposed. Embedded devices are listed for diagnosis "
                      "and cannot be opened. This backend cannot currently reach the dock.", file=sys.stderr)
            elif args.backend == "ioi2c" and not any(entry["native_aux"] for entry in endpoints):
                print("No native AUX interface exposed. This backend cannot update MST on this setup. "
                      "Apple Silicon support is not established.", file=sys.stderr)
            return 0
        with native.open(args.device) as aux:
            if args.command == "read-dpcd":
                data = aux.read(args.address, args.length)
                print(json.dumps({"device": f"0x{args.device:x}", "backend": args.backend,
                                  "address": f"0x{args.address:05x}", "length": len(data),
                                  "hex": data.hex()}, indent=2))
                return 0
            mst = Mst(aux)
            info = mst.check_chip()
            print(json.dumps({"device": f"0x{args.device:x}", **info}, indent=2))
            if args.command == "backup":
                digest = mst.backup(args.output)
                print(f"64 KiB EEPROM backup saved to {args.output}; SHA-256 {digest}")
            elif args.command == "flash":
                if not args.write:
                    print("Dry run: image and chip checked using DPCD reads only. "
                          "Board ID, EEPROM access and backup are checked only during backup/write. "
                          "No remote-control or flash writes performed.")
                else:
                    print("EXPERIMENTAL: native transport has not been validated on TB16 hardware.", flush=True)
                    mst.flash(image, args.backup, progress=lambda line: print(line, flush=True))
                    print("Update verified. Power-cycle the dock to load the new firmware, then probe again.")
        return 0
    except (MstError, AuxError, OSError, RuntimeError, subprocess.SubprocessError,
            ValueError, plistlib.InvalidFileException) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. If an update was running, keep the dock powered.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
