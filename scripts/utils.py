


import os
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv


# ---------- dynamic dhan headers ----------
def get_dhan_headers() -> dict:
    """
    Always reload Dhan credentials from .env.
    Prevents stale access-token after daily refresh.
    """
    load_dotenv("/home/ubuntu/nseo/.env", override=True)

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