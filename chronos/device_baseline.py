"""Device Manager baseline snapshot and comparison via WMI."""
import uuid
from typing import List

import wmi

PNP_CLASSES = ["Net", "Bluetooth"]


def list_devices(pnp_classes: List[str] = None) -> List[dict]:
    """Return currently present devices for the given PNP classes (default Net + Bluetooth)."""
    pnp_classes = pnp_classes or PNP_CLASSES
    conn = wmi.WMI()
    devices = []
    for cls in pnp_classes:
        for item in conn.Win32_PnPEntity(PNPClass=cls):
            devices.append({
                "device_id": item.DeviceID,
                "name": item.Name or "",
                "pnp_class": cls,
                "status": item.Status or "",
                "error_code": item.ConfigManagerErrorCode or 0,
                "present": True,
            })
    return devices


def take_snapshot(tracked_device_ids: List[str]) -> List[dict]:
    """Snapshot only the devices the user chose to track. Devices that are missing
    (unplugged / failed to re-enumerate) are reported with present=False."""
    current = {d["device_id"]: d for d in list_devices()}
    snapshot = []
    for device_id in tracked_device_ids:
        if device_id in current:
            snapshot.append(current[device_id])
        else:
            snapshot.append({
                "device_id": device_id,
                "name": "(missing)",
                "pnp_class": "",
                "status": "",
                "error_code": -1,
                "present": False,
            })
    return snapshot


def new_batch_id() -> str:
    return uuid.uuid4().hex


def compare(baseline: List[dict], current: List[dict]) -> List[dict]:
    """Compare two snapshots (by device_id) and return a list of diffs:
    each item has device_id, name, and the fields that changed."""
    current_by_id = {d["device_id"]: d for d in current}
    diffs = []
    for base_dev in baseline:
        device_id = base_dev["device_id"]
        cur_dev = current_by_id.get(device_id)
        if cur_dev is None:
            diffs.append({
                "device_id": device_id,
                "name": base_dev["name"],
                "change": "device not found during comparison",
            })
            continue
        changed_fields = []
        for field in ("present", "status", "error_code"):
            if base_dev.get(field) != cur_dev.get(field):
                changed_fields.append(f"{field}: {base_dev.get(field)!r} -> {cur_dev.get(field)!r}")
        if changed_fields:
            diffs.append({
                "device_id": device_id,
                "name": base_dev["name"],
                "change": "; ".join(changed_fields),
            })
    return diffs
