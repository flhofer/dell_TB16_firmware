"""TB16 Thunderbolt configuration and NVM access."""
import ctypes as C
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path

from native import AuxError, Bridge, bind, check


class TbtEndpoint(C.Structure):
    _fields_ = [("registry_id", C.c_uint64), ("controller_id", C.c_uint64),
                ("route", C.c_uint64), ("model_id", C.c_uint32),
                ("chip_id", C.c_uint32), ("name", C.c_char * 128)]


def validate_read(space, port, offset, count):
    if (space not in (1, 2) or not 0 <= port <= 63 or (space == 2 and port != 0) or
            not 1 <= count <= 16 or not 0 <= offset <= 0x1FFF or offset + count > 0x2000):
        raise AuxError("Invalid configuration range: space 1/2, port 0-63 (0 for switch), "
                       "offset 0-0x1fff, count 1-16")


class Thunderbolt(Bridge):
    def __init__(self):
        super().__init__()
        bind(self.lib, "tb16_tbt_abi_supported", [])
        bind(self.lib, "tb16_tbt_list", [C.POINTER(C.POINTER(TbtEndpoint)), C.POINTER(C.c_uint32)])
        bind(self.lib, "tb16_tbt_open", [C.c_uint64, C.POINTER(C.c_void_p)])
        bind(self.lib, "tb16_tbt_read", [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32,
                                       C.POINTER(C.c_uint32), C.c_uint32])
        bind(self.lib, "tb16_tbt_close", [C.c_void_p])
        bind(self.lib, "tb16_tbt_nvm_header", [C.c_void_p, C.c_void_p])
        bind(self.lib, "tb16_tbt_nvm_read", [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32])
        bind(self.lib, "tb16_tbt_nvm_stage_begin", [C.c_void_p, C.c_uint32, C.c_uint32])
        bind(self.lib, "tb16_tbt_nvm_stage_write", [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32])
        bind(self.lib, "tb16_tbt_nvm_authenticate", [C.c_void_p, C.POINTER(C.c_uint32),
                                                   C.POINTER(C.c_uint32)])

    def endpoints(self):
        entries, count = C.POINTER(TbtEndpoint)(), C.c_uint32()
        check(self.lib.tb16_tbt_list(C.byref(entries), C.byref(count)), "enumerate TB16 switches")
        try:
            return [{"id": f"0x{entries[i].registry_id:x}",
                     "controller_id": f"0x{entries[i].controller_id:x}",
                     "route": f"0x{entries[i].route:x}",
                     "model_id": f"0x{entries[i].model_id:04x}",
                     "chip_id": f"0x{entries[i].chip_id:04x}",
                     "name": entries[i].name.decode("utf-8", "replace"),
                     "read_abi_supported": bool(self.lib.tb16_tbt_abi_supported())}
                    for i in range(count.value)]
        finally:
            self.lib.tb16_free(entries)

    def open(self, registry_id):
        if not self.lib.tb16_tbt_abi_supported():
            raise AuxError("Thunderbolt access requires arm64 macOS build 26A434")
        return ConfigReader(self.lib, registry_id)


