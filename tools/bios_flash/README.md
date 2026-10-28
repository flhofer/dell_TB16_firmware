# TB16 PD/EC extraction and BIOS-assisted flashing

The scripts target `official/DellDockingStationFwUp_1.0.0_03192018_TB16.exe`.
They do not modify firmware or lift power limits. Extraction has been validated
offline; the Windows wrapper and hardware flashing have not been tested here.

## Extract the firmware

From the repository root, with Python 3:

```sh
python3 tools/bios_flash/extract_tb16_pd.py
```

The extractor checks the original EXE SHA-256, decompresses its PFS stream at
EXE offset `0x2A5810`, checks PFS boundaries and CRC, then writes:

| File in `bins/` | PFS data offset | Bytes |
| --- | --- | ---: |
| `TB16_TI_Port1_1.2.11.bin` | `0x23c` | 57,736 |
| `TB16_TI_Port2_1.2.32.bin` | `0xe50c` | 57,812 |
| `TB16_Dock_EC_1.0.0.10.bin` | `0x1c828` | 57,344 |
| `TB16_TBT_Cable_PD_0.0.3.12.bin` | `0x2a970` | 22,016 |
| `TB16_Universal_Cable_PD_0.0.3.12.bin` | `0x300b8` | 22,016 |

The package's embedded name table identifies these components. Both TI images
also contain TPS65982 build strings. Cable variants are separate targets, not
two images to write indiscriminately to one cable.

`TB16_PD_EC_1.0.0.pfs` preserves the complete decompressed signed container.
`TB16_PD_EC_metadata/` preserves each 256-byte signature, package-version data
and the name table. `TB16_PD_EC_manifest.json` records provenance, GUIDs, offsets
and hashes. RSA signatures are preserved, not cryptographically verified.
The extractor refuses to overwrite differing files, including patched images.

These are update payloads, not full SPI backups. Do not pass them to the existing
Thunderbolt NVM writer or write them at SPI address zero. The extracted PFS is
also not established to be a directly installable UEFI capsule.

## Windows 10 / Windows 11

The wrapper uses Windows PowerShell 5.1-compatible commands, with no fixed Dell
model list. Dell lists Windows 10, 8.1 and 7 for this exact package; Windows 11
execution and XPS 13 Plus 9320 compatibility remain unvalidated. A Dell brand
check alone does not prove the BIOS supports this older dock's update service.

Connect the dock to its AC adapter and a Dell Thunderbolt-capable laptop. Install
the model's required BIOS and Thunderbolt prerequisites if Dell's updater asks
for them. From an **Administrator PowerShell** at the repository root:

```powershell
# Read component versions first; this is the default action.
.\tools\bios_flash\flash_tb16.ps1 -Action Info

# Launch the original interactive updater, using its embedded signed payloads.
.\tools\bios_flash\flash_tb16.ps1 -Action Update
```

The wrapper validates the EXE hash before execution and prints its log path.
The updater determines which components need updating. This package includes
Intel/ASMedia/Synaptics components as well as PD/EC; this is not a PD-only flash.
An already-current component may be skipped. No force or downgrade behavior is
implemented, and the script does not promise a same-version reflash.

Follow the vendor UI and any restart request, keeping the dock powered and
connected throughout. The EXE contains RBU staging/version-selection code and
a flash-reboot request path: the PD/EC update is BIOS-assisted after staging
from Windows. Do not treat renaming the EXE to `.efi` or selecting a bare BIN in
F12 BIOS Flash Update as an equivalent route.

After the updater and requested BIOS stage finish, unplug the dock from the
laptop, disconnect dock AC, hold its power button for 30 seconds, reconnect AC,
then reconnect the laptop. Run `-Action Info` again and compare versions/logs.
The wrapper's process return code alone cannot verify the completed BIOS flash.

## Non-Dell hosts and alternative writers

The BIOS-assisted PD/EC route requires Dell host firmware. The wrapper declines
to launch it on a non-Dell host. Windows 10 versus 11 does not remove that
dependency. A fwupd maintainer confirmed that older fwupd could trigger the
proprietary mechanism, but support was later removed. Restoring that code is a
potential Dell/Linux route, not a solution for non-Dell machines.

TI documents a separate TPS65982 I2C host-interface updater, using region
selection, erase, write, verification and restart commands. TI also provides a
Host Interface Utility. Neither is a demonstrated external-TB16-USB flasher.
Before implementing this route we need to establish access to the dock's TI
I2C interface and reconstruct/validate the required region image format.
The extracted TI payloads begin `00 00 01 00 dd 00 00 00`; they do not begin
with the `0xACE00001` boot-header magic in TI's documented application image.
An occurrence of that constant inside code does not make a complete boot header.

An external SPI programmer is another research route, but needs a full readback,
the actual flash layout and preservation of configuration/shared firmware.
TI's update protocol does not establish a writer for the separate cable-PD or
dock-EC payloads. No direct writer for those has been validated in this repository.
Patched PFS entries would invalidate the preserved signatures; enforcement on
this particular update path is still untested.

## Sources

- [Dell release H3YG7: exact EXE, SHA-256, OS support and installation](https://www.dell.com/support/home/en-us/drivers/driversdetails?driverid=h3yg7).
- [Dell current TB16 updater and post-update reset procedure](https://www.dell.com/support/home/en-us/drivers/driversdetails?driverid=6ykv0).
- [fwupd maintainer discussion of TB16 proprietary updates and removed support](https://github.com/fwupd/fwupd/issues/1671).
- [TI TPS6598x I2C firmware update application note](https://www.ti.com/lit/an/slva783a/slva783a.pdf).
- [TI firmware user's guide: image layout and update methods](https://www.ti.com/lit/ug/slvuah7b/slvuah7b.pdf).
- [TI host-interface utility](https://www.ti.com/tool/TPS65982-HIUTILITY).
- [Dell PFS structure reference](https://github.com/platomav/BIOSUtilities/blob/main/biosutilities/dell_pfs_extract.py).
