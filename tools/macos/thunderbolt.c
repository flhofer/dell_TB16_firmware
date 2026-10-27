/* TB16 configuration reads via the macOS 27.0.1/26A434 arm64 user client.
 * Verified from IOThunderboltFamilyUserClient::externalMethod/configReadAction.
 * Selector 0 takes six uint64 scalars: route, port, space, DWORD offset,
 * userspace output-buffer address, DWORD count. No generic write API is
 * exposed; only fixed FLASH_READ mailbox commands use the write selector.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <libkern/OSByteOrder.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/sysctl.h>
#include <time.h>
#include <unistd.h>

typedef struct {
    uint64_t registry_id;
    uint64_t controller_id;
    uint64_t route;
    uint32_t model_id;
    uint32_t chip_id;
    char name[128];
} tb16_tbt_endpoint;

typedef struct {
    io_connect_t connection;
    uint64_t route;
    uint32_t dma_port;
    uint32_t active_size;
} tb16_tbt_handle;

static int number(io_service_t service, CFStringRef key, uint64_t *value)
{
    CFTypeRef property = IORegistryEntryCreateCFProperty(service, key, kCFAllocatorDefault, 0);
    int result = property && CFGetTypeID(property) == CFNumberGetTypeID() &&
                 CFNumberGetValue((CFNumberRef)property, kCFNumberSInt64Type, value);
    if (property)
        CFRelease(property);
    return result;
}

static int is_tb16(io_service_t service)
{
    uint64_t vendor = 0, model = 0;
    return IOObjectConformsTo(service, "IOThunderboltSwitch") &&
           number(service, CFSTR("Device Vendor ID"), &vendor) && vendor == 0x00d4 &&
           number(service, CFSTR("Device Model ID"), &model) &&
           (model == 0xb051 || model == 0xb054);
}

static io_service_t copy_controller(io_service_t service)
{
    io_registry_entry_t current = service;
    IOObjectRetain(current);
    for (unsigned depth = 0; depth < 64; ++depth) {
        if (IOObjectConformsTo(current, "IOThunderboltController"))
            return current;
        io_registry_entry_t parent = IO_OBJECT_NULL;
        IOReturn result = IORegistryEntryGetParentEntry(current, kIOServicePlane, &parent);
        IOObjectRelease(current);
        if (result != kIOReturnSuccess)
            return IO_OBJECT_NULL;
        current = parent;
    }
    IOObjectRelease(current);
    return IO_OBJECT_NULL;
}

uint32_t tb16_tbt_abi_supported(void)
{
#if defined(__arm64__)
    char build[64] = {0};
    size_t size = sizeof(build);
    return sysctlbyname("kern.osversion", build, &size, NULL, 0) == 0 &&
           strcmp(build, "26A434") == 0;
#else
    return 0;
#endif
}

IOReturn tb16_tbt_list(tb16_tbt_endpoint **out, uint32_t *count)
{
    *out = NULL;
    *count = 0;
    io_iterator_t iterator = IO_OBJECT_NULL;
    IOReturn result = IOServiceGetMatchingServices(kIOMainPortDefault,
        IOServiceMatching("IOThunderboltSwitch"), &iterator);
    if (result != kIOReturnSuccess)
        return result;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        io_service_t controller = is_tb16(service) ? copy_controller(service) : IO_OBJECT_NULL;
        tb16_tbt_endpoint entry = {0};
        uint64_t model = 0, chip = 0;
        if (controller &&
            IORegistryEntryGetRegistryEntryID(service, &entry.registry_id) == kIOReturnSuccess &&
            IORegistryEntryGetRegistryEntryID(controller, &entry.controller_id) == kIOReturnSuccess &&
            number(service, CFSTR("Route String"), &entry.route) && entry.route &&
            number(service, CFSTR("Device Model ID"), &model) &&
            number(service, CFSTR("Device ID"), &chip)) {
            entry.model_id = (uint32_t)model;
            entry.chip_id = (uint32_t)chip;
            CFTypeRef name = IORegistryEntryCreateCFProperty(service,
                CFSTR("Device Model Name"), kCFAllocatorDefault, 0);
            if (name) {
                if (CFGetTypeID(name) == CFStringGetTypeID())
                    CFStringGetCString((CFStringRef)name, entry.name, sizeof(entry.name),
                                       kCFStringEncodingUTF8);
                CFRelease(name);
            }
            tb16_tbt_endpoint *grown = realloc(*out, ((size_t)*count + 1) * sizeof(**out));
            if (!grown) {
                result = kIOReturnNoMemory;
            } else {
                *out = grown;
                grown[(*count)++] = entry;
            }
        }
        if (controller)
            IOObjectRelease(controller);
        IOObjectRelease(service);
        if (result != kIOReturnSuccess)
            break;
    }
    IOObjectRelease(iterator);
    if (result != kIOReturnSuccess) {
        free(*out);
        *out = NULL;
        *count = 0;
    }
    return result;
}

IOReturn tb16_tbt_read(tb16_tbt_handle *handle, uint32_t port, uint32_t space,
                      uint32_t offset, uint32_t *output, uint32_t count)
{
    /* Hops and counters are unnecessary for this investigation. */
    if (!handle || !handle->connection || !handle->route || !output || !count || count > 16 ||
        (space != 1 && space != 2) || port > 63 || (space == 2 && port != 0) ||
        offset > 0x1fff || count > 0x2000 - offset)
        return kIOReturnBadArgument;
    memset(output, 0, count * sizeof(*output));
    const uint64_t input[] = {handle->route, port, space, offset, (uintptr_t)output, count};
    IOReturn result = IOConnectCallScalarMethod(handle->connection, 0, input, 6, NULL, NULL);
    if (result == kIOReturnSuccess) {
        /* The user client copies Thunderbolt wire-order DWORDs unchanged. */
        for (uint32_t i = 0; i < count; ++i)
            output[i] = OSSwapBigToHostInt32(output[i]);
    }
    return result;
}

