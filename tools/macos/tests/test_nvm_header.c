/* Emulate only the active-flash read mailbox; reject every other write. */
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
#define IOConnectCallScalarMethod fake_scalar
#define geteuid fake_uid
#define clock_gettime fake_clock
#include "../thunderbolt.c"
#undef IOConnectCallScalarMethod
#undef geteuid
#undef clock_gettime

static uint8_t flash[80];
static unsigned calls, writes, address, clock_calls;
static int nonroot, busy, stuck, denied, status_error, bad_cap;

static uid_t fake_uid(void) { return nonroot ? 501 : 0; }
static int fake_clock(clockid_t clock, struct timespec *value)
{
    assert(clock == CLOCK_MONOTONIC);
    value->tv_sec = 6 * clock_calls++;
    value->tv_nsec = 0;
    return 0;
}

static kern_return_t fake_scalar(mach_port_t connection, uint32_t selector,
                                  const uint64_t *in, uint32_t in_count,
                                  uint64_t *out, uint32_t *out_count)
{
    ++calls;
    assert(connection == 42 && in_count == 6 && in[0] == 0x301 && in[2] == 1);
    assert(out == NULL && out_count == NULL);
    uint32_t *data = (uint32_t *)(uintptr_t)in[4];
    if (selector == 1) {
        assert(in[1] == 5 && in[3] == 0x4f && in[5] == 1);
        uint32_t command = OSSwapBigToHostInt32(*data);
        assert(command == 0x20000001 || command == 0x24000041);
        address = command == 0x20000001 ? 0 : 64;
        ++writes;
        return denied ? kIOReturnNotPrivileged : kIOReturnSuccess;
    }
    assert(selector == 0);
    if (in[3] == 2) {
        assert(in[5] == 1);
        *data = OSSwapHostToBigInt32(in[1] == 5 ? 2 : 1);
    } else {
        assert(in[1] == 5);
        if (in[3] == 0x3e) {
            *data = OSSwapHostToBigInt32(bad_cap ? 0 : 0x13010552);
        } else if (in[3] == 0x4f) {
            *data = OSSwapHostToBigInt32(busy || (stuck && writes) ? 1 : 0);
        } else if (in[3] == 0x50) {
            *data = OSSwapHostToBigInt32(status_error ? 2 : 0);
        } else {
            assert(in[3] == 0x3f && in[5] == (address == 0 ? 16 : 4));
            for (unsigned i = 0; i < in[5]; ++i) {
                uint32_t value;
                memcpy(&value, flash + address + i * 4, 4);
                data[i] = OSSwapHostToBigInt32(OSSwapLittleToHostInt32(value));
            }
        }
    }
    return kIOReturnSuccess;
}

int main(void)
{
    tb16_tbt_handle handle = {.connection = 42, .route = 0x301};
    uint8_t output[80];
    for (unsigned i = 0; i < 80; ++i)
        flash[i] = (uint8_t)i;
    flash[5] = 0x78;
    flash[6] = 0x15;
    flash[0x45] = 3;
    assert(tb16_tbt_nvm_header(&handle, output) == kIOReturnSuccess);
    assert(memcmp(output, flash, 80) == 0 && writes == 2);
    assert(tb16_tbt_nvm_read(&handle, 0, output, 64) == kIOReturnSuccess);
    assert(memcmp(output, flash, 64) == 0 && writes == 3);
    nonroot = 1;
    unsigned previous = calls;
    assert(tb16_tbt_nvm_header(&handle, output) == kIOReturnNotPrivileged && calls == previous);
    nonroot = 0;
    writes = 0;
    busy = 1;
    assert(tb16_tbt_nvm_header(&handle, output) == kIOReturnBusy && writes == 0);
    busy = 0;
    bad_cap = 1;
    assert(tb16_tbt_nvm_header(&handle, output) == kIOReturnUnsupported && writes == 0);
    bad_cap = 0;
    denied = 1;
    assert(tb16_tbt_nvm_header(&handle, output) == kIOReturnNotPrivileged && writes == 1);
    denied = 0;
    writes = 0;
    status_error = 1;
    assert(tb16_tbt_nvm_header(&handle, output) == kIOReturnNotPermitted && writes == 1);
    status_error = 0;
    writes = 0;
    clock_calls = 0;
    stuck = 1;
    assert(tb16_tbt_nvm_header(&handle, output) == kIOReturnTimeout && writes == 1);
    assert(tb16_tbt_nvm_header(NULL, output) == kIOReturnBadArgument);
    assert(tb16_tbt_nvm_read(&handle, 1, output, 4) == kIOReturnBadArgument);
    assert(tb16_tbt_nvm_read(&handle, 0, output, 65) == kIOReturnBadArgument);
    assert(tb16_tbt_nvm_read(&handle, handle.active_size, output, 4) == kIOReturnBadArgument);
    puts("NVM header read command, byte order, privilege, busy, status and timeout checks passed");
    return 0;
}
