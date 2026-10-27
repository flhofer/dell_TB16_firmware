"""Synaptics Leaf VMM3320/VMM3330 remote-control protocol; see README references."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import struct
import time
import warnings

CAP, COMMAND, LENGTH, OFFSET, DATA = 0x4B0, 0x4B2, 0x4B8, 0x4BC, 0x4C0
ENABLE, DISABLE, CHECKSUM, ERASE = 0x01, 0x02, 0x11, 0x14
WRITE_EEPROM, READ_EEPROM, READ_MEMORY = 0x20, 0x30, 0x31
FLASH_SIZE = 0x10000
IMAGE_SIZE = 65486
IMAGE_SHA256 = "8305593acb4ca190dd2a87bf0f35230054b0fe673aeda2739e2af65e8ced87a6"
BOARD_ID = 0x0112


class MstError(RuntimeError):
    pass


def validate_image(image):
    if len(image) != IMAGE_SIZE or hashlib.sha256(image).hexdigest() != IMAGE_SHA256:
        raise MstError("Expected the unmodified bins/bme-ie-03.12.002.eeprom image")
    if int.from_bytes(image[0x10E:0x110], "big") != BOARD_ID:
        raise MstError("Firmware board ID is not TB16 board 0x0112")


def save_backup(path, data):
    """Save exclusively, flush and verify before allowing erase."""
    if len(data) != FLASH_SIZE:
        raise MstError("Backup must contain the full 64 KiB EEPROM")
    with Path(path).open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    if Path(path).read_bytes() != data:
        raise MstError("Saved backup failed verification")


class Mst:
    def __init__(self, aux, sleep=time.sleep, monotonic=time.monotonic):
        self.aux, self.sleep, self.monotonic = aux, sleep, monotonic

    def read(self, address, size):
        data = self.aux.read(address, size)
        if len(data) != size:
            raise MstError(f"Short AUX read at 0x{address:x}: {len(data)}/{size}")
        return data

    def probe(self):
        """Read chip/version without enabling remote control."""
        capable = bool(self.read(CAP, 1)[0] & 0x04)
        chip = int.from_bytes(self.read(0x507, 2), "big")
        version = ".".join(f"{part:02d}" for part in self.read(0x50A, 3))
        return {"chip": f"VMM{chip:04x}", "version": version,
                "remote_control": capable,
                "supported_chip": chip in (0x3320, 0x3330)}

    def check_chip(self):
        info = self.probe()
        if not info["supported_chip"] or not info["remote_control"]:
            raise MstError(f"Unsupported MST target: {info}")
        return info

    def command(self, command, allow_disabled=False):
        # Do not submit a new command over an unfinished operation.
        if self.read(COMMAND, 1)[0] & 0x80:
            raise MstError("MST remote control is busy; no new command submitted")
        self.aux.write(COMMAND, bytes([command | 0x80]))
        deadline = self.monotonic() + 3.0
        while True:
            state, result = self.read(COMMAND, 2)
            if not state & 0x80:
                if result and not (allow_disabled and result == 4):
                    raise MstError(f"MST command 0x{command:02x} failed: status 0x{result:02x}")
                return
            if self.monotonic() >= deadline:
                raise MstError(f"MST command 0x{command:02x} timed out; keep dock powered")
            self.sleep(0.1)

    def parameters(self, offset, size):
        self.aux.write(OFFSET, struct.pack("<I", offset))
        self.aux.write(LENGTH, struct.pack("<I", size))

    def set(self, command, offset, data):
        if not data:
            self.command(command)
            return
        for position in range(0, len(data), 32):
            chunk = data[position:position + 32]
            self.aux.write(DATA, chunk)
            self.parameters(offset + position, len(chunk))
            self.command(command)

    def get(self, command, offset, size):
        result = bytearray()
        for position in range(0, size, 32):
            length = min(32, size - position)
            self.parameters(offset + position, length)
            self.command(command)
            result.extend(self.read(DATA, length))
        return bytes(result)

    @contextmanager
    def session(self):
        self.check_chip()
        self.command(DISABLE, allow_disabled=True)
        try:
            self.set(ENABLE, 0, b"PRIUS")
            yield
        except BaseException:
            # Never send another command if one timed out and is still busy.
            try:
                self.command(DISABLE, allow_disabled=True)
            except Exception as cleanup_error:
                warnings.warn(f"Could not leave remote control: {cleanup_error}")
            raise
        else:
            self.command(DISABLE, allow_disabled=True)

    def check_board(self):
        board = int.from_bytes(self.get(READ_MEMORY, 0x170E, 4)[:2], "big")
        if board != BOARD_ID:
            raise MstError(f"Board 0x{board:04x} is not TB16 board 0x{BOARD_ID:04x}")
        return board

    def backup(self, path):
        with self.session():
            self.check_board()
            data = self.get(READ_EEPROM, 0, FLASH_SIZE)
            if self.get(READ_EEPROM, 0, FLASH_SIZE) != data:
                raise MstError("EEPROM reads differ; refusing to save an unstable backup")
            save_backup(path, data)
        return hashlib.sha256(data).hexdigest()

    def flash(self, image, backup_path, progress=lambda message: None):
        validate_image(image)
        if Path(backup_path).exists():
            raise MstError("Backup already exists; choose a new path")
        with self.session():
            self.check_board()
            original = self.get(READ_EEPROM, 0, FLASH_SIZE)
            if self.get(READ_EEPROM, 0, FLASH_SIZE) != original:
                raise MstError("EEPROM reads differ; refusing to erase")
            save_backup(backup_path, original)
            progress(f"Backup saved: {backup_path} (SHA-256 {hashlib.sha256(original).hexdigest()})")
            self.check_chip()
            self.check_board()
            # Erase once; a failed update must not restart automatically.
            progress("Erasing EEPROM; keep dock power and display cables connected")
            try:
                self.set(ERASE, 0, b"\xff\xff")
                self.sleep(5.0)
                for offset in range(0, len(image), 32):
                    self.set(WRITE_EEPROM, offset, image[offset:offset + 32])
                    if offset % 4096 == 0:
                        progress(f"Writing: {offset * 100 // len(image)}%")
                self.parameters(0, len(image))
                self.command(CHECKSUM)
                checksum = int.from_bytes(self.read(DATA, 4), "little")
                if checksum != sum(image):
                    raise MstError("Device EEPROM checksum does not match the image")
                expected = image + b"\xff" * (FLASH_SIZE - len(image))
                if self.get(READ_EEPROM, 0, FLASH_SIZE) != expected:
                    raise MstError("Full EEPROM readback does not match the written image")
            except BaseException as error:
                raise MstError("Update interrupted or failed after erase began. Keep the dock powered; "
                               f"do not restart it. Preserve backup {backup_path}. Cause: {error}") from error
            progress("Written image verified by device checksum and full EEPROM readback")
