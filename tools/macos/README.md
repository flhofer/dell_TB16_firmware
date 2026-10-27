# Experimental macOS port

This is an initial native macOS implementation of the TB16 **Synaptics MST**
and **Thunderbolt NVM** update paths. It is not a complete macOS replacement
for the Linux/Windows procedure. **Cable NVM staging/authentication have passed
one hardware test; activation is pending. MST and dock NVM writing remain
unvalidated on hardware.**
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
chips and the cable/dock Thunderbolt controllers. It could address the VMM3330
part of an HDMI problem once its AUX transport is validated. It cannot fix a
Thunderbolt link that does not enumerate, and it cannot yet perform the
repository's complete update sequence.

On Apple Silicon, repeatable read-only VMM3330 DPCD access remains a separate
development milestone. A private IODP read backend now exists, and its
underlying API was validated with a bounded capability read on the M5's
built-in panel. The connected TB16 still exposes no external IODP device,
so neither AUX backend can currently reach its display chips on this setup.
The Thunderbolt NVM transport works independently of that missing device;
cable staging/authentication have now passed one hardware test. Activation
and HDMI behavior still require verification.

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
| Thunderbolt Cable / Dock NVM | Verified reads/backups on the tested M5; cable staging/authentication passed one hardware test | Verify cable activation and HDMI; validate dock NVM writes |
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

These MST commands use the IOI2C backend. For Thunderbolt controller NVM
backups, use the separate commands in the next section.

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

## Lower-level Thunderbolt access and active NVM backups

This path works independently of display detection. Its private kernel ABI
is deliberately restricted to **arm64 macOS build 26A434 (27.0.1)**, the build
whose actual kernel was inspected. Other builds require ABI validation before
enabling it; there is no force override. Registry listing is still available.

```sh
make -C tools/macos
python3 tools/macos/tb16.py list-tbt
python3 tools/macos/tb16.py read-tbt-config --experimental --device 0x100001234
```

Use an actual switch ID from `list-tbt`; it is different from a display/AUX
interface ID and changes after unplugging. Only Dell cable/dock model IDs
`00d4:b051` and `00d4:b054` are listed. Opening a reader revalidates the model,
finds its parent Thunderbolt controller, and reads the switch identity to
require Intel `8086:1578`. The host Mac is not an allowed target.

`read-tbt-config` defaults to five switch-header DWORDs. It also supports
`--space port --port NUMBER --offset DWORD_OFFSET --count COUNT`. Reads are
limited to 1-16 DWORDs in switch/port space; the native wrapper has no generic
configuration-write entry point. Configuration reads worked as a normal user
on the tested Mac.

To read the installed firmware version from active NVM:

```sh
sudo python3 tools/macos/tb16.py read-nvm-header --experimental --device 0x100001234
```

This locates the controller's DMA/NHI port and validates its mailbox capability.
It submits only **FLASH_READ** commands to the mailbox, then reads 80 bytes
of the active digital header. Submitting the read command writes a temporary
control register and requires administrator access; it does not program
firmware. The read commands never call the separate staging/authentication
entry points. Busy mailboxes, errors and timeouts abort without a retry or reset.

For a verified backup of the entire active firmware bank:

```sh
mkdir -p tools/macos/backups
sudo python3 tools/macos/tb16.py backup-nvm --experimental \
  --device 0x100001234 --output tools/macos/backups/cable-active.backup.bin
```

Use separate files for cable and dock. The backup reads the active bank twice,
requires identical bytes, saves to a new file, flushes it and checks the saved
bytes. The destination must not already exist. Files are created with private
permissions and assigned to the invoking sudo user. The `backups` directory
and `*.backup.bin` files are ignored by Git because raw NVM may contain device
identifiers. The CLI reports a SHA-256 digest and byte count.

An active-bank backup is **not a complete physical SPI-flash dump**. It excludes
the separate flash header, inactive bank and other controllers' firmware.
There is no restore command yet, so these files do not guarantee recovery.
A root-owned lock serializes this tool's mailbox users; do not run other
firmware tools concurrently. Keep the dock connected throughout the reads.

