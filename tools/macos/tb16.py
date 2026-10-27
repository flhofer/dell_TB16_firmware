#!/usr/bin/env python3
"""Experimental native macOS TB16 MST updater. No NVM or ASMedia writer."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from mst import Mst, MstError, validate_image
from native import AuxError, Native

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
    commands.add_parser("list", help="list IOI2C interfaces and native AUX capability; no bus transactions")
    inspect = commands.add_parser("inspect-image", help="validate the bundled raw MST image offline")
    inspect.add_argument("image", nargs="?", type=Path, default=DEFAULT_IMAGE)
    for name in ("probe", "backup", "flash"):
        command = commands.add_parser(name)
        command.add_argument("--device", type=device_id, required=True,
                             help="exact IORegistry interface ID from list; IDs can change after replug")
        if name == "backup":
            command.add_argument("--output", type=Path, required=True)
        if name == "flash":
            command.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
            command.add_argument("--write", action="store_true", help="perform a real EEPROM update")
            command.add_argument("--experimental", action="store_true", help="acknowledge unvalidated hardware support")
            command.add_argument("--backup", type=Path, help="new file for a mandatory pre-write backup")
    args = parser.parse_args(argv)
    if args.command == "flash" and args.write and (not args.experimental or args.backup is None):
        parser.error("--write requires --experimental and --backup NEW_FILE")
    try:
        # Validate before loading IOKit, allowing offline use on any OS.
        if args.command in ("inspect-image", "flash"):
            image = args.image.read_bytes()
            validate_image(image)
        if args.command == "inspect-image":
            print(json.dumps({"image": str(args.image), "size": len(image), "board_id": "0x0112",
                              "version": "03.12.002", "sha256": hashlib.sha256(image).hexdigest()}, indent=2))
            return 0
        native = Native()
        if args.command == "list":
            endpoints = native.endpoints()
            print(json.dumps(endpoints, indent=2))
            if not any(entry["native_aux"] for entry in endpoints):
                print("No native AUX interface exposed. This backend cannot update MST on this setup. "
                      "Apple Silicon support is not established.", file=sys.stderr)
            return 0
        with native.open(args.device) as aux:
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
    except (MstError, AuxError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. If an update was running, keep the dock powered.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
