"""DeepSeek browser agent — screenshot + structured info for full page visibility."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.request
from typing import Optional

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """You are a survey automation agent controlling a browser via CSS selectors.

CRITICAL RULES:
- MATRIX QUESTIONS: A matrix/grid question has MULTIPLE radio groups (e.g. Q27_1_1, Q27_1_2, ... Q27_1_11). You MUST select one radio from EVERY group before clicking next. Missing any group will block progress.
- For radio buttons: select one option per group. Pick option index 3 (4th option) for variety.
- For checkboxes: check 1-3 options per group.
- For text inputs: use {"type": "type", "selector": "<selector>", "value": "<number>"} with the pre-computed selector from page_info. For number inputs, use a valid number (1-20). For text inputs, use short Korean text.
- For ranking questions (type "ranking"): click 3 different items in order using {"type": "click", "selector": "#Q31_1"} etc.
- After answering ALL questions/groups on the page, call next_page.
- Use the "selector" field from page_info for reliable targeting.
- Do NOT invent selectors — use the exact selector provided in the page structure.

Return ONLY valid JSON: {"actions": [...], "reasoning": "..."}
Action formats: {"type": "click", "selector": "#ID"} or {"type": "type", "selector": "...", "value": "..."} or {"type": "next_page"}"""


class DeepSeekBrowserAgent:
    """Agent that uses DeepSeek with screenshot + structured page info."""

    def __init__(self, page: Page, api_key: str = None):
        self.page = page
        self.api_key = api_key or self._get_api_key()

    def solve_page(self, progress_pct: int = None, page_num: int = None) -> dict:
        """Analyze current page via screenshot + structure, execute actions."""
        prev_url = self.page.url
        prev_qnum = self._get_question_num()

        screenshot_b64 = self._take_screenshot()
        page_info = self._get_page_structure()

        context = {
            "url": self.page.url,
            "page_num": page_num,
            "progress_pct": progress_pct,
            "page_info": page_info,
            "screenshot_b64": screenshot_b64,
        }

        plan = self._ask_deepseek(context)
        if not plan:
            return {"success": False, "error": "DeepSeek returned no plan"}

        result = self._execute_plan(plan)

        # Verify page actually changed
        self.page.wait_for_timeout(1500)
        new_url = self.page.url
        new_qnum = self._get_question_num()
        page_changed = (new_url != prev_url or new_qnum != prev_qnum)
        result["page_changed"] = page_changed
        result["prev_qnum"] = prev_qnum
        result["new_qnum"] = new_qnum

        if not page_changed:
            logger.warning("Page did NOT change after DeepSeek actions (%s -> %s)", prev_qnum, new_qnum)
            filled = self._auto_fill_unanswered()
            if filled:
                logger.info("Auto-filled %d unanswered groups", filled)
            self._click_next_js()
            self.page.wait_for_timeout(1500)
            new_qnum2 = self._get_question_num()
            if new_qnum2 != prev_qnum:
                result["page_changed"] = True
                result["new_qnum"] = new_qnum2
                result["auto_fill_rescue"] = True

        return result

    def _get_page_structure(self) -> str:
        """Extract structured info about all interactive elements on the page."""
        info = self.page.evaluate("""() => {
            const result = [];

            // Radio groups
            const radios = document.querySelectorAll('input[type=radio]');
            const groups = {};
            radios.forEach(r => {
                if (!groups[r.name]) groups[r.name] = [];
                groups[r.name].push({id: r.id, checked: r.checked, hkey: r.getAttribute('hkey')});
            });
            for (const [name, items] of Object.entries(groups)) {
                const checked = items.filter(i => i.checked).map(i => i.id);
                result.push({
                    type: 'radio_group',
                    name: name,
                    options: items.length,
                    checked_ids: checked,
                    all_ids: items.map(i => i.id)
                });
            }

            // Checkbox groups
            const checks = document.querySelectorAll('input[type=checkbox]');
            const cbGroups = {};
            checks.forEach(c => {
                if (!cbGroups[c.name]) cbGroups[c.name] = [];
                cbGroups[c.name].push({id: c.id, checked: c.checked});
            });
            for (const [name, items] of Object.entries(cbGroups)) {
                const checked = items.filter(i => i.checked).map(i => i.id);
                result.push({
                    type: 'checkbox_group',
                    name: name,
                    options: items.length,
                    checked_ids: checked,
                    all_ids: items.map(i => i.id)
                });
            }

            // Text inputs & textareas
            const inputs = document.querySelectorAll('input[type=text], input[type=number], input[type=date], textarea');
            inputs.forEach(inp => {
                if (inp.disabled) return;
                let selector;
                if (inp.tagName === 'TEXTAREA') {
                    if (inp.id) {
                        selector = 'textarea#' + inp.id;
                    } else {
                        const allTa = Array.from(document.querySelectorAll('textarea')).filter(t => !t.disabled);
                        selector = 'textarea:nth-of-type(' + (allTa.indexOf(inp) + 1) + ')';
                    }
                } else if (inp.id) {
                    selector = 'input#' + inp.id;
                } else if (inp.getAttribute('inputtype') && inp.getAttribute('index')) {
                    selector = 'input[inputtype="' + inp.getAttribute('inputtype') + '"][index="' + inp.getAttribute('index') + '"]';
                } else {
                    selector = 'input[type=' + inp.type + ']:nth-of-type(' + (Array.from(document.querySelectorAll('input[type=' + inp.type + ']')).indexOf(inp) + 1) + ')';
                }
                result.push({
                    type: 'text_input',
                    name: inp.name || inp.id || '',
                    inputType: inp.tagName === 'TEXTAREA' ? 'textarea' : (inp.type || 'text'),
                    inputtype: inp.getAttribute('inputtype') || '',
                    index: inp.getAttribute('index') || '',
                    min: inp.getAttribute('min') || '',
                    max: inp.getAttribute('max') || '',
                    value: inp.value || '',
                    placeholder: inp.placeholder || '',
                    selector: selector
                });
            });

            // Dropdowns
            const selects = document.querySelectorAll('select');
            selects.forEach(sel => {
                result.push({
                    type: 'select',
                    name: sel.name || sel.id,
                    value: sel.value,
                    options: Array.from(sel.options).map(o => ({value: o.value, text: o.text}))
                });
            });

            // Ranking items (div.pincette — not td.pincette which are table cells)
            const pincettes = document.querySelectorAll('div.pincette');
            if (pincettes.length > 0) {
                const items = [];
                pincettes.forEach(p => {
                    items.push({
                        id: p.id,
                        val: p.getAttribute('val'),
                        label: p.closest('label')?.textContent?.trim() || '',
                        selected: p.classList.contains('selected') || p.style.backgroundColor !== ''
                    });
                });
                result.push({
                    type: 'ranking',
                    instruction: 'Click items in order: #ID for 1st, then 2nd, then 3rd',
                    items: items
                });
            }

            // Question number
            const qnum = document.querySelector('.questionNum');
            const progress = document.querySelector('.progress-bar');

            return {
                questionNum: qnum ? qnum.textContent.trim() : null,
                progressText: progress ? progress.textContent.trim() : null,
                elements: result
            };
        }""")
        return json.dumps(info, ensure_ascii=False, indent=1)

    def _get_question_num(self) -> str:
        try:
            return self.page.evaluate("""() => {
                const el = document.querySelector('.questionNum');
                return el ? el.textContent.trim() : '';
            }""")
        except Exception:
            return ""

    def _take_screenshot(self) -> Optional[str]:
        try:
            buf = self.page.screenshot(type="png", full_page=False)
            return base64.b64encode(buf).decode("utf-8")
        except Exception as e:
            logger.warning("Screenshot failed: %s", e)
            return None

    def _ask_deepseek(self, context: dict) -> Optional[dict]:
        if not self.api_key:
            logger.error("No DeepSeek API key")
            return None

        user_content = f"""Current page state:
