# Dell TB16 Firmware
Firmware and flashing instructions for the (now) affordable TB16 to fix some major issues. We're using three of those between home and work.
* low price — got all of them used under 50eur/piece
* Up-to-date performance—Thunderbolt 3 has the same interface and speeds as TB4, but TB4 adds mostly some security features.
* When fixed, works with MacBooks and all types of Windows/Linux PCs
* One of the few Docks that can deliver more than 100W on the cable
  
makes it an unbeatable bargain.

The Power button seems to work only on Dell PCs, though. Maybe a script out there somewhere?


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
TI 1.2.11 Port Controller 1	 | 01.02.11 | N/A | Updated through BIOS[^1] | none yet | 
TI 1.2.32 Port Controller 2	| 01.02.32 | N/A | Updated through BIOS[^1] | none yet | 
Dock EC | 01.00.00.10 | N/A | Updated through BIOS[^1] | none yet | 
Cable PD | 00.03.12 | N/A | Updated through BIOS[^1]| none yet | 
[^1]: These are updated early on and should already be done (Dell Tool v1.00.00 - v1.00.02)

## Flashing instructions

I will find alternative flashing methods for all files to the original Dell tool, which is limited and buggy. Also, while the original tool works ONLY with Dell PCs, these should work on all Thunderbolt-equipped systems.

### Flashing MST chips

While there is a `mst.exe` for manual flashing, that too is unreliable and buggy. For starters, it only sometimes reports the installed firmware version correctly.

> [!NOTE]
> The official update tool tends to report version such as 00.00.fd. These are actually error codes reported from the `mst.exe` and do not show if you perform a manual version check.

For a few years now, it has been possible to flash the chips also on Linux. You will need a recent `fwupd` package, e.g., shipped in Ubuntu 23.10 or newer. If you don't use Linux, you can use a Live-USB using an official Ubuntu which comes with `fwupd` installed.

Unlike what is suggested online, you MUST have a monitor connected to perform this update. This means that for MST1, you'll need a DP or VGA connection; for MST2, you will need a miniDP or an HDMI screen.
To check if both MSTs are running, type the following as root or with `sudo`

```
$ fwupdmgr get-devices
```
You will see them as Dell TB16/TB18/WD15 Dock or similar.

> [!NOTE]
> If you don't see both MST devices, check cables and power or perform NVM updates first.

To install, type the following as root or with `sudo`

```
$ fwupdmgr install <cab-file>
```
> [!WARNING]
> This install may fail at the prompt but continue flashing and succeed in the background. Thus, do not remove the power to the dock for a minute or two after the command ends.


### Flashing TB16's NVM

For the two following, `Cable` and `Dock/BME`, the requirements are identical: Linux and recent `fwupd` package.

To update Thunderbolt Cable or Dock NVM, type as root/`sudo`
```
$ fwupdtool install-blob <bin-file>
```

It will prompt you to select the correct device to flash. Select `Cable` with `Cable_xxx.bin` and vice versa.

### Flashing the ASMedia USB Controller

While a C #- coded Linux tool exists, I prefer the official ASM flasher. Use the `exe` found in `tools/ASMedia_win` of this repos on Windows or a Windows-to-go disk made, e.g., with Rufus, and execute it with the binary file copied into its folder.

If you use the `cmd` prompt and enter the directory, you can check the installed version with `/version` or force overwrite using the `/f` flag.
```
> asm.exe /version
```
The tool will not flash if the bin is older or equal to the installed one and exits (unless run with `/f`).
If there is more than one bin file in the directory, it will take the first one using ASCII order, e.g., numbers before letters.

> [!NOTE]
> The Dell firmware updater checks only the last digits of the firmware version and may thus think the firmware is older. However, `asm.exe` is invoked and does not update.

## Official Flashing tools

If you prefer to use the official Flash tool, you can find a copy in the `official` folder. However, it works only on Dell laptops. If your device doesn't have the controller, EC, and PD updates listed above, you may need to flash with version 1.00 and then 1.02 first. These install a Bios-based update file that executes an update at Bios start.

Furthermore, Dell messed up the firmware packaging for the 1.05. The Dock companions of that generation, the WD15, and TB18, got a new `Cable.bin` and were released the same day. You can use the WD15s flasher to update the `Cable.bin`.

## What's there and what works

![TB16 Ports Image](images/ports.png)

### 1. 	HDMI
This is a 1.4 standard connector and supports up to 4K (3840x2160) resolution at 24/30Hz. I personally tested QHD (2560x1440@60Hz). If MST and Cable NVM are not up to date, it may show black, not always wake up, or not work at all.

### 2. 	VGA
Standard traditional VGA, up to Wide-Full-HD 1920 x 1200 @ 60. Works, tested Full-HD 1920 x 1200 @ 60Hz

### 3. + 4 	DisplayPort (DP) and mini-DisplayPort (mDP)
These ports are v1.2 compliant and typically support Full-HD 3840 x 2160 @ 60Hz, and Daisy Chaining. Mini-DP or DP may casually stop working without the latest Cable NVM.

### 5. 	RJ45 Gigabit Ethernet
Generic RTL8153 Gigabit Ethernet controller. No surprises. However, it may have issues waking up from deep sleep (suspend) if the ASMedia USB controller firmware is not up-to-date. The problem can also be solved by detaching and re-registering the controller on the PCI bus via script.

### 6. 	USB 2.0 (2 ports)
"Slow"-speed port generally intended for input devices such as mouse, keyboard, trackpad, Smart-card readers, etc. No issues

### 7. 	USB 3.0
SuperSpeed USB is ideal for, e.g., monitor USB-HUBs or USB-NAS. No problems

### 8. 	Thunderbolt 3 (USB Type-C)
Limited (intended) Thunderbolt is available for Daisy-chain DP via tunneling, e.g., Multiple USB-C monitors or some USB 3.1 Superspeed devices. In particular configurations, it may reach 5120 x 2880 @ 60 Hz for a single display. DP functionality not tested.

### 9. 	7.4 mm DC-in power
According to the manual, the Dock does not accept 130W power supplies. However, viable power options are 130W, 180W, or 240W. The power supply limits the energy that can be supplied to the laptop. Unless you have a specific Dell Model, you should not need the 240W power supply, as the 100W limit can only be waived by Dell proprietary protocols. Power limits are 40-60W with a 130W PSU, 60-90W with a 180W PSU, and up to 130W with a 240W PSU. Some users say the TB16 won't deliver more than 60W (20V @3A) for non-Dell systems. It should be enough for most Laptops/Ultrabooks.

### 10. 	3.5 mm Speaker-out

### 11. 	Dell Docking station connector 
Dell Proprietary connection to USB Type 3 port on PC. The light does not go on with, e.g., MacBooks, but it works and charges.

### 12. 	Headset Jack

### 13. 	USB 3.0 w/PowerShare

### 14. 	USB 3.0

### 15. 	Power Adapter LED

### 16. 	Dock Button

### 17. 	Kensington lock slot
    
