from contextlib import nullcontext, redirect_stderr, redirect_stdout
import ctypes as C
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native import AuxError
from nvm import digest, plan_update, update, validate_nvm_image
from thunderbolt import ConfigReader, parse_nvm_header
import tb16

BINS = tb16.DEFAULT_IMAGE.parent


def active_image(role="cable"):
    filename = "Cable_16_00.bin" if role == "cable" else "Dock_BME_16_00.bin"
    image = (BINS / filename).read_bytes()
    start = int.from_bytes(image[:4], "little") & 0xffffff
    digital = image[start:]
    return digital.ljust(parse_nvm_header(digital[:80])["active_bank_size"], b"\xff")


class EmulatedReader(ConfigReader):
    def __init__(self, backup_path, active=None):
        self.handle = C.c_void_p(42)
        self.lib = MagicMock()
        self.active = active if active is not None else active_image()
        self.backup_path = backup_path
        self.staged = bytearray()
        self.fail_write = None
        self.corrupt_active = False
        self.auth_code = self.auth_status = 0
        self.auth_attempted = 1
        self.lib.tb16_tbt_nvm_stage_begin.side_effect = self.begin
        self.lib.tb16_tbt_nvm_stage_write.side_effect = self.write
        self.lib.tb16_tbt_nvm_authenticate.side_effect = self.auth

    def mailbox(self):
        return nullcontext()

    def _nvm_header(self):
        return parse_nvm_header(self.active[:80])

    def _active_bank(self, size, progress=lambda line: None):
        assert size == len(self.active)
        if self.corrupt_active and self.staged:
            return self.active[:-1] + bytes([self.active[-1] ^ 1])
        return self.active

    def begin(self, handle, model, size):
        assert handle == self.handle and model in (0xb051, 0xb054)
        assert self.backup_path.read_bytes() == self.active
        self.expected_size = size
        return 0

    def write(self, handle, address, data, size):
        assert handle == self.handle and address == len(self.staged)
        assert self.backup_path.read_bytes() == self.active
        if address == self.fail_write:
            return 0xe00002d6
        self.staged.extend(bytes(data))
        assert len(data) == size <= 64 and size % 4 == 0
        return 0

    def auth(self, handle, status, attempted):
        assert handle == self.handle and len(self.staged) == self.expected_size
        status._obj.value, attempted._obj.value = self.auth_status, self.auth_attempted
        return self.auth_code


