


import os
import time
from typing import Dict, List, Optional

import requests

from scripts.runtime_config import load_runtime_env


# ---------- dynamic dhan headers ----------
def get_dhan_headers() -> dict:
    """
    Always reload Dhan credentials from .env.
    Prevents stale access-token after daily refresh.
    """
    load_runtime_env(override=True)

    token = os.getenv("DHAN_ACCESS_TOKEN")
    client_id = os.getenv("DHAN_CLIENT_ID")

    if not token or not client_id:
        raise RuntimeError("Missing Dhan credentials")

    return {
        "access-token": token,
        "client-id": client_id,
    }


# ---------- Marketfeed LTP ----------
DHAN_LTP_URL = "https://api.dhan.co/v2/marketfeed/ltp"


def fetch_ltp_map(
    security_ids: List[int],
    *,
    exchange_segment: str = "NSE_FNO",
    timeout: int = 10,
) -> Dict[int, Optional[float]]:
    """
    Dhan LTP (batch):
      POST https://api.dhan.co/v2/marketfeed/ltp
      Body: { "NSE_FNO": [54966, ...] }

    Response:
      { "data": { "NSE_FNO": { "54966": { "last_price": 134.3 } } }, "status": "success" }

    Returns:
      {54966: 134.3, ...}
    """
    if not security_ids:
        return {}

    headers = get_dhan_headers()
    headers["Accept"] = "application/json"
    headers["Content-Type"] = "application/json"

    out: Dict[int, Optional[float]] = {}

    # Dhan supports up to 1000 instruments per request
    CHUNK = 1000

    for i in range(0, len(security_ids), CHUNK):
        chunk = [int(x) for x in security_ids[i : i + CHUNK]]
        payload = {exchange_segment: chunk}

        try:
            r = requests.post(
                DHAN_LTP_URL, headers=headers, json=payload, timeout=timeout
            )
        except Exception:
            for sid in chunk:
                out[sid] = None
            continue

        if r.status_code != 200:
            for sid in chunk:
                out[sid] = None
            continue

        j = r.json() or {}
        seg = ((j.get("data") or {}).get(exchange_segment) or {})

        for sid in chunk:
            rec = seg.get(str(sid))
            if not rec:
                out[sid] = None
                continue

            lp = rec.get("last_price")
            out[sid] = float(lp) if lp is not None else None

    return out


def ensure_complete_ltp_map(
    security_ids: List[int],
    *,
    ltp_map: Optional[Dict[int, Optional[float]]] = None,
    exchange_segment: str = "NSE_FNO",
    timeout: int = 10,
    retry_delay_sec: float = 0.3,
    fetcher=None,
    sleep_fn=None,
    logger=None,
):
    """
    Ensure we have a complete LTP map for the requested security ids.

    Returns:
      (ltp_map, is_complete)
    """
    security_ids = [int(sid) for sid in security_ids]
    merged = dict(ltp_map or {})

    if not security_ids:
        return merged, True

    fetch = fetcher or (
        lambda ids: fetch_ltp_map(
            ids,
            exchange_segment=exchange_segment,
            timeout=timeout,
        )
    )
    sleeper = sleep_fn or time.sleep

    missing_ids = [sid for sid in security_ids if merged.get(sid) is None]

    if missing_ids:
        if logger:
            logger.warning(f"LTP_MAP_INCOMPLETE -> fetching fallback for {missing_ids}")
        merged.update(fetch(missing_ids))
        missing_ids = [sid for sid in security_ids if merged.get(sid) is None]

    if missing_ids:
        if logger:
            logger.warning(f"LTP_MAP_RETRY -> retrying fallback for {missing_ids}")
        sleeper(retry_delay_sec)
        merged.update(fetch(missing_ids))
        missing_ids = [sid for sid in security_ids if merged.get(sid) is None]

    return merged, not missing_ids
