"""CLI entry point for survey-auto using Click."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import click

from survey_auto.browser import BrowserManager
from survey_auto.executor import ActionExecutor
from survey_auto.models import Platform
from survey_auto.navigator import NavigationController
from survey_auto.parser import SurveyParser
from survey_auto.strategies import StrategyEngine
from survey_auto.self_improve import SelfImproveLoop

logger = logging.getLogger(__name__)

DEFAULT_STRATEGY_PATH = Path(__file__).resolve().parent.parent / "strategies" / "default.yaml"


def _setup_logging(verbose: bool, log_file: Optional[str] = None) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def _print_strategy_template() -> None:
    """Print the default strategy YAML template."""
    template = """# 설문 자동 응답 전략 설정 파일
# 우선순위: by_variable > by_type > default
strategies:
  by_variable:
    pass
  by_type:
    single: { select: "random" }
    multi: { select: "random", min: 1, max: 3 }
    open: { fill: "dummy_text" }
    scale: { select: "middle" }
    rank: { select: "random_order" }
    group: { select: "random" }
    combo: { select: "random" }
  default:
    single: { select: "random" }
    multi: { select: "random", min: 1 }
    open: { fill: "\ud14c\uc2a4\ud2b8 \uc751\ub2f5\uc785\ub2c8\ub2e4." }
    unknown: { select: "skip" }
"""
    click.echo(template)


@click.command()
@click.option("-u", "--url", default=None, help="Survey URL to automate")
@click.option(
    "-s", "--strategy",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to YAML strategy file",
)
@click.option("--visible", is_flag=True, help="Run browser in headed (visible) mode")
@click.option("--timeout", type=int, default=30, help="Page load timeout in seconds")
@click.option("--max-pages", type=int, default=500, help="Maximum pages to process")
@click.option("-o", "--output", type=click.Path(dir_okay=False), default=None, help="Log file path")
@click.option("--verbose", is_flag=True, help="Enable debug logging")
@click.option("--list-strategies", is_flag=True, help="Print strategy template and exit")
@click.option(
    "--platform", type=click.Choice(["auto", "kiwi", "surveymachine", "nielseniq"]),
    default="auto", help="Survey platform (auto-detect by default)",
)
@click.option("--self-improve", is_flag=True, help="Enable self-improving loop with auto-delegation")
@click.option("--daemon", is_flag=True, help="Run in daemon mode (infinite loop with work order monitoring)")
def run(
    url: Optional[str],
    strategy: Optional[str],
    visible: bool,
    timeout: int,
    max_pages: int,
    output: Optional[str],
    verbose: bool,
    list_strategies: bool,
    platform: str,
    self_improve: bool,
    daemon: bool,
) -> None:
    """Automate a survey: read questions, fill answers, navigate pages."""
    _setup_logging(verbose, output)

    if list_strategies:
        _print_strategy_template()
        sys.exit(0)

    if not url:
        click.echo("Error: -u/--url is required (unless --list-strategies is used)", err=True)
        sys.exit(1)

    # Map CLI platform string to Platform enum
    platform_map = {
        "auto": Platform.AUTO,
        "kiwi": Platform.KIWI,
        "surveymachine": Platform.SURVEY_MACHINE,
        "nielseniq": Platform.NIELSEN_IQ,
    }
    selected_platform = platform_map[platform]

    # Load strategy
    strategy_path = strategy or str(DEFAULT_STRATEGY_PATH)
    if Path(strategy_path).exists():
        strategy_engine = StrategyEngine.from_yaml(strategy_path)
        click.echo(f"Loaded strategy from: {strategy_path}")
    else:
        strategy_engine = StrategyEngine()
        click.echo("No strategy file found, using random fallback", err=True)

    if self_improve:
        loop = SelfImproveLoop(url=url, headless=not visible, timeout=timeout,
                               max_pages=max_pages, daemon=daemon)
        r = loop.run()
        ok = r.get("success", False) if isinstance(r, dict) else r
        msg = "completed" if ok else "failed"
        ai = r.get("ai_pages", 0) if isinstance(r, dict) else 0
        no_ai = r.get("no_ai_pages", 0) if isinstance(r, dict) else 0
        click.echo(f"Self-improve: {msg}")
        click.echo(f"  Pages solved by AI (DeepSeek): {ai}")
        click.echo(f"  Pages solved without AI (parser/executor/DOM): {no_ai}")
        sys.exit(0 if ok else 1)

    browser = BrowserManager(headless=not visible, timeout=timeout * 1000, platform=selected_platform)
    try:
        browser.start()
        browser.navigate(url)

        # Auto-detect platform if needed
        if selected_platform == Platform.AUTO:
            browser.detect_platform()
        current_platform = browser.platform
        click.echo(f"Platform: {current_platform.value}")

        # If not auto-detected yet, detect now
        if not browser.wait_for_question():
            click.echo("Failed to load survey page", err=True)
            sys.exit(1)

        navigator = NavigationController(browser.page, current_platform, max_pages=max_pages)
        executor = ActionExecutor(browser.page)

        click.echo(f"Starting survey at: {url}")
        click.echo(f"Max pages: {max_pages}")

        while True:
            # Parse current page
            html = browser.get_page_html()
            parser_platform = "surveymachine" if current_platform == Platform.SURVEY_MACHINE else "kiwi"
            parser = SurveyParser(html, platform=parser_platform)
            questions = parser.parse()

            if not questions:
                click.echo("No questions detected on current page")
                if navigator.is_survey_ended():
                    break

            # Generate and apply answers
            for q in questions:
                answer = strategy_engine.get_answer(q)
                click.echo(f"  {q.variable} ({q.qtype.value}): {answer.selected_values or '(text)'}")
                executor.fill_answers([q], [answer])

            # Navigate next
            if not navigator.next_page():
                break

            progress = navigator.get_progress()
            if progress is not None:
                click.echo(f"Progress: page {navigator.pages_visited}, {progress}%")

        click.echo("")
        if navigator.is_survey_ended():
            click.echo("Survey completed successfully!")
        else:
            click.echo(f"Stopped after {navigator.pages_visited} pages")

    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        navigator = NavigationController(browser.page, browser.platform)
        navigator.handle_error(browser, str(exc))
        sys.exit(1)
    finally:
        browser.close()


cli = run
