/* Execute the real native writer against a mailbox/registry emulator. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <assert.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>

static kern_return_t fake_scalar(mach_port_t, uint32_t, const uint64_t *, uint32_t,
                                 uint64_t *, uint32_t *);
static uid_t fake_uid(void);
static int fake_clock(clockid_t, struct timespec *);
static int fake_sleep(useconds_t);
static io_service_t fake_service(mach_port_t, CFDictionaryRef);
static CFMutableDictionaryRef fake_matching(uint64_t);
static boolean_t fake_conforms(io_object_t, const io_name_t);
static CFTypeRef fake_property(io_registry_entry_t, CFStringRef, CFAllocatorRef, IOOptionBits);
static kern_return_t fake_parent(io_registry_entry_t, const io_name_t, io_registry_entry_t *);
static kern_return_t fake_id(io_registry_entry_t, uint64_t *);
static boolean_t fake_plane(io_registry_entry_t, const io_name_t);
static kern_return_t fake_object(io_object_t);
#define IOConnectCallScalarMethod fake_scalar
#define geteuid fake_uid
#define clock_gettime fake_clock
#define usleep fake_sleep
#define IOServiceGetMatchingService fake_service
#define IORegistryEntryIDMatching fake_matching
#define IOObjectConformsTo fake_conforms
#define IORegistryEntryCreateCFProperty fake_property
#define IORegistryEntryGetParentEntry fake_parent
#define IORegistryEntryGetRegistryEntryID fake_id
#define IORegistryEntryInPlane fake_plane
#define IOObjectRetain fake_object
#define IOObjectRelease fake_object
#include "../thunderbolt.c"
#undef IOConnectCallScalarMethod

static uint8_t active[0x8000], inactive[0x8000], packet[64];
static uint32_t read_address, packet_size, last_command, auth_status;
static unsigned writes, auths, scalar_calls, clock_calls;
static int missing, wrong_route, nonroot, busy, denied, stuck, bad_status, auth_disconnect;
static int auth_delay, auth_no_status, auth_busy;

static uid_t fake_uid(void) { return nonroot ? 501 : 0; }
static int fake_clock(clockid_t clock, struct timespec *value)
{
    assert(clock == CLOCK_MONOTONIC);
    uint64_t ticks = (uint64_t)clock_calls++ * (stuck || auth_no_status ? 6000000000 : 100000000);
    value->tv_sec = ticks / 1000000000;
    value->tv_nsec = ticks % 1000000000;
    return 0;
}
static int fake_sleep(useconds_t delay) { (void)delay; return 0; }
static CFMutableDictionaryRef fake_matching(uint64_t id)
{
    assert(id == 700);
    return CFDictionaryCreateMutable(NULL, 0, NULL, NULL);
}
static io_service_t fake_service(mach_port_t port, CFDictionaryRef matching)
{
    (void)port;
    CFRelease(matching);
    return missing ? IO_OBJECT_NULL : 88;
}
static boolean_t fake_conforms(io_object_t object, const io_name_t name)
{
    return (object == 88 && strcmp(name, "IOThunderboltSwitch") == 0) ||
           (object == 99 && strcmp(name, "IOThunderboltController") == 0);
}
static CFTypeRef fake_property(io_registry_entry_t object, CFStringRef key,
                               CFAllocatorRef allocator, IOOptionBits options)
{
    (void)allocator; (void)options;
    assert(object == 88);
    int64_t value;
    if (CFEqual(key, CFSTR("Device Vendor ID"))) value = 0xd4;
    else if (CFEqual(key, CFSTR("Device Model ID"))) value = 0xb054;
    else if (CFEqual(key, CFSTR("Device ID"))) value = 0x1578;
    else { assert(CFEqual(key, CFSTR("Route String"))); value = wrong_route ? 1 : 0x301; }
    return CFNumberCreate(NULL, kCFNumberSInt64Type, &value);
}
static kern_return_t fake_parent(io_registry_entry_t object, const io_name_t plane,
                                 io_registry_entry_t *parent)
{
    (void)plane;
    assert(object == 88); *parent = 99; return 0;
}
static kern_return_t fake_id(io_registry_entry_t object, uint64_t *id)
{
    assert(object == 99); *id = 900; return 0;
}
static boolean_t fake_plane(io_registry_entry_t object, const io_name_t plane)
{
    (void)plane; assert(object == 88); return 1;
}
static kern_return_t fake_object(io_object_t object)
{
    assert(object == 88 || object == 99); return 0;
}

static kern_return_t fake_scalar(mach_port_t connection, uint32_t selector,
                                 const uint64_t *in, uint32_t count,
                                 uint64_t *out, uint32_t *out_count)
{
    ++scalar_calls;
    assert(connection == 42 && count == 6 && in[0] == 0x301);
    assert(!out && !out_count);
    uint32_t *data = (uint32_t *)(uintptr_t)in[4];
    if (selector == 0 && in[2] == 2) {
        assert(in[1] == 0 && in[3] == 0 && in[5] == 1);
        *data = OSSwapHostToBigInt32(0x15788086); return 0;
    }
    assert(in[2] == 1);
    if (selector == 1) {
        assert(in[1] == 5);
        if (denied) return kIOReturnNotPrivileged;
        if (in[3] == 0x3f) {
            packet_size = (uint32_t)in[5] * 4;
            for (unsigned i = 0; i < in[5]; ++i) {
                uint32_t word = OSSwapHostToLittleInt32(OSSwapBigToHostInt32(data[i]));
                memcpy(packet + i * 4, &word, 4);
            }
        } else {
            assert(in[3] == 0x4f && in[5] == 1);
            uint32_t command = OSSwapBigToHostInt32(*data);
            assert((command & 3) == 1); /* Never CSS or power-cycle. */
            last_command = command >> 28;
            unsigned address = command & 0xfffffc;
            if (last_command == 2) read_address = address;
            else if (last_command == 0) {
                assert((((command >> 24) & 15) + 1) * 4 == packet_size);
                assert(address + packet_size <= sizeof(inactive));
                memcpy(inactive + address, packet, packet_size); ++writes;
            } else {
                assert(last_command == 1 && command == 0x10000001);
                ++auths;
                if (auth_disconnect) return kIOReturnNoDevice;
            }
        }
        return 0;
    }
    assert(selector == 0);
    uint32_t value = 0;
    if (in[3] == 2) value = in[1] == 5 ? 2 : 1;
    else {
        assert(in[1] == 5);
        if (in[3] == 0x3e) value = 0x13010552;
        else if (in[3] == 0x4f) value = busy || (stuck && writes) ||
                                      (auth_busy && last_command == 1) ? 1 : 0;
        else if (in[3] == 0x50) {
            value = last_command << 4 | (bad_status ? 2 : 0) |
                    (last_command == 1 ? auth_status : 0);
            if (last_command == 1 && (auth_no_status || auth_delay > 0)) {
                if (auth_delay > 0) --auth_delay;
                value = 0;
            }
        }
        else {
            assert(in[3] == 0x3f);
            for (unsigned i = 0; i < in[5]; ++i) {
                uint32_t word;
                memcpy(&word, active + read_address + i * 4, 4);
                data[i] = OSSwapHostToBigInt32(OSSwapLittleToHostInt32(word));
            }
            return 0;
        }
    }
    *data = OSSwapHostToBigInt32(value);
    return 0;
}

