"""Firefox browser engine for survey automation using Playwright."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from survey_auto.models import PLATFORM_CONFIGS, Platform

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30000  # 30 seconds


class BrowserManager:
    """Manages a Firefox browser instance for survey navigation."""

    def __init__(self, headless: bool = True, timeout: int = DEFAULT_TIMEOUT, platform: Platform = Platform.AUTO):
        self.headless = headless
        self.timeout = timeout
        self._platform = platform
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def platform(self) -> Platform:
        """Get the detected platform. Raises RuntimeError if not yet detected."""
        if self._platform == Platform.AUTO:
            raise RuntimeError("Platform not yet detected. Call detect_platform() first.")
        return self._platform

    def start(self) -> None:
        """Launch Firefox browser and create a new context and page."""
        logger.info("Launching Firefox (headless=%s)", self.headless)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.firefox.launch(headless=self.headless)
        self._context = self._browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) "
                "Gecko/20100101 Firefox/115.0"
            ),
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout)
        logger.info("Firefox launched successfully")

    @property
    def page(self) -> Page:
        """Get the current page. Raises RuntimeError if not started."""
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    def navigate(self, url: str) -> None:
        """Navigate to a URL and wait for the page to load."""
        logger.info("Navigating to %s", url)
        self.page.goto(url, wait_until="networkidle")

    def detect_platform(self) -> Platform:
        """Auto-detect the survey platform based on DOM elements present.

        Returns the detected Platform and caches it.
        """
        if self._platform != Platform.AUTO:
            return self._platform

        page = self.page
        # Check for SurveyMachine markers
        if page.query_selector("#vb_application"):
            self._platform = Platform.SURVEY_MACHINE
            logger.info("Detected platform: SurveyMachine")
        elif page.query_selector("#question_body") or page.query_selector("#kiwi_progress"):
            self._platform = Platform.KIWI
            logger.info("Detected platform: KiwiSurvey")
        else:
            # Default to KiwiSurvey (backward compatible)
            self._platform = Platform.KIWI
            logger.info("Platform auto-detect defaulting to KiwiSurvey")

        return self._platform

    def get_config(self) -> "SurveyConfig":
        """Get platform-specific survey configuration."""
        from survey_auto.models import PLATFORM_CONFIGS
        return PLATFORM_CONFIGS[self.platform]

    def wait_for_question(self, timeout: Optional[int] = None) -> bool:
        """Wait for the question container to render. Returns True if rendered."""
        timeout_ms = timeout or self.timeout
        try:
            # First try platform-specific container
            if self._platform != Platform.AUTO:
                config = self.get_config()
                selector = config.question_container
            else:
                # Before detection, try both
                selector = "#vb_application, #question_body"

            self.page.wait_for_selector(
                selector,
                state="attached",
                timeout=timeout_ms,
            )
            # Wait for child elements (questions are dynamically rendered)
            self.page.wait_for_function(
                f"document.querySelector('{selector}')?.children.length > 0",
                timeout=timeout_ms,
            )
            self.page.wait_for_timeout(500)  # Wait for AJAX rendering to complete
            return True
        except Exception as exc:
            logger.warning("Question body did not render: %s", exc)
            return False

    def get_page_html(self) -> str:
        """Get the inner HTML of the question container element."""
        config = self.get_config()
        return self.page.inner_html(config.question_container)

    def click_next(self) -> None:
        """Click the Next button and wait for navigation."""
        config = self.get_config()
        next_btn = config.next_button
        logger.info("Clicking Next button: %s", next_btn)
        self.page.click(next_btn)
        # Wait for loader to disappear or new content to render
        if config.loader_selector:
            try:
                self.page.wait_for_selector(config.loader_selector, state="hidden", timeout=5000)
            except Exception:
                pass
        self.page.wait_for_timeout(800)  # Small buffer for JS execution

    def screenshot(self, path: str | Path) -> None:
        """Save a screenshot for debugging."""
        self.page.screenshot(path=str(path), full_page=True)

    def close(self) -> None:
        """Clean up browser resources."""
        logger.info("Closing browser")
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("Browser closed")
