#!/bin/sh

# 0b:00.0 USB controller [0c03]: ASMedia Technology Inc. ASM1042A USB 3.0 Host Controller [1b21:1142]
SERIAL=$(lspci -Dd "1b21:1142" | awk '{ print $1 }')
DRIVER="/sys/bus/pci/drivers/xhci_hcd"

echo "Unbinding" $( echo -n $SERIAL | sudo tee $DRIVER/unbind ) "..."
sleep 4
echo "Rebinding" $( echo -n $SERIAL | sudo tee $DRIVER/bind ) "..."
sleep 4
echo "Setting power-savig mode 'd3cold' to disallowed for USB controller.."
echo "d3cold_allowed="$( echo 0 | sudo tee $DRIVER/$SERIAL/d3cold_allowed )

