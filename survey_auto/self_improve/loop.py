"""SelfImproveLoop — parser-first with DeepSeek fallback for stuck pages."""
from __future__ import annotations
import logging, time
from survey_auto.browser import BrowserManager
from survey_auto.executor import ActionExecutor
from survey_auto.navigator import NavigationController
from survey_auto.parser import SurveyParser
from survey_auto.strategies import StrategyEngine
from survey_auto.self_improve.checkpoint import clear as clear_ckpt, load as load_ckpt, save as save_ckpt
from survey_auto.self_improve.deepseek_browser_agent import DeepSeekBrowserAgent

logger = logging.getLogger(__name__)

SAME_CONTENT_LIMIT = 12


def _detect_and_fill_matrix(page) -> bool:
    """Detect matrix (multiple radio groups) and fill via DOM JS. Returns True if filled."""
    filled = page.evaluate("""() => {
        const radios = document.querySelectorAll('input[type=radio]');
        const groups = {};
        radios.forEach(r => {
            if (!groups[r.name]) groups[r.name] = [];
            groups[r.name].push(r);
        });
        const groupNames = Object.keys(groups);
        if (groupNames.length < 2) return false;

        let anyFilled = false;
        for (const [name, items] of Object.entries(groups)) {
            const anyChecked = items.some(r => r.checked);
            if (!anyChecked && items.length > 0) {
                const idx = Math.min(3, items.length - 1);
                const radio = items[idx];
                if (typeof $ !== 'undefined') {
                    $(radio).prop('checked', true).trigger('change').trigger('click');
                } else {
                    radio.checked = true;
                    radio.dispatchEvent(new Event('change', {bubbles: true}));
                    radio.dispatchEvent(new Event('click', {bubbles: true}));
                }
                anyFilled = true;
            }
        }
        return anyFilled ? groupNames.length : 0;
    }""")
    if filled:
        logger.info("Matrix detected: filled %d groups via DOM", filled)
        page.wait_for_timeout(2000)
    return bool(filled)


def _detect_and_fill_percentage(page, container: str = ".answerBox") -> bool:
    """Detect percentage-sum tables and fill inputs that total 100."""
    filled = page.evaluate("""(container) => {
        const sumEl = document.querySelector('.sum_value');
        if (!sumEl) return false;

        const inputs = document.querySelectorAll(container + ' input[type=text]');
        if (inputs.length < 2) return false;

        const currentSum = parseInt(sumEl.textContent) || 0;
        if (currentSum === 100) return false;

        const n = inputs.length;
        const base = Math.floor(100 / n);
        const remainder = 100 - base * n;

        for (let i = 0; i < n; i++) {
            const val = base + (i < remainder ? 1 : 0);
            inputs[i].value = val;
            inputs[i].dispatchEvent(new Event('input', {bubbles: true}));
            inputs[i].dispatchEvent(new Event('change', {bubbles: true}));
        }
        return n;
    }""", container)
    if filled:
        logger.info("Percentage sum detected: filled %d inputs to total 100%%", filled)
        page.wait_for_timeout(1000)
    return bool(filled)


def _fill_unfilled_inputs(page, container: str = "#vb_application") -> int:
    """Fill any unfilled text inputs the parser missed, using JS evaluate for DOM events.
    Returns the number of inputs filled."""
    count = page.evaluate("""(container) => {
        const inputs = document.querySelectorAll(container + ' input[type=text]');
        let filled = 0;
        inputs.forEach((inp) => {
            if (inp.disabled || inp.value !== '') return;
            const inputtype = (inp.getAttribute('inputtype') || '').toLowerCase();
            let val;

            if (inputtype === 'number') {
                /* date/count fields: use small safe values to avoid
                   cross-question validation errors (e.g. SQ4 > SQ2) */
                val = '1';
            } else if (typeof SurveyLoader !== 'undefined' && SurveyLoader.__ary_madeModules) {
                /* Match input to a module by finding the nearest .questionNum,
                   then use getData().DATA for InputNumber constraints */
                let found = false;
                const qNumEl = inp.closest('.answerBox')?.previousElementSibling?.querySelector('.questionNum')
                    || inp.closest('.questionBox')?.parentElement?.querySelector('.questionNum');
                const qNumText = qNumEl ? qNumEl.textContent.trim().replace('.', '') : '';

                for (const mod of SurveyLoader.__ary_madeModules) {
                    const fullData = mod.getData ? mod.getData() : {};
                    const d = fullData.DATA || {};
                    if (d.MODULE_TYPE === 'InputNumber' && d.NUM && d.NUM.replace('.', '') === qNumText) {
                        const minVal = parseInt(d.MIN_VALUE) || 0;
                        const maxVal = parseInt(d.MAX_VALUE) || 10000;
                        val = String(Math.floor((minVal + maxVal) / 2));
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    val = 'A';
                }
            } else {
                val = 'A';
            }

            inp.value = val;
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            inp.dispatchEvent(new Event('keyup', {bubbles: true}));
            filled++;
        });
        return filled;
    }""", container)
    if count:
        logger.info("Auto-filled %d unfilled text inputs via DOM events", count)
        page.wait_for_timeout(500)
    return count


