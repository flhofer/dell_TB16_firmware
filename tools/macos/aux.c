/* Native AUX bridge. Build against SDK headers rather than duplicating IOI2C's ABI. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/i2c/IOI2CInterface.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct {
    uint64_t registry_id;
    uint64_t transaction_types;
    char path[512];
} tb16_endpoint;

static uint64_t transaction_types(io_service_t service)
{
    uint64_t value = 0;
    CFTypeRef property = IORegistryEntryCreateCFProperty(
        service, CFSTR(kIOI2CTransactionTypesKey), kCFAllocatorDefault, 0);
    if (property) {
        if (CFGetTypeID(property) == CFNumberGetTypeID())
            CFNumberGetValue((CFNumberRef)property, kCFNumberSInt64Type, &value);
        CFRelease(property);
    }
    return value;
}

/* Caller owns the returned array, including when count is zero. */
IOReturn tb16_list(tb16_endpoint **out, uint32_t *count)
{
    *out = NULL;
    *count = 0;
    io_iterator_t iterator = IO_OBJECT_NULL;
    IOReturn result = IOServiceGetMatchingServices(
        kIOMainPortDefault, IOServiceMatching(kIOI2CInterfaceClassName), &iterator);
    if (result != kIOReturnSuccess)
        return result;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        tb16_endpoint *grown = realloc(*out, ((size_t)*count + 1) * sizeof(**out));
        if (!grown) {
            IOObjectRelease(service);
            IOObjectRelease(iterator);
            free(*out);
            *out = NULL;
            *count = 0;
            return kIOReturnNoMemory;
        }
        *out = grown;
        tb16_endpoint *entry = &grown[*count];
        *entry = (tb16_endpoint){0};
        result = IORegistryEntryGetRegistryEntryID(service, &entry->registry_id);
        if (result == kIOReturnSuccess) {
            entry->transaction_types = transaction_types(service);
            if (IORegistryEntryGetPath(service, kIOServicePlane, entry->path) != kIOReturnSuccess)
                entry->path[0] = '\0';
            ++*count;
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
    return kIOReturnSuccess;
}

void tb16_free(void *pointer) { free(pointer); }

IOReturn tb16_open(uint64_t registry_id, IOI2CConnectRef *connection)
{
    *connection = NULL;
    io_service_t service = IOServiceGetMatchingService(
        kIOMainPortDefault, IORegistryEntryIDMatching(registry_id));
    if (!service)
        return kIOReturnNoDevice;
    IOReturn result = kIOReturnUnsupportedMode;
    if (IOObjectConformsTo(service, kIOI2CInterfaceClassName) &&
        (transaction_types(service) & (1ULL << kIOI2CDisplayPortNativeTransactionType)))
        result = IOI2CInterfaceOpen(service, 0, connection);
    IOObjectRelease(service);
    return result;
}

IOReturn tb16_close(IOI2CConnectRef connection)
{
    return IOI2CInterfaceClose(connection, 0);
}

/* One native AUX packet, with the 20-bit DPCD address passed unshifted. */
IOReturn tb16_transfer(IOI2CConnectRef connection, uint32_t address,
                      uint8_t *data, uint32_t length, uint32_t writing)
{
    if (!connection || !data || !length || length > 16 ||
        address > 0xfffff || length > 0x100000 - address)
        return kIOReturnBadArgument;
    IOI2CRequest request = {0};
    if (writing) {
        request.sendTransactionType = kIOI2CDisplayPortNativeTransactionType;
        request.sendAddress = address;
        request.sendBuffer = (vm_address_t)data;
        request.sendBytes = length;
    } else {
        request.replyTransactionType = kIOI2CDisplayPortNativeTransactionType;
        request.replyAddress = address;
        request.replyBuffer = (vm_address_t)data;
        request.replyBytes = length;
    }
    IOReturn result = IOI2CSendRequest(connection, 0, &request);
    if (result != kIOReturnSuccess)
        return result;
    if (request.result != kIOReturnSuccess)
        return request.result;
    if ((writing ? request.sendBytes : request.replyBytes) != length)
        return kIOReturnUnderrun;
    return kIOReturnSuccess;
}
