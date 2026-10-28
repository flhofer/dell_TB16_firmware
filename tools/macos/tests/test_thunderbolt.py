import ctypes as C
from contextlib import nullcontext, redirect_stderr
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native import AuxError
from thunderbolt import ConfigReader, parse_nvm_header, validate_read
import tb16


class ThunderboltTests(unittest.TestCase):
    def test_configuration_read_bounds(self):
        validate_read(2, 0, 0, 5)
        validate_read(1, 63, 0x1fff, 1)
        for parameters in ((0, 0, 0, 1), (2, 1, 0, 1), (1, 64, 0, 1),
                           (2, 0, -1, 1), (2, 0, 0x1fff, 2), (2, 0, 0, 17), (2, 0, 0, 0)):
            with self.subTest(parameters=parameters), self.assertRaises(AuxError):
                validate_read(*parameters)

    def test_native_configuration_argument_order(self):
        reader = ConfigReader.__new__(ConfigReader)
        reader.handle = C.c_void_p(42)
        reader.lib = MagicMock()

        def read(handle, port, space, offset, data, count):
            self.assertEqual((port, space, offset, count), (8, 1, 0, 3))
            data[0], data[1], data[2] = 0x15788086, 123, 0xE0102
            return 0

        reader.lib.tb16_tbt_read.side_effect = read
        self.assertEqual(reader.read(space=1, port=8, count=3), [0x15788086, 123, 0xE0102])

    def test_bundled_intel_images_have_expected_versions(self):
        bins = tb16.DEFAULT_IMAGE.parent
        for filename, version in (("Cable_16_00.bin", "16.00"), ("Cable_26_06.bin", "26.06"),
                                  ("Dock_BME_27_00.bin", "27.00")):
            data = (bins / filename).read_bytes()
            offset = int.from_bytes(data[:4], "little") & 0xFFFFFF
            parsed = parse_nvm_header(data[offset:offset + 80])
            self.assertEqual(parsed["nvm_version"], version)
            self.assertFalse(parsed["firmware_written"])

    def test_wrong_chip_or_truncated_header_is_rejected(self):
        for data in (bytes(80), bytes(79), bytes(81)):
            with self.assertRaises(AuxError):
                parse_nvm_header(data)

    def test_nonroot_nvm_read_never_opens_lock_or_calls_native(self):
        reader = ConfigReader.__new__(ConfigReader)
        reader.lib = MagicMock()
        with patch("thunderbolt.os.geteuid", return_value=501), patch("thunderbolt.os.open") as opened:
            with self.assertRaisesRegex(AuxError, "requires sudo"):
                reader.nvm_header()
        opened.assert_not_called()
        reader.lib.tb16_tbt_nvm_header.assert_not_called()

    def test_private_commands_require_explicit_opt_in(self):
        for command in ("read-tbt-config", "read-nvm-header"):
            with patch("thunderbolt.Thunderbolt") as native, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    tb16.main([command, "--device", "1"])
                self.assertEqual(error.exception.code, 2)
                native.assert_not_called()

    def test_invalid_config_parameters_rejected_before_native(self):
        with patch("thunderbolt.Thunderbolt") as native, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                tb16.main(["read-tbt-config", "--experimental", "--device", "1", "--port", "1"])
            native.assert_not_called()

    def backup_reader(self):
        reader = ConfigReader.__new__(ConfigReader)
        reader.handle = C.c_void_p(42)
        reader.lib = MagicMock()
        reader.mailbox = lambda: nullcontext()
        reader._nvm_header = lambda: {"active_bank_size": 128, "nvm_version": "16.00"}

        def read(handle, address, packet, length):
            for i in range(length):
                packet[i] = (address + i) & 255
            return 0

        reader.lib.tb16_tbt_nvm_read.side_effect = read
        return reader

    def test_backup_requires_two_matching_reads_and_saved_bytes(self):
        reader = self.backup_reader()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active.bin"
            result = reader.backup_nvm(path)
            self.assertEqual(path.read_bytes(), bytes(range(128)))
            self.assertEqual(result["matching_reads"], 2)
            self.assertEqual(reader.lib.tb16_tbt_nvm_read.call_count, 4)
            self.assertIn("not a complete", result["scope"])

    def test_unstable_backup_is_not_saved(self):
        reader = self.backup_reader()
        read = reader.lib.tb16_tbt_nvm_read.side_effect
        calls = 0

        def unstable(*args):
            nonlocal calls
            calls += 1
            status = read(*args)
            if calls == 3:
                args[2][0] ^= 1
            return status

        reader.lib.tb16_tbt_nvm_read.side_effect = unstable
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active.bin"
            with self.assertRaisesRegex(AuxError, "reads differ"):
                reader.backup_nvm(path)
            self.assertFalse(path.exists())

    def test_backup_never_overwrites_existing_file(self):
        reader = self.backup_reader()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active.bin"
            path.write_bytes(b"original")
            with self.assertRaises(AuxError):
                reader.backup_nvm(path)
            self.assertEqual(path.read_bytes(), b"original")
            reader.lib.tb16_tbt_nvm_read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
