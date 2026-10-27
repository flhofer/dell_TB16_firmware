# Experimental macOS port

This is an initial native macOS implementation of the TB16 **Synaptics MST**
update path. It is not a complete macOS replacement for the Linux/Windows
procedure. **Firmware writing has not been validated on a physical TB16.**
Do not treat passing software tests or a successful build as evidence that a
firmware write will work on your Mac.

## Goal: HDMI and everyday dock use on a Mac

The first practical goal is a reliable single monitor on the dock's HDMI
output. The existing repository reports Mac compatibility improvements from
MST firmware 03.12.002 and display reliability improvements from Thunderbolt
Cable NVM updates. Those reports do not establish which update a particular
dock needs. Identify the current failure and installed versions first.

The relevant path is Mac -> Thunderbolt link/Cable controller -> VMM3330 ->
HDMI. The VMM3320 serves DP/VGA. This implementation targets the two display
chips, so it could address the VMM3330 part of an HDMI problem once its
transport is validated. It cannot fix a Thunderbolt link that does not
enumerate, and it cannot yet perform the repository's complete update sequence.

On Apple Silicon, the next development milestone is obtaining repeatable
read-only VMM3330 DPCD access. A private IODP read backend now exists, and its
underlying API was validated with a bounded capability read on the M5's
built-in panel. The connected TB16 still exposes no external IODP device,
so neither backend can currently reach its display chips on this setup.

After HDMI, validate USB, Ethernet, audio, charging and sleep/wake. The
ASMedia update concerns the USB-controller path and is separate from the
display-chip update. Use the repository's Mac-compatible ASMedia choice;
the `140124_10_10_4_2.BIN` alternative is explicitly reported as incompatible
with Macs in the main README.

There are limits firmware updates do not remove:

