#!/usr/bin/env python3
"""Experimental macOS TB16 firmware tools."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from mst import Mst, validate_image
from native import AuxError, IodpNative, Native

DEFAULT_IMAGE = Path(__file__).resolve().parents[2] / "bins/bme-ie-03.12.002.eeprom"
NVM_COMMANDS = {
    "read-tbt-config": "read switch/port registers",
    "read-nvm-header": "read active firmware version (sudo)",
    "backup-nvm": "back up the active bank (sudo)",
    "update-nvm": "update NVM (sudo; dry run unless --write)",
}


def device_id(value):
    try:
        result = int(value, 0)
        if not 0 < result < 2**64:
            raise ValueError
        return result
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected a nonzero 64-bit IORegistry ID") from error


def show(value):
    print(json.dumps(value, indent=2))


def progress(message):
    print(message, file=sys.stderr, flush=True)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    device = argparse.ArgumentParser(add_help=False)
    device.add_argument("--device", type=device_id, required=True, help="IORegistry ID from list; changes after replug")
    device.add_argument("--experimental", action="store_true")

    for name, help_text in (("diagnose", "filtered dock/display report"),
                            ("display-modes", "external-display modes and refresh rates"),
                            ("list-tbt", "list TB16 Thunderbolt controllers")):
        commands.add_parser(name, help=help_text)
    for name, help_text in NVM_COMMANDS.items():
        command = commands.add_parser(name, help=help_text, parents=[device])
        if name == "read-tbt-config":
            command.add_argument("--space", choices=("switch", "port"), default="switch")
            command.add_argument("--port", type=int, default=0)
            command.add_argument("--offset", type=lambda s: int(s, 0), default=0, help="DWORD offset")
            command.add_argument("--count", type=int, default=5, help="1-16 DWORDs")
        elif name == "backup-nvm":
            command.add_argument("--output", type=Path, required=True)
        elif name == "update-nvm":
            command.add_argument("--image", type=Path, required=True)
            command.add_argument("--backup", type=Path, help="new backup file required for --write")
            command.add_argument("--write", action="store_true", help="stage the inactive bank; default is a dry run")
            command.add_argument("--authenticate", action="store_true", help="authenticate after staging")

    plan = commands.add_parser("plan-nvm", help="offline update plan")
    plan.add_argument("--target", choices=("cable", "dock"), required=True)
    plan.add_argument("--image", type=Path, required=True)
    plan.add_argument("--backup", type=Path, required=True)
    inspect = commands.add_parser("inspect-image", help="validate the bundled MST image")
    inspect.add_argument("image", nargs="?", type=Path, default=DEFAULT_IMAGE)
    for name, help_text in (("list", "list AUX interfaces"), ("probe", "read MST chip/version"),
                            ("backup", "back up MST EEPROM"), ("flash", "experimental MST update"),
                            ("read-dpcd", "read DPCD bytes")):
        command = commands.add_parser(name, help=help_text, parents=[] if name == "list" else [device])
        command.add_argument("--backend", choices=("ioi2c", "iodp"), default="ioi2c")
        if name == "list":
            command.add_argument("--experimental", action="store_true")
        elif name == "read-dpcd":
            command.add_argument("--address", type=lambda s: int(s, 0), default=0)
            command.add_argument("--length", type=int, default=16)
        elif name == "backup":
            command.add_argument("--output", type=Path, required=True)
        elif name == "flash":
            command.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
            command.add_argument("--write", action="store_true")
            command.add_argument("--backup", type=Path, help="new backup file required for --write")
    return parser


def validate_args(parser, args):
    if args.command in NVM_COMMANDS and not args.experimental:
        parser.error(f"{args.command} requires --experimental (build-specific private ABI)")
    if args.command == "update-nvm":
        if args.authenticate and not args.write:
            parser.error("--authenticate requires --write in the same session")
        if args.write and args.backup is None:
            parser.error("--write requires --backup NEW_FILE")
        if not args.write and args.backup is not None:
            parser.error("Dry runs do not save backups; omit --backup or use plan-nvm")
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
            parser.error("--backend iodp requires --experimental")
        if args.command == "backup" or (args.command == "flash" and args.write):
            parser.error("IODP is read-only; EEPROM backup and writing are unavailable")
    if args.command == "read-dpcd" and (not 1 <= args.length <= 256 or args.address < 0 or
                                       args.address + args.length > 0x100000):
        parser.error("DPCD address must be 20-bit and length 1-256")


def run_update(args):
    from nvm import IMAGES, plan_header, update, validate_nvm_image
    from thunderbolt import Thunderbolt

    image = args.image.read_bytes()
    if hashlib.sha256(image).hexdigest() not in IMAGES:
        raise AuxError("Expected a pinned cable/dock NVM image")
    native = Thunderbolt()
    endpoint = next((e for e in native.endpoints() if int(e["id"], 0) == args.device), None)
    if endpoint is None:
        raise AuxError("TB16 switch is no longer present; enumerate again")
    model = int(endpoint["model_id"], 0)
    validate_nvm_image(image, model)
    with native.open(args.device) as reader:
        if args.write:
            result = update(reader, image, model, args.backup, args.authenticate, progress)
        else:
            result = {**plan_header(image, reader.nvm_header(), model), "state": "dry_run",
                      "backup_checked": False, "authentication_attempted": False}
    show({"device": f"0x{args.device:x}", **result})
    return {"authentication_failed": 1, "authentication_outcome_unknown": 2}.get(result["state"], 0)


def run_thunderbolt(args):
    from thunderbolt import Thunderbolt

    native = Thunderbolt()
    if args.command == "list-tbt":
        show(native.endpoints())
        return
    with native.open(args.device) as reader:
        if args.command == "backup-nvm":
            result = reader.backup_nvm(args.output, progress)
        elif args.command == "read-nvm-header":
            result = reader.nvm_header()
        else:
            data = reader.read(2 if args.space == "switch" else 1, args.port, args.offset, args.count)
            result = {"space": args.space, "port": args.port, "dword_offset": args.offset,
                      "dwords": [f"0x{word:08x}" for word in data]}
        show({"device": f"0x{args.device:x}", **result})


def run_aux(args):
    if args.command == "flash":
        image = args.image.read_bytes()
        validate_image(image)
    native = IodpNative() if args.backend == "iodp" else Native()
    if args.command == "list":
        endpoints = native.endpoints()
        show(endpoints)
        capability = "external" if args.backend == "iodp" else "native_aux"
        if not any(e[capability] for e in endpoints):
            progress("No usable external AUX interface.")
        return
    with native.open(args.device) as aux:
        if args.command == "read-dpcd":
            data = aux.read(args.address, args.length)
            show({"device": f"0x{args.device:x}", "backend": args.backend,
                  "address": f"0x{args.address:05x}", "length": len(data), "hex": data.hex()})
            return
        mst = Mst(aux)
        show({"device": f"0x{args.device:x}", **mst.check_chip()})
        if args.command == "backup":
            print(f"EEPROM backup: {args.output}; SHA-256 {mst.backup(args.output)}")
        elif args.command == "flash":
            if args.write:
                progress("Experimental MST write; not hardware-validated.")
                mst.flash(image, args.backup, progress)
                print("EEPROM verified. Power-cycle the dock, then probe again.")
            else:
                print("Dry run: image and chip checked. Board/EEPROM checks require backup or write.")


def run(args):
    if args.command == "update-nvm":
        return run_update(args)
    if args.command == "list-tbt" or args.command in NVM_COMMANDS:
        return run_thunderbolt(args)
    if args.command == "plan-nvm":
        from nvm import plan_update
        show(plan_update(args.image.read_bytes(), args.backup.read_bytes(),
                         0xb051 if args.target == "cable" else 0xb054))
    elif args.command == "inspect-image":
        image = args.image.read_bytes()
        validate_image(image)
        show({"image": str(args.image), "size": len(image), "board_id": "0x0112",
              "version": "03.12.002", "sha256": hashlib.sha256(image).hexdigest()})
    elif args.command == "diagnose":
        from diagnostics import collect
        show(collect())
    elif args.command == "display-modes":
        from display_modes import collect
        show(collect())
    else:
        return run_aux(args)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    try:
        return run(args) or 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        progress(f"Error: {error}")
        return 1
    except KeyboardInterrupt:
        progress("Interrupted. If writing firmware, keep the dock powered.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
