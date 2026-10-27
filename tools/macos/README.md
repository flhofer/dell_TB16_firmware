# macOS tools

Native TB16 Thunderbolt NVM updater and display diagnostics. Requires Python
3.9+, Xcode Command Line Tools and **arm64 macOS 27.0.1, build 26A434**.
Other builds are blocked until their private Thunderbolt ABI is validated.

## Build and test

```sh
make -C tools/macos
make -C tools/macos test
python3 tools/macos/tb16.py list-tbt
```

## Update Thunderbolt firmware

Only the bundled images below and installed firmware **16.00** are supported.
The updater checks image hashes and requires the matching controller model.

| Controller | Model | Image | Target version |
| --- | --- | --- | --- |
| Cable | `00d4:b051` | `bins/Cable_26_06.bin` | 26.06 |
| Dock | `00d4:b054` | `bins/Dock_BME_27_00.bin` | 27.00 |

Keep dock AC power connected and approve accessory access if macOS asks.
Replace the example ID below with the cable ID from `list-tbt`. IDs change
when reconnecting. A working external display is not required.

Check the image, target and active header without programming firmware:

```sh
sudo python3 tools/macos/tb16.py update-nvm --experimental \
  --device 0x100001234 --image bins/Cable_26_06.bin
```

To write and authenticate, choose a **new** backup file:

```sh
mkdir -p tools/macos/backups
sudo python3 tools/macos/tb16.py update-nvm --experimental \
  --device 0x100001234 --image bins/Cable_26_06.bin \
  --backup tools/macos/backups/cable-before.backup.bin --write --authenticate
```

Each write requires two matching active-bank reads and a verified saved
backup. The updater stages the digital image to the inactive bank, checks
that the active bank stayed unchanged, then requests authentication once.
Do not run other firmware utilities concurrently.

After `authentication_reported` with status zero:

1. Disconnect Thunderbolt and dock AC power for 10 seconds.
2. Reconnect AC, then Thunderbolt; approve accessory access if prompted.
3. Run `list-tbt` again and read the active version using the new ID:

   ```sh
   sudo python3 tools/macos/tb16.py read-nvm-header --experimental --device 0x100001234
   ```

Require **26.06** before repeating the procedure with the **dock ID**,
`Dock_BME_27_00.bin` and a separate new backup file. After its power-cycle,
require **27.00**. System Information may instead display `26.26`/`27.27`;
use the active header for verification.

Exit code 1 indicates failure; 2 means authentication was attempted but its
outcome is unknown. Keep the dock powered and preserve the output and backup
before investigating. There are no automatic retries or resets. Backups cover
the active NVM bank, not the complete SPI flash; restore is not implemented.
Staging cannot be read back independently, so authentication and the subsequent
active-version check are required. Raw backups are ignored by Git.

Use `backup-nvm --output NEW_FILE` for a separate two-pass backup, or
`plan-nvm --target cable --image IMAGE --backup EXISTING_FILE` for an offline
plan. Run a command with `--help` for all options.

## Diagnostics

```sh
python3 tools/macos/tb16.py diagnose
python3 tools/macos/tb16.py display-modes
python3 tools/macos/tb16.py list --backend iodp --experimental
python3 tools/macos/tb16.py probe --backend iodp --experimental --device 0x100001234
```

These commands are read-only. The probe uses an **External** ID from the IODP
list; embedded displays are rejected. `diagnose` excludes serials and raw
EDID/DROM. `display-modes` reports framebuffer dimensions and refresh rates,
not measured wire timings; manually selected modes may be absent from its list.

HDMI is limited to the dock's HDMI 1.4a path. If 1440p/120 is blank, select
60 Hz before trying 1440p. Use DisplayPort for higher refresh rates.

## Hardware validation

One M5/TB16 setup passed cable and dock updates, authentication, activation
and exact payload readback. Cable 26.06 alone left HDMI blank; HDMI and USB
worked after dock 27.00 and a power-cycle. This does not establish whether
the dock update alone would have sufficed.

| Connection | User-confirmed working modes |
| --- | --- |
| HDMI | 1920x1080/120 Hz, 2560x1440/60 Hz |
| DisplayPort | 2560x1440/120 Hz |

Charging worked before updating. Ethernet, audio and sleep/wake remain
untested. [Validation data](validation/m5-tb16.json) includes backup hashes.

## Experimental MST support

The IOI2C backend supports VMM3320 (DP/VGA) and VMM3330 (mDP/HDMI) with board
ID `0x0112` and the pinned `bme-ie-03.12.002.eeprom` image. It requires a native
AUX interface from `list`; none was exposed on the tested M5. IODP can probe
the VMM3330 but cannot write or back up its EEPROM.

For a supported IOI2C interface, `probe` and the default `flash` are read-only.
`backup --output NEW_FILE` reads EEPROM twice. A real update requires
`flash --write --experimental --backup NEW_FILE`; it saves a verified backup,
erases, programs, checks the device checksum and verifies full readback.
MST writes have not been hardware-tested. MST/ASMedia/TI/EC firmware was not
changed to obtain the working display and USB results above.

Protocols: Linux [Thunderbolt NVM](https://github.com/torvalds/linux/blob/v6.12/drivers/thunderbolt/nvm.c)
and [DMA mailbox](https://github.com/torvalds/linux/blob/v6.12/drivers/thunderbolt/dma_port.c),
fwupd [Synaptics MST](https://github.com/fwupd/fwupd/tree/4e6b89312b23c225b5ae7456a0566a2fdc3d870c/plugins/synaptics-mst).
