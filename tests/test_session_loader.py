from __future__ import annotations

import json
from pathlib import Path

from scripts.session_loader import load_spot_candles_from_jsonl


def test_load_spot_candles_from_jsonl_parses_archive_format(tmp_path: Path) -> None:
    target = tmp_path / "2026-04-02.jsonl"
    target.write_text(
        "\n".join(
            [
                json.dumps({"ts": "2026-04-02 09:15:00", "open": 22227.4, "high": 22227.4, "low": 22213.4, "close": 22214.55, "volume": 0}),
                json.dumps({"ts": "2026-04-02 09:16:00", "open": 22258.3, "high": 22262.1, "low": 22256.5, "close": 22256.5, "volume": 0}),
            ]
        ),
        encoding="utf-8",
    )

    candles = load_spot_candles_from_jsonl(target)

    assert len(candles) == 2
    assert candles[0].instrument.name == "NIFTY_50_INDEX"
    assert candles[0].start.isoformat() == "2026-04-02T09:15:00+05:30"
    assert candles[1].close == 22256.5
