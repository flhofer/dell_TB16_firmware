#!/bin/sh

# ID 0bda:8153 Realtek Semiconductor Corp. RTL8153 Gigabit Ethernet Adapter
echo "Reload RTL8153 Ethernet ECM module"
sudo -v
sudo modprobe --remove r8153_ecm && sudo modprobe r8153_ecm
