"""SelfImproveLoop — main orchestrator with checkpoint resume, pattern learning, and Jenkins integration."""
from __future__ import annotations
import logging, time
from typing import Optional
from survey_auto.browser import BrowserManager
from survey_auto.executor import ActionExecutor
from survey_auto.navigator import NavigationController
from survey_auto.parser import SurveyParser
from survey_auto.strategies import StrategyEngine
from survey_auto.self_improve.checkpoint import clear as clear_ckpt, load as load_ckpt, save as save_ckpt
from survey_auto.self_improve.detector import detect_bs4_deep, detect_new_patterns, save_html_snapshot
from survey_auto.self_improve.generator import apply_extensions, extend_parser
from survey_auto.self_improve.work_order import WorkOrderStatus, create_work_order, load_pending_orders, update_work_order

logger = logging.getLogger(__name__)

class SelfImproveLoop:
    """Self-improving survey loop with checkpoint resume, pattern learning, and Jenkins integration."""
    def __init__(self, url: str, headless: bool = True, timeout: int = 60,
                 max_pages: int = 500, max_attempts: int = 20, daemon: bool = False):
        self.url, self.headless, self.timeout = url, headless, timeout
        self.max_pages, self.max_attempts, self.daemon = max_pages, max_attempts, daemon
        self._q_total, self._p_total = 0, 0

    def run(self) -> bool:
        for att in range(1, self.max_attempts + 1):
            logger.info("=== Attempt %d/%d ===", att, self.max_attempts)
            r = self._attempt()
            if r["success"]:
                clear_ckpt()
                logger.info("=== COMPLETED %d attempts, %d pages, %d questions ===",
                            att, self._p_total, self._q_total)
                return True
            html = r.get("unknown_html")
            if html: self._handle_unknown(html, r.get("page", 0))
            else: logger.warning("Attempt %d failed: %s", att, r.get("error"))
            if self.daemon: self._process_work_orders()
            time.sleep(2)
        logger.error("Max attempts (%d) reached", self.max_attempts)
        return False

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
            pd, qd, unk = 0, 0, None
            sp = load_ckpt(self.url) or 0
            if sp: logger.info("Resume from page %d", sp)
            while True:
                if nav.pages_visited < sp:
                    if not nav.next_page(): break
                    continue
                h = br.get_page_html()
                fmt = "surveymachine" if pf.value == "surveymachine" else "kiwi"
                qs = SurveyParser(h, platform=fmt).parse()
                if not qs: qs = apply_extensions(h)
                if not qs:
                    if nav.is_survey_ended():
                        return {"success": True, "pages": pd, "questions": qd}
                    unk = h; break
                for q in qs:
                    a = se.get_answer(q)
                    logger.info("  %s (%s): %s", q.variable, q.qtype.value, a.selected_values or "(text)")
                    ex.fill_answers([q], [a]); qd += 1
                if not nav.next_page(): break
                pd += 1; save_ckpt(pd, self.url)
                pg = nav.get_progress()
                if pg is not None: logger.info("Progress: page %d, %d%%", pd, pg)
            self._p_total += pd; self._q_total += qd
            if unk: return {"success": False, "unknown_html": unk, "page": pd}
            return {"success": True, "pages": pd, "questions": qd}
        except Exception as e:
            logger.error("Exception: %s", e); return {"success": False, "error": str(e)}
        finally: br.close()

    def _handle_unknown(self, html: str, page_num: int) -> None:
        f = save_html_snapshot(html, page_num)
        pats = detect_new_patterns(html)
        if not pats:
            try: pats = detect_bs4_deep(html)
            except Exception as e: logger.warning("BS4 failed: %s", e)
        if pats:
            logger.info("Detected %d pattern(s)", len(pats))
            for p in pats: logger.info("  %s:%s", p["type"], p["variable"])
            if extend_parser(pats): logger.info("Parser extended"); return
        # Jenkins 연동: 워커가 만든 work_order를 Jenkins가 처리
        logger.warning("Auto-detection failed, creating work order for Jenkins")
        wo = create_work_order(str(f), {"url": self.url, "page": page_num}, "jenkins")
        # Jenkins job 트리거 시도
        try:
            from survey_auto.self_improve.jenkins_bridge import trigger_analysis_job
            if trigger_analysis_job(str(f), wo.id):
                logger.info("Jenkins job completed, checking results")
                # 결과 확인 후 재시도
                pats = detect_bs4_deep(html)
                if pats and extend_parser(pats):
                    logger.info("Jenkins-generated extensions applied")
        except Exception as e:
            logger.warning("Jenkins trigger failed: %s (work order created for manual processing)", e)

    def _process_work_orders(self) -> None:
        for o in load_pending_orders():
            logger.info("Processing work order %s", o.id)
            hp = Path(o.html_file) if o.html_file else None
            if not hp or not hp.exists():
                update_work_order(o.id, WorkOrderStatus.FAILED, {"error": "missing HTML"}); continue
            html = hp.read_text(encoding="utf-8")
            pats = []
            try: pats = detect_bs4_deep(html)
            except: pass
            if pats and extend_parser(pats):
                update_work_order(o.id, WorkOrderStatus.COMPLETED, {"found": len(pats)})
            else:
                update_work_order(o.id, WorkOrderStatus.FAILED, {"error": "auto-detect failed"})
