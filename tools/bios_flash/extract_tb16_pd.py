#!/usr/bin/env python3
"""Extract the signed PD/EC PFS payload from the known Dell TB16 1.0.0 EXE.

Offline extraction only. Does not flash devices or verify RSA signatures.
"""
import hashlib
import json
from pathlib import Path
import struct
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'official/DellDockingStationFwUp_1.0.0_03192018_TB16.exe'
EXPECTED = 'ff9f2fa9b6a56ba000b57d1cbe29b0a5fbe3e563b3d0ac95c67198e7649db4e1'
NAMES = [
    'TB16_Package_Version_1.0.0',
    'TB16_TI_Port1_1.2.11',
    'TB16_TI_Port2_1.2.32',
    'TB16_Dock_EC_1.0.0.10',
    'TB16_TBT_Cable_PD_0.0.3.12',
    'TB16_Universal_Cable_PD_0.0.3.12',
    'TB16_PFS_Names',
]


def extract():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        raise ValueError('Source differs from the supported Dell release')
    data = zlib.decompress(raw[0x2A5810:])
    tag, version, size = struct.unpack_from('<8sII', data)
    if (tag, version, size) != (b'PFS.HDR.', 1, len(data) - 32):
        raise ValueError('Unexpected PFS header')
    footer_size, crc, tag = struct.unpack_from('<II8s', data, len(data) - 16)
    if tag != b'PFS.FTR.' or footer_size != size:
        raise ValueError('Unexpected PFS footer')
    if crc != (~zlib.crc32(data[16:-16]) & 0xFFFFFFFF):
        raise ValueError('PFS CRC mismatch')
    files = {'TB16_PD_EC_1.0.0.pfs': data}
    entries = []
    offset = 16
    for index, name in enumerate(NAMES):
        revision = struct.unpack_from('<I', data, offset + 16)[0]
        sizes = struct.unpack_from('<4I', data, offset + 40)
        if revision != 1 or sizes[1:] != (256, 0, 0):
            raise ValueError('Unexpected PFS entry layout')
        start = offset + 72
        end = start + sum(sizes)
        if end > len(data) - 16:
            raise ValueError('Entry outside PFS payload')
        payload = data[start:start + sizes[0]]
        # Preserve package metadata separately from the five firmware images.
        prefix = '' if 1 <= index <= 5 else 'TB16_PD_EC_metadata/'
        filename = prefix + name + '.bin'
        signature = 'TB16_PD_EC_metadata/' + name + '.sig'
        files[filename] = payload
        files[signature] = data[start + sizes[0]:end]
        entries.append(dict(
            file=filename, signature=signature,
            guid=str(uuid.UUID(bytes_le=data[offset:offset + 16])),
            version=list(struct.unpack_from('<4H', data, offset + 24)),
            pfs_data_offset=hex(start), size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest()))
        offset = end
    if offset != len(data) - 16:
        raise ValueError('Unparsed PFS entries')
    manifest = dict(source=str(SOURCE.relative_to(ROOT)), source_sha256=EXPECTED,
                    zlib_offset='0x2a5810', pfs_crc_verified=True,
                    signatures_cryptographically_verified=False, entries=entries)
    files['TB16_PD_EC_manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    # Refuse to overwrite any different artifact, including locally patched images.
    for name, content in files.items():
        path = ROOT / 'bins' / name
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f'Refusing to overwrite different file: {path}')
    for name, content in files.items():
        path = ROOT / 'bins' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(f'Extracted five firmware images, intact PFS, signatures and metadata to {ROOT / "bins"}')


if __name__ == '__main__':
    extract()
