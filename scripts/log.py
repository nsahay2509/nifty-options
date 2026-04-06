"""Central logging setup for the rebuilt NIFTY system."""

from __future__ import annotations

import logging
from pathlib import Path


LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
DEFAULT_LEVEL = logging.INFO


def configure_logging(
    *,
    level: int = DEFAULT_LEVEL,
    log_file: str | Path | None = None,
) -> None:
    """Configure the root logger once for all execution pathways."""
    root = logging.getLogger()
    if root.handlers:
        return

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path))

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=handlers,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for a specific execution pathway."""
    return logging.getLogger(name)
