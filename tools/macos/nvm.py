"""Pinned Alpine Ridge images and an update workflow; no native import at load time."""
import hashlib

from native import AuxError


IMAGES = {
    "3e1b0b7f349854eee359dd653d6aac2360a4ff12bc74eeae1b6d9a2fd6cc2069":
        ("cable", 0xb051, "26.06", "Cable_26_06.bin"),
    "c7e6e20de545b9fdeba64e830abcae5e75f21ac064ebcdd1d2c2b388fd3fde64":
        ("dock", 0xb054, "27.00", "Dock_BME_27_00.bin"),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_nvm_image(image, model):
    from thunderbolt import parse_nvm_header
    identity = IMAGES.get(digest(image))
    if identity is None:
        raise AuxError("Only the pinned Cable_26_06.bin and Dock_BME_27_00.bin images are supported")
    role, expected_model, version, filename = identity
    if model != expected_model:
        raise AuxError(f"{filename} requires the {role} controller (model {expected_model:#06x})")
    offset = int.from_bytes(image[:4], "little") & 0xffffff
    if offset != 0x4000 or offset % 0x1000 or not 0x8000 <= len(image) <= 0x100000:
        raise AuxError("Unsupported Alpine Ridge image/FARB layout")
    payload = image[offset:]
    header = parse_nvm_header(payload[:80])
    digital_size = int.from_bytes(payload[:2], "little")
    if (not 80 <= digital_size < len(payload) or len(payload) % 4 or
            header["nvm_version"] != version or len(payload) > header["active_bank_size"]):
        raise AuxError("Invalid digital section size, version or bank geometry")
    return payload, {"target": role, "model_id": f"0x{model:04x}", "image": filename,
                     "image_sha256": digest(image), "target_version": version,
                     "farb_bytes_skipped": offset, "staging_bytes": len(payload),
                     "staging_sha256": digest(payload), "packets": (len(payload) + 63) // 64}


def plan_header(image, active, model):
    payload, info = validate_nvm_image(image, model)
    if active["nvm_version"] != "16.00":
        raise AuxError("This initial update path supports an installed NVM version of 16.00 only")
    if len(payload) > active["active_bank_size"]:
        raise AuxError("Image exceeds the target active-bank geometry")
    return {**info, "current_version": active["nvm_version"],
            "active_bank_bytes": active["active_bank_size"],
            "css_header_write": False, "firmware_written": False,
            "activation_verified": False,
            "inactive_readback_available": False,
            "backup_scope": "active bank only; recovery is not implemented"}


def plan_update(image, backup, model):
    from thunderbolt import parse_nvm_header
    active = parse_nvm_header(backup[:80])
    if len(backup) != active["active_bank_size"]:
        raise AuxError("Backup must contain the entire active bank, without a FARB prefix")
    return {**plan_header(image, active, model), "backup_sha256": digest(backup)}


def update(reader, image, model, backup_path, authenticate=False, progress=lambda line: None):
    """One lock/session: backup twice, stage once, check active bank, optional auth.

    The mailbox reads only the ACTIVE bank. Staging acknowledgements cannot be
    advertised as inactive-bank readback. Only device authentication can check
    the staged image; activation still requires a subsequent version check.
    """
    payload, _ = validate_nvm_image(image, model)  # Reject image/role before any device access.
    with reader.mailbox():
        info, backup = reader._backup_nvm(backup_path, progress)
        plan = plan_update(image, backup, model)
        progress("Backup verified; beginning inactive-bank staging. Keep dock power connected.")
        reader.stage_begin(model, len(payload))
        for address in range(0, len(payload), 64):
            reader.stage_write(address, payload[address:address + 64])
            if address % 0x4000 == 0 or address + 64 >= len(payload):
                progress(f"Inactive-bank staging: {min(address + 64, len(payload)) * 100 // len(payload)}%")
        progress("Staging acknowledged; checking that the active bank is unchanged.")
        if reader._active_bank(len(backup)) != backup:
            raise AuxError("Active bank changed during staging; authentication was NOT requested. "
                           "Keep dock powered and preserve the backup")
        result = {**plan, "firmware_written": True, "backup": info["output"],
                  "active_bank_unchanged": True, "staged_readback_verified": False,
                  "state": "staged_unverified", "authentication_attempted": False}
        if authenticate:
            progress("Requesting device authentication once; disconnects/timeouts leave the outcome unknown.")
            result.update(reader.authenticate())
        return result