The six-scalar configuration-read ABI was verified from the local
`IOThunderboltFamilyUserClient::externalMethod` and `configReadAction` code.
The output is in big-endian Thunderbolt wire order, which the wrapper converts
to host DWORDs. The active-flash mailbox protocol, Intel header version fields
and bank-size calculation were checked against the Linux kernel's
[`dma_port.c`](https://github.com/torvalds/linux/blob/master/drivers/thunderbolt/dma_port.c)
and [`nvm.c`](https://github.com/torvalds/linux/blob/master/drivers/thunderbolt/nvm.c).
No kernel modifications, entitlements or SIP changes are used.

## Experimental Thunderbolt NVM staging and authentication

**Cable staging/authentication have passed one hardware test; activation is
pending. Dock NVM programming remains untested.** The writer is restricted to the same
verified macOS build, Intel 1578 and Dell cable/dock model IDs as the reader.
Only migration from installed NVM **16.00** is enabled in this initial path.
The two allowed images have pinned SHA-256 values; modified images, older
images and the security-disabled alternatives are rejected. The cable image
is the repository's unofficial 26.06 choice, rather than a new Dell release
specifically qualified for this Mac. Its compatibility still needs testing.

An offline plan uses an existing active-bank backup without loading IOKit,
requiring root, or contacting the dock:

```sh
python3 tools/macos/tb16.py plan-nvm --target cable \
  --image bins/Cable_26_06.bin \
  --backup tools/macos/backups/cable-active.backup.bin
```

For the dock controller, select `--target dock` and
`bins/Dock_BME_27_00.bin` with its own backup. Offline validation checks the
bank layout/version and image's intended role; it cannot prove which physical
device supplied an arbitrary backup. The saved development
[update plans](validation/m5-tb16-nvm-update-plan.json) were checked against
both actual M5/TB16 backups. They contain no raw firmware or device UIDs.

A live dry run additionally matches the selected controller and reads its
active header. It submits FLASH_READ control commands, with no programming
or authentication and no backup file created:

```sh
sudo python3 tools/macos/tb16.py update-nvm --experimental \
  --device 0x100001234 --image bins/Cable_26_06.bin
```

The following command performs a real inactive-bank write and then requests
authentication. Use a real **cable** switch ID from a fresh `list-tbt` and a
**new** backup filename. Do not run it as part of read-only diagnostics:

```sh
sudo python3 tools/macos/tb16.py update-nvm --experimental \
  --device 0x100001234 --image bins/Cable_26_06.bin \
  --backup tools/macos/backups/cable-before-staging.backup.bin \
  --write --authenticate
```

For the dock controller, use its own ID, image and new backup filename.
Update one controller at a time. The workflow holds the mailbox lock, reads
the full active bank twice, saves and verifies the new backup, then stages
the digital region in packets of at most 64 bytes. It skips the image's
16 KiB FARB prefix; Alpine Ridge does not use the older-generation CSS-header
write. Write lengths use the mailbox's count-minus-one encoding.

The native layer rechecks the exact registry entry, route, parent controller,
Dell model, Intel identity and mailbox before every programming packet. A
disconnect or any failed packet invalidates the session; incomplete or failed
staging cannot authenticate. The active bank is read again and must match the
backup before authentication. Do not run other firmware utilities concurrently;
the lock coordinates only instances of this tool.

Without `--authenticate`, `--write` stops at `staged_unverified`. A later
process cannot authenticate an old session: rerun the full backup/staging
workflow with another new backup file if authentication is needed. There is
no independent authenticate, erase, reset or generic register-write command.

The mailbox's FLASH_READ command addresses the **active** bank, so the writer
cannot independently read back its inactive staging buffer. It reports staging
acknowledgements separately from authentication and activation:

| Result state | Meaning | Exit code |
| --- | --- | --- |
| `dry_run` | Image/target/header checked; no firmware written | 0 |
| `staged_unverified` | All staging packets acknowledged; no auth requested | 0 |
| `authentication_reported` | Device returned auth status zero; activation still unverified | 0 |
| `authentication_failed` | Device returned a nonzero authentication status | 1 |
| `authentication_outcome_unknown` | Command attempted but disconnect, timeout or missing status prevented confirmation | 2 |

Never interpret exit zero alone as proof of activated firmware. Authentication
is attempted once, with no retry and no automatic dock reset. Native staging
polls have a five-second deadline. Authentication waits up to 150 ms for
command completion, then up to five seconds for its status; kernel calls can
add their own timeout. If the
outcome is unknown or a write fails, keep the dock powered, preserve output
and the backup, and investigate before retrying. Backups do not guarantee
recovery, and this tool has no restore operation.

After confirmed authentication, manually power-cycle the dock, enumerate
again, and run `read-nvm-header` against its new ID. Require **26.06** for the
cable or **27.00** for the dock from the active header. Then test HDMI, USB,
Ethernet, audio and sleep/wake. NVM activation does not establish that HDMI
works or update the MST/ASMedia firmware.

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
The Thunderbolt C tests additionally verify the six-scalar request, wire byte
order, read-only mailbox opcodes, privilege rejection, capability matching,
busy/error/timeout handling and bounds. A separate native mailbox/registry
emulator executes the actual staging/authentication implementation, including
wire byte order, one- and sixteen-DWORD lengths, short final packets,
replacement/disconnect rejection, staging failures and single-attempt auth.
Python tests check role/hash/version validation, backup-before-write ordering,
payload slicing, unchanged-active-bank checks, failure states and CLI defaults.

Validation completed during development: native arm64 compilation with
warnings as errors, Intel syntax checks, offline image inspection, tests, and
live IORegistry enumeration. Initially no firmware or remote-control writes
were run on hardware; the later cable NVM experiment is recorded below.

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

Lower-level hardware validation subsequently succeeded without a working
external display:

- Both switch headers returned Intel identity `0x15788086` and the expected
  routes (`0x1` for cable, `0x301` for dock) through native configuration reads.
- Both controllers exposed an idle DMA flash-read mailbox on NHI port 5.
- Active NVM headers identified **16.00 on both controllers**, with a
  516,096-byte active bank each. These are actual header-derived NVM versions,
  distinct from System Information's `16.16` display.
- Both 516,096-byte active banks were subsequently backed up. Each backup
  passed two matching device reads and saved-file verification. Raw dumps are
  retained locally under the ignored `backups` directory; the filtered
  [NVM validation report](validation/m5-tb16-nvm-read.json) records versions,
  byte counts and SHA-256 digests.

The Thunderbolt DP output user client's exposed methods are link/HPD/mux
controls rather than direct AUX reads. Configuration/NVM reads are now working,
but the display-chip AUX route remains unavailable. NVM staging/authentication
was implemented and emulator-tested, followed by the cable-only test below.
No guessed kernel selectors were sent.

The first approved hardware write targeted only the cable controller:

- A fresh 516,096-byte backup passed two matching reads and saved-file
  verification. Its SHA-256 matched the earlier 16.00 backup exactly.
- All 3,392 staging packets (217,088 digital-region bytes) were acknowledged.
- A subsequent full active-bank read matched the backup before authentication.
- One authentication request returned IOReturn zero and device status zero.
- The dock controller was not programmed. Activation and the HDMI retest are
  pending a physical power-cycle; authentication alone is not proof of either.

The sanitized [cable update report](validation/m5-tb16-cable-update.json)
records the result. Raw backup, log and command output remain locally under
the ignored `backups` directory.

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
The experimental native implementation above supplies a separate, build-specific
Thunderbolt transport. ASMedia requires its own PCIe register access, as
illustrated by [`ASMTool`](https://github.com/smx-smx/ASMTool); that transport
is not implemented here.
