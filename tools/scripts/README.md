# Script Notes

These scripts are Linux-oriented helpers for TB16 recovery and troubleshooting.
Most actions require root privileges (`sudo`).

## Quick usage

Run from repository root:

```sh
./tools/scripts/<script-name>.sh
```

## Scripts

### `ethernet_reload.sh`
- Purpose: Reload Realtek ethernet module (`r8153_ecm`).
- Level: Least invasive.
- Requires: `sudo`, `modprobe`.
- Typical use: First recovery attempt after suspend/wake ethernet issues.

### `ethernet_rebind.sh`
- Purpose: Unbind/rebind RTL8153 USB function from `r8152` driver.
- Level: Medium.
- Requires: `lspci`, access to `/sys/bus/usb/drivers/r8152`.
- Typical use: Module reload was not enough.

### `usb_rebind.sh`
- Purpose: Unbind/rebind ASMedia USB controller (`1b21:1142`) in `xhci_hcd`.
- Level: Most invasive of legacy scripts.
- Requires: `lspci`, access to `/sys/bus/pci/drivers/xhci_hcd`.
- Typical use: Last resort before unplug/reboot.

### `ethernet_recover.sh`
- Purpose: Unified staged recovery: module reload -> ethernet USB rebind -> USB controller rebind.
- Level: Escalating workflow with automatic stop on success.
- Requires: `lspci`, `modprobe`, `sudo`.
- Selection logic: Auto-detects the ethernet interface attached to ASMedia parent path (`1b21:1142`).
- Optional env vars:
  - `ASM_BDF=0000:0b:00.0` force specific ASMedia PCI device.
  - `NET_IF=enx...` force specific network interface.

### `collect_diagnostics.sh`
- Purpose: Collect troubleshooting data into a timestamped log file.
- Output: `tools/logs/tb16_diag_<timestamp>.log`
- Includes:
  - `fwupdmgr get-devices`
  - `lspci -nn`
  - filtered `dmesg` lines related to TB16/Thunderbolt/RTL8153/ASMedia
- Typical use: Attach output when reporting issues or after a failed recovery attempt.

## Safety notes

- Scripts that write to `/sys` can temporarily disconnect USB/network devices.
- Close active transfers before running rebind scripts.
- Prefer `ethernet_recover.sh` unless you intentionally want a specific low-level step.
