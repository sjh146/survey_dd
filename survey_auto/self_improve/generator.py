"""Parser extension code generation, validation, and hot-reload."""
from __future__ import annotations
import importlib, importlib.util, logging, sys
from pathlib import Path
from typing import Optional
from survey_auto.models import Question, QuestionType, Option, TextInput

logger = logging.getLogger(__name__)
EXT_DIR = Path(__file__).resolve().parent.parent.parent / ".omo" / "extensions"

def _ensure_dir(p: Path): p.mkdir(parents=True, exist_ok=True)

def _next_version() -> str:
    _ensure_dir(EXT_DIR)
    nums = []
    for f in EXT_DIR.glob("v*.py"):
        try: nums.append(int(f.stem[1:]))
        except ValueError: pass
    return f"v{(max(nums)+1 if nums else 1):03d}"

def validate_code(code: str) -> bool:
    try: compile(code, "<ext>", "exec"); return True
    except SyntaxError as e: logger.error("Syntax error: %s", e); return False

def generate_parser_code(p: dict) -> Optional[str]:
    v = p["variable"]; vt = v.lower()
    if p["type"] == "select":
        return f'''def parse_select_{vt}(html):
    import re
    from survey_auto.models import Question, QuestionType, Option
    m = re.search(r'<select[^>]*name=[\\\"']+{v}[\\\"']+[^>]*>(.*?)</select>', html, re.I|re.S)
    if not m: return []
    opts = [Option(value=o.group(1), label=re.sub(r'<[^>]+>','',o.group(2)).strip())
            for o in re.finditer(r'<option[^>]*value=[\\\"']+([^\\\"']+)[\\\"']+[^>]*>(.*?)</option>', m.group(1), re.I|re.S)]
    return [Question(variable="{v}", qtype=QuestionType.SINGLE, options=opts)] if opts else []'''
    elif p["type"] == "open":
        ti = p["text_inputs"][0] if p["text_inputs"] else {"name": v, "input_type": "text"}
        return f'''def parse_open_{vt}(html):
    from survey_auto.models import Question, QuestionType, TextInput
    return [Question(variable="{v}", qtype=QuestionType.OPEN,
                     text_inputs=[TextInput(name="{ti['name']}", input_type="{ti['input_type']}")])]'''
    return None

def extend_parser(patterns: list[dict]) -> bool:
    if not patterns: return False
    codes = []
    for p in patterns:
        code = generate_parser_code(p)
        if code and validate_code(code):
            codes.append(code)
            logger.info("Generated extension: parse_%s_%s", p["type"], p["variable"].lower())
    if not codes: return False
    ver = _next_version(); _ensure_dir(EXT_DIR)
    p = EXT_DIR / f"{ver}.py"
    p.write_text("\n".join(codes) + "\n")
    logger.info("Wrote %d extension(s) to %s", len(codes), p)
    return True

def apply_extensions(html: str) -> list[Question]:
    _ensure_dir(EXT_DIR)
    qs: list[Question] = []
    for vp in sorted(EXT_DIR.glob("v*.py")):
        try:
            mod_name = f"_ext_{vp.stem}"
            if mod_name in sys.modules:
                mod = importlib.reload(sys.modules[mod_name])
            else:
                spec = importlib.util.spec_from_file_location(mod_name, vp)
                if spec is None or spec.loader is None: continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                sys.modules[mod_name] = mod
            for nm in dir(mod):
                if nm.startswith("parse_"):
                    try:
                        r = getattr(mod, nm)(html)
                        if r: qs.extend(r); logger.info("Ext %s: %d q(s)", nm, len(r))
                    except Exception as e: logger.warning("Ext %s failed: %s", nm, e)
        except Exception as e: logger.warning("Load %s failed: %s", vp.name, e)
    return qs
