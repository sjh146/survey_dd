"""Survey question parser that extracts questions, options, and text inputs from DOM HTML.

Supports KiwiSurvey and SurveyMachine platforms.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from survey_auto.models import Option, Question, QuestionType, TextInput

logger = logging.getLogger(__name__)


# ── KiwiSurvey helpers (original) ──────────────────────────────────


def _has_etc_input(html_fragment: str, value: str, variable: str) -> bool:
    """Check if an option has an associated 'etc' (기타) text input field."""
    pattern = re.compile(
        r'input[^>]*name=["'']T' + re.escape(variable) + r'_' + re.escape(value) + r'["'']',
        re.IGNORECASE,
    )
    return bool(pattern.search(html_fragment))


def _has_none_flag(html_fragment: str) -> bool:
    """Check if an option has data-none='1' attribute."""
    return 'data-none="1"' in html_fragment or "data-none='1'" in html_fragment


def _extract_options_radio(html: str, variable: str) -> list[Option]:
    """Extract options from radio button groups (SINGLE type)."""
    options: list[Option] = []
    pattern = re.compile(
        r'<input[^>]*type=["'']radio["''][^>]*name=["'']'
        + re.escape(variable)
        + r'["''][^>]*value=["'']([^"'']+)["''][^>]*>',
        re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        value = match.group(1)
        surrounding = _get_surrounding_label(html, match.start(), variable, value)
        is_etc = _has_etc_input(html, value, variable)
        options.append(Option(value=value, label=surrounding, is_etc=is_etc))
    return options


def _extract_options_checkbox(html: str, variable: str) -> list[Option]:
    """Extract options from checkbox groups (MULTI type)."""
    options: list[Option] = []
    pattern = re.compile(
        r'<input[^>]*type=["'']checkbox["''][^>]*name=["'']'
        + re.escape(variable) + r'_(\d+)["''][^>]*value=["'']([^"'']+)["''][^>]*>',
        re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        value = match.group(2)
        chunk = html[max(0, match.start() - 200): match.end() + 200]
        is_none = _has_none_flag(chunk)
        is_etc = _has_etc_input(html, value, variable)
        label = _extract_label_from_chunk(chunk, variable, value)
        options.append(Option(value=value, label=label, is_etc=is_etc, is_none=is_none))
    return options


def _get_surrounding_label(html: str, input_start: int, variable: str, value: str) -> str:
    """Extract label text near an input element."""
    chunk = html[max(0, input_start - 500): input_start + 500]
    return _extract_label_from_chunk(chunk, variable, value)


def _extract_label_from_chunk(chunk: str, variable: str, value: str) -> str:
    """Extract option label text from an HTML chunk."""
    span_match = re.search(r'<span[^>]*>(.*?)</span>', chunk)
    if span_match:
        text = span_match.group(1)
        text = re.sub(r'<[^>]+>', '', text).strip()
        if text:
            return text
    text = re.sub(r'<[^>]+>', ' ', chunk).strip()
    text = re.sub(r'\s+', ' ', text)
    return text[:100].strip()


def _find_text_inputs(html: str, variable: str) -> list[TextInput]:
    """Find text input fields (OPEN type)."""
    inputs: list[TextInput] = []
    pattern = re.compile(
        r'<(input|textarea)[^>]*name=["'']' + re.escape(variable) + r'_(\d+)["''][^>]*>',
        re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        name = variable + "_" + match.group(2)
        tag = match.group(1)
        chunk = html[max(0, match.start() - 300): match.end() + 100]
        input_type = "text"
        type_match = re.search(r'type=["''](\w+)["'']', match.group(0))
        if type_match:
            input_type = type_match.group(1)
        if tag.lower() == "textarea":
            input_type = "textarea"
        must = "must=" in chunk or "required" in chunk
        label = ""
        label_match = re.search(r'placeholder=["'']([^"'']+)["'']', match.group(0))
        if label_match:
            label = label_match.group(1)
        else:
            prev_text = chunk[:match.start() - max(0, match.start() - 300)]
            label = re.sub(r'<[^>]+>', ' ', prev_text).strip()[-50:]
        inputs.append(TextInput(name=name, label=label.strip(), must=must, input_type=input_type))
    return inputs


def _get_max_select(html: str) -> Optional[int]:
    """Try to extract max selection count from survey data attributes."""
    max_match = re.search(r'max=["''](\d+)["'']', html)
    if max_match:
        return int(max_match.group(1))
    return None


def _detect_question_type(html: str) -> QuestionType:
    """Detect the question type from HTML content."""
    html_lower = html.lower()
    if 'type="radio"' in html_lower or "type='radio'" in html_lower:
        return QuestionType.SINGLE
    if 'type="checkbox"' in html_lower or "type='checkbox'" in html_lower:
        return QuestionType.MULTI
    if 'type="text"' in html_lower or 'type="number"' in html_lower or '<textarea' in html_lower:
        return QuestionType.OPEN
    if 'type="range"' in html_lower or 'class="scalebtn"' in html_lower or 'scalebtn' in html_lower:
        return QuestionType.SCALE
    if 'class="rank' in html_lower:
        return QuestionType.RANK
    return QuestionType.UNKNOWN


def _extract_variable(html: str) -> Optional[str]:
    """Extract the question variable name from HTML."""
    for pattern in [
        r'<input[^>]*type=["'']radio["''][^>]*name=["''](\w+)["'']',
        r'<input[^>]*type=["'']checkbox["''][^>]*name=["''](\w+)_\d+["'']',
        r'<input[^>]*type=["''](?:text|number)["''][^>]*name=["''](\w+)_\d+["'']',
    ]:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


# ── SurveyMachine parser ──────────────────────────────────────────


def _sm_extract_questions(html: str) -> list[Question]:
    """Parse SurveyMachine #vb_application HTML into Question objects.

    SurveyMachine structure:
      .questionBox > .questionNum (e.g. "Q3."), .questionText
      .answerBox.radioset / .checkboxset  > table.table-survey > tbody > tr > td > input
    """
    questions: list[Question] = []

    # Find all answerBox elements and their preceding questionBox
    answer_boxes = list(re.finditer(
        r'<div[^>]*class=["'']answerBox\s+(\w+)["''][^>]*>(.*?)</div>\s*</div>',
        html,
        re.IGNORECASE | re.DOTALL,
    ))

    for box_match in answer_boxes:
        box_html = box_match.group(0)
        answer_type = box_match.group(1)  # radioset, checkboxset, etc.

        # Extract variable name from inputs
        variable = _extract_variable(box_html)
        if not variable:
            continue

        # Determine question type
        if answer_type == "checkboxset" or "type=\"checkbox\"" in box_html.lower():
            qtype = QuestionType.MULTI
        elif answer_type == "radioset" or "type=\"radio\"" in box_html.lower():
            # Count unique radio values to distinguish SINGLE vs SCALE
            radio_values = set(re.findall(
                r'<input[^>]*type=["'']radio["''][^>]*value=["''](\d+)["'']',
                box_html,
            ))
            if len(radio_values) >= 5:
                qtype = QuestionType.SCALE
            else:
                qtype = QuestionType.SINGLE
        elif "type=\"text\"" in box_html.lower() or "textarea" in box_html.lower():
            qtype = QuestionType.OPEN
        else:
            qtype = QuestionType.UNKNOWN

        # Extract options from table cells
        options = _sm_extract_options(box_html, variable)

        # Extract title from preceding questionBox
        title = _sm_find_question_title(html, box_match.start())

        questions.append(Question(
            variable=variable,
            qtype=qtype,
            options=options,
            title=title,
        ))

    # Fallback: if no answerBox found, try generic detection
    if not questions:
        variable = _extract_variable(html)
        if variable:
            qtype = _detect_question_type(html)
            if qtype == QuestionType.SINGLE:
                options = _extract_options_radio(html, variable)
            elif qtype == QuestionType.MULTI:
                options = _extract_options_checkbox(html, variable)
            else:
                options = []
            title = _sm_find_question_title(html, 0)
            questions.append(Question(
                variable=variable, qtype=qtype, options=options, title=title,
            ))

    return questions


def _sm_extract_options(box_html: str, variable: str) -> list[Option]:
    """Extract options from a SurveyMachine answer box HTML."""
    options: list[Option] = []

    # Find all input elements with their labels
    # Pattern: <td>...<input ... value="X">...<label>...</label>...</td>
    td_pattern = re.compile(
        r'<td[^>]*>(.*?)</td>',
        re.IGNORECASE | re.DOTALL,
    )

    for td_match in td_pattern.finditer(box_html):
        td_html = td_match.group(1)

        # Find input
        input_match = re.search(
            r'<input[^>]*type=["''](?:radio|checkbox)["''][^>]*value=["'']([^"'']+)["''][^>]*>',
            td_html,
            re.IGNORECASE,
        )
        if not input_match:
            continue

        value = input_match.group(1)

        # Extract label text
        label = ""
        # Try <label> text
        label_tag = re.search(r'<label[^>]*>(.*?)</label>', td_html, re.DOTALL)
        if label_tag:
            label = re.sub(r'<[^>]+>', '', label_tag.group(1)).strip()
        else:
            # Get text from <th> row
            label = re.sub(r'<[^>]+>', ' ', td_html).strip()

        label = re.sub(r'\s+', ' ', label).strip()
        options.append(Option(value=value, label=label[:100]))

    return options


def _sm_find_question_title(html: str, near_pos: int) -> str:
    """Find the question title text from a nearby .questionBox."""
    # Look backwards from near_pos for .questionBox
    before = html[:near_pos]
    qbox_match = re.search(
        r'<div[^>]*class=["'']questionBox["''][^>]*>(.*?)</div>\s*</div>',
        before,
        re.IGNORECASE | re.DOTALL,
    )
    if qbox_match:
        qbox_html = qbox_match.group(1)
        # Remove questionNum
        qbox_html = re.sub(r'<div[^>]*class=["'']questionNum["''][^>]*>.*?</div>', '', qbox_html, flags=re.DOTALL)
        title = re.sub(r'<[^>]+>', '', qbox_html).strip()
        title = re.sub(r'\s+', ' ', title)
        return title[:200]
    return ""


# ── Main parser (platform-aware) ──────────────────────────────────


class SurveyParser:
    """Parses survey question HTML into structured Question objects.

    Supports both KiwiSurvey and SurveyMachine HTML formats.
    """

    def __init__(self, html: str, platform: str = "kiwi"):
        self.html = html
        self.platform = platform

    def parse(self) -> list[Question]:
        """Parse the HTML and return a list of identified questions."""
        if not self.html or not self.html.strip():
            logger.info("Empty HTML, no questions to parse")
            return []

        if self.platform == "surveymachine":
            return self._parse_surveymachine()

        return self._parse_kiwi()

    def _parse_surveymachine(self) -> list[Question]:
        """Parse SurveyMachine format HTML."""
        return _sm_extract_questions(self.html)

    def _parse_kiwi(self) -> list[Question]:
        """Parse KiwiSurvey format HTML."""
        variable = _extract_variable(self.html)
        if not variable:
            logger.info("No question variable found in HTML")
            return []

        qtype = _detect_question_type(self.html)
        title = self._extract_title_kiwi()

        if qtype == QuestionType.SINGLE:
            options = _extract_options_radio(self.html, variable)
            return [Question(variable=variable, qtype=qtype, options=options, title=title)]

        elif qtype == QuestionType.MULTI:
            options = _extract_options_checkbox(self.html, variable)
            max_select = _get_max_select(self.html)
            return [Question(variable=variable, qtype=qtype, options=options, max_select=max_select, title=title)]

        elif qtype == QuestionType.OPEN:
            text_inputs = _find_text_inputs(self.html, variable)
            return [Question(variable=variable, qtype=qtype, text_inputs=text_inputs, title=title)]

        else:
            options = _extract_options_radio(self.html, variable)
            text_inputs = _find_text_inputs(self.html, variable)
            return [Question(variable=variable, qtype=qtype, options=options, text_inputs=text_inputs or None, title=title)]

    def _extract_title_kiwi(self) -> str:
        """Extract KiwiSurvey question title from HTML."""
        title_match = re.search(
            r'<div[^>]*id=["'']qtitle["''][^>]*>(.*?)</div>',
            self.html,
            re.IGNORECASE | re.DOTALL,
        )
        if title_match:
            text = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
            return text
        return ""