IOReturn tb16_tbt_open(uint64_t registry_id, tb16_tbt_handle **out)
{
    *out = NULL;
    if (!tb16_tbt_abi_supported())
        return kIOReturnUnsupported;
    io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault,
                                                     IORegistryEntryIDMatching(registry_id));
    if (!service)
        return kIOReturnNoDevice;
    io_service_t controller = is_tb16(service) ? copy_controller(service) : IO_OBJECT_NULL;
    uint64_t route = 0, chip = 0;
    IOReturn result = kIOReturnBadArgument;
    if (controller && number(service, CFSTR("Route String"), &route) && route &&
        number(service, CFSTR("Device ID"), &chip) && chip == 0x1578) {
        tb16_tbt_handle *handle = calloc(1, sizeof(*handle));
        if (!handle) {
            result = kIOReturnNoMemory;
        } else {
            handle->route = route;
            result = IOServiceOpen(controller, mach_task_self(), 0, &handle->connection);
            if (result == kIOReturnSuccess) {
                uint32_t identity = 0;
                result = tb16_tbt_read(handle, 0, 2, 0, &identity, 1);
                if (result == kIOReturnSuccess && identity != 0x15788086)
                    result = kIOReturnNoDevice;
                if (result == kIOReturnSuccess)
                    *out = handle;
                else
                    IOServiceClose(handle->connection);
            }
            if (!*out)
                free(handle);
        }
    }
    if (controller)
        IOObjectRelease(controller);
    IOObjectRelease(service);
    return result;
}

IOReturn tb16_tbt_close(tb16_tbt_handle *handle)
{
    if (!handle)
        return kIOReturnBadArgument;
    IOReturn result = IOServiceClose(handle->connection);
    free(handle);
    return result;
}

static double monotonic_seconds(void)
{
    struct timespec now = {0};
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0)
        return -1;
    return now.tv_sec + now.tv_nsec / 1e9;
}

/* Only active-flash READ requests. Never writes DATA, authenticates, erases,
 * resets, or exposes a generic configuration-write operation. The caller
 * serializes mailbox use against other instances of this tool.
 */
