# Experimental macOS port

This is an initial native macOS implementation of the TB16 **Synaptics MST**
update path. It is not a complete macOS replacement for the Linux/Windows
procedure. **No physical TB16 has been used to validate this implementation.**
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

On Apple Silicon, the next development milestone is detecting a connected
TB16 and obtaining repeatable read-only VMM3330 DPCD access. The current
IOI2C backend has not demonstrated this. It may require a separate Apple
Silicon transport before the EEPROM/update protocol can be used on those Macs.

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
| VMM3320 / VMM3330 MST | Experimental IOI2C native AUX backend and Leaf update protocol | Validate AUX reads, EEPROM access, erase/write and power-cycle on hardware |
| Thunderbolt Cable / Dock NVM | No writer | Implement and validate macOS switch NVM access and authentication |
| ASMedia ASM1042A | No writer | Implement privileged PCIe register access and validate the flashing protocol |
| TI PD / EC | No writer | Identify and implement their update transports |

## Requirements and platform limits

- macOS 12 or later, Python 3.9 or later, and Xcode Command Line Tools (`xcode-select --install`).
- A host graphics driver exposing an `IOI2CInterface` with the
  `kIOI2CDisplayPortNativeTransactionType` capability. The backend checks this
  capability and refuses interfaces without it. Driver support varies; Intel
  Macs are the intended first hardware validation target, not confirmed supported hosts.
- **Apple Silicon support is not established.** The bridge compiles for arm64,
  but Apple Silicon display drivers may expose no usable IOI2C interfaces.
  No private IOAV/IOPD API fallback has been implemented. An empty `list`
  means this backend cannot proceed on that setup; `sudo` does not create a
  missing transport. An empty list with no dock connected does not prove the
  same Mac cannot expose an endpoint when a dock and display are attached.
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
  this tested configuration. An Apple Silicon transport remains necessary
  to demonstrate native MST updating on this Mac.

This observation does not identify the cause of the HDMI failure, validate
firmware writes, or establish that an MST update alone would resolve it.

Before describing this as a working macOS updater, collect evidence for:

1. IOI2C enumeration and repeatable DPCD reads with a connected TB16 on each
   proposed host/graphics-driver configuration.
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

The native bridge uses the public SDK
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
