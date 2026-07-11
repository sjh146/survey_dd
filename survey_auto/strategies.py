"""Answer strategy engine: loads YAML config and generates responses per question."""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any, Optional

import yaml

from survey_auto.models import Answer, Question, QuestionType, StrategyConfig

logger = logging.getLogger(__name__)

DEFAULT_TEXT = "테스트 응답입니다."
FALLBACK_TEXT = "해당없음"


def _load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML strategy file."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _select_option(options: list, strategy: dict[str, Any]) -> list[str]:
    """Select option values based on strategy settings."""
    if not options:
        return []

    select_mode = strategy.get("select", "random")
    values = [o.value for o in options]

    if select_mode == "first":
        return [values[0]]
    elif select_mode == "last":
        return [values[-1]]
    elif select_mode == "all":
        return values
    elif select_mode == "none":
        return []
    elif select_mode == "random":
        max_count = strategy.get("max", 1)
        min_count = strategy.get("min", 1)
        count = random.randint(min_count, min(max_count, len(values)))
        return random.sample(values, count)
    elif isinstance(select_mode, list):
        # Specific values list
        return [v for v in select_mode if v in values]
    else:
        return [random.choice(values)]


def _fill_text(strategy: dict[str, Any]) -> str:
    """Generate text content based on strategy settings."""
    fill_mode = strategy.get("fill", "dummy_text")
    if fill_mode == "dummy_text":
        return DEFAULT_TEXT
    elif fill_mode == "empty":
        return ""
    elif isinstance(fill_mode, str):
        return fill_mode  # Use the string directly
    return DEFAULT_TEXT


class StrategyEngine:
    """Generates answers for questions based on YAML strategy configuration."""

    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig(strategies={})

    @classmethod
    def from_yaml(cls, path: str | Path) -> "StrategyEngine":
        """Create a StrategyEngine from a YAML file."""
        data = _load_yaml(path)
        strategies = data.get("strategies", {})
        config = StrategyConfig(strategies=strategies)
        return cls(config)

    def get_answer(self, question: Question) -> Answer:
        """Generate an answer for the given question based on strategy config."""
        strategy = self._find_strategy(question)
        answer = Answer()

        if question.qtype in (QuestionType.SINGLE, QuestionType.MULTI, QuestionType.SCALE):
            selected = _select_option(question.options, strategy)
            answer.selected_values = selected
            answer.strategy_used = strategy.get("_matched_by", "default_fallback")

        if question.qtype == QuestionType.OPEN and question.text_inputs:
            text = _fill_text(strategy)
            for ti in question.text_inputs:
                answer.text_responses[ti.name] = text
            if not answer.strategy_used:
                answer.strategy_used = strategy.get("_matched_by", "default_fallback")

        return answer

    def _find_strategy(self, question: Question) -> dict[str, Any]:
        """Find the best matching strategy for a question.

        Priority: by_variable > by_type > default
        """
        strategies = self.config.strategies

        # 1. by_variable match
        by_variable = strategies.get("by_variable", {})
        if question.variable in by_variable:
            s = by_variable[question.variable]
            if isinstance(s, dict):
                s["_matched_by"] = f"by_variable:{question.variable}"
                return s

        # 2. by_type match
        by_type = strategies.get("by_type", {})
        qtype_key = question.qtype.value
        if qtype_key in by_type:
            s = by_type[qtype_key]
            if isinstance(s, dict):
                s["_matched_by"] = f"by_type:{qtype_key}"
                return s

        # 3. default match
        defaults = strategies.get("default", {})
        if qtype_key in defaults:
            s = defaults[qtype_key]
            if isinstance(s, dict):
                s["_matched_by"] = f"default:{qtype_key}"
                return s

        # 4. ultimate fallback
        fallback = {"select": "random", "fill": "dummy_text", "_matched_by": "ultimate_fallback"}
        return fallback
