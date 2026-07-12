"""Navigation controller: manages survey page flow (next/prev/end detection)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from survey_auto.browser import BrowserManager
from survey_auto.models import PLATFORM_CONFIGS, Platform

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
MAX_PAGES = 500


class NavigationController:
    """Controls survey page navigation and detects survey completion."""

    def __init__(self, page: Page, platform: Platform, max_pages: int = MAX_PAGES):
        self.page = page
        self.platform = platform
        self.max_pages = max_pages
        self._pages_visited = 0
        self._config = PLATFORM_CONFIGS[platform]

    @property
    def pages_visited(self) -> int:
        """Get the number of pages visited so far."""
        return self._pages_visited

    def is_survey_ended(self) -> bool:
        """Check if the survey has ended."""
        current_url = self.page.url.lower()
        if any(pattern.lower() in current_url for pattern in self._config.end_patterns):
            logger.info("Survey end detected via URL: %s", current_url)
            return True
        # Check if question container is empty
        try:
            body = self.page.locator(self._config.question_container)
            if body.count() == 0 or body.inner_html().strip() == "":
                logger.info("Survey end detected: question body is empty")
                return True
        except Exception:
            pass
        # Check for error page (NielsenIQ, etc.)
        try:
            err = self.page.locator(".survey-error, .error-page, .error-text")
            if err.count() > 0 and err.is_visible():
                logger.info("Survey end detected: error page shown")
                return True
        except Exception:
            pass
        # SurveyMachine: check if next button is gone
        if self.platform == Platform.SURVEY_MACHINE:
            try:
                next_btn = self.page.locator(self._config.next_button)
                if next_btn.count() == 0 or not next_btn.is_visible():
                    logger.info("Survey end detected: next button not visible")
                    return True
            except Exception:
                pass
        return False

    def get_progress(self) -> Optional[int]:
        """Estimate survey progress percentage."""
        try:
            if self.platform == Platform.SURVEY_MACHINE:
                # Parse width percentage from .progressbar .bar
                bar = self.page.locator(self._config.progress_selector)
                if bar.count() > 0:
                    style = bar.get_attribute("style") or ""
                    width_match = __import__("re").search(r"width:\s*(\d+)%", style)
                    if width_match:
                        return int(width_match.group(1))
                return None
            else:
                # KiwiSurvey: count active progress dots
                progress_dots = self.page.locator(self._config.progress_selector)
                count = progress_dots.count()
                return count if count > 0 else None
        except Exception:
            return None

    def next_page(self) -> bool:
        """Navigate to the next survey page.

        Returns True if navigation succeeded, False if survey ended or failed.
        """
        if self._pages_visited >= self.max_pages:
            logger.warning("Max pages (%d) reached, stopping", self.max_pages)
            return False

        if self.is_survey_ended():
            return False

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                old_qnum = self.page.evaluate(
                    "() => (document.querySelector('.questionNum') || {}).textContent || ''"
                ).strip()

                self.page.evaluate(
                    "() => { if (typeof SurveyLoader !== 'undefined') SurveyLoader.next(); }"
                )
                self.page.wait_for_timeout(2000)

                new_qnum = self.page.evaluate(
                    "() => (document.querySelector('.questionNum') || {}).textContent || ''"
                ).strip()

                if old_qnum == new_qnum and old_qnum:
                    logger.warning("Page did not change (still %s)", old_qnum)
                    return False

                self._pages_visited += 1
                logger.info("Navigated to page %d", self._pages_visited)
                return True
            except Exception as exc:
                logger.warning(
                    "Next page attempt %d/%d failed: %s",
                    attempt, MAX_RETRIES, exc,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(1)

        logger.error("Failed to navigate after %d attempts", MAX_RETRIES)
        return False

    def handle_error(self, browser: BrowserManager, error_msg: str) -> None:
        """Take a screenshot and log on error."""
        screenshot_path = Path(f"error_page_{self._pages_visited}.png")
        try:
            browser.screenshot(screenshot_path)
            logger.error("%s — Screenshot saved to %s", error_msg, screenshot_path)
        except Exception as exc:
            logger.error("%s — Screenshot also failed: %s", error_msg, exc)
