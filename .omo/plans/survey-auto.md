# survey-auto - Work Plan

## TL;DR (For humans)

**What you'll get:** A Python CLI tool (`survey-auto`) that opens the KiwiSurvey URL in Firefox, reads each question on every page (radio buttons, checkboxes, text inputs), automatically fills in answers based on a YAML config file or random choice, then clicks "Next" — repeating until the survey ends. One command and you're done.

**Why this approach:** CLI is dead-simple (no web server, no DB). YAML config keeps answers flexible without touching code. Playwright Firefox handles the dynamic JavaScript survey pages reliably.

**What it will NOT do:** No web dashboard, no database, no captcha bypass, no parallel surveys, no result analysis — just fill and submit.

**Effort:** Medium
**Risk:** Low — Playwright + Firefox is proven, the survey DOM is well-understood
**Decisions to sanity-check:** (1) YAML strategy format, (2) question-type detection heuristics

Your next move: approve and start work.

---

> TL;DR (machine): Effort=Medium, Risk=Low, Deliverables=Python CLI `survey-auto` with Playwright Firefox + YAML strategy config for KiwiSurvey automation

## Scope
### Must have
- Playwright Firefox 기반 설문 자동화 CLI
- Single(radio), Multi(checkbox), Open(text) 3대 질문 유형 지원
- Scale, Rank, Group, Combo 기본 지원
- YAML 설정 파일로 질문별 응답 전략 지정 (변수명 매칭, 유형별 기본값, 랜덤 폴백)
- `--url`, `--strategy`, `--visible`, `--headless` CLI 옵션
- 페이지 로딩 대기, 진행률 표시, 완료 로그
- 오류 발생 시 재시도 + graceful 종료
- 예외 상황 stderr 로깅

### Must NOT have (guardrails, anti-slop, scope boundaries)
- ❌ 웹 서비스 / API 서버 구축
- ❌ 데이터베이스 저장 (SQLite/PostgreSQL 등)
- ❌ captcha/봇 차단 우회 또는 불법 우회 시도
- ❌ GUI/웹 대시보드
- ❌ 멀티 프로젝트 병렬 실행
- ❌ 설문 데이터 수집/분석 (원본 설문만 자동 응답)
- ❌ 250라인 초과 모듈 금지 (분할 필수)

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- **Test decision**: tests-after + manual smoke test
- **Framework**: `pytest` + `pytest-playwright` (unit), 직접 URL 실행 (integration)
- **Evidence**: `.omo/evidence/task-<N>-survey-auto.<ext>`

## Execution strategy
### Parallel execution waves
| Wave | Tasks | 성격 |
|---|---|---|
| 1 | T1, T2 | Foundation — 프로젝트 구조 + 데이터 모델 |
| 2 | T3, T4, T5, T6, T7 | Core — 병렬 개발 가능한 독립 컴포넌트 |
| 3 | T8, T9 | Integration — CLI 오케스트레이터 + 전략 파일 |
| 4 | F1~F4 | Final verification |

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
|---|---|---|---|
| T1. Project setup | — | T2~T9 | — |
| T2. Data models | T1 | T3~T7 | — |
| T3. Browser engine | T1, T2 | T8 | T4, T5, T6, T7 |
| T4. Question parser | T1, T2 | T8 | T3, T5, T6, T7 |
| T5. Answer strategy | T1, T2 | T8 | T3, T4, T6, T7 |
| T6. Action executor | T1, T2 | T8 | T3, T4, T5, T7 |
| T7. Navigation controller | T1, T2 | T8 | T3, T4, T5, T6 |
| T8. CLI + Orchestrator | T3~T7 | — | T9 |
| T9. Default strategy | T1 | — | T3~T7 |

## Todos
> Implementation + self-test = ONE todo.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->

### Wave 1: Foundation