class NvmUpdateTests(unittest.TestCase):
    def test_image_plans_strip_prefix_and_bind_roles(self):
        for name, role, model, version, size in (
                ("Cable_26_06.bin", "cable", 0xb051, "26.06", 217088),
                ("Dock_BME_27_00.bin", "dock", 0xb054, "27.00", 212992)):
            image = (BINS / name).read_bytes()
            plan = plan_update(image, active_image(role), model)
            self.assertEqual((plan["target_version"], plan["staging_bytes"]), (version, size))
            self.assertEqual(plan["farb_bytes_skipped"], 16384)
            self.assertEqual(plan["staging_sha256"], digest(image[16384:]))
            self.assertFalse(plan["css_header_write"])
            self.assertFalse(plan["firmware_written"])
            self.assertFalse(plan["inactive_readback_available"])
            with self.assertRaisesRegex(AuxError, "requires the"):
                validate_nvm_image(image, 0xb054 if model == 0xb051 else 0xb051)

    def test_modified_old_unsigned_and_other_component_images_rejected(self):
        current = (BINS / "Cable_26_06.bin").read_bytes()
        candidates = [b"", current[:-1], current[:-1] + bytes([current[-1] ^ 1])]
        candidates += [(BINS / name).read_bytes() for name in
                       ("Cable_16_00.bin", "Cable_16_00_nosec.bin", "bme-ie-03.12.002.eeprom")]
        for image in candidates:
            with self.assertRaisesRegex(AuxError, "pinned"):
                validate_nvm_image(image, 0xb051)

    def test_backup_shape_and_installed_version_must_be_supported(self):
        image = (BINS / "Cable_26_06.bin").read_bytes()
        backup = active_image()
        for bad in (backup[:-4], image, backup[:80], b"", backup + b"\xff" * 4):
            with self.assertRaises(AuxError):
                plan_update(image, bad, 0xb051)
        newer = bytearray(backup)
        newer[10] = 0x26
        with self.assertRaisesRegex(AuxError, "16.00 only"):
            plan_update(image, newer, 0xb051)

    def test_update_saves_backup_then_stages_payload_and_authenticates_once(self):
        for name, role, model in (("Cable_26_06.bin", "cable", 0xb051),
                                  ("Dock_BME_27_00.bin", "dock", 0xb054)):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "before.backup.bin"
                reader = EmulatedReader(path, active_image(role))
                image = (BINS / name).read_bytes()
                result = update(reader, image, model, path, authenticate=True)
                self.assertEqual(bytes(reader.staged), image[0x4000:])
                self.assertEqual(path.read_bytes(), reader.active)
                self.assertEqual(result["state"], "authentication_reported")
                self.assertTrue(result["active_bank_unchanged"])
                self.assertFalse(result["activation_verified"])
                self.assertFalse(result["staged_readback_verified"])
                reader.lib.tb16_tbt_nvm_authenticate.assert_called_once()

    def test_stage_only_never_authenticates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "before.backup.bin"
            reader = EmulatedReader(path)
            result = update(reader, (BINS / "Cable_26_06.bin").read_bytes(), 0xb051, path)
            self.assertEqual(result["state"], "staged_unverified")
            self.assertFalse(result["authentication_attempted"])
            reader.lib.tb16_tbt_nvm_authenticate.assert_not_called()

    def test_write_failure_or_active_change_never_authenticates(self):
        for failure in ("write", "active"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "before.backup.bin"
                reader = EmulatedReader(path)
                reader.fail_write = 64 if failure == "write" else None
                reader.corrupt_active = failure == "active"
                with self.assertRaises(AuxError):
                    update(reader, (BINS / "Cable_26_06.bin").read_bytes(), 0xb051, path, True)
                self.assertEqual(path.read_bytes(), reader.active)
                reader.lib.tb16_tbt_nvm_authenticate.assert_not_called()

    def test_image_or_backup_failure_never_begins_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "before.backup.bin"
            reader = EmulatedReader(path)
            image = (BINS / "Cable_26_06.bin").read_bytes()
            with self.assertRaises(AuxError):
                update(reader, image, 0xb054, path, True)
            self.assertFalse(path.exists())
            path.write_bytes(b"preserve")
            with self.assertRaises(AuxError):
                update(reader, image, 0xb051, path, True)
            self.assertEqual(path.read_bytes(), b"preserve")
            reader.lib.tb16_tbt_nvm_stage_begin.assert_not_called()
            reader.lib.tb16_tbt_nvm_authenticate.assert_not_called()

    def test_authentication_error_and_disconnect_are_never_reported_as_activation(self):
        for code, status, expected in ((0, 1, "authentication_failed"),
                                        (0xe00002c0, 0xffffffff, "authentication_outcome_unknown"),
                                        (0, 0xffffffff, "authentication_outcome_unknown")):
            reader = EmulatedReader(Path("unused"))
            reader.expected_size = 0
            reader.auth_code, reader.auth_status = code, status
            result = reader.authenticate()
            self.assertEqual(result["state"], expected)
            self.assertFalse(result["activation_verified"])
            reader.lib.tb16_tbt_nvm_authenticate.assert_called_once()
        reader = EmulatedReader(Path("unused"))
        reader.expected_size = 0
        reader.auth_code, reader.auth_attempted = 0xe00002c0, 0
        with self.assertRaisesRegex(AuxError, "no authentication requested"):
            reader.authenticate()

    def test_offline_cli_does_not_load_native_library(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "before.backup.bin"
            path.write_bytes(active_image())
            out = io.StringIO()
            with patch("thunderbolt.Thunderbolt") as native, redirect_stdout(out):
                result = tb16.main(["plan-nvm", "--target", "cable", "--image",
                                    str(BINS / "Cable_26_06.bin"), "--backup", str(path)])
            native.assert_not_called()
            self.assertEqual(result, 0)
            self.assertFalse(json.loads(out.getvalue())["firmware_written"])

    def test_live_cli_defaults_to_header_only_dry_run(self):
        reader = MagicMock()
        reader.nvm_header.return_value = parse_nvm_header(active_image()[:80])
        out = io.StringIO()
        with patch("thunderbolt.Thunderbolt") as native, redirect_stdout(out):
            native.return_value.endpoints.return_value = [{"id": "0x1", "model_id": "0xb051"}]
            native.return_value.open.return_value.__enter__.return_value = reader
            result = tb16.main(["update-nvm", "--experimental", "--device", "1", "--image",
                                str(BINS / "Cable_26_06.bin")])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(out.getvalue())["state"], "dry_run")
        reader.nvm_header.assert_called_once()
        reader._backup_nvm.assert_not_called()
        reader.stage_begin.assert_not_called()
        reader.authenticate.assert_not_called()

    def test_cli_write_and_auth_guards_precede_native_loading(self):
        base = ["update-nvm", "--device", "1", "--image", str(BINS / "Cable_26_06.bin")]
        for flags in ([], ["--experimental", "--write"], ["--experimental", "--authenticate"],
                      ["--experimental", "--backup", "unused"]):
            with patch("thunderbolt.Thunderbolt") as native, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    tb16.main(base + flags)
                native.assert_not_called()

    def test_cli_preserves_authentication_exit_codes(self):
        for state, expected in (("authentication_reported", 0), ("authentication_failed", 1),
                                ("authentication_outcome_unknown", 2)):
            with patch("thunderbolt.Thunderbolt") as native, patch("nvm.update") as writer:
                native.return_value.endpoints.return_value = [{"id": "0x1", "model_id": "0xb051"}]
                writer.return_value = {"state": state, "activation_verified": False}
                output = io.StringIO()
                with redirect_stdout(output):
                    code = tb16.main(["update-nvm", "--experimental", "--device", "1",
                                      "--image", str(BINS / "Cable_26_06.bin"), "--write",
                                      "--authenticate", "--backup", "unused.backup.bin"])
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(output.getvalue())["state"], state)
                writer.assert_called_once()

    def test_cli_wrong_controller_never_opens_device(self):
        with patch("thunderbolt.Thunderbolt") as native, redirect_stderr(io.StringIO()):
            native.return_value.endpoints.return_value = [{"id": "0x1", "model_id": "0xb054"}]
            code = tb16.main(["update-nvm", "--experimental", "--device", "1", "--image",
                              str(BINS / "Cable_26_06.bin"), "--write", "--backup", "unused.backup.bin"])
            self.assertEqual(code, 1)
            native.return_value.open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