- The TB16 HDMI output supports up to 4K at 30 Hz, according to
  [Dell's TB16 display-resolution table](https://www.dell.com/support/kbdoc/en-id/000123995/how-to-use-and-troubleshoot-dell-thunderbolt-dock-tb16?lang=en).
- macOS does not support ordinary MST extended-desktop fan-out, as documented
  in [Dell's Mac dock compatibility notes](https://www.delltechnologies.com/asset/en-us/products/electronics-and-accessories/briefs-summaries/dell-thunderbolt-dock-wd22tb4-with-apple-compatibility.pdf).
  This does not prevent a single HDMI display; multiple independent displays
  need a supported stream arrangement and must respect the Mac's display limits.
- The repository reports that the dock power button only controls Dell PCs.

For diagnosis, connect dock AC power, the upstream Thunderbolt cable and one
HDMI monitor directly. Approve the accessory if macOS asks; charging alone
does not establish a working data connection. See
[Apple's accessory access instructions](https://support.apple.com/en-my/102282).
Check System Information -> Thunderbolt/USB4 for the dock and note whether
USB devices work. If the dock is missing there, investigate the link before
attempting display-chip access.

| Component | macOS implementation | Remaining work |
| --- | --- | --- |
| VMM3320 / VMM3330 MST | Experimental IOI2C update backend; private IODP read-only backend | Obtain external device access on the tested M5; validate backup and writing on hardware |
| Thunderbolt Cable / Dock NVM | No writer | Implement and validate macOS switch NVM access and authentication |
| ASMedia ASM1042A | No writer | Implement privileged PCIe register access and validate the flashing protocol |
| TI PD / EC | No writer | Identify and implement their update transports |

## Requirements and platform limits

- macOS 12 or later, Python 3.9 or later, and Xcode Command Line Tools (`xcode-select --install`).
- A host graphics driver exposing an `IOI2CInterface` with the
  `kIOI2CDisplayPortNativeTransactionType` capability. The backend checks this
  capability and refuses interfaces without it. Driver support varies; Intel
  Macs are the intended first hardware validation target, not confirmed supported hosts.
- **Apple Silicon firmware updating is not established.** Display drivers may
  expose no usable IOI2C interfaces. The optional `iodp` backend uses private
  APIs for read-only diagnostics, requires an external DP device exposed by
  macOS, and cannot issue remote-control or firmware writes. `sudo` does not
  create a missing transport/device. See the diagnostic commands below.
- A powered TB16 connected directly over Thunderbolt, with an active monitor
  connected to the MST path being tested: DP/VGA for VMM3320, mDP/HDMI for VMM3330.
  Test one path at a time to make target identification easier.

Neither a USB device connection nor ordinary DDC/I2C monitor control provides
the native AUX access this protocol requires. A Linux VM's USB passthrough
does not by itself expose the dock's Thunderbolt switches, PCIe controller or
DisplayPort AUX transport.

## Build and inspect without writing

Run these commands from the repository root:

```sh
make -C tools/macos
python3 tools/macos/tb16.py inspect-image
python3 tools/macos/tb16.py list
```

`inspect-image` runs offline on any OS and accepts only the exact repository
`bins/bme-ie-03.12.002.eeprom` payload, identified by its pinned SHA-256 and
board ID. It rejects CAB containers, NVM blobs, ASMedia images and modified
images. Firmware version in its output is the known version of that pinned
image, not a version parsed from arbitrary firmware.

`list` enumerates IORegistry interfaces and their advertised capabilities. It
does not issue AUX transactions. It may include interfaces unrelated to a TB16;
an advertised AUX capability alone does not identify a dock.

For an interface with `"native_aux": true`, use its exact `id`:

```sh
python3 tools/macos/tb16.py probe --device 0x100001234
python3 tools/macos/tb16.py flash --device 0x100001234
```

Replace the example ID with the real value. IDs can change after a disconnect
or reboot; enumerate again each time. There is no automatic target selection.
The IORegistry path helps associate an interface with its display connector.

`probe` reads the remote-control capability, chip ID and running firmware
version from DPCD. It accepts VMM3320 and VMM3330 only. The default `flash`
command also validates the image but performs **no writes**, including no
remote-control register writes. It does not validate the board ID or prove
that EEPROM access will succeed. A nonzero exit status means a check failed.

If opening an advertised interface returns a permission error, retry the same
probe with `sudo`. Unsupported-mode errors and missing capabilities cannot
be fixed by running as root. Do not disable SIP for this tool.

## Apple Silicon read-only diagnostics

```sh
python3 tools/macos/tb16.py diagnose
python3 tools/macos/tb16.py list --backend iodp --experimental
```

`diagnose` needs no compiled bridge, root access or third-party packages. It
reports the dock switches, raw version properties, HDMI/DP adapter hot-plug
and link metadata, ASMedia driver and USB children, display devices and AUX
availability. It filters out UIDs, serial-number properties, raw EDID and DROM
before printing JSON. Nothing is sent off the Mac. The registry and System
Information are collected separately, so hot-plug may change state between them.

The `iodp` list shows devices advertising `IODPDeviceUserInterfaceSupported`,
including embedded devices for diagnostic visibility. The native bridge
refuses to open embedded or unknown-location devices. An embedded-only list
does not mean that the dock's display chips were read successfully.

If an **External** device appears, use its ID from that backend's list:

```sh
python3 tools/macos/tb16.py read-dpcd --backend iodp --experimental \
  --device 0x100001234 --address 0x500 --length 16
python3 tools/macos/tb16.py probe --backend iodp --experimental --device 0x100001234
```

The example ID is a placeholder. `read-dpcd` performs only bounded reads
(1-256 bytes, split into packets of at most 16 bytes). At `0x500` it can obtain
the branch identification area containing the Synaptics chip/version fields,
if the selected external device actually provides them. `probe` additionally
checks the TB16 chip ID and remote-control capability using reads only.
Neither command enables remote control.

The backend resolves `IODPDeviceCreateWithService` and `IODPDeviceReadDPCD`
at runtime. Their four-argument read ABI was inspected in the local IOKit
binary on macOS 27.0.1 arm64e. One 16-byte read at DPCD address zero on the
built-in panel returned `141ec44100000180020000000f090000` with success during
development. This was a control read for API validation; the shipping backend
does not permit using the built-in panel as a target. No external read has
yet been validated. The ABI is private and may change on other macOS versions.
The private API returns a status without exposing an actual byte count;
it is therefore not presented as a verified firmware-update transport.
The existence of Apple Silicon DPCD diagnostics is also documented by the
[BetterDisplay developer](https://github.com/waydabber/BetterDisplay/issues/5496).
This tool does not require BetterDisplay.

There is deliberately no native IODP write entry point. `backup` and
`flash --write` with `--backend iodp` are rejected before opening a device,
because even EEPROM backup requires remote-control register writes. The
existing experimental IOI2C update path is separate.

## EEPROM backup and experimental write

The next operations enable the Synaptics remote-control mode. Backup reads
EEPROM and temporarily writes control registers, but does not erase or program
EEPROM. Do not run other display-control or firmware tools concurrently.

```sh
sudo python3 tools/macos/tb16.py backup \
  --device 0x100001234 --output /path/to/mst-original.backup.bin
```

The chip must report TB16 board `0x0112`. Backup reads the complete 64 KiB
EEPROM twice and requires identical results, saves it to a new file, flushes
it to disk, and checks the saved bytes. Existing files are never overwritten.
Keep backups separately for each MST chip and each dock. A backup is useful
for recovery research; this tool does **not** offer a restore command, and a
backup does not guarantee recovery after a failed single-image flash.

The following is the real, **unvalidated experimental firmware write**:

```sh
sudo python3 tools/macos/tb16.py flash \
  --device 0x100001234 --write --experimental \
  --backup /path/to/mst-before-update.backup.bin
```

Choose a new backup filename. Both `--write` and `--experimental` are required,
along with `--backup`. Do not use the file created by the preceding backup
command as the destination; each operation creates a new file.

Before erasing, the updater validates the image, chip, board, two complete
EEPROM reads, and the saved backup. It then erases once, waits five seconds,
programs 32-byte remote-control blocks (split into 16-byte AUX packets), checks
the device's additive checksum, and reads the complete EEPROM back. The final
50 bytes outside the 65,486-byte image must remain erased (`0xff`). There is
no forced target override, automatic erase retry or automatic reboot.

Keep the dock powered and all cables connected throughout the operation.
After a successful verified update, power-cycle the dock and run `probe`
again. Repeat the procedure separately for the other MST path. A successful
MST update does not update the Thunderbolt or ASMedia components.

If a write fails or times out, keep the dock powered and preserve the output
and backup. A failed update may have left its single firmware image incomplete.
Do not immediately power-cycle it. The updater attempts to leave remote-control
mode, but does not submit a cleanup command over a still-busy operation.

## Tests and hardware validation still needed

```sh
make -C tools/macos test
```

The tests use an in-memory remote-control endpoint with the real bundled
firmware. They cover both chip IDs, little-endian command parameters, packet
splitting, the short final block, mandatory backup before erase, target/image
rejection, busy/timeout handling, write failure, device checksum mismatch,
readback mismatch, and the read-only CLI default. They do not emulate the
macOS graphics driver or prove electrical AUX behavior.
The native C checks intercept request submission to verify address/buffer
construction and handling of submission errors, transaction errors and short
transfers without issuing hardware requests.

Validation completed during development: native arm64 compilation with
warnings as errors, Intel syntax checks, offline image inspection, tests, and
live IORegistry enumeration. No firmware or remote-control writes were run on
hardware.

A connected TB16 was subsequently inspected on an M5 MacBook Pro running
macOS 27.0.1. The user reported charging working, with HDMI and USB peripherals
not working. Read-only inspection found:

- System Information enumerated `Dell Thunderbolt Cable` and
  `Dell Thunderbolt Dock - Unsupported`, each reporting firmware `16.16` and
  a 40 Gb/s connection. These are the macOS-reported values, not independently
  decoded NVM versions or proof that a particular image needs installing.
- IORegistry showed the ASMedia `1b21:1142` PCIe device with the
  `AppleASMedia1042USBXHCI` driver attached, plus `USB5807 Hub` and `USB2807 Hub`
  children. Thus the unsupported device name does not by itself establish
  that all Thunderbolt/PCIe communication is blocked. Driver/hub enumeration
  also does not establish usable downstream USB peripherals.
- The updater's `list` returned no IOI2C endpoints, both with and without the
  dock connected. The current AUX backend cannot access either MST chip on
  this tested configuration.
- With a monitor on HDMI, including after reconnecting the upstream
  Thunderbolt cable with dock power and HDMI left connected, the monitor
  still had no signal. The Thunderbolt output adapter reported both HPD
  states true, two established DP lanes and link-rate value `2`. These are
  driver-reported metadata, not proof of an end-to-end active video stream.
- The private IODP backend enumerated only the embedded display device;
  System Information listed only `Color LCD`. The external controllers
  existed, but there was no external DP **device** for the read API to open.
  The tool correctly refused to open the embedded device as an updater target.
- USB Ethernet and USB Audio also enumerated below the ASMedia controller
  during this session. This is stronger evidence of enumeration than the
  earlier hub-only observation, but still does not verify peripheral operation.
- The user confirmed that the same HDMI cable and monitor display an image
  when connected directly to the Mac. The no-signal result is specific to
  the dock path in this test; the exact failing component is still unknown.

The filtered post-reconnect report is saved in
[`validation/m5-tb16-hdmi-no-signal.json`](validation/m5-tb16-hdmi-no-signal.json).

This observation does not identify the cause of the HDMI failure, validate
firmware writes, or establish that an MST update alone would resolve it.

The next transport investigation is an access path available before a working
external display exists. Static inspection of the local macOS 27.0.1 kernel
identified a Thunderbolt DP output user client, but its exposed methods are
link/HPD/mux controls rather than a direct AUX read operation. The generic
Thunderbolt user client has configuration-read and IECS/I2C command methods;
their permission model and wire arguments still need validating before any
use. No guessed kernel method selectors or commands were sent to hardware.

Before describing this as a working macOS updater, collect evidence for:

1. Repeatable DPCD reads from the dock on each proposed host/graphics-driver
   configuration, including an access path that works when HDMI has no signal.
2. Correct VMM3320/VMM3330 selection and repeatable full EEPROM backups.
3. A successful write on recoverable test hardware, verified readback and the
   expected running firmware after a power-cycle.
4. Display operation on both MST paths after updating.

## Transport references

The protocol constants, Leaf command sequence and board-ID locations were
checked against fwupd commit
[`4e6b893`](https://github.com/fwupd/fwupd/tree/4e6b89312b23c225b5ae7456a0566a2fdc3d870c/plugins/synaptics-mst).
This implementation is limited to the two TB16 Leaf chips and the pinned
03.12.002 image, rather than supporting the other Synaptics families.

The IOI2C bridge uses the public SDK
[`IOI2CInterface.h`](https://github.com/apple-oss-distributions/IOGraphics/blob/76285384ff0ce63965a21b8023bf6d7e447fcc19/IOGraphicsFamily/IOKit/i2c/IOI2CInterface.h)
and follows Apple's
[`IOFramebuffer` native AUX request layout](https://github.com/apple-oss-distributions/IOGraphics/blob/76285384ff0ce63965a21b8023bf6d7e447fcc19/IOGraphicsFamily/IOFramebuffer.cpp#L14624).
Both the submission result and the transaction result are checked; short
transfers are rejected. No SDK structure layout is hard-coded in Python.

The existing Linux Thunderbolt writer relies on
[`nvm_non_active` and `nvm_authenticate`](https://github.com/torvalds/linux/blob/master/Documentation/admin-guide/thunderbolt.rst),
which are kernel interfaces, not portable files. A macOS NVM implementation
needs a separate transport; installing a CLI does not supply those interfaces.
ASMedia similarly requires PCIe register access, as illustrated by
[`ASMTool`](https://github.com/smx-smx/ASMTool). Neither transport is implemented here.
