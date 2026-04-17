#!/bin/sh
set -eu

# Recover RTL8153 Ethernet behind TB16 dock by escalating actions:
# 1) Reload ethernet module
# 2) Rebind ethernet USB function
# 3) Rebind ASMedia USB controller
#
# Target selection:
# - Auto-detect ASMedia ASM1042A controller (1b21:1142), first match by default
# - Find r8152 net device whose sysfs path is attached to that ASMedia PCI path
#
# Optional environment overrides:
#   ASM_BDF=0000:0b:00.0   # specific ASMedia PCI BDF
#   NET_IF=enx...          # force interface name

ASM_VID_DID="${ASM_VID_DID:-1b21:1142}"
ASM_BDF="${ASM_BDF:-}"
NET_IF="${NET_IF:-}"
ETH_USB_DRIVER="r8152"
USB_PCI_DRIVER="xhci_hcd"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

as_root_sh() {
  if [ "$(id -u)" -eq 0 ]; then
    sh -c "$1"
  else
    sudo sh -c "$1"
  fi
}

get_first_asm_bdf() {
  lspci -D -d "$ASM_VID_DID" 2>/dev/null | awk 'NR==1 { print $1 }'
}

iface_driver() {
  ifname="$1"
  basename "$(readlink -f "/sys/class/net/$ifname/device/driver" 2>/dev/null)" 2>/dev/null || true
}

iface_on_asm_path() {
  ifname="$1"
  bdf="$2"
  devpath="$(readlink -f "/sys/class/net/$ifname/device" 2>/dev/null || true)"
  case "$devpath" in
    *"$bdf"*) return 0 ;;
    *) return 1 ;;
  esac
}

find_iface_for_asm() {
  bdf="$1"
  for d in /sys/class/net/*; do
    ifname="${d##*/}"
    [ "$ifname" = "lo" ] && continue
    [ "$(iface_driver "$ifname")" = "$ETH_USB_DRIVER" ] || continue
    iface_on_asm_path "$ifname" "$bdf" || continue
    echo "$ifname"
    return 0
  done
  return 1
}

find_usb_rebind_id_for_asm() {
  bdf="$1"
  for n in /sys/bus/usb/drivers/"$ETH_USB_DRIVER"/*:*; do
    [ -e "$n" ] || continue
    base="$(basename "$n")"
    [ "$base" = "bind" ] && continue
    [ "$base" = "unbind" ] && continue
    [ "$base" = "new_id" ] && continue
    [ "$base" = "remove_id" ] && continue
    target="$(readlink -f "$n" 2>/dev/null || true)"
    case "$target" in
      *"$bdf"*)
        echo "$base"
        return 0
        ;;
    esac
  done
  return 1
}

iface_healthy() {
  ifname="$1"
  [ -n "$ifname" ] || return 1
  [ -d "/sys/class/net/$ifname" ] || return 1
  [ "$(iface_driver "$ifname")" = "$ETH_USB_DRIVER" ] || return 1
  iface_on_asm_path "$ifname" "$ASM_BDF" || return 1
  return 0
}

print_status() {
  ifname="$1"
  if [ -n "$ifname" ] && [ -d "/sys/class/net/$ifname" ]; then
    operstate="$(cat "/sys/class/net/$ifname/operstate" 2>/dev/null || echo unknown)"
    carrier="$(cat "/sys/class/net/$ifname/carrier" 2>/dev/null || echo unknown)"
    echo "Interface: $ifname (operstate=$operstate, carrier=$carrier)"
  else
    echo "Interface: not detected"
  fi
}

reload_eth_module() {
  echo "[1/3] Reloading ethernet module"
  # Try both names; distros vary between r8153_ecm and r8152 usage.
  as_root modprobe -r r8153_ecm 2>/dev/null || true
  as_root modprobe -r r8152 2>/dev/null || true
  as_root modprobe r8152 2>/dev/null || true
  as_root modprobe r8153_ecm 2>/dev/null || true
  sleep 2
}

rebind_eth_usb() {
  echo "[2/3] Rebinding ethernet USB function"
  id="$(find_usb_rebind_id_for_asm "$ASM_BDF" || true)"
  if [ -z "$id" ]; then
    echo "No $ETH_USB_DRIVER USB function found under ASMedia path $ASM_BDF"
    return 1
  fi
  as_root_sh "echo '$id' > '/sys/bus/usb/drivers/$ETH_USB_DRIVER/unbind'"
  sleep 2
  as_root_sh "echo '$id' > '/sys/bus/usb/drivers/$ETH_USB_DRIVER/bind'"
  sleep 2
  return 0
}

rebind_usb_controller() {
  echo "[3/3] Rebinding ASMedia USB controller ($ASM_BDF)"
  as_root_sh "echo '$ASM_BDF' > '/sys/bus/pci/drivers/$USB_PCI_DRIVER/unbind'"
  sleep 4
  as_root_sh "echo '$ASM_BDF' > '/sys/bus/pci/drivers/$USB_PCI_DRIVER/bind'"
  sleep 4

  # Optional power-management tweak used by existing script.
  d3="/sys/bus/pci/drivers/$USB_PCI_DRIVER/$ASM_BDF/d3cold_allowed"
  if [ -f "$d3" ]; then
    as_root_sh "echo 0 > '$d3'"
  fi
}

check_or_find_iface() {
  if [ -n "$NET_IF" ] && iface_healthy "$NET_IF"; then
    echo "$NET_IF"
    return 0
  fi
  find_iface_for_asm "$ASM_BDF" || return 1
}

need_cmd lspci
need_cmd modprobe

if [ -z "$ASM_BDF" ]; then
  ASM_BDF="$(get_first_asm_bdf)"
fi

if [ -z "$ASM_BDF" ]; then
  echo "No ASMedia controller ($ASM_VID_DID) detected via lspci." >&2
  exit 1
fi

echo "Using ASMedia controller: $ASM_BDF"
[ -n "$NET_IF" ] && echo "Requested interface override: $NET_IF"

iface="$(check_or_find_iface || true)"
if [ -n "$iface" ]; then
  echo "Detected dock ethernet interface: $iface"
  print_status "$iface"
else
  echo "No healthy dock ethernet interface detected yet (continuing recovery)."
fi

reload_eth_module
iface="$(check_or_find_iface || true)"
if [ -n "$iface" ]; then
  echo "Recovered after module reload."
  print_status "$iface"
  exit 0
fi

rebind_eth_usb || true
iface="$(check_or_find_iface || true)"
if [ -n "$iface" ]; then
  echo "Recovered after ethernet USB rebind."
  print_status "$iface"
  exit 0
fi

rebind_usb_controller
iface="$(check_or_find_iface || true)"
if [ -n "$iface" ]; then
  echo "Recovered after USB controller rebind."
  print_status "$iface"
  exit 0
fi

echo "Recovery failed: no healthy dock ethernet interface detected for ASMedia path $ASM_BDF." >&2
echo "Tip: try with explicit override, e.g. NET_IF=enx... ASM_BDF=0000:0b:00.0 $0" >&2
exit 2
