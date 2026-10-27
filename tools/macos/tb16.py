#!/usr/bin/env python3
"""Experimental native macOS TB16 MST/NVM tools. No ASMedia writer."""
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
    commands.add_parser("display-modes", help="read-only external-display modes/refresh rates using CoreGraphics")
    commands.add_parser("list-tbt", help="list TB16 switches and parent controllers using IORegistry")
    tbt = commands.add_parser("read-tbt-config", help="experimental read-only Thunderbolt configuration access")
    tbt.add_argument("--device", type=device_id, required=True)
    tbt.add_argument("--experimental", action="store_true")
    tbt.add_argument("--space", choices=("switch", "port"), default="switch")
    tbt.add_argument("--port", type=int, default=0)
    tbt.add_argument("--offset", type=lambda s: int(s, 0), default=0, help="DWORD offset, not byte address")
    tbt.add_argument("--count", type=int, default=5, help="1-16 DWORDs")
    nvm = commands.add_parser("read-nvm-header", help="read active NVM version using the control mailbox; requires sudo")
    nvm.add_argument("--device", type=device_id, required=True)
    nvm.add_argument("--experimental", action="store_true")
    nvm_backup = commands.add_parser("backup-nvm", help="save two matching reads of the active NVM bank; requires sudo")
    nvm_backup.add_argument("--device", type=device_id, required=True)
    nvm_backup.add_argument("--experimental", action="store_true")
    nvm_backup.add_argument("--output", type=Path, required=True)
    plan = commands.add_parser("plan-nvm", help="offline NVM update plan from an existing active-bank backup")
    plan.add_argument("--target", choices=("cable", "dock"), required=True)
    plan.add_argument("--image", type=Path, required=True)
    plan.add_argument("--backup", type=Path, required=True)
    update = commands.add_parser("update-nvm", help="NVM dry run; staging requires --write; auth requires --authenticate")
    update.add_argument("--device", type=device_id, required=True)
    update.add_argument("--experimental", action="store_true")
    update.add_argument("--image", type=Path, required=True)
    update.add_argument("--backup", type=Path, help="new active-bank backup file required for --write")
    update.add_argument("--write", action="store_true", help="stage to inactive NVM bank (experimental; tested on one M5/TB16)")
    update.add_argument("--authenticate", action="store_true", help="also request authentication once after staging")
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
    if args.command in ("read-tbt-config", "read-nvm-header", "backup-nvm", "update-nvm") and not args.experimental:
        parser.error(f"{args.command} requires --experimental (private, build-specific kernel ABI)")
    if args.command == "update-nvm":
        if args.authenticate and not args.write:
            parser.error("--authenticate requires --write in the same session")
        if args.write and args.backup is None:
            parser.error("--write requires --backup NEW_FILE")
        if not args.write and args.backup is not None:
            parser.error("Dry runs do not save a backup; omit --backup or use offline plan-nvm")
    if args.command == "read-tbt-config":
        from thunderbolt import validate_read
        try:
            validate_read(2 if args.space == "switch" else 1, args.port, args.offset, args.count)
        except AuxError as error:
            parser.error(str(error))
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
        if args.command == "display-modes":
            from display_modes import collect
            print(json.dumps(collect(), indent=2))
            return 0
        if args.command == "plan-nvm":
            from nvm import plan_update
            print(json.dumps(plan_update(args.image.read_bytes(), args.backup.read_bytes(),
                                         0xb051 if args.target == "cable" else 0xb054), indent=2))
            return 0
        if args.command == "update-nvm":
            from nvm import plan_header, update, validate_nvm_image
            from thunderbolt import Thunderbolt
            image = args.image.read_bytes()
            # Hash allowlist before opening a device; exact role is checked below.
            from nvm import IMAGES
            if hashlib.sha256(image).hexdigest() not in IMAGES:
                raise AuxError("Unsupported NVM image; expected a pinned cable/dock image")
            native = Thunderbolt()
            endpoint = next((entry for entry in native.endpoints() if int(entry["id"], 0) == args.device), None)
            if endpoint is None:
                raise AuxError("Selected TB16 switch is no longer present; enumerate again")
            model = int(endpoint["model_id"], 0)
            validate_nvm_image(image, model)
            with native.open(args.device) as reader:
                if args.write:
                    result = update(reader, image, model, args.backup, args.authenticate,
                                    progress=lambda line: print(line, file=sys.stderr, flush=True))
                else:
                    result = {**plan_header(image, reader.nvm_header(), model), "state": "dry_run",
                              "backup_checked": False, "authentication_attempted": False}
            print(json.dumps({"device": f"0x{args.device:x}", **result}, indent=2))
            if result["state"] == "authentication_outcome_unknown":
                return 2
            return 1 if result["state"] == "authentication_failed" else 0
        if args.command in ("list-tbt", "read-tbt-config", "read-nvm-header", "backup-nvm"):
            from thunderbolt import Thunderbolt
            thunderbolt = Thunderbolt()
            if args.command == "list-tbt":
                print(json.dumps(thunderbolt.endpoints(), indent=2))
            else:
                with thunderbolt.open(args.device) as reader:
                    if args.command == "backup-nvm":
                        result = reader.backup_nvm(args.output, progress=lambda line: print(line, file=sys.stderr, flush=True))
                        print(json.dumps({"device": f"0x{args.device:x}", **result}, indent=2))
                        return 0
                    if args.command == "read-nvm-header":
                        print(json.dumps({"device": f"0x{args.device:x}", **reader.nvm_header()}, indent=2))
                        return 0
                    data = reader.read(2 if args.space == "switch" else 1,
                                       args.port, args.offset, args.count)
                    print(json.dumps({"device": f"0x{args.device:x}", "space": args.space,
                                      "port": args.port, "dword_offset": args.offset,
                                      "dwords": [f"0x{word:08x}" for word in data]}, indent=2))
            return 0
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
