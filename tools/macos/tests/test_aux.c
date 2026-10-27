/* Exercise the actual C request construction without issuing IOKit requests. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/i2c/IOI2CInterface.h>
#include <assert.h>
#include <stdio.h>

static IOReturn fake_send(IOI2CConnectRef, IOOptionBits, IOI2CRequest *);
#define IOI2CSendRequest fake_send
#include "../aux.c"
#undef IOI2CSendRequest

static unsigned calls;
static unsigned mode;
static unsigned writing_expected;
static uint8_t *buffer_expected;

static IOReturn fake_send(IOI2CConnectRef connection, IOOptionBits options, IOI2CRequest *request)
{
    ++calls;
    assert(connection == (IOI2CConnectRef)(uintptr_t)1 && options == 0);
    assert(request->completion == NULL && request->commFlags == 0);
    if (writing_expected) {
        assert(request->sendTransactionType == kIOI2CDisplayPortNativeTransactionType);
        assert(request->replyTransactionType == kIOI2CNoTransactionType);
        assert(request->sendAddress == 0x4c0 && request->sendBytes == 16);
        assert(request->sendBuffer == (vm_address_t)buffer_expected);
        if (mode == 3)
            request->sendBytes = 15;
    } else {
        assert(request->replyTransactionType == kIOI2CDisplayPortNativeTransactionType);
        assert(request->sendTransactionType == kIOI2CNoTransactionType);
        assert(request->replyAddress == 0x4c0 && request->replyBytes == 16);
        assert(request->replyBuffer == (vm_address_t)buffer_expected);
        if (mode == 3)
            request->replyBytes = 15;
    }
    if (mode == 1)
        return kIOReturnNotPermitted;
    request->result = mode == 2 ? kIOReturnNotResponding : kIOReturnSuccess;
    return kIOReturnSuccess;
}

int main(void)
{
    uint8_t buffer[16] = {0};
    buffer_expected = buffer;
    IOI2CConnectRef connection = (IOI2CConnectRef)(uintptr_t)1;
    for (writing_expected = 0; writing_expected < 2; ++writing_expected) {
        const IOReturn expected[] = {kIOReturnSuccess, kIOReturnNotPermitted,
                                    kIOReturnNotResponding, kIOReturnUnderrun};
        for (mode = 0; mode < 4; ++mode)
            assert(tb16_transfer(connection, 0x4c0, buffer, 16, writing_expected) == expected[mode]);
    }
    assert(calls == 8);
    assert(tb16_transfer(NULL, 0x4c0, buffer, 16, 0) == kIOReturnBadArgument);
    assert(tb16_transfer(connection, 0x4c0, NULL, 16, 0) == kIOReturnBadArgument);
    assert(tb16_transfer(connection, 0x4c0, buffer, 0, 0) == kIOReturnBadArgument);
    assert(tb16_transfer(connection, 0x4c0, buffer, 17, 0) == kIOReturnBadArgument);
    assert(tb16_transfer(connection, 0xfffff, buffer, 2, 0) == kIOReturnBadArgument);
    assert(tb16_transfer(connection, 0x100000, buffer, 1, 0) == kIOReturnBadArgument);
    assert(calls == 8);
    puts("Native AUX request and error handling checks passed");
    return 0;
}
