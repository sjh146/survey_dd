"""DeepSeek API integration for analyzing unknown survey HTML patterns.

When heuristic + BS4 detection fail, sends HTML to DeepSeek for analysis.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

ANALYSIS_PROMPT = """You are analyzing a SurveyMachine survey page HTML fragment.

CRITICAL: Extract the EXACT variable name from <div class="questionNum">Q13a.</div> → "Q13a".
Do NOT use a generic variable. Use the EXACT question number shown.

Analyze the HTML and return JSON with:
- "question_type": single | multi | open | scale | select
- "variable_name": EXACT variable from questionNum div (e.g. "Q13a")
- "title": the question text from .questionText
- "text_inputs": array of {name: "VARIABLE_INDEX", input_type: "number"|"text"} for each input field
- "fill_instruction": how to fill (e.g. "Type 2024 in year field, 6 in month field")

SurveyMachine input patterns:
- <input inputtype="number" index="1"> → name = "VARIABLE_1"
- <input inputtype="number" index="2"> → name = "VARIABLE_2"
- <input type="text" name="VAR_1"> → name = "VAR_1"
- Radio: <input type="radio" name="VAR" value="1">
- Checkbox: <input type="checkbox" name="VAR_1" value="1">

Return ONLY valid JSON. No markdown, no explanation.

Example for Q13a (year/month inputs):
{"question_type":"open","variable_name":"Q13a","title":"When did you experience the defect?","text_inputs":[{"name":"Q13a_1","input_type":"number"},{"name":"Q13a_2","input_type":"number"}],"fill_instruction":"Type 2024 in year field (index=1), type 6 in month field (index=2)"}"""


def analyze_html(html: str, context: dict = None) -> Optional[dict]:
    api_key = _get_api_key()
    if not api_key:
        logger.warning("DeepSeek API key not found")
        return None

    user_msg = f"SurveyMachine page HTML:\n\n{html[:4000]}"
    if context:
        user_msg += f"\n\nContext: {json.dumps(context)}"

    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": ANALYSIS_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        req = urllib.request.Request(DEEPSEEK_API_URL, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            # Try to extract JSON from response
            return _parse_response(content)
    except Exception as e:
        logger.error("DeepSeek API call failed: %s", e)
        return None


def analyze_and_extend(html: str, context: dict = None) -> bool:
    """Analyze HTML with DeepSeek and generate parser extension.
    
    Returns True if extension was successfully generated.
    """
    result = analyze_html(html, context)
    if not result:
        return False

    logger.info("DeepSeek analysis: type=%s variable=%s",
                result.get("question_type"), result.get("variable_name"))

    # If we got extractor code, save it directly
    code = result.get("extractor_code", "")
    if code:
        return _save_extractor_code(code, result.get("variable_name", "unknown"))

    # Otherwise generate from structured data
    return _generate_from_analysis(result)


def _get_api_key() -> Optional[str]:
    """Get DeepSeek API key from environment or .env file."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    
    # Try .env files
    for env_path in [".env", "../.env", os.path.expanduser("~/.env")]:
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY="):
                        return line.split("=", 1)[1].strip().strip("'\"")
        except FileNotFoundError:
            continue
    return None


def _parse_response(content: str) -> Optional[dict]:
    """Parse JSON from DeepSeek response, handling markdown code blocks."""
    # Remove markdown code blocks if present
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```\w*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Try to find JSON object in text
        match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logger.warning("Failed to parse DeepSeek response")
    return None


def _save_extractor_code(code: str, variable: str) -> bool:
    from survey_auto.self_improve.generator import validate_code, EXT_DIR, _ensure_dir, _next_version
    
    if not validate_code(code):
        logger.error("DeepSeek-generated code has syntax errors")
        return False
    
    _ensure_dir(EXT_DIR)
    ver = _next_version()
    ext_path = EXT_DIR / f"{ver}.py"
    
    if "def " not in code:
        func_name = f"parse_deepseek_{variable.lower()}"
        code = f"def {func_name}(html):\n" + "\n".join(f"    {line}" for line in code.split("\n"))
    else:
        code = re.sub(r"def (\w+)\(", lambda m: f"def parse_{variable.lower()}(", code, count=1)
    
    ext_path.write_text(code + "\n")
    logger.info("Saved DeepSeek extractor to %s", ext_path)
    return True


def _generate_from_analysis(result: dict) -> bool:
    from survey_auto.self_improve.generator import extend_parser

    qtype = result.get("question_type", "unknown")
    variable = result.get("variable_name", "")
    options = result.get("options", [])
    text_inputs = result.get("text_inputs", [])

    if not variable:
        return False

    pattern = {
        "type": qtype,
        "variable": variable,
        "options": [{"value": o.get("value", ""), "label": o.get("label", "")} for o in options],
        "text_inputs": [{"name": t.get("name", ""), "label": "", "must": False, "input_type": t.get("input_type", "text")} for t in text_inputs] if text_inputs else [],
    }

    return extend_parser([pattern])
