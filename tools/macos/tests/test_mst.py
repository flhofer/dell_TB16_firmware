"""Protocol emulator: exercises real bundled firmware without touching a dock."""
from contextlib import redirect_stderr, redirect_stdout
import ctypes as C
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mst
import native
import tb16

IMAGE = tb16.DEFAULT_IMAGE.read_bytes()


class Dock:
    """A Leaf remote-control endpoint, independently decoding on-wire registers."""
    def __init__(self, chip=0x3320, board=0x0112):
        self.chip, self.board = chip, board
        self.flash = bytearray((i * 17 + 3) % 256 for i in range(65536))
        self.registers = bytearray(0x1000)
        self.enabled = False
        self.commands = []
        self.writes = []
        self.fail_write = False
        self.bad_checksum = False
        self.corrupt_readback = False
        self.stuck = False
        self.short_read = False
        self.capable = True
        self.erase_count = 0

    def read(self, address, size):
        if address == 0x4B0:
            return bytes([4 if self.capable else 0])
        if address == 0x507:
            return self.chip.to_bytes(2, "big")
        if address == 0x50A:
            return b"\x03\x0c\x02"
        if self.short_read:
            return b""
        return bytes(self.registers[address:address + size])

    def write(self, address, data):
        self.writes.append((address, bytes(data)))
        self.registers[address:address + len(data)] = data
        if address != 0x4B2:
            return
        command = data[0] & 0x7F
        self.commands.append(command)
        if self.stuck:
            return
        offset = struct.unpack_from("<I", self.registers, 0x4BC)[0]
        size = struct.unpack_from("<I", self.registers, 0x4B8)[0]
        payload = self.registers[0x4C0:0x4C0 + size]
        status = 0
        if command == 2:
            status = 0 if self.enabled else 4
            self.enabled = False
        elif command == 1:
            self.enabled = payload == b"PRIUS"
            status = 0 if self.enabled else 3
        elif not self.enabled:
            status = 4
        elif command == 0x31:
            assert offset == 0x170E and size == 4
            self.registers[0x4C0:0x4C4] = self.board.to_bytes(2, "big") + b"\0\0"
        elif command == 0x30:
            assert 0 < size <= 32 and offset + size <= 65536
            result = self.flash[offset:offset + size]
            if self.corrupt_readback and self.erase_count:
                result[0] ^= 1
            self.registers[0x4C0:0x4C0 + size] = result
        elif command == 0x14:
            assert offset == 0 and payload == b"\xff\xff"
            self.erase_count += 1
            self.flash[:] = b"\xff" * 65536
        elif command == 0x20:
            assert 0 < size <= 32 and offset + size <= 65536
            if self.fail_write:
                status = 3
            else:
                self.flash[offset:offset + size] = payload
        elif command == 0x11:
            checksum = sum(self.flash[offset:offset + size]) + int(self.bad_checksum)
            self.registers[0x4C0:0x4C4] = checksum.to_bytes(4, "little")
        else:
            raise AssertionError(f"Unexpected command {command:#x}")
        self.registers[0x4B2:0x4B4] = bytes([command, status])


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backup = Path(self.temp.name) / "original.bin"
        self.dock = Dock()
        self.device = mst.Mst(self.dock, sleep=lambda _: None)

    def test_known_image_and_reject_other_component(self):
        mst.validate_image(IMAGE)
        for wrong in (b"", IMAGE[:-1], bytes([IMAGE[0] ^ 1]) + IMAGE[1:],
                      tb16.DEFAULT_IMAGE.with_name("Cable_26_06.bin").read_bytes()):
            with self.assertRaises(mst.MstError):
                mst.validate_image(wrong)

    def test_probe_is_read_only(self):
        self.assertEqual(self.device.check_chip()["version"], "03.12.02")
        self.assertEqual(self.dock.writes, [])

    def test_backup_preserves_all_bytes_without_erase(self):
        original = bytes(self.dock.flash)
        self.device.backup(self.backup)
        self.assertEqual(self.backup.read_bytes(), original)
        self.assertNotIn(0x14, self.dock.commands)
        self.assertNotIn(0x20, self.dock.commands)
        self.assertFalse(self.dock.enabled)

    def test_update_both_supported_chips_and_short_final_block(self):
        for chip in (0x3320, 0x3330):
            with self.subTest(chip=chip):
                dock = Dock(chip=chip)
                original = bytes(dock.flash)
                path = self.backup.with_name(f"{chip:x}.bin")
                mst.Mst(dock, sleep=lambda _: None).flash(IMAGE, path)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(dock.flash, IMAGE + b"\xff" * 50)
                self.assertEqual(dock.erase_count, 1)
                self.assertFalse(dock.enabled)

    def test_incompatible_chip_or_missing_rc_never_writes(self):
        for chip, capable in ((0x5320, True), (0x3320, False)):
            self.dock.chip, self.dock.capable = chip, capable
            with self.assertRaises(mst.MstError):
                self.device.flash(IMAGE, self.backup)
            self.assertEqual(self.dock.writes, [])

    def test_wrong_board_aborts_before_backup_or_erase(self):
        self.dock.board = 0x0113
        with self.assertRaisesRegex(mst.MstError, "not TB16"):
            self.device.flash(IMAGE, self.backup)
        self.assertFalse(self.backup.exists())
        self.assertNotIn(0x14, self.dock.commands)
        self.assertFalse(self.dock.enabled)

    def test_bad_image_rejected_before_any_device_write(self):
        with self.assertRaises(mst.MstError):
            self.device.flash(IMAGE[:-1], self.backup)
        self.assertEqual(self.dock.writes, [])

    def test_existing_backup_is_not_overwritten(self):
        self.backup.write_bytes(b"keep me")
        with self.assertRaises(mst.MstError):
            self.device.flash(IMAGE, self.backup)
        self.assertEqual(self.backup.read_bytes(), b"keep me")
        self.assertEqual(self.dock.writes, [])

    def test_cannot_save_backup_never_erases(self):
        with self.assertRaises(OSError):
            self.device.flash(IMAGE, self.backup / "missing" / "file")
        self.assertNotIn(0x14, self.dock.commands)
        self.assertFalse(self.dock.enabled)

    def test_unstable_backup_aborts(self):
        read = self.device.get
        count = 0

        def unstable(command, offset, size):
            nonlocal count
            data = read(command, offset, size)
            if command == mst.READ_EEPROM:
                count += 1
                if count == 2:
                    return bytes([data[0] ^ 1]) + data[1:]
            return data

        with patch.object(self.device, "get", side_effect=unstable):
            with self.assertRaisesRegex(mst.MstError, "reads differ"):
                self.device.flash(IMAGE, self.backup)
        self.assertFalse(self.backup.exists())
        self.assertNotIn(0x14, self.dock.commands)

    def test_backup_persisted_before_erase(self):
        write = self.dock.write
        original = bytes(self.dock.flash)

        def assert_backup(address, data):
            if address == mst.COMMAND and data[0] == (mst.ERASE | 0x80):
                self.assertEqual(self.backup.read_bytes(), original)
            write(address, data)

        with patch.object(self.dock, "write", side_effect=assert_backup):
            self.device.flash(IMAGE, self.backup)

    def test_failures_after_erase_preserve_backup_and_do_not_retry(self):
        for failure in ("fail_write", "bad_checksum", "corrupt_readback"):
            with self.subTest(failure=failure):
                dock = Dock()
                original = bytes(dock.flash)
                setattr(dock, failure, True)
                path = self.backup.with_name(failure)
                with self.assertRaisesRegex(mst.MstError, "do not restart"):
                    mst.Mst(dock, sleep=lambda _: None).flash(IMAGE, path)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(dock.erase_count, 1)
                self.assertFalse(dock.enabled)

    def test_busy_operation_is_not_overwritten(self):
        self.dock.registers[0x4B2] = 0x80
        with self.assertRaisesRegex(mst.MstError, "busy"):
            self.device.command(mst.DISABLE)
        self.assertEqual(self.dock.writes, [])

    def test_timeout_is_bounded(self):
        self.dock.stuck = True
        with patch.object(self.device, "monotonic", side_effect=(0, 0, 4)):
            with self.assertRaisesRegex(mst.MstError, "timed out"):
                self.device.command(mst.DISABLE)
        self.assertEqual(self.dock.commands, [mst.DISABLE])

    def test_short_aux_read_is_failure(self):
        self.dock.short_read = True
        with self.assertRaisesRegex(mst.MstError, "Short AUX read"):
            self.device.command(mst.DISABLE)