- [ ] 1. 프로젝트 구조 및 의존성 설정
  **What to do / Must NOT do:**
  - `survey/` 디렉토리 내에 다음 구조 생성:
    ```
    survey/
    ├── survey_auto/
    │   ├── __init__.py
    │   ├── cli.py
    │   ├── browser.py
    │   ├── parser.py
    │   ├── strategies.py
    │   ├── executor.py
    │   ├── navigator.py
    │   └── models.py
    ├── strategies/
    │   └── default.yaml
    ├── main.py              # `python main.py ...` 진입
    ├── pyproject.toml
    └── .omo/
    ```
  - `pyproject.toml`에 의존성 명시: `playwright>=1.40`, `click>=8.0`, `pyyaml>=6.0`, `pydantic>=2.0`
  - `pip install -e .` 가능하도록 구성
  - Must NOT: `__pycache__` / `.pyc` 커밋 금지, `.gitignore`는 생성하지 않음 (git repo 아님)
  
  **Parallelization:** Wave 1 | Blocked by: — | Blocks: T2~T9
  **References:** `pyproject.toml` 포맷은 PEP 621; `survey_auto/__init__.py`는 빈 파일
  **Acceptance criteria:** `python -c "import survey_auto; print('ok')"` 가 OK 출력
  **QA scenarios:** happy: 위 import 명령 성공; failure: 의존성 미설치 시 ImportError 확인
  **Evidence:** `.omo/evidence/task-1-survey-auto.log`
  **Commit:** Y | `chore(survey-auto): initialize project structure`

- [ ] 2. 데이터 모델 (survey_auto/models.py)
  **What to do / Must NOT do:**
  - `QuestionType` Enum: `SINGLE`, `MULTI`, `OPEN`, `SCALE`, `RANK`, `GROUP`, `COMBO`, `UNKNOWN`
  - `Question` dataclass: `variable: str`, `qtype: QuestionType`, `options: list[Option]`, `text_inputs: list[TextInput]`, `max_select: int | None`, `title: str`
  - `Option` dataclass: `value: str`, `label: str`, `is_etc: bool`, `is_none: bool`
  - `TextInput` dataclass: `name: str`, `label: str`, `must: bool`, `input_type: str` (text/number/han/tel 등)
  - `StrategyConfig` Pydantic model: 질문별 변수 매칭, 유형별 기본값, 글로벌 기본값
  - `SurveyState` dataclass: URL, 현재 페이지 변수명, 진행률, 완료 여부
  - Must NOT: Pydantic v1 문법 사용 금지 (v2 @field_validator 사용)
  
  **Parallelization:** Wave 1 | Blocked by: T1 | Blocks: T3~T7
  **References:** `single.js`의 `single_page_logic()`, `multi.js`의 `multi_page_logic()`, `open.js`의 `open_page_logic()`
  **Acceptance criteria:** `python -c "from survey_auto.models import QuestionType, Question, Option, TextInput, StrategyConfig; print('ok')"`
  **QA scenarios:** happy: 모든 클래스 import + 인스턴스 생성; failure: 잘못된 Enum 값 검증
  **Evidence:** `.omo/evidence/task-2-survey-auto.log`
  **Commit:** Y | `feat(survey-auto): add data models for questions and strategy config`

### Wave 2: Core Components (병렬 개발)

- [ ] 3. 브라우저 엔진 (survey_auto/browser.py)
  **What to do / Must NOT do:**
  - `BrowserManager` 클래스: Firefox launch (headless 기본, `visible=True` 시 headed)
  - `navigate(url)` → 페이지 로딩 완료 대기 (networkidle)
  - `wait_for_question()` → `#question_body`에 자식 노드 생길 때까지 대기 (최대 timeout)
  - `get_page_html()` → 현재 `#question_body`의 innerHTML 반환
  - `click_next()` → `#next` 버튼 클릭 후 새 페이지 로딩 대기
  - `close()` → 브라우저/컨텍스트 정리
  - `screenshot(path)` → 디버깅용 스크린샷 저장
  - Must NOT: chromium/webkit 사용 금지, 메모리 누수 방지를 위해 `async with` 패턴
  
  **Parallelization:** Wave 2 | Blocked by: T1, T2 | Blocks: T8
  **References:** `Question.asp` HTML 구조: `#next` 버튼, `#question_body`, `#loader` 오버레이
  **Acceptance criteria:** `python -c "from survey_auto.browser import BrowserManager; b=BrowserManager(); b.navigate('https://kon.kiwisurvey.kr/project/2606009_B/Question.asp'); print(b.wait_for_question()); b.close()"` 가 True/False 반환
  **QA scenarios:** happy: URL 접속 후 질문 body 렌더링 확인; failure: 잘못된 URL → 예외 처리 확인, 타임아웃 처리 확인
  **Evidence:** `.omo/evidence/task-3-survey-auto.log`
  **Commit:** Y | `feat(survey-auto): implement Firefox browser engine`

