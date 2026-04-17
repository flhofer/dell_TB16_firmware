#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BIN_DIR="${REPO_ROOT}/bins"

cd "${BIN_DIR}"
shasum -a 256 \
  140124_10_10_4_2.BIN \
  Cable_16_00.bin \
  Cable_16_00_nosec.bin \
  Cable_26_06.bin \
  DELL_131025_10_11_A9.bin \
  Dock_BME_16_00.bin \
  Dock_BME_16_00_nosec.bin \
  Dock_BME_27_00.bin \
  HP_131025_10_11_AB.bin \
  mst_03_12_002.cab > SHA256SUMS

echo "Updated ${BIN_DIR}/SHA256SUMS"
