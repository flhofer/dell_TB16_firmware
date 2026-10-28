import ctypes as C
import io
from pathlib import Path
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diagnostics import summarize_profiler, summarize_registry
from native import AuxError, IodpAux
import tb16


class DiagnosticTests(unittest.TestCase):
    def fixture(self):
        dock = {"IOObjectClass": "IOThunderboltSwitchType3", "Device Vendor ID": 212,
                "Device Model ID": 0xB054, "Device Model Name": "Dock - Unsupported",
                "ROM Version": 22, "EEPROM Revision": 16,
                "UID": "secret-uid", "DROM": b"secret-drom",
                "IORegistryEntryChildren": [{"Description": "DP or HDMI Adapter",
                    "Port Number": 8, "Required Bandwidth Allocated": 1,
                    "Hop Table": [{"Path": "secret-path"}],
                    "IORegistryEntryChildren": [{"IOObjectClass": "AppleThunderboltDPOutAdapterCM",
                                                  "HPD Plug State": True, "DP State": 2}]}]}
        duplicate_nub = {**dock, "IOObjectClass": "IOThunderboltNub"}
        controller = {"IOObjectClass": "AppleASMedia1042USBXHCI",
                      "IORegistryEntryChildren": [{"IOObjectClass": "IOUSBHostDevice",
                           "IORegistryEntryName": "USB5807 Hub",
                           "USB Serial Number": "secret-usb-serial"}]}
        return {"IOObjectClass": "Root", "IORegistryEntryChildren": [dock, duplicate_nub,
            controller, {"IOObjectClass": "DCPDPDeviceProxy",
                         "IODPDeviceUserInterfaceSupported": True, "Location": "Embedded"},
            {"IOObjectClass": "DCPDPDeviceProxy",
             "IODPDeviceUserInterfaceSupported": True, "Location": "External"},
            {"IOI2CTransactionTypes": 18}, {"IOI2CTransactionTypes": 2}]}

    def test_list_and_single_root_registry_formats(self):
        root = self.fixture()
        result = summarize_registry(root)
        self.assertEqual(result, summarize_registry([root]))
        self.assertEqual(len(result["tb16_switches"]), 1)
        self.assertTrue(result["asmedia_driver_attached"])
        self.assertEqual(result["usb_devices_below_asmedia"], ["USB5807 Hub"])
        self.assertEqual(result["external_iodp_device_count"], 1)
        self.assertEqual(result["ioi2c_native_aux_interfaces"], 1)
        self.assertEqual(len(result["iodp_devices"]), 2)
        self.assertEqual(result["thunderbolt_display_outputs"],
                         [{"IOObjectClass": "AppleThunderboltDPOutAdapterCM",
                           "HPD Plug State": True, "DP State": 2}])

    def test_report_omits_sensitive_properties(self):
        self.assertNotIn("secret-", str(summarize_registry(self.fixture())))

    def test_no_device_does_not_imply_transport_available(self):
        result = summarize_registry({})
        self.assertEqual(result["external_iodp_device_count"], 0)
        self.assertFalse(result["asmedia_driver_attached"])
        self.assertEqual(result["ioi2c_native_aux_interfaces"], 0)

    def test_nested_profiler_dock_and_display_omit_serials(self):
        source = {"SPThunderboltDataType": [{"_name": "Host", "_items": [
            {"vendor_id_key": "0x00D4", "device_name_key": "Cable", "_items": [
                {"vendor_id_key": "0x00d4", "device_name_key": "Dock - Unsupported",
                 "switch_uid_key": "secret-uid", "switch_version_key": "16.16"}]}]}],
            "SPDisplaysDataType": [{"spdisplays_ndrvs": [{"_name": "Test Monitor",
                                    "_spdisplays_display-serial-number": "secret-serial"}]}]}
        result = summarize_profiler(source)
        self.assertEqual(len(result["thunderbolt_dell_devices"]), 2)
        self.assertEqual(result["displays"][0]["name"], "Test Monitor")
        self.assertNotIn("secret-", str(result))


class IodpTests(unittest.TestCase):
    def test_read_packets_and_no_write_path(self):
        class Library:
            calls = []

            def tb16_iodp_read(self, connection, address, packet, length):
                self.calls.append((address, length))
                for i in range(length):
                    packet[i] = (address + i) & 255
                return 0

        aux = IodpAux.__new__(IodpAux)
        aux.lib, aux.connection = Library(), C.c_void_p(1)
        self.assertEqual(aux.read(0x500, 35), bytes(range(35)))
        self.assertEqual(aux.lib.calls, [(0x500, 16), (0x510, 16), (0x520, 3)])
        with self.assertRaisesRegex(AuxError, "read-only"):
            aux.write(0x4B2, b"\x81")
        for address, length in ((-1, 1), (0, 0), (0xFFFFF, 2)):
            with self.assertRaises(AuxError):
                aux.read(address, length)

    def test_cli_private_backend_requires_opt_in_and_blocks_flash_control(self):
        cases = [["list", "--backend", "iodp"],
                 ["backup", "--backend", "iodp", "--experimental", "--device", "1", "--output", "unused"],
                 ["flash", "--backend", "iodp", "--experimental", "--device", "1",
                  "--write", "--backup", "unused"]]
        with patch("tb16.IodpNative", side_effect=AssertionError("must not open")):
            for args in cases:
                with self.subTest(args=args), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        tb16.main(args)
                    self.assertEqual(error.exception.code, 2)

    def test_raw_read_never_runs_chip_probe(self):
        from unittest.mock import MagicMock
        aux = MagicMock()
        aux.read.return_value = b"\x14\x1e"
        backend = MagicMock()
        backend.open.return_value.__enter__.return_value = aux
        with patch("tb16.IodpNative", return_value=backend), redirect_stdout(io.StringIO()):
            self.assertEqual(tb16.main(["read-dpcd", "--backend", "iodp", "--experimental",
                                       "--device", "1", "--length", "2"]), 0)
        aux.read.assert_called_once_with(0, 2)
        aux.write.assert_not_called()

    def test_raw_read_bounds_checked_before_loading_native(self):
        for address, length in (("-1", "1"), ("0xfffff", "2"), ("0", "257"), ("0", "0")):
            with patch("tb16.Native", side_effect=AssertionError("must not open")), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    tb16.main(["read-dpcd", "--device", "1", "--address", address, "--length", length])


if __name__ == "__main__":
    unittest.main()
