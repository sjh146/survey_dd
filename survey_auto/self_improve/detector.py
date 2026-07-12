"""Pattern detection — heuristic regex + BeautifulSoup deep analysis."""
from __future__ import annotations
import logging, re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
UNKNOWN_DIR = Path(__file__).resolve().parent.parent.parent / ".omo" / "unknown_patterns"

def _ensure_dir(p: Path | None = None): (p or UNKNOWN_DIR).mkdir(parents=True, exist_ok=True)

def save_html_snapshot(html: str, page_num: int, tag: str = "unknown") -> Path:
    _ensure_dir()
    f = UNKNOWN_DIR / f"page{page_num}_{tag}_{datetime.now():%Y%m%d_%H%M%S}.html"
    f.write_text(html, encoding="utf-8")
    logger.info("Saved snapshot: %s", f)
    return f

def detect_new_patterns(html: str) -> list[dict]:
    """Regex-based detection of unknown patterns. Returns pattern dicts."""
    patterns: list[dict] = []
    for m in re.finditer(r'<select[^>]*name=(["\'])(\w+)\1[^>]*>(.*?)</select>', html, re.I | re.S):
        var, opts = m.group(2), []
        for o in re.finditer(r'<option[^>]*value=(["\'])([^"\']+)\1[^>]*>(.*?)</option>', m.group(3), re.I | re.S):
            opts.append({"value": o.group(2), "label": re.sub(r'<[^>]+>', "", o.group(3)).strip()})
        if opts: patterns.append({"type": "select", "variable": var, "options": opts, "text_inputs": []})
    for m in re.finditer(r'<(input|textarea)[^>]*name=(["\'])(\w+)\2[^>]*>', html, re.I):
        name, full = m.group(3), m.group(0)
        t = re.search(r'type=(["\'])([^"\']+)\1', full, re.I)
        itype = t.group(2).lower() if t else "text"
        if itype in ("radio", "checkbox", "submit", "button", "hidden"): continue
        patterns.append({"type": "open", "variable": name, "options": [],
                         "text_inputs": [{"name": name, "label": "", "must": False, "input_type": itype}]})
    return patterns

def detect_bs4_deep(html: str) -> list[dict]:
    """BeautifulSoup deep detection. Requires beautifulsoup4."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    patterns, soup = [], BeautifulSoup(html, "html.parser")
    for sel in soup.find_all("select"):
        name = sel.get("name", "")
        if not name: continue
        opts = [{"value": o.get("value",""), "label": o.get_text(strip=True)} for o in sel.find_all("option") if o.get("value")]
        if opts: patterns.append({"type": "select", "variable": name, "options": opts, "text_inputs": []})
    for inp in soup.find_all("input", type=lambda t: t and t.lower() not in ("radio","checkbox","hidden","submit","button")):
        name = inp.get("name", "")
        if name: patterns.append({"type": "open", "variable": name, "options": [],
                                  "text_inputs": [{"name": name, "label": "", "must": False, "input_type": inp.get("type","text")}]})
    for ta in soup.find_all("textarea"):
        name = ta.get("name", "")
        if name: patterns.append({"type": "open", "variable": name, "options": [],
                                  "text_inputs": [{"name": name, "label": "", "must": False, "input_type": "textarea"}]})
    for ul in soup.select('[class*="rank"], [class*="Rank"], ul[data-rank]'):
        items = ul.find_all("li")
        if len(items) >= 2:
            name = ul.get("data-name", ul.get("id", "rank"))
            opts = [{"value": li.get("data-value", li.get_text(strip=True)[:20]), "label": li.get_text(strip=True)} for li in items]
            if opts: patterns.append({"type": "rank", "variable": name, "options": opts, "text_inputs": []})
    return patterns
