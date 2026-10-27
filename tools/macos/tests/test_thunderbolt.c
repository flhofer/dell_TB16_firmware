/* Test the actual native request against the six-scalar ABI, with no hardware. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <assert.h>
#include <stdio.h>

static kern_return_t fake_scalar(mach_port_t, uint32_t, const uint64_t *, uint32_t,
                                  uint64_t *, uint32_t *);
#define IOConnectCallScalarMethod fake_scalar
#include "../thunderbolt.c"
#undef IOConnectCallScalarMethod

static unsigned calls;
static IOReturn status;

static kern_return_t fake_scalar(mach_port_t connection, uint32_t selector,
                                  const uint64_t *input, uint32_t input_count,
                                  uint64_t *output, uint32_t *output_count)
{
    ++calls;
    assert(connection == 42 && selector == 0);
    assert(input_count == 6 && output == NULL && output_count == NULL);
    assert(input[0] == 0x301 && input[1] == 0 && input[2] == 2);
    assert(input[3] == 0 && input[5] == 5);
    uint32_t *buffer = (uint32_t *)(uintptr_t)input[4];
    for (unsigned i = 0; i < input[5]; ++i)
        assert(buffer[i] == 0);
    buffer[0] = 0x86807815; /* big-endian wire bytes for 8086:1578 */
    buffer[2] = 0x01030000; /* big-endian wire bytes for route 0x301 */
    return status;
}

int main(void)
{
    tb16_tbt_handle handle = {.connection = 42, .route = 0x301};
    uint32_t data[5] = {1, 2, 3, 4, 5};
    assert(tb16_tbt_read(&handle, 0, 2, 0, data, 5) == kIOReturnSuccess);
    assert(data[0] == 0x15788086 && data[2] == 0x301);
    status = kIOReturnNotPrivileged;
    assert(tb16_tbt_read(&handle, 0, 2, 0, data, 5) == kIOReturnNotPrivileged);
    assert(calls == 2);
    assert(tb16_tbt_read(NULL, 0, 2, 0, data, 5) == kIOReturnBadArgument);
    assert(tb16_tbt_read(&handle, 0, 2, 0, NULL, 5) == kIOReturnBadArgument);
    assert(tb16_tbt_read(&handle, 0, 2, 0, data, 0) == kIOReturnBadArgument);
    assert(tb16_tbt_read(&handle, 0, 2, 0, data, 17) == kIOReturnBadArgument);
    assert(tb16_tbt_read(&handle, 1, 2, 0, data, 5) == kIOReturnBadArgument);
    assert(tb16_tbt_read(&handle, 64, 1, 0, data, 5) == kIOReturnBadArgument);
    assert(tb16_tbt_read(&handle, 0, 0, 0, data, 5) == kIOReturnBadArgument);
    assert(tb16_tbt_read(&handle, 0, 3, 0, data, 5) == kIOReturnBadArgument);
    assert(tb16_tbt_read(&handle, 0, 2, 0x1fff, data, 2) == kIOReturnBadArgument);
    handle.route = 0;
    assert(tb16_tbt_read(&handle, 0, 2, 0, data, 5) == kIOReturnBadArgument);
    assert(calls == 2);
    puts("Thunderbolt read ABI, bounds and error checks passed");
    return 0;
}
