#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TOOLS_DIR="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${TOOLS_DIR}/logs"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="${LOG_DIR}/tb16_diag_${TS}.log"

mkdir -p "${LOG_DIR}"

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

section() {
  title="$1"
  shift
  {
    echo
    echo "===== ${title} ====="
  } >>"${OUT}"
  if "$@" >>"${OUT}" 2>&1; then
    :
  else
    rc=$?
    echo "[command exited with ${rc}]" >>"${OUT}"
  fi
}

write_header() {
  {
    echo "TB16 diagnostics"
    echo "Timestamp: $(date -Iseconds)"
    echo "Hostname: $(hostname 2>/dev/null || echo unknown)"
    echo "Kernel: $(uname -srvmo 2>/dev/null || uname -a)"
    echo "Collector: ${0}"
  } >"${OUT}"
}

write_header

if have_cmd fwupdmgr; then
  section "fwupdmgr get-devices" fwupdmgr get-devices
  section "fwupdmgr get-history" fwupdmgr get-history
else
  {
    echo
    echo "===== fwupdmgr ====="
    echo "fwupdmgr not found"
  } >>"${OUT}"
fi

if have_cmd lspci; then
  section "lspci -nn" lspci -nn
  section "lspci -D -d 1b21:1142" lspci -D -d 1b21:1142
else
  {
    echo
    echo "===== lspci ====="
    echo "lspci not found"
  } >>"${OUT}"
fi

if have_cmd lsusb; then
  section "lsusb" lsusb
else
  {
    echo
    echo "===== lsusb ====="
    echo "lsusb not found"
  } >>"${OUT}"
fi

if have_cmd ip; then
  section "ip -br link" ip -br link
else
  {
    echo
    echo "===== ip ====="
    echo "ip command not found"
  } >>"${OUT}"
fi

if have_cmd dmesg; then
  # Try non-root first. If restricted and sudo is available non-interactively, retry with sudo -n.
  if dmesg >/dev/null 2>&1; then
    section "dmesg (filtered)" sh -c "dmesg | grep -Ei 'thunderbolt|tb16|wd15|tb18|rtl8153|r8152|asmedia|asm1042|xhci|mst|synaptics'"
  elif have_cmd sudo && sudo -n true >/dev/null 2>&1; then
    section "sudo dmesg (filtered)" sh -c "sudo -n dmesg | grep -Ei 'thunderbolt|tb16|wd15|tb18|rtl8153|r8152|asmedia|asm1042|xhci|mst|synaptics'"
  else
    {
      echo
      echo "===== dmesg ====="
      echo "dmesg access denied (try running script with sudo)."
    } >>"${OUT}"
  fi
else
  {
    echo
    echo "===== dmesg ====="
    echo "dmesg command not found"
  } >>"${OUT}"
fi

echo
echo "Diagnostics written to: ${OUT}"
