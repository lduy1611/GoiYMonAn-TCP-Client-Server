"""Checksummed, append-only local snapshots for Admin recipe recovery."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

ROOT = Path(__file__).resolve().parents[2] / "statics" / "runtime" / "recipe-snapshots"
_SNAPSHOT_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class SnapshotError(ValueError):
    pass


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create(kind: str, recipe_id: int, recipe: dict, image: dict | None, *, revision_id: int | None = None,
           root: Path | None = None) -> dict:
    """Persist the exact editable state before a save; exclusive create prevents overwrite."""
    if kind not in {"legacy", "v2"} or type(recipe_id) is not int or recipe_id <= 0:
        raise SnapshotError("invalid recipe snapshot identity")
    if kind == "v2" and (type(revision_id) is not int or revision_id <= 0):
        raise SnapshotError("v2 snapshot requires a revision ID")
    lines = recipe.get("ingredients")
    required = ("title", "description", "instructions", "minutes", "edit_version")
    if any(key not in recipe for key in required) or not isinstance(lines, list) or not lines:
        raise SnapshotError("recipe detail is incomplete; snapshot was not written")
    if not isinstance(recipe["edit_version"], str) or not re.fullmatch(r"[0-9a-f]{64}", recipe["edit_version"]):
        raise SnapshotError("recipe edit version is invalid")
    fields = {key: recipe[key] for key in required}
    fields["ingredients"] = []
    for line in lines:
        if kind == "legacy":
            fields["ingredients"].append({"ingredient_id": line["id"], "quantity": line["quantity"],
                                           "is_required": line["is_required"]})
        else:
            fields["ingredients"].append({"ingredient_id": line["ingredient_id"],
                "quantity_raw": line.get("quantity_raw"), "requirement": line["requirement"]})
    if kind == "legacy":
        fields["is_visible"] = recipe.get("is_visible", True)
    else:
        fields["role"] = recipe.get("role") or "main"
        fields["revision_status"] = recipe.get("status")
    snapshot = {"format_version": 1, "snapshot_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(), "kind": kind,
        "recipe_id": recipe_id, "revision_id": revision_id, "edit_version": recipe["edit_version"],
        "fields": fields, "image": image}
    checksum = hashlib.sha256(_canonical(snapshot)).hexdigest()
    envelope = {"snapshot": snapshot, "checksum_sha256": checksum}
    directory = Path(root) if root is not None else ROOT
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{snapshot['snapshot_id']}.json"
    encoded = _canonical(envelope)
    try:
        with target.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            import os
            os.fsync(stream.fileno())
    except FileExistsError:
        raise SnapshotError("snapshot ID collision; retry snapshot creation") from None
    return {"snapshot_id": snapshot["snapshot_id"], "checksum_sha256": checksum,
            "recipe_id": recipe_id, "kind": kind, "revision_id": revision_id}


def load(snapshot_id: str, *, root: Path | None = None) -> dict:
    if not isinstance(snapshot_id, str) or not _SNAPSHOT_ID.fullmatch(snapshot_id):
        raise SnapshotError("invalid snapshot ID")
    directory = Path(root) if root is not None else ROOT
    target = directory / f"{snapshot_id}.json"
    try:
        envelope = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SnapshotError("snapshot is missing or unreadable") from None
    snapshot = envelope.get("snapshot") if isinstance(envelope, dict) else None
    checksum = envelope.get("checksum_sha256") if isinstance(envelope, dict) else None
    if (not isinstance(snapshot, dict) or snapshot.get("snapshot_id") != snapshot_id
            or not isinstance(checksum, str)
            or not hashlib.sha256(_canonical(snapshot)).hexdigest() == checksum):
        raise SnapshotError("snapshot checksum or identity is invalid")
    return snapshot
