"""Data models for survey-auto: question types, options, platform config, and strategy configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class QuestionType(str, Enum):
    """Enumeration of supported survey question types."""

    SINGLE = "single"
    MULTI = "multi"
    OPEN = "open"
    SCALE = "scale"
    RANK = "rank"
    GROUP = "group"
    COMBO = "combo"
    UNKNOWN = "unknown"


class Platform(str, Enum):
    """Supported survey platforms."""

    KIWI = "kiwi"
    SURVEY_MACHINE = "surveymachine"
    NIELSEN_IQ = "nielseniq"
    QUALTRICS = "qualtrics"
    AUTO = "auto"


@dataclass
class SurveyConfig:
    """Platform-specific selectors and settings."""

    question_container: str
    next_button: str
    prev_button: str = ""
    loader_selector: str = ""
    progress_selector: str = ""
    end_patterns: tuple = ()


# Platform configuration registry
PLATFORM_CONFIGS: dict[Platform, SurveyConfig] = {
    Platform.KIWI: SurveyConfig(
        question_container="#question_body",
        next_button="#next",
        loader_selector="#loader",
        progress_selector="#kiwi_progress .progAct",
        end_patterns=("SurveyEnd.asp", "surveyend.asp", "END"),
    ),
    Platform.SURVEY_MACHINE: SurveyConfig(
        question_container="#vb_application",
        next_button="#btn_next",
        prev_button="#btn_prev",
        loader_selector="",
        progress_selector=".progressbar .bar",
        end_patterns=("END", "complete"),
    ),
    Platform.NIELSEN_IQ: SurveyConfig(
        question_container=".survey-body",
        next_button="button.next, input[type=submit], .btn-next",
        prev_button="button.prev, .btn-prev",
        loader_selector=".loading, .survey-loading",
        progress_selector=".progress-bar, .survey-progress",
        end_patterns=("complete", "thank", "END"),
    ),
    Platform.QUALTRICS: SurveyConfig(
        question_container="#Questions",
        next_button="#NextButton",
        prev_button="#PreviousButton",
        loader_selector="",
        progress_selector="",
        end_patterns=("surveyend", "endofsurvey", "complete", "EndOfSurvey"),
    ),
}


@dataclass
class Option:
    """A single selectable option within a question."""

    value: str
    label: str
    is_etc: bool = False
    is_none: bool = False


@dataclass
class TextInput:
    """A text input field for open-ended questions."""

    name: str
    label: str = ""
    must: bool = False
    input_type: str = "text"


@dataclass
class Answer:
    """The generated answer for a single question."""

    selected_values: list[str] = field(default_factory=list)
    text_responses: dict[str, str] = field(default_factory=dict)
    strategy_used: str = ""


@dataclass
class Question:
    """Represents a single survey question parsed from the DOM."""

    variable: str
    qtype: QuestionType
    options: list[Option] = field(default_factory=list)
    text_inputs: Optional[list[TextInput]] = None
    max_select: Optional[int] = None
    title: str = ""


class StrategyConfig(BaseModel):
    """Configuration model for answer strategies loaded from YAML."""

    strategies: dict = {}
    model_config = {"extra": "allow"}
