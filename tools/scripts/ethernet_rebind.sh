#!/bin/sh

# 0b:00.0 USB controller [0c03]: ASMedia Technology Inc. ASM1042A USB 3.0 Host Controller [1b21:1142]
PCIBUS=$(lspci -Dd "1b21:1142" | awk '{ print $1 }')
# ID 0bda:8153 Realtek Semiconductor Corp. RTL8153 Gigabit Ethernet Adapter => look for USB on PCI above
DRIVER="/sys/bus/usb/drivers/r8152"
# find loaded usb driver for controller attached to our dock's USB controller
SERIAL=$(ls -la $DRIVER | grep "${PCIBUS}" | awk '{ print $9 }')

echo "Unbinding Realtek Ethernet controller at" $( echo -n $SERIAL | sudo tee $DRIVER/unbind ) "..."
sleep 4
echo "Rebinding Realtek Ethernet controller at" $( echo -n $SERIAL | sudo tee $DRIVER/bind ) "..."

