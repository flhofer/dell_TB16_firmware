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

I will find alternative flashing methods for all files to the original Dell tool, as it is limited and buggy.

