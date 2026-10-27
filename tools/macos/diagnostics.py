"""Read-only, filtered macOS report. Never includes raw registry dumps or UIDs."""
import json
import platform
import plistlib
import subprocess


def walk_registry(value):
    roots = value if isinstance(value, list) else [value]
    for entry in roots:
        yield entry
        yield from walk_registry(entry.get("IORegistryEntryChildren", []))


def summarize_registry(registry):
    """Keep transport evidence, excluding serials, UIDs, DROM and raw EDID."""
    entries = list(walk_registry(registry))
    switches = []
    dp_devices = []
    display_outputs = []
    for entry in entries:
        if (entry.get("IOObjectClass", "").startswith("IOThunderboltSwitch") and
                entry.get("Device Vendor ID") == 0xD4 and
                entry.get("Device Model ID") in (0xB051, 0xB054)):
            ports = []
            for child in entry.get("IORegistryEntryChildren", []):
                if child.get("Description") == "DP or HDMI Adapter":
                    ports.append({key: child[key] for key in
                                  ("Port Number", "Adapter Type", "Required Bandwidth Allocated",
                                   "Maximum Bandwidth Allocated") if key in child})
            switches.append({"name": entry.get("Device Model Name"),
                             "model_id": f"0x{entry['Device Model ID']:04x}",
                             "rom_version_raw": entry.get("ROM Version"),
                             "eeprom_revision_raw": entry.get("EEPROM Revision"),
                             "display_adapters": ports})
            for output in walk_registry(entry):
                if output.get("IOObjectClass", "").startswith("AppleThunderboltDPOutAdapter"):
                    summary = {key: output[key] for key in
                               ("IOObjectClass", "HPD Plug State", "HPD State", "DP State",
                                "Delegate", "Established DP Lane Count", "Established DP Link Rate",
                                "Established DP Bandwidth") if key in output}
                    if summary not in display_outputs:
                        display_outputs.append(summary)
        if entry.get("IODPDeviceUserInterfaceSupported") is True:
            dp_devices.append({"class": entry.get("IOObjectClass"),
                               "location": entry.get("Location", "Unknown"),
                               "unit": entry.get("Unit")})
    asmedia = [e for e in entries if e.get("IOObjectClass") == "AppleASMedia1042USBXHCI"]
    usb_names = sorted({e["IORegistryEntryName"] for controller in asmedia
                        for e in walk_registry(controller)
                        if e.get("IOObjectClass") == "IOUSBHostDevice" and
                        "IORegistryEntryName" in e})
    ioi2c = [e for e in entries if "IOI2CTransactionTypes" in e]
    external = [d for d in dp_devices if d["location"] == "External"]
    return {"tb16_switches": switches,
            "thunderbolt_display_outputs": display_outputs,
            "asmedia_driver_attached": bool(asmedia),
            "usb_devices_below_asmedia": usb_names,
            "ioi2c_interfaces_with_capabilities": len(ioi2c),
            "ioi2c_native_aux_interfaces": sum(bool(e["IOI2CTransactionTypes"] & 16)
                                               for e in ioi2c
                                               if isinstance(e["IOI2CTransactionTypes"], int)),
            "iodp_devices": dp_devices,
            "external_iodp_device_count": len(external)}


def summarize_profiler(profiler):
    def devices(items):
        result = []
        for item in items:
            if item.get("vendor_id_key", "").lower() == "0x00d4":
                result.append({"name": item.get("device_name_key", item.get("_name")),
                               "firmware_reported": item.get("switch_version_key"),
                               "mode": item.get("mode_key")})
            result.extend(devices(item.get("_items", [])))
        return result

    displays = []
    for gpu in profiler.get("SPDisplaysDataType", []):
        for display in gpu.get("spdisplays_ndrvs", []):
            displays.append({"name": display.get("_name"),
                             "connection": display.get("spdisplays_connection_type"),
                             "online": display.get("spdisplays_online"),
                             "mode_reported": display.get("_spdisplays_resolution"),
                             "pixels_reported": display.get("_spdisplays_pixels")})
    return {"thunderbolt_dell_devices": devices(profiler.get("SPThunderboltDataType", [])),
            "displays": displays}


def collect():
    if platform.system() != "Darwin":
        raise RuntimeError("Live diagnostics require macOS")
    registry = subprocess.run(["/usr/sbin/ioreg", "-a", "-l", "-w", "0"],
                              check=True, capture_output=True, timeout=30)
    profiler = subprocess.run(["/usr/sbin/system_profiler", "SPThunderboltDataType",
                               "SPDisplaysDataType", "-json"],
                              check=True, capture_output=True, timeout=30)
    return {"schema_version": 1,
            "host": {"macos": platform.mac_ver()[0], "architecture": platform.machine()},
            "registry": summarize_registry(plistlib.loads(registry.stdout)),
            "system_information": summarize_profiler(json.loads(profiler.stdout)),
            "interpretation": [
                "Monitor wake/hot-plug is not evidence of an active video stream.",
                "An Unsupported device name alone does not prove Thunderbolt traffic is blocked.",
                "Driver/hub enumeration does not prove usable USB peripherals.",
                "No External IODP device means the private read backend has no dock target.",
                "Registry and System Information are separate snapshots; hot-plug can change state."]}