class SelfImproveLoop:
    def __init__(self, url: str, headless: bool = True, timeout: int = 60,
                 max_pages: int = 500, max_attempts: int = 20, daemon: bool = False):
        self.url, self.headless, self.timeout = url, headless, timeout
        self.max_pages, self.max_attempts, self.daemon = max_pages, max_attempts, daemon
        self._q_total, self._p_total = 0, 0
        self._ai_pages = 0       # pages solved by DeepSeek
        self._no_ai_pages = 0    # pages solved by parser/executor/DOM fillers

    @property
    def ai_pages(self) -> int:
        return self._ai_pages

    @property
    def no_ai_pages(self) -> int:
        return self._no_ai_pages

    def run(self) -> dict:
        for att in range(1, self.max_attempts + 1):
            logger.info("=== Attempt %d/%d ===", att, self.max_attempts)
            r = self._attempt()
            if r["success"]:
                clear_ckpt()
                logger.info("=== COMPLETED %d attempts, %d pages, %d questions ===",
                            att, self._p_total, self._q_total)
                logger.info("=== Pages solved: %d by AI (DeepSeek), %d without AI (parser/executor/DOM) ===",
                            self._ai_pages, self._no_ai_pages)
                return r
            logger.warning("Attempt %d failed: %s", att, r.get("error", "unknown"))
            time.sleep(2)
        logger.error("Max attempts (%d) reached", self.max_attempts)
        return {"success": False, "error": "max attempts reached"}

    def _attempt(self) -> dict:
        br = BrowserManager(headless=self.headless, timeout=self.timeout * 1000)
        se = StrategyEngine()
        try:
            br.start(); br.navigate(self.url)
            pf = br.detect_platform(); logger.info("Platform: %s", pf.value)
            if not br.wait_for_question(timeout=self.timeout * 1000):
                return {"success": False, "error": "Question body did not render"}
            nav = NavigationController(br.page, pf, max_pages=self.max_pages)
            ex = ActionExecutor(br.page)
            agent = DeepSeekBrowserAgent(br.page)
            container = br.get_config().question_container
            pd, qd = 0, 0
            prev_html = ""
            same_count = 0
            sp = load_ckpt(self.url) or 0
            if sp: logger.info("Resume from page %d", sp)

            while True:
                # Catch browser/page closed — SurveyMachine closes popup on completion
                try:
                    _html = br.get_page_html()
                except Exception as page_err:
                    if "closed" in str(page_err).lower() or "target page" in str(page_err).lower():
                        logger.info("Survey completed: browser page closed (%s)", page_err)
                        self._p_total += pd; self._q_total += qd
                        return {"success": True, "pages": pd, "questions": qd,
                                "ai_pages": self._ai_pages, "no_ai_pages": self._no_ai_pages}
                    raise

                if nav.pages_visited < sp:
                    if not nav.next_page():
                        logger.warning("Stuck at page %d during skip, trying DeepSeek", nav.pages_visited)
                        result = agent.solve_page(progress_pct=nav.get_progress(), page_num=pd)
                        if result.get("success") and result.get("page_changed"):
                            logger.info("DeepSeek resolved skip stuck: %s->%s", result.get("prev_qnum"), result.get("new_qnum"))
                            self._ai_pages += 1
                            continue
                        else:
                            break
                    continue

                fmt = pf.value if pf.value in ("surveymachine", "nielseniq") else "kiwi"
                qs = SurveyParser(_html, platform=fmt).parse()
                if qs:
                    for q in qs:
                        if q.options or q.text_inputs:
                            a = se.get_answer(q)
                            logger.info("  %s (%s): %s", q.variable, q.qtype.value, a.selected_values or "(text)")
                            ex.fill_answers([q], [a]); qd += 1

                if nav.is_survey_ended():
                    return {"success": True, "pages": pd, "questions": qd,
                            "ai_pages": self._ai_pages, "no_ai_pages": self._no_ai_pages}

                if nav.next_page():
                    pd += 1; self._no_ai_pages += 1; save_ckpt(pd, self.url)
                    pg = nav.get_progress()
                    if pg is not None: logger.info("Progress: page %d, %d%%", pd, pg)
                    continue

                if _detect_and_fill_matrix(br.page):
                    br.page.wait_for_timeout(500)
                    if nav.next_page():
                        pd += 1; self._no_ai_pages += 1; save_ckpt(pd, self.url); qd += 1
                        pg = nav.get_progress()
                        if pg is not None: logger.info("Progress: page %d, %d%%", pd, pg)
                        continue

                if _detect_and_fill_percentage(br.page, container):
                    br.page.wait_for_timeout(500)
                    if nav.next_page():
                        pd += 1; self._no_ai_pages += 1; save_ckpt(pd, self.url); qd += 1
                        pg = nav.get_progress()
                        if pg is not None: logger.info("Progress: page %d, %d%%", pd, pg)
                        continue

                if _fill_unfilled_inputs(br.page, container):
                    br.page.wait_for_timeout(500)
                    if nav.next_page():
                        pd += 1; self._no_ai_pages += 1; save_ckpt(pd, self.url); qd += 1
                        pg = nav.get_progress()
                        if pg is not None: logger.info("Progress: page %d, %d%%", pd, pg)
                        continue

                logger.warning("Navigator stuck, delegating to DeepSeek")
                result = agent.solve_page(progress_pct=nav.get_progress(), page_num=pd)
                if result.get("success") and result.get("page_changed"):
                    logger.info("DeepSeek solved: %s->%s", result.get("prev_qnum"), result.get("new_qnum"))
                    pd += 1; self._ai_pages += 1; save_ckpt(pd, self.url); qd += 1
                    continue
                else:
                    logger.warning("DeepSeek failed: %s", result.get("error"))
                    break

            self._p_total += pd; self._q_total += qd
            return {"success": False, "error": "loop ended",
                    "ai_pages": self._ai_pages, "no_ai_pages": self._no_ai_pages}
        except Exception as e:
            logger.error("Exception: %s", e); return {"success": False, "error": str(e)}
        finally: br.close()