static tb16_tbt_handle fresh(void)
{
    writes = auths = scalar_calls = clock_calls = last_command = 0;
    missing = wrong_route = nonroot = busy = denied = stuck = bad_status = auth_disconnect = 0;
    auth_status = 0;
    auth_delay = auth_no_status = auth_busy = 0;
    return (tb16_tbt_handle){.connection = 42, .route = 0x301, .registry_id = 700,
                            .controller_id = 900, .model_id = 0xb054};
}

int main(void)
{
    active[5] = 0x78; active[6] = 0x15; active[10] = 0x16; active[0x45] = 3;
    uint8_t payload[0x8000];
    for (unsigned i = 0; i < sizeof(payload); ++i) payload[i] = (uint8_t)(i * 7);
    tb16_tbt_handle h = fresh();
    uint32_t status, attempted;
    assert(tb16_tbt_nvm_authenticate(&h, &status, &attempted) == kIOReturnNotReady);
    assert(!attempted && !scalar_calls);
    assert(tb16_tbt_nvm_stage_begin(&h, 0xb051, sizeof(payload)) == kIOReturnBadArgument);
    assert(!scalar_calls);
    assert(tb16_tbt_nvm_stage_begin(&h, 0xb054, sizeof(payload)) == 0);
    assert(!writes && !auths);
    assert(tb16_tbt_nvm_stage_write(&h, 0, payload, 4) == 0); /* count field zero */
    assert(tb16_tbt_nvm_authenticate(&h, &status, &attempted) == kIOReturnNotReady);
    for (unsigned pos = 4; pos < sizeof(payload); pos += 64) {
        unsigned length = sizeof(payload) - pos;
        if (length > 64) length = 64;
        assert(tb16_tbt_nvm_stage_write(&h, pos, payload + pos, length) == 0);
    }
    assert(memcmp(payload, inactive, sizeof(payload)) == 0);
    assert(tb16_tbt_nvm_authenticate(&h, &status, &attempted) == 0);
    assert(status == 0 && attempted && auths == 1);
    assert(tb16_tbt_nvm_authenticate(&h, &status, &attempted) == kIOReturnNotReady && auths == 1);

    for (unsigned failure = 0; failure < 7; ++failure) {
        h = fresh();
        assert(tb16_tbt_nvm_stage_begin(&h, 0xb054, sizeof(payload)) == 0);
        missing = failure == 0; wrong_route = failure == 1; nonroot = failure == 2;
        busy = failure == 3; denied = failure == 4; stuck = failure == 5; bad_status = failure == 6;
        assert(tb16_tbt_nvm_stage_write(&h, 0, payload, 64) != 0);
        assert(tb16_tbt_nvm_authenticate(&h, &status, &attempted) == kIOReturnNotReady && !auths);
    }
    h = fresh();
    assert(tb16_tbt_nvm_stage_begin(&h, 0xb054, sizeof(payload)) == 0);
    assert(tb16_tbt_nvm_stage_write(&h, 4, payload, 64) == kIOReturnBadArgument && !writes);
    assert(tb16_tbt_nvm_stage_begin(&h, 0xb054, sizeof(payload)) != 0);
    for (unsigned outcome = 0; outcome < 6; ++outcome) {
        h = fresh();
        assert(tb16_tbt_nvm_stage_begin(&h, 0xb054, sizeof(payload)) == 0);
        for (unsigned pos = 0; pos < sizeof(payload); pos += 64)
            assert(tb16_tbt_nvm_stage_write(&h, pos, payload + pos, 64) == 0);
        auth_status = outcome == 0 ? 1 : 0;
        auth_disconnect = outcome == 1;
        auth_delay = outcome == 2 ? 3 : 0;
        auth_no_status = outcome == 3;
        auth_busy = outcome == 4;
        missing = outcome == 5;
        IOReturn result = tb16_tbt_nvm_authenticate(&h, &status, &attempted);
        if (outcome == 5) {
            assert(result == kIOReturnNoDevice && !attempted && !auths);
            continue;
        }
        assert(attempted && auths == 1);
        if (outcome == 0) assert(result == 0 && status == 1);
        else if (outcome == 1) assert(result == kIOReturnNoDevice && status == UINT32_MAX);
        else if (outcome == 3) assert(result == kIOReturnTimeout && status == UINT32_MAX);
        else assert(result == 0 && status == 0);
    }
    puts("Inactive staging byte order/counts, target binding, failures and one-shot auth checks passed");
    return 0;
}
