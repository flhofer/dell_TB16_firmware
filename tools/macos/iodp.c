/* Experimental, READ-ONLY Apple Silicon DPCD bridge.
 * The private IOKit ABI was inspected on macOS 27.0.1 arm64e. These functions
 * are resolved at runtime; there is deliberately no DPCD write entry point.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdlib.h>

typedef CFTypeRef (*create_device_fn)(CFAllocatorRef, io_service_t);
typedef IOReturn (*read_dpcd_fn)(CFTypeRef, uint32_t, void *, uint32_t);

typedef struct {
    uint64_t registry_id;
    char path[512];
    char location[32];
} tb16_dp_endpoint;

uint32_t tb16_iodp_available(void)
{
    return dlsym(RTLD_DEFAULT, "IODPDeviceCreateWithService") != NULL &&
           dlsym(RTLD_DEFAULT, "IODPDeviceReadDPCD") != NULL;
}

static CFTypeRef property(io_service_t service, CFStringRef key)
{
    return IORegistryEntryCreateCFProperty(service, key, kCFAllocatorDefault, 0);
}

static int supported(io_service_t service)
{
    CFTypeRef flag = property(service, CFSTR("IODPDeviceUserInterfaceSupported"));
    int result = flag && CFEqual(flag, kCFBooleanTrue);
    if (flag)
        CFRelease(flag);
    return result;
}

/* List all advertised DP devices so an embedded-only result is visible.
 * Only External devices can subsequently be opened by this bridge.
 */
IOReturn tb16_iodp_list(tb16_dp_endpoint **out, uint32_t *count)
{
    *out = NULL;
    *count = 0;
    CFMutableDictionaryRef match = IOServiceMatching("IOService");
    if (!match)
        return kIOReturnNoMemory;
    const void *keys[] = {CFSTR("IODPDeviceUserInterfaceSupported")};
    const void *values[] = {kCFBooleanTrue};
    CFDictionaryRef properties = CFDictionaryCreate(kCFAllocatorDefault, keys, values, 1,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    if (!properties) {
        CFRelease(match);
        return kIOReturnNoMemory;
    }
    CFDictionarySetValue(match, CFSTR(kIOPropertyMatchKey), properties);
    CFRelease(properties);
    io_iterator_t iterator = IO_OBJECT_NULL;
    IOReturn result = IOServiceGetMatchingServices(kIOMainPortDefault, match, &iterator);
    if (result != kIOReturnSuccess)
        return result;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        tb16_dp_endpoint *grown = realloc(*out, ((size_t)*count + 1) * sizeof(**out));
        if (!grown) {
            IOObjectRelease(service);
            IOObjectRelease(iterator);
            free(*out);
            *out = NULL;
            *count = 0;
            return kIOReturnNoMemory;
        }
        *out = grown;
        tb16_dp_endpoint *entry = &grown[*count];
        *entry = (tb16_dp_endpoint){0};
        result = IORegistryEntryGetRegistryEntryID(service, &entry->registry_id);
        if (result == kIOReturnSuccess) {
            if (IORegistryEntryGetPath(service, kIOServicePlane, entry->path) != kIOReturnSuccess)
                entry->path[0] = '\0';
            CFTypeRef location = property(service, CFSTR("Location"));
            if (location) {
                if (CFGetTypeID(location) == CFStringGetTypeID())
                    CFStringGetCString((CFStringRef)location, entry->location,
                                       sizeof(entry->location), kCFStringEncodingUTF8);
                CFRelease(location);
            }
            ++*count;
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
    return kIOReturnSuccess;
}

IOReturn tb16_iodp_open(uint64_t registry_id, CFTypeRef *device)
{
    *device = NULL;
    if (!tb16_iodp_available())
        return kIOReturnUnsupported;
    io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault,
                                                     IORegistryEntryIDMatching(registry_id));
    if (!service)
        return kIOReturnNoDevice;
    CFTypeRef location = property(service, CFSTR("Location"));
    IOReturn result = kIOReturnUnsupported;
    if (supported(service) && location && CFEqual(location, CFSTR("External"))) {
        create_device_fn create = (create_device_fn)dlsym(RTLD_DEFAULT, "IODPDeviceCreateWithService");
        *device = create(kCFAllocatorDefault, service);
        result = *device ? kIOReturnSuccess : kIOReturnNotOpen;
    }
    if (location)
        CFRelease(location);
    IOObjectRelease(service);
    return result;
}

void tb16_iodp_close(CFTypeRef device)
{
    if (device)
        CFRelease(device);
}

IOReturn tb16_iodp_read(CFTypeRef device, uint32_t address, void *buffer, uint32_t length)
{
    if (!device || !buffer || !length || length > 16 || address > 0xfffff ||
        length > 0x100000 - address)
        return kIOReturnBadArgument;
    read_dpcd_fn read = (read_dpcd_fn)dlsym(RTLD_DEFAULT, "IODPDeviceReadDPCD");
    if (!read)
        return kIOReturnUnsupported;
    return read(device, address, buffer, length);
}
