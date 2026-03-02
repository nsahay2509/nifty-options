


# python scripts/download_dhan_instruments.py

from pathlib import Path
from datetime import datetime
import requests


def download_dhan_instruments(
    url: str = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv",
    force: bool = False,
) -> Path:
    """
    Download Dhan detailed instruments CSV and save under data/ folder.

    Rules:
    - If file exists and was downloaded today (local date), skip download
    - If force=True, always re-download

    Returns:
        Path to saved CSV file
    """

    # project root (../ from scripts/)
    base_dir = Path(__file__).resolve().parents[1]

    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    out_file = data_dir / "dhan_instruments.csv"

    # ---- skip if already downloaded today ----
    if out_file.exists() and not force:
        mtime = datetime.fromtimestamp(out_file.stat().st_mtime).date()
        today = datetime.now().date()

        if mtime == today:
            print("[DhanInstruments] Already downloaded today — skipping")
            return out_file

    # ---- download ----
    print("[DhanInstruments] Downloading fresh instruments CSV...")

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    out_file.write_bytes(resp.content)

    print(f"[DhanInstruments] Saved → {out_file}")
    return out_file


# ---------------- ENTRYPOINT ----------------
def main():
    download_dhan_instruments()


if __name__ == "__main__":
    main()