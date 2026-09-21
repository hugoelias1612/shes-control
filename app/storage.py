"""UTF-8 JSON snapshots, replaced atomically only after successful serialization."""
import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path


def json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Tipo no serializable: {type(value).__name__}")


def write_json(path, data):
    path = Path(path)
    payload = json.dumps(data, ensure_ascii=False, indent=2,
                         allow_nan=False, default=json_default)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return path
