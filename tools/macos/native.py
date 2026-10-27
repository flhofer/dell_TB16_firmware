"""ctypes bindings for the IOI2C and read-only IODP backends."""
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


def bind(lib, name, arguments, result=C.c_uint32):
    function = getattr(lib, name)
    function.argtypes, function.restype = arguments, result
    return function


class Bridge:
    def __init__(self):
        if sys.platform != "darwin":
            raise AuxError("The native bridge requires macOS")
        path = Path(__file__).resolve().parent / "build/libtb16aux.dylib"
        try:
            self.lib = C.CDLL(str(path))
        except OSError as error:
            raise AuxError("Build the native bridge with: make -C tools/macos") from error
        bind(self.lib, "tb16_free", [C.c_void_p], None)


class Native(Bridge):
    def __init__(self):
        super().__init__()
        bind(self.lib, "tb16_list", [C.POINTER(C.POINTER(Endpoint)), C.POINTER(C.c_uint32)])
        bind(self.lib, "tb16_open", [C.c_uint64, C.POINTER(C.c_void_p)])
        bind(self.lib, "tb16_close", [C.c_void_p])
        bind(self.lib, "tb16_transfer", [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32, C.c_uint32])

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
              "open native AUX interface")

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
            check(self._packet(address + offset, packet, writing),
                  f"AUX {'write' if writing else 'read'} at 0x{address + offset:05x}")

    def _packet(self, address, packet, writing):
        return self.lib.tb16_transfer(self.connection, address, packet, len(packet), int(writing))

    def read(self, address, length):
        if length <= 0 or address < 0 or address + length > 0x100000:
            raise AuxError("DPCD read must fit within the 20-bit address space")
        data = bytearray(length)
        self._transfer(address, data, False)
        return bytes(data)

    def write(self, address, data):
        self._transfer(address, bytearray(data), True)


class DpEndpoint(C.Structure):
    _fields_ = [("registry_id", C.c_uint64), ("path", C.c_char * 512),
                ("location", C.c_char * 32)]


class IodpNative(Bridge):
    def __init__(self):
        super().__init__()
        bind(self.lib, "tb16_iodp_available", [])
        bind(self.lib, "tb16_iodp_list", [C.POINTER(C.POINTER(DpEndpoint)), C.POINTER(C.c_uint32)])
        bind(self.lib, "tb16_iodp_open", [C.c_uint64, C.POINTER(C.c_void_p)])
        bind(self.lib, "tb16_iodp_close", [C.c_void_p], None)
        bind(self.lib, "tb16_iodp_read", [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32])
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


class IodpAux(Aux):
    def __init__(self, lib, registry_id):
        self.lib, self.connection = lib, C.c_void_p()
        check(lib.tb16_iodp_open(registry_id, C.byref(self.connection)),
              "open external IODP device")

    def __exit__(self, kind, value, traceback):
        self.lib.tb16_iodp_close(self.connection)

    def _packet(self, address, packet, writing):
        if writing:
            raise AuxError("IODP is read-only")
        return self.lib.tb16_iodp_read(self.connection, address, packet, len(packet))
