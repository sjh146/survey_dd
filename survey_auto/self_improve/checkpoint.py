"""Checkpoint system for resuming surveys after failure."""
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Optional

CKPT = Path("/tmp/survey_checkpoint.json")

def save(page_num: int, url: str) -> None:
    CKPT.write_text(json.dumps({"page": page_num, "url": url, "ts": time.time()}))

def load(url: str) -> Optional[int]:
    if not CKPT.exists(): return None
    try:
        d = json.loads(CKPT.read_text())
        return d["page"] if d.get("url") == url else None
    except Exception:
        return None

def clear() -> None:
    CKPT.unlink(missing_ok=True)
