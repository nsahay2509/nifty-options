import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"


def resolve_env_file() -> Path | None:
    explicit = os.getenv("DHAN_ENV_FILE")
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.exists() else None

    project_env = BASE_DIR / ".env"
    if project_env.exists():
        return project_env

    return None


def load_runtime_env(*, override: bool = True) -> Path | None:
    env_file = resolve_env_file()
    if env_file:
        load_dotenv(env_file, override=override)
        return env_file

    load_dotenv(override=override)
    return None