class ConfigReader:
    def __init__(self, lib, registry_id):
        self.lib, self.handle = lib, C.c_void_p()
        check(lib.tb16_tbt_open(registry_id, C.byref(self.handle)),
              "open TB16 controller and verify Intel 8086:1578")

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        code = self.lib.tb16_tbt_close(self.handle)
        if kind is None:
            check(code, "close Thunderbolt reader")

    def read(self, space=2, port=0, offset=0, count=5):
        validate_read(space, port, offset, count)
        output = (C.c_uint32 * count)()
        check(self.lib.tb16_tbt_read(self.handle, port, space, offset, output, count),
              f"Thunderbolt configuration read space={space} port={port} DWORD={offset:#x}")
        return list(output)

    @contextmanager
    def mailbox(self):
        if os.geteuid() != 0:
            raise AuxError("NVM mailbox access requires sudo")
        # Serializes this tool's mailbox users, including reads.
        fd = os.open("/var/run/tb16-macos-nvm.lock",
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            if os.fstat(fd).st_uid != 0:
                raise AuxError("NVM mailbox lock is not owned by root")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise AuxError("Another instance is using the NVM mailbox") from error
            yield
        finally:
            os.close(fd)

    def _nvm_header(self):
        output = (C.c_uint8 * 80)()
        check(self.lib.tb16_tbt_nvm_header(self.handle, output), "read active NVM header")
        return parse_nvm_header(bytes(output))

    def nvm_header(self):
        with self.mailbox():
            return self._nvm_header()

    def backup_nvm(self, output_path, progress=lambda line: None):
        with self.mailbox():
            info, _ = self._backup_nvm(output_path, progress)
            return info

    def _active_bank(self, size, progress=lambda line: None):
        data = bytearray(size)
        last_percent = -1
        for address in range(0, size, 64):
            packet = (C.c_uint8 * min(64, size - address)).from_buffer(data, address)
            check(self.lib.tb16_tbt_nvm_read(self.handle, address, packet, len(packet)),
                  f"active NVM read at {address:#x}")
            percent = (address + len(packet)) * 100 // size
            if percent // 10 != last_percent:
                progress(f"{percent}%")
                last_percent = percent // 10
        return bytes(data)

    def _backup_nvm(self, output_path, progress):
        output_path = Path(output_path)
        if output_path.exists():
            raise AuxError("Backup already exists; choose a new file")
        # Caller holds the mailbox lock.
        info = self._nvm_header()
        size = info["active_bank_size"]
        copies = []
        for pass_number in (1, 2):
            copies.append(self._active_bank(size, lambda percent:
                progress(f"NVM backup pass {pass_number}/2: {percent}")))
        if copies[0] != copies[1]:
            raise AuxError("Active NVM reads differ; no backup saved")
        fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(copies[0])
            output.flush()
            os.fsync(output.fileno())
            # Return ownership to the invoking sudo user.
            if "SUDO_UID" in os.environ and "SUDO_GID" in os.environ:
                os.fchown(output.fileno(), int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
        if output_path.read_bytes() != copies[0]:
            raise AuxError("Saved NVM backup failed verification")
        return {**info, "output": str(output_path), "bytes": size,
                "sha256": hashlib.sha256(copies[0]).hexdigest(), "matching_reads": 2,
                "scope": "active NVM bank only; not a complete physical SPI flash dump"}, copies[0]

    def stage_begin(self, model, size):
        check(self.lib.tb16_tbt_nvm_stage_begin(self.handle, model, size), "begin inactive NVM staging")

    def stage_write(self, address, data):
        packet = (C.c_uint8 * len(data)).from_buffer_copy(data)
        check(self.lib.tb16_tbt_nvm_stage_write(self.handle, address, packet, len(data)),
              f"inactive NVM write at {address:#x}; authentication not requested; keep dock powered")

    def authenticate(self):
        status, attempted = C.c_uint32(0xffffffff), C.c_uint32(0)
        code = self.lib.tb16_tbt_nvm_authenticate(self.handle, C.byref(status), C.byref(attempted))
        if not attempted.value:
            check(code, "authentication preflight failed; no authentication requested")
            raise AuxError("Native authentication returned without attempting the command")
        result = {"authentication_attempted": True, "authentication_ioreturn": f"0x{code:08x}",
                  "authentication_status": None, "activation_verified": False}
        if code or status.value == 0xffffffff:
            return {**result, "state": "authentication_outcome_unknown",
                    "next_step": "Keep dock powered; preserve output and backup"}
        return {**result, "authentication_status": status.value,
                "state": "authentication_reported" if status.value == 0 else "authentication_failed",
                "next_step": ("Power-cycle, then verify active NVM version" if status.value == 0 else
                              "Authentication rejected; preserve output and backup")}


def parse_nvm_header(data):
    if len(data) != 80 or int.from_bytes(data[5:7], "little") != 0x1578:
        raise AuxError("Invalid Intel 1578 NVM header")
    version = int.from_bytes(data[8:12], "little")
    flash_field = int.from_bytes(data[0x45:0x49], "little")
    # Intel Alpine Ridge uses a 16 KiB header and two firmware banks.
    bank_size = (((1 << 20) << (flash_field & 7)) // 8 - (16 << 10)) // 2
    if not 0 < bank_size <= 0x100000:
        raise AuxError("Unsupported active NVM bank size")
    return {"device_id": "0x1578", "nvm_version": f"{(version >> 16) & 255:02x}.{(version >> 8) & 255:02x}",
            "active_bank_size": bank_size,
            "source": "active Intel NVM digital header (80 bytes)", "firmware_written": False}