class PacketTests(unittest.TestCase):
    def test_native_transport_splits_at_sixteen_bytes(self):
        class Library:
            packets = []

            def tb16_transfer(self, connection, address, packet, length, writing):
                self.packets.append((address, length, writing))
                if not writing:
                    for i in range(length):
                        packet[i] = (address + i) & 255
                return 0

        aux = native.Aux.__new__(native.Aux)
        aux.lib, aux.connection = Library(), C.c_void_p(1)
        aux.write(0x4C0, b"x" * 32)
        self.assertEqual(aux.lib.packets, [(0x4C0, 16, 1), (0x4D0, 16, 1)])
        aux.lib.packets.clear()
        self.assertEqual(aux.read(0x4C0, 35), bytes(range(0xC0, 0xE3)))
        self.assertEqual(aux.lib.packets, [(0x4C0, 16, 0), (0x4D0, 16, 0), (0x4E0, 3, 0)])
        for address, data in ((-1, b"x"), (0xFFFFF, b"xx"), (0, b"")):
            with self.assertRaises(native.AuxError):
                aux.write(address, data)


class CliTests(unittest.TestCase):
    def run_cli(self, args):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            result = tb16.main(args)
        return result, output.getvalue()

    def test_image_inspection_needs_no_native_backend(self):
        with patch("tb16.Native", side_effect=AssertionError("must be offline")):
            result, output = self.run_cli(["inspect-image"])
        self.assertEqual(result, 0)
        self.assertIn(mst.IMAGE_SHA256, output)

    def test_dry_run_never_enables_remote_control(self):
        dock = Dock()
        backend = unittest.mock.MagicMock()
        backend.open.return_value.__enter__.return_value = dock
        with patch("tb16.Native", return_value=backend):
            result, output = self.run_cli(["flash", "--device", "0x123"])
        self.assertEqual(result, 0)
        self.assertIn("Dry run", output)
        self.assertEqual(dock.writes, [])

    def test_write_requires_explicit_flags_before_loading_native(self):
        for extra in ([], ["--experimental"], ["--backup", "new.bin"]):
            with patch("tb16.Native", side_effect=AssertionError("must not open")):
                with self.assertRaises(SystemExit) as error:
                    self.run_cli(["flash", "--device", "0x123", "--write"] + extra)
                self.assertEqual(error.exception.code, 2)

    def test_invalid_device_id(self):
        for value in ("-1", "0", "0x10000000000000000", "oops"):
            with self.assertRaises(SystemExit):
                self.run_cli(["probe", "--device", value])


if __name__ == "__main__":
    unittest.main()
