# dell_TB16_firmware
Firmware and flashing instructions for the (now) affordable TB16 to fix some major issues

## Firmware versions and status

System | newest/available version | file | fixes? | alt flashing |
--- | --- | --- | --- | ---
Synaptic MST-1 VMM3320 DP + VGA | 03.12.002 | mst_03.12.002.cab | Glitches on screens, compatibility for MacBooks | Linux |
Synaptic MST-2 VMM3330 miniDP + HDMI | 03.12.002 | mst_03.12.002.cab | " "  | Linux |
Thunderbolt TB16 Cable | 16.00 | Cable_16_0.bin | Fixes MacBook charging problem (to confirm) | Linux |
  " | 26.06 | Cable_26_06.bin | Unofficial update borrowed from WD15, fixes "DROM data CRC32 mismatch" error and random display malfunction | Linux |
Thunderbolt TB16 Dock | 27.00 | Dock_BME_27_0.bin | Unknown benefits | Linux |
ASM USB controller | 	131025_10.11_A9 | DELL_131025_10_11_A9.bin | Fixes Realtek audio noise | Windows/Linux |
 " | 	140124_10.10_04_2 aka 131025_10.11_AB aka 131025_10.11_171 | 140124_10_10_4_2.BIN | Unofficial update, fixes S3 wakeup hang for RTL Ethernet controller | Windows/Linux |
TI 1.2.11 Port Controller 1	 | 01.02.11 | N/A | Updated through BIOS | none yet | 
TI 1.2.32 Port Controller 2	| 01.02.32 | N/A | Updated through BIOS | none yet | 
Dock EC | 01.00.00.10 | N/A | Updated through BIOS | none yet | 
Cable PD | 00.03.12 | N/A | Updated through BIOS | none yet | 

## Flashing instructions

I will find alternative flashing methods for all files to the original Dell tool, which is limited and buggy.

### Flashing MST chips

While there is a `mst.exe` for manual flashing, that too is unreliable and buggy. For starters, it only sometimes reports the installed firmware version correctly.
For a few years now, it has been possible to flash the chips also on Linux. You will need a recent `fwupd` package, e.g., shipped in Ubuntu 23.10 or newer.

Unlike what is suggested online, you MUST have a monitor connected to perform this update. This means that for MST1, you'll need a DP or VGA connection, and for MST2, you will need a miniDP or an HDMI screen.
To install, type the following as root or with `sudo`

```
$ fwupdmgr install <cab-file>
```
This install may fail at the prompt but continue flashing and succeed in the background. Thus, do not remove the power to the dock for a minute or two after the command ends.

### Flashing TB16's NVM

For the two following, `Cable` and `Dock/BME`, the requirements are identical: Linux and recent `fwupd` package.

To update Thunderbolt Cable or Dock NVM, type as root/`sudo`
```
$ fwupdtool install-blob <bin-file>
```

It will prompt you to select the correct device to flash. Be sure to select `Cable` with `Cable_xxx.bin` and vice versa.

### Flashing the ASMedia USB Controller

While a C #- coded Linux tool exists, I prefer the official ASM flasher. Use the `exe` found in `tools/ASMedia_win` of this repos on Windows or a Windows-to-go disk made, e.g., with Rufus, and execute it with the binary file copied into its folder.

If you use the `cmd` prompt and enter the directory, you can check the installed version with `/version` or force overwrite using the `/f` flag.
```
> asm.exe /version
```
The tool will not flash if the bin is older or equal to the installed one and exits (unless run with `/f`).
If there is more than one bin file in the directory, it will take the first one using ASCII order, e.g., numbers before letters.