URL: {context['url']}
Page: {context.get('page_num', '?')}
Progress: {context.get('progress_pct', '?')}%

Page structure (all interactive elements):
{context['page_info']}

Analyze ALL radio groups and text inputs above. For matrix questions with multiple radio groups (e.g. Q27_1_1 through Q27_1_11), you MUST select one radio from EVERY group. Pick the 3rd or 4th option (hkey=3 or hkey=4) for variety. Use the #ID selector (e.g. #Q27_1_1_3).

For text inputs, fill with short Korean text.
When done answering everything, add a next_page action at the end."""

        payload = json.dumps({
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 3000,
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            req = urllib.request.Request(DEEPSEEK_API_URL, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                logger.info("DeepSeek response: %s", content[:500])
                return self._parse_response(content)
        except Exception as e:
            logger.error("DeepSeek API call failed: %s", e)
            return None

    def _parse_response(self, content: str) -> Optional[dict]:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
        try:
            result = json.loads(content)
            logger.info("Parsed JSON: %s", json.dumps(result, ensure_ascii=False)[:400])
            return result
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                    logger.info("Parsed JSON from match: %s", json.dumps(result, ensure_ascii=False)[:400])
                    return result
                except json.JSONDecodeError:
                    pass
        logger.warning("Failed to parse DeepSeek response: %s", content[:300])
        return None

    def _execute_plan(self, plan: dict) -> dict:
        actions = plan.get("actions", [])
        reasoning = plan.get("reasoning", "")
        logger.info("DeepSeek plan (%d actions): %s", len(actions), reasoning[:150] if reasoning else str(actions)[:150])

        executed = 0
        for action in actions:
            atype = action.get("type") or action.get("tool") or action.get("action", "")
            selector = action.get("selector", "")
            value = action.get("value", "")
            args = action.get("args", [])
            if selector and not args:
                args = [selector]
            if value and len(args) == 1:
                args.append(value)

            try:
                if atype == "click" and args:
                    selector = args[0]
                    # Escape special CSS characters (~, :, ., etc.) in the selector
                    safe_selector = selector.replace('~', '\\~').replace(':', '\\:').replace('.', '\\.')
                    # Evaluate if selector contains special chars that need JS-like querying
                    use_js = any(c in selector for c in '~:. ')
                    if use_js:
                        # Use [id=] attribute selector for IDs with special characters
                        if selector.startswith('#'):
                            id_val = selector[1:]
                            self.page.evaluate(f"""() => {{
                                const el = document.querySelector('[id="{id_val}"]');
                                if (el) {{
                                    el.checked = true;
                                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                                    el.dispatchEvent(new Event('click', {{bubbles: true}}));
                                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                                }}
                            }}""")
                        else:
                            self.page.click(safe_selector, force=True, timeout=5000)
                    else:
                        self.page.click(safe_selector, force=True, timeout=5000)
                    self.page.wait_for_timeout(300)
                    executed += 1
                elif atype == "type" and len(args) >= 2:
                    self.page.fill(args[0], args[1], timeout=5000)
                    self.page.wait_for_timeout(300)
                    executed += 1
                elif atype == "check" and args:
                    self.page.check(args[0], force=True, timeout=5000)
                    self.page.wait_for_timeout(300)
                    executed += 1
                elif atype == "select" and len(args) >= 2:
                    self.page.select_option(args[0], args[1], timeout=5000)
                    self.page.wait_for_timeout(300)
                    executed += 1
                elif atype == "next_page":
                    self._click_next_js()
                    executed += 1
                else:
                    logger.warning("Unknown action: %s %s", atype, args)
            except Exception as e:
                logger.warning("Action %s(%s) failed: %s", atype, args, e)

        return {"success": executed > 0, "actions_executed": executed, "reasoning": reasoning}

    def _click_next_js(self):
        """Click next via platform-specific JS or DOM click."""
        # Try common survey platform next button selectors
        try:
            # Qualtrics
            if self.page.locator("#NextButton").count() > 0:
                if not self.page.locator("#NextButton").is_disabled():
                    self.page.click("#NextButton", timeout=5000)
                    self.page.wait_for_timeout(2000)
                    return
        except Exception:
            pass

        try:
            self.page.evaluate("() => { if (typeof SurveyLoader !== 'undefined') SurveyLoader.next(); }")
            self.page.wait_for_timeout(2000)
            return
        except Exception as e:
            logger.warning("SurveyLoader.next() failed: %s", e)

        # Fallback: DOM click
        for selector in ["#btn_next", "#next", "button[type='submit']", "#NextButton"]:
            try:
                if self.page.locator(selector).count() > 0:
                    self.page.click(selector, timeout=5000)
                    self.page.wait_for_timeout(2000)
                    return
            except Exception:
                continue

        # Last resort: click any visible button with "next" or "다음" in text
        try:
            self.page.evaluate("""() => {
                const btns = document.querySelectorAll('button, input[type=button], input[type=submit]');
                for (const btn of btns) {
                    const text = (btn.textContent || btn.value || '').toLowerCase();
                    if (!btn.disabled && btn.offsetParent !== null &&
                        (text.includes('next') || text.includes('다음') || text.includes('>>'))) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }""")
            self.page.wait_for_timeout(2000)
        except Exception:
            pass

    def _auto_fill_unanswered(self) -> int:
        """Select first available option in any radio group that has no selection."""
        filled = self.page.evaluate("""() => {
            let count = 0;
            const radios = document.querySelectorAll('input[type=radio]');
            const groups = {};
            radios.forEach(r => {
                if (!groups[r.name]) groups[r.name] = [];
                groups[r.name].push(r);
            });
            for (const [name, items] of Object.entries(groups)) {
                const anyChecked = items.some(r => r.checked);
                if (!anyChecked && items.length > 0) {
                    const idx = Math.min(2, items.length - 1);
                    const radio = items[idx];
                    radio.checked = true;
                    radio.dispatchEvent(new Event('change', {bubbles: true}));
                    radio.dispatchEvent(new Event('click', {bubbles: true}));
                    radio.dispatchEvent(new Event('input', {bubbles: true}));
                    count++;
                }
            }
            return count;
        }""")
        return filled

    def _get_api_key(self) -> Optional[str]:
        key = os.environ.get("DEEPSEEK_API_KEY")
        if key:
            return key
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