- [ ] 4. 질문 파서 (survey_auto/parser.py)
  **What to do / Must NOT do:**
  - `SurveyParser` 클래스, 입력: HTML 문자열 (BrowserManager.get_page_html())
  - `parse()` → `list[Question]` 반환 (한 페이지에 여러 질문 가능)
  - 감지 로직 (CSS 셀렉터 우선순위):
    1. `input[type=radio]` 존재 → SINGLE
    2. `input[type=checkbox]` 존재 → MULTI (`max` 값은 MM1~MM4의 `option.max || ""` 참조)
    3. `input[type=text], input[type=number], textarea` 존재 → OPEN
    4. `input[type=range], .scaleBtn` → SCALE
    5. `.rankBtn, .rank-list` → RANK
    6. 그 외 → UNKNOWN
  - 각 Option 추출: `value`, `label`, `is_etc` (옆에 `input[name^=T...]` 존재 여부), `is_none` (data-none=1)
  - 각 TextInput 추출: `name`, `label` (앞의 span/label 텍스트), `must` (옆에 필수 표시), `input_type` (onkeyup 패턴 분석)
  - Must NOT: 잘못된 CSS 셀렉터 사용 금지, 250라인 초과 금지
  
  **Parallelization:** Wave 2 | Blocked by: T1, T2 | Blocks: T8
  **References:** `single.js` SM1/SM2/SM3 렌더링 패턴, `multi.js` MM1/MM2/MM3/MM4 렌더링 패턴, `open.js` OM1/OM2/OM3/OM4 렌더링 패턴
  **Acceptance criteria:** `python -c "from survey_auto.parser import SurveyParser; p=SurveyParser('<html>...</html>'); qs=p.parse(); print(len(qs))"` 가 0 이상 정수 반환 (실제 HTML로 테스트)
  **QA scenarios:** happy: single.html/multi.html/open.html 각각 파싱 정확성; failure: 빈 HTML, 질문 없는 페이지, 알 수 없는 구조
  **Evidence:** `.omo/evidence/task-4-survey-auto.log`
  **Commit:** Y | `feat(survey-auto): implement survey question parser from DOM`

- [ ] 5. 응답 전략 엔진 (survey_auto/strategies.py)
  **What to do / Must NOT do:**
  - `StrategyEngine` 클래스, 생성자에 `config: StrategyConfig`
  - `load_yaml(path)` → YAML 파일 로드 → `StrategyConfig` 변환
  - `get_answer(question: Question)` → `Answer` 반환
  - Answer dataclass: `selected_values: list[str]`, `text_responses: dict[str, str]`, `_strategy_used: str`
  - YAML 구조:
    ```yaml
    strategies:
      by_variable:
        SQ01: { select: "first" }            # 변수명 직접 매칭
        MQ01: { select: "random", max: 2 }   # 랜덤 2개
      by_type:
        single: { select: "random" }
        multi: { select: "random", min: 1, max: 2 }
        open: { fill: "dummy_text" }
      default:
        single: { select: "random" }
        multi: { select: "random", min: 1 }
        open: { fill: "테스트 응답입니다." }
        scale: { select: "middle" }
        rank: { select: "random_order" }
    ```
  - `select` 옵션: `first`, `last`, `random`, `all`, `none`, 또는 특정 값 리스트
  - `fill` 옵션: `dummy_text`(질문 기반 생성), 고정 문자열, `random_chars`(길이 지정)
  - 매칭 우선순위: `by_variable[question.variable]` > `by_type[question.qtype]` > `default[question.qtype]`
  - 최종 폴백: SINGLE/MULTI → random, OPEN → "테스트 응답입니다."
  - Must NOT: 파일 I/O 실패 시 프로그램 중단 금지 (fallback 적용)
  
  **Parallelization:** Wave 2 | Blocked by: T1, T2 | Blocks: T8
  **References:** `models.py`의 `StrategyConfig`
  **Acceptance criteria:** `python -c "from survey_auto.strategies import StrategyEngine; e=StrategyEngine(); a=e.get_answer(question); print(a.selected_values)"` 가 적절한 응답 반환
  **QA scenarios:** happy: YAML 로드 + 질문 매칭 + 응답 생성; failure: 잘못된 YAML→fallback, 매칭 없는 질문→random fallback
  **Evidence:** `.omo/evidence/task-5-survey-auto.log`
  **Commit:** Y | `feat(survey-auto): implement YAML-based answer strategy engine`

