"""ctypes wrapper for the small SDK-built IOI2C bridge; no private Apple APIs."""
import ctypes as C
from pathlib import Path
import sys


class AuxError(RuntimeError):
    pass


class Endpoint(C.Structure):
    _fields_ = [("registry_id", C.c_uint64), ("transaction_types", C.c_uint64),
                ("path", C.c_char * 512)]


def check(code, operation):
    if code:
        raise AuxError(f"{operation}: IOKit error 0x{code:08x}")


class Native:
    def __init__(self):
        if sys.platform != "darwin":
            raise AuxError("The native AUX backend requires macOS.")
        path = Path(__file__).resolve().parent / "build/libtb16aux.dylib"
        try:
            self.lib = C.CDLL(str(path))
        except OSError as error:
            raise AuxError("Build the native bridge with: make -C tools/macos") from error
        self.lib.tb16_list.argtypes = [C.POINTER(C.POINTER(Endpoint)), C.POINTER(C.c_uint32)]
        self.lib.tb16_list.restype = C.c_uint32
        self.lib.tb16_free.argtypes = [C.c_void_p]
        self.lib.tb16_free.restype = None
        self.lib.tb16_open.argtypes = [C.c_uint64, C.POINTER(C.c_void_p)]
        self.lib.tb16_open.restype = C.c_uint32
        self.lib.tb16_close.argtypes = [C.c_void_p]
        self.lib.tb16_close.restype = C.c_uint32
        self.lib.tb16_transfer.argtypes = [C.c_void_p, C.c_uint32, C.c_void_p,
                                         C.c_uint32, C.c_uint32]
        self.lib.tb16_transfer.restype = C.c_uint32

    def endpoints(self):
        entries, count = C.POINTER(Endpoint)(), C.c_uint32()
        check(self.lib.tb16_list(C.byref(entries), C.byref(count)), "enumerate AUX interfaces")
        try:
            return [{"id": f"0x{entries[i].registry_id:x}",
                     "native_aux": bool(entries[i].transaction_types & (1 << 4)),
                     "transaction_types": f"0x{entries[i].transaction_types:x}",
                     "path": entries[i].path.decode("utf-8", "replace")}
                    for i in range(count.value)]
        finally:
            self.lib.tb16_free(entries)

    def open(self, registry_id):
        return Aux(self.lib, registry_id)


class Aux:
    def __init__(self, lib, registry_id):
        self.lib, self.connection = lib, C.c_void_p()
        check(lib.tb16_open(registry_id, C.byref(self.connection)),
              "open native AUX interface (it must advertise native AUX support)")

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        code = self.lib.tb16_close(self.connection)
        if kind is None:
            check(code, "close AUX interface")

    def _transfer(self, address, data, writing):
        if not data or address < 0 or address + len(data) > 0x100000:
            raise AuxError("AUX transfer must fit within the 20-bit DPCD address space")
        for offset in range(0, len(data), 16):
            packet = (C.c_uint8 * min(16, len(data) - offset)).from_buffer(data, offset)
            check(self.lib.tb16_transfer(self.connection, address + offset, packet,
                                         len(packet), int(writing)),
                  f"AUX {'write' if writing else 'read'} at 0x{address + offset:05x}")

    def read(self, address, length):
        data = bytearray(length)
        self._transfer(address, data, False)
        return bytes(data)

    def write(self, address, data):
        self._transfer(address, bytearray(data), True)


class DpEndpoint(C.Structure):
    _fields_ = [("registry_id", C.c_uint64), ("path", C.c_char * 512),
                ("location", C.c_char * 32)]


class IodpNative(Native):
    """Private Apple Silicon API; intentionally limited to read-only diagnostics."""
    def __init__(self):
        super().__init__()
        self.lib.tb16_iodp_available.argtypes = []
        self.lib.tb16_iodp_available.restype = C.c_uint32
        self.lib.tb16_iodp_list.argtypes = [C.POINTER(C.POINTER(DpEndpoint)), C.POINTER(C.c_uint32)]
        self.lib.tb16_iodp_list.restype = C.c_uint32
        self.lib.tb16_iodp_open.argtypes = [C.c_uint64, C.POINTER(C.c_void_p)]
        self.lib.tb16_iodp_open.restype = C.c_uint32
        self.lib.tb16_iodp_close.argtypes = [C.c_void_p]
        self.lib.tb16_iodp_close.restype = None
        self.lib.tb16_iodp_read.argtypes = [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32]
        self.lib.tb16_iodp_read.restype = C.c_uint32
        if not self.lib.tb16_iodp_available():
            raise AuxError("Private IODP device/read functions are unavailable on this macOS version")

    def endpoints(self):
        entries, count = C.POINTER(DpEndpoint)(), C.c_uint32()
        check(self.lib.tb16_iodp_list(C.byref(entries), C.byref(count)), "enumerate IODP devices")
        try:
            return [{"id": f"0x{entries[i].registry_id:x}",
                     "backend": "iodp", "read_only": True,
                     "location": entries[i].location.decode("utf-8", "replace"),
                     "external": entries[i].location == b"External",
                     "path": entries[i].path.decode("utf-8", "replace")}
                    for i in range(count.value)]
        finally:
            self.lib.tb16_free(entries)

    def open(self, registry_id):
        return IodpAux(self.lib, registry_id)


class IodpAux:
    def __init__(self, lib, registry_id):
        self.lib, self.connection = lib, C.c_void_p()
        check(lib.tb16_iodp_open(registry_id, C.byref(self.connection)),
              "open IODP device (only an advertised External device is allowed)")

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        self.lib.tb16_iodp_close(self.connection)

    def read(self, address, length):
        if length <= 0 or address < 0 or address + length > 0x100000:
            raise AuxError("DPCD read must fit within the 20-bit address space")
        data = bytearray(length)
        for offset in range(0, length, 16):
            packet = (C.c_uint8 * min(16, length - offset)).from_buffer(data, offset)
            check(self.lib.tb16_iodp_read(self.connection, address + offset, packet, len(packet)),
                  f"IODP read at 0x{address + offset:05x}")
        return bytes(data)

    def write(self, address, data):
        raise AuxError("The IODP backend is read-only; firmware backup/control/write is unavailable")