static IOReturn nvm_read(tb16_tbt_handle *handle, uint8_t *output,
                        uint32_t start, uint32_t size)
{
    if (!handle || !output)
        return kIOReturnBadArgument;
    if (geteuid() != 0)
        return kIOReturnNotPrivileged;
    uint32_t port = handle->dma_port, value = 0;
    const uint32_t candidates[] = {3, 5, 7};
    for (unsigned i = 0; !port && i < 3; ++i) {
        IOReturn result = tb16_tbt_read(handle, candidates[i], 1, 2, &value, 1);
        if (result == kIOReturnSuccess && (value & 0xffffff) == 2) {
            port = candidates[i];
            break;
        }
    }
    if (!port)
        return kIOReturnNotFound;
    IOReturn result = tb16_tbt_read(handle, port, 1, 0x3e, &value, 1);
    /* VSE capability 1, 0x13 DWORDs: header, DATA[16], MAIL_IN, MAIL_OUT. */
    if (result != kIOReturnSuccess)
        return result;
    if ((value & 0xffffff00) != 0x13010500)
        return kIOReturnUnsupported;
    memset(output, 0, size);
    for (uint32_t position = 0; position < size; position += 64) {
        uint32_t address = start + position;
        uint32_t count = (size - position < 64 ? size - position : 64) / 4;
        result = tb16_tbt_read(handle, port, 1, 0x4f, &value, 1);
        if (result != kIOReturnSuccess)
            return result;
        if (value & 1)
            return kIOReturnBusy;
        double started = monotonic_seconds();
        if (started < 0)
            return kIOReturnError;
        /* FLASH_READ=2; 16 DWORDs use a zero length field. Address is bytes
         * with its bottom two bits reserved for request/CSS flags.
         */
        uint32_t command = 0x20000001 | address | (count == 16 ? 0 : count << 24);
        uint32_t wire_command = OSSwapHostToBigInt32(command);
        const uint64_t input[] = {handle->route, port, 1, 0x4f, (uintptr_t)&wire_command, 1};
        result = IOConnectCallScalarMethod(handle->connection, 1, input, 6, NULL, NULL);
        if (result != kIOReturnSuccess)
            return result;
        for (;;) {
            result = tb16_tbt_read(handle, port, 1, 0x4f, &value, 1);
            if (result != kIOReturnSuccess)
                return result;
            if (!(value & 1))
                break;
            double now = monotonic_seconds();
            if (now < 0)
                return kIOReturnError;
            if (now - started >= 5.0)
                return kIOReturnTimeout;
            usleep(1000);
        }
        result = tb16_tbt_read(handle, port, 1, 0x50, &value, 1);
        if (result != kIOReturnSuccess)
            return result;
        if ((value & 15) != 0)
            return (value & 15) == 2 ? kIOReturnNotPermitted : kIOReturnIOError;
        uint32_t data[16] = {0};
        result = tb16_tbt_read(handle, port, 1, 0x3f, data, count);
        if (result != kIOReturnSuccess)
            return result;
        for (uint32_t i = 0; i < count; ++i) {
            uint32_t little = OSSwapHostToLittleInt32(data[i]);
            memcpy(output + position + i * 4, &little, 4);
        }
    }
    handle->dma_port = port;
    return kIOReturnSuccess;
}

IOReturn tb16_tbt_nvm_header(tb16_tbt_handle *handle, uint8_t *output)
{
    if (handle)
        handle->active_size = 0;
    IOReturn result = nvm_read(handle, output, 0, 80);
    if (result != kIOReturnSuccess)
        return result;
    if (output[5] != 0x78 || output[6] != 0x15)
        return kIOReturnNoDevice;
    uint32_t size = (((1U << 20) << (output[0x45] & 7)) / 8 - 0x4000) / 2;
    if (!size || size > 0x100000)
        return kIOReturnUnsupported;
    handle->active_size = size;
    return kIOReturnSuccess;
}

IOReturn tb16_tbt_nvm_read(tb16_tbt_handle *handle, uint32_t address,
                          uint8_t *output, uint32_t length)
{
    if (!handle || !handle->active_size || !length || length > 64 ||
        (address & 3) || (length & 3) || address >= handle->active_size ||
        length > handle->active_size - address)
        return kIOReturnBadArgument;
    return nvm_read(handle, output, address, length);
}