- [ ] 6. 액션 실행기 (survey_auto/executor.py)
  **What to do / Must NOT do:**
  - `ActionExecutor` 클래스, `page` 객체 주입
  - `fill_answers(questions: list[Question], answers: list[Answer])` → 각 질문에 순차 적용
  - SINGLE 처리:
    - `page.click('input[type=radio][value="X"]')`으로 선택
    - 기타 필드면 `page.fill('input[name="TVARIABLE_X"]', text)` 후 활성화 확인
  - MULTI 처리:
    - `page.check('input[type=checkbox][value="X"]')`으로 복수 선택
    - `max` 초과 방지 (데이터 속성 확인)
    - `data-none="1"` 항목 선택 시 다른 항목 해제 (JS 동작) - Playwright로 한 번에 체크하지 않고 순차 처리
  - OPEN 처리:
    - `page.fill('input[name="VARIABLE_KEY"]', text)` 또는 `page.fill('textarea[name="VARIABLE_KEY"]', text)`
  - SCALE 처리:
    - `.scaleBtn` 내부의 `input[type=radio]` 클릭
  - RANK 처리:
    - 드래그 또는 select 옵션 변경 (랭크 유형에 따라)
  - 각 액션 전후 100ms 대기 (페이지 안정성)
  - Must NOT: disabled 요소 강제 클릭 금지, `page.evaluate()`로 JS 우회 금지
  
  **Parallelization:** Wave 2 | Blocked by: T1, T2 | Blocks: T8
  **References:** `single.js`의 `etcRadio()`, `multi.js`의 `etcCheck()`, `noneCheck()` 함수 동작
  **Acceptance criteria:** Mock page object로 `fill_answers()` 호출 시 각 요소에 올바른 action 실행 확인
  **QA scenarios:** happy: 각 유형별 정상 실행; failure: disabled 요소 → skip 로깅, 존재하지 않는 요소 → graceful skip
  **Evidence:** `.omo/evidence/task-6-survey-auto.log`
  **Commit:** Y | `feat(survey-auto): implement DOM action executor`

- [ ] 7. 내비게이션 컨트롤러 (survey_auto/navigator.py)
  **What to do / Must NOT do:**
  - `NavigationController` 클래스, `page` 객체 주입
  - `next_page()`:
    1. `page.click('#next')` 클릭
    2. 최대 timeout(30s)까지 `#loader` 오버레이 사라짐 + 새 `#question_body` 렌더링 대기
    3. 설문 종료 감지: `SurveyEnd.asp` URL 리디렉션 OR `#question_body` 비어있음
  - `is_survey_ended()` → 종료 조건 확인 (현재 URL, body 상태)
  - `get_progress()` → `#kiwi_progress .progAct` 개수로 진행률 추정
  - `handle_error(page)` → 오류 발생 시 스크린샷 저장 + 재시도 (최대 2회)
  - Must NOT: 무한 루프 금지 (최대 페이지 500 제한), 재시도 실패 시 무시 금지 (예외 발생)
  
  **Parallelization:** Wave 2 | Blocked by: T1, T2 | Blocks: T8
  **References:** `Question.asp`의 `#next` click handler: `page_logic()` → `kon.survey.save()` → `form.submit()`; `SurveyEnd.asp` 종료 페이지
  **Acceptance criteria:** Mock page으로 `next_page()` 호출 시 `#next` 클릭 + 대기 로직 실행 확인
  **QA scenarios:** happy: 정상 페이지 이동; failure: 네트워크 오류→재시도, 설문 종료→`is_survey_ended()=True`
  **Evidence:** `.omo/evidence/task-7-survey-auto.log`
  **Commit:** Y | `feat(survey-auto): implement survey page navigation controller`

### Wave 3: Integration

- [ ] 8. CLI 진입점 + 오케스트레이터 (survey_auto/cli.py + main.py)
  **What to do / Must NOT do:**
  - `main.py`: `from survey_auto.cli import cli; cli()` 진입
  - `cli.py`: Click 기반 CLI
    - `@click.command()` → `run` 서브커맨드 (기본)
    - 옵션:
      - `--url`, `-u` (필수): 설문 URL
      - `--strategy`, `-s` (선택): YAML 전략 파일 경로
      - `--visible` (플래그): headed 모드 (기본 headless)
      - `--timeout` (선택, 기본 30): 페이지 로딩 타임아웃(초)
      - `--max-pages` (선택, 기본 500): 최대 페이지 제한
      - `--output`, `-o` (선택): 로그 파일 경로
      - `--list-strategies` (플래그): 내장 전략 템플릿 출력 후 종료
  - 오케스트레이션 루프:
    ```
    browser.navigate(url)
    while not navigator.is_survey_ended() and pages < max_pages:
        questions = parser.parse(browser.get_page_html())
        answers = [strategy.get_answer(q) for q in questions]
        executor.fill_answers(questions, answers)
        navigator.next_page()
        pages += 1
        log_progress(pages, navigator.get_progress())
    log_completion()
    browser.close()
    ```
  - 로깅: INFO(진행), WARNING(재시도), ERROR(치명적 오류), 결과 JSON 출력
  - Must NOT: Click decorator 중복 사용 금지, 250라인 초과 시 `orchestrator.py`로 분리
  
  **Parallelization:** Wave 3 | Blocked by: T3, T4, T5, T6, T7 | Blocks: —
  **References:** 모든 상위 태스크의 인터페이스
  **Acceptance criteria:** `python main.py --url https://kon.kiwisurvey.kr/project/2606009_B/Question.asp --visible --max-pages 1` 이 1페이지 실행 후 로그 출력
  **QA scenarios:** happy: 1페이지 실행 완료; failure: 잘못된 URL→에러 메시지, 전략 파일 없음→fallback 경고+계속 진행
  **Evidence:** `.omo/evidence/task-8-survey-auto.log`
  **Commit:** Y | `feat(survey-auto): implement CLI entry point and survey orchestrator`

