import json
import os
import tempfile
from pathlib import Path
from typing import Any


def safe_load_json(path: Path, default: Any):
    if not path.exists():
        return default

    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return default


def atomic_write_json(path: Path, payload: Any, *, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.stem}_",
        suffix=path.suffix,
        dir=path.parent,
    )

    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=indent)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
