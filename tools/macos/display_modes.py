"""Read-only external-display modes via public CoreGraphics APIs; no IOKit bridge."""
import ctypes as C
import platform


def collect():
    if platform.system() != "Darwin":
        raise RuntimeError("Live display modes require macOS")
    cg = C.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

    def bind(lib, name, arguments, result):
        function = getattr(lib, name)
        function.argtypes, function.restype = arguments, result
        return function

    online = bind(cg, "CGGetOnlineDisplayList",
                  [C.c_uint32, C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)], C.c_int32)
    builtin = bind(cg, "CGDisplayIsBuiltin", [C.c_uint32], C.c_uint32)
    copy_modes = bind(cg, "CGDisplayCopyAllDisplayModes", [C.c_uint32, C.c_void_p], C.c_void_p)
    copy_current = bind(cg, "CGDisplayCopyDisplayMode", [C.c_uint32], C.c_void_p)
    getters = [(key, bind(cg, name, [C.c_void_p], kind)) for key, name, kind in (
        ("width_points", "CGDisplayModeGetWidth", C.c_size_t),
        ("height_points", "CGDisplayModeGetHeight", C.c_size_t),
        ("pixel_width", "CGDisplayModeGetPixelWidth", C.c_size_t),
        ("pixel_height", "CGDisplayModeGetPixelHeight", C.c_size_t),
        ("refresh_hz", "CGDisplayModeGetRefreshRate", C.c_double),
        ("usable_for_desktop", "CGDisplayModeIsUsableForDesktopGUI", C.c_bool))]
    array_count = bind(cf, "CFArrayGetCount", [C.c_void_p], C.c_long)
    array_get = bind(cf, "CFArrayGetValueAtIndex", [C.c_void_p, C.c_long], C.c_void_p)
    release = bind(cf, "CFRelease", [C.c_void_p], None)

    def describe(mode):
        if not mode:
            return None
        result = {key: getter(mode) for key, getter in getters}
        result["refresh_hz"] = round(result["refresh_hz"], 3)
        return result

    identifiers, count = (C.c_uint32 * 32)(), C.c_uint32()
    status = online(len(identifiers), identifiers, C.byref(count))
    if status or count.value > len(identifiers):
        raise RuntimeError(f"CoreGraphics display enumeration failed: {status}")
    displays = []
    for identifier in identifiers[:count.value]:
        if builtin(identifier):
            continue
        current = copy_current(identifier)
        modes = copy_modes(identifier, None)
        try:
            entries = [describe(array_get(modes, index))
                       for index in range(array_count(modes))] if modes else []
            unique = {tuple(entry.values()): entry for entry in entries if entry}
            displays.append({"current": describe(current), "modes": list(unique.values())})
        finally:
            if current:
                release(current)
            if modes:
                release(modes)
    return {"source": "public CoreGraphics APIs; external displays only; no mode changes",
            "note": "Pixels describe the framebuffer, not measured HDMI wire timing. "
                    "Listed modes are advertised by macOS, not proof they work on the monitor. "
                    "Manually selected current modes may be absent from the default modes list.",
            "external_displays": displays}
