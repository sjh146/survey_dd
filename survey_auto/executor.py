"""DOM action executor: performs clicks, checks, and text input on the survey page."""

from __future__ import annotations

import logging
import random
import time
from typing import Optional

from playwright.sync_api import Page

from survey_auto.models import Answer, Option, Question, QuestionType

logger = logging.getLogger(__name__)

ACTION_DELAY = 0.1  # 100ms between actions for stability


def _radio_value_selector(variable: str, value: str) -> str:
    """Build CSS selector for a radio button by value."""
    return f'input[type="radio"][name="{variable}"][value="{value}"]'


def _checkbox_value_selector(variable: str, value: str) -> str:
    """Build CSS selector for a checkbox by value."""
    return f'input[type="checkbox"][name="{variable}_{value}"][value="{value}"]'


def _text_input_selector(name: str) -> str:
    """Build CSS selector for a text input by name."""
    return f'input[name="{name}"], textarea[name="{name}"]'


def _etc_input_selector(variable: str, value: str) -> str:
    """Build CSS selector for an 'etc' (기타) text input."""
    return f'input[name="T{variable}_{value}"]'


class ActionExecutor:
    """Executes answer actions on the survey page DOM."""

    def __init__(self, page: Page):
        self.page = page

    def fill_answers(self, questions: list[Question], answers: list[Answer]) -> None:
        """Apply all answers to the page DOM."""
        for question, answer in zip(questions, answers):
            try:
                self._apply_answer(question, answer)
            except Exception as exc:
                logger.warning("Failed to answer %s: %s", question.variable, exc)

    def _apply_answer(self, question: Question, answer: Answer) -> None:
        """Apply a single answer to the DOM."""
        if question.qtype == QuestionType.SINGLE:
            self._apply_single(question, answer)
        elif question.qtype == QuestionType.MULTI:
            self._apply_multi(question, answer)
        elif question.qtype == QuestionType.OPEN:
            self._apply_open(question, answer)
        elif question.qtype == QuestionType.SCALE:
            self._apply_single(question, answer)
        else:
            logger.info("Unsupported question type: %s", question.qtype)

    def _apply_single(self, question: Question, answer: Answer) -> None:
        """Select a radio button."""
        for selected in answer.selected_values:
            selector = _radio_value_selector(question.variable, selected)
            if self.page.locator(selector).count() > 0:
                self.page.click(selector)
                time.sleep(ACTION_DELAY)
                # Handle 'etc' field if present
                self._fill_etc_if_needed(question, selected, answer)
                logger.debug("Selected %s = %s", question.variable, selected)
            else:
                logger.warning("Radio %s not found for %s", selected, question.variable)

    def _apply_multi(self, question: Question, answer: Answer) -> None:
        """Check multiple checkboxes."""
        for selected in answer.selected_values:
            selector = _checkbox_value_selector(question.variable, selected)
            if self.page.locator(selector).count() > 0:
                self.page.check(selector)
                time.sleep(ACTION_DELAY)
                self._fill_etc_if_needed(question, selected, answer)
                logger.debug("Checked %s = %s", question.variable, selected)
            else:
                logger.warning("Checkbox %s not found for %s", selected, question.variable)

    def _apply_open(self, question: Question, answer: Answer) -> None:
        for text_input in (question.text_inputs or []):
            text = answer.text_responses.get(text_input.name, "")
            if text_input.input_type == "number":
                text = str(random.randint(1, 15))
            elif not text:
                text = "좋습니다"

            selectors = [
                f'input[name="{text_input.name}"], textarea[name="{text_input.name}"]',
            ]
            parts = text_input.name.rsplit("_", 1)
            if len(parts) == 2:
                selectors.append(f'input[inputtype="{text_input.input_type}"][index="{parts[1]}"]')

            for selector in selectors:
                if self.page.locator(selector).count() > 0:
                    self.page.fill(selector, text)
                    time.sleep(ACTION_DELAY)
                    logger.debug("Filled %s with %s", text_input.name, text)
                    break

    def _fill_etc_if_needed(self, question: Question, selected: str, answer: Answer) -> None:
        """Fill the 'etc' text field for an option if it exists."""
        # Check if this option is an etc option
        for opt in question.options:
            if opt.value == selected and opt.is_etc:
                etc_selector = _etc_input_selector(question.variable, selected)
                if self.page.locator(etc_selector).count() > 0:
                    # ETC field starts disabled; wait for it to become enabled after selection
                    try:
                        self.page.wait_for_function(
                            f"!document.querySelector('{etc_selector}').disabled",
                            timeout=3000,
                        )
                    except Exception:
                        pass
                    etc_text = answer.text_responses.get(f"T{question.variable}_{selected}", "기타 의견입니다.")
                    self.page.fill(etc_selector, etc_text)
                    time.sleep(ACTION_DELAY)
                    logger.debug("Filled etc for %s_%s", question.variable, selected)
