"""Credential loading for broker adapters."""

from __future__ import annotations

from pathlib import Path

from scripts.config import APP_CONFIG

from .types import BrokerCredentials


def load_dotenv_file(path: str | Path) -> dict[str, str]:
    """Parse a simple .env file without requiring external dependencies."""
    env_path = Path(path)
    if not env_path.exists():
        raise FileNotFoundError(f"Missing env file: {env_path}")

    values: dict[str, str] = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')

    return values


def load_dhan_credentials(path: str | Path | None = None) -> BrokerCredentials:
    env_values = load_dotenv_file(path or APP_CONFIG.broker.env_file)

    client_id = env_values.get("DHAN_CLIENT_ID", "")
    access_token = env_values.get("DHAN_ACCESS_TOKEN", "")
    if not client_id or not access_token:
        raise ValueError("DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN must both be present in the env file")

    return BrokerCredentials(
        client_id=client_id,
        access_token=access_token,
    )
