"""File-based work order system for cross-agent delegation."""
from __future__ import annotations
import json, logging, time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
WO_DIR = Path(__file__).resolve().parent.parent.parent / ".omo" / "work_orders"

class WorkOrderStatus(str, Enum):
    PENDING = "pending"; ANALYZING = "analyzing"; COMPLETED = "completed"; FAILED = "failed"

@dataclass
class WorkOrder:
    id: str
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    created_at: str = ""; html_file: str = ""
    context: dict = field(default_factory=dict); agent_type: str = "deep"
    result: Optional[dict] = None

def _ensure(): WO_DIR.mkdir(parents=True, exist_ok=True)

def create_work_order(html_file: str, context: dict | None = None, agent_type: str = "deep") -> WorkOrder:
    _ensure(); ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    o = WorkOrder(id=f"wo_{ts}", created_at=datetime.now().isoformat(),
                  html_file=html_file, context=context or {}, agent_type=agent_type)
    (WO_DIR / f"{o.id}.json").write_text(json.dumps(asdict(o), indent=2, default=str))
    logger.info("Work order created: %s", o.id)
    return o

def load_pending_orders() -> list[WorkOrder]:
    _ensure(); orders = []
    for f in sorted(WO_DIR.glob("wo_*.json")):
        try:
            d = json.loads(f.read_text())
            if d.get("status") == "pending":
                d["status"] = WorkOrderStatus(d["status"])
                orders.append(WorkOrder(**d))
        except Exception as e: logger.warning("Load WO %s failed: %s", f, e)
    return orders

def update_work_order(order_id: str, status: WorkOrderStatus, result: dict | None = None):
    _ensure(); p = WO_DIR / f"{order_id}.json"
    if not p.exists(): return
    d = json.loads(p.read_text()); d["status"] = status.value
    if result: d["result"] = result
    p.write_text(json.dumps(d, indent=2, default=str))