- [ ] 9. 기본 전략 YAML 파일 (strategies/default.yaml)
  **What to do / Must NOT do:**
  - `strategies/default.yaml` 생성
  - 모든 질문 유형별 기본 전략 정의 (상세 주석 포함)
  - 샘플 전략 설명 및 사용법 주석
  - 예시:
    ```yaml
    # 설문 자동 응답 전략 설정 파일
    # 우선순위: by_variable > by_type > default
    strategies:
      by_variable:
        # 특정 변수명에 대한 직접 지정
        # SQ01: { select: "first" }
        # MQ01: { select: "random", max: 2 }
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
        open: { fill: "테스트 응답입니다." }
        unknown: { select: "skip" }
    ```
  - `--list-strategies` 명령어로 이 파일 내용 출력 가능하게 연결
  - Must NOT: 실행 불가능한 전략 포함 금지
  
  **Parallelization:** Wave 3 | Blocked by: T1 | Blocks: —
  **References:** `survey_auto/strategies.py`의 `StrategyEngine` YAML 포맷
  **Acceptance criteria:** `python -c "import yaml; yaml.safe_load(open('strategies/default.yaml')); print('valid')"` 가 valid 출력
  **QA scenarios:** happy: YAML 파싱 성공; failure: 문법 오류→schemas.validate 실패
  **Evidence:** `.omo/evidence/task-9-survey-auto.log`
  **Commit:** Y | `feat(survey-auto): add default strategy YAML configuration`

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.

- [ ] F1. Plan compliance audit
  - 각 todo의 acceptance criteria 검증
  - 모든 파일이 계획된 위치에 생성되었는지 확인 (`ls survey_auto/ strategies/ main.py pyproject.toml`)
  - 250라인 초과 모듈 없는지 확인 (`wc -l survey_auto/*.py`)
  - Evidence: `.omo/evidence/f1-compliance.log`

- [ ] F2. Code quality review
  - `import` 순서, 타입 힌트, docstring 존재 여부
  - `try/except` 오류 처리 적절성
  - 하드코딩된 값 최소화
  - Evidence: `.omo/evidence/f2-quality.log`

- [ ] F3. Real manual QA (실제 URL 1페이지 실행)
  - `python main.py --url https://kon.kiwisurvey.kr/project/2606009_B/Question.asp --visible --max-pages 1`
  - 실행 결과 검증: 질문 파싱, 응답 입력, 다음 페이지 이동 성공
  - Evidence: `.omo/evidence/f3-qa.log` + 스크린샷

- [ ] F4. Scope fidelity
  - Must have 목록 모두 충족 확인
  - Must NOT have 목록 위반 사항 없음 확인
  - Evidence: `.omo/evidence/f4-scope.log`

## Commit strategy
- 각 Todo 완료 시 개별 커밋 (위 Commit 필드 참조)
- 메시지 포맷: `type(scope): summary` (Conventional Commits)
- 타입: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`
- Wave 2의 T3~T7은 병렬 작업이므로 커밋 순서 무관

## Success criteria
1. `python main.py -u <URL> -s strategies/default.yaml` 단일 명령으로 설문 자동 완성
2. Single/Multi/Open 3대 유형 정확한 응답
3. 기타(etc) 입력 필드 자동 활성화 및 채움
4. '다음' 버튼 반복 클릭 → 설문 종료 페이지 도달
5. 오류 발생 시 graceful 종료 및 로그 출력
6. YAML 전략 파일 변경만으로 응답 패턴 커스터마이징 가능
