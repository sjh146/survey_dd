# Self-Improving Loop — Deep Analysis + Auto-Delegation Architecture

## 분석 배경

현재 `self_improve.py`의 문제점:
1. **328라인** — `/shared/programming` 스킬의 250라인 제한 초과 (분할 필요)
2. **heuristic only** — 정규식으로 `<select>`, `<input>`만 찾음 → 복잡한 구조의 unknown pattern은 감지 실패
3. **oracle/momus 불가** — subagent가 tool 실행 불가 → 딥 분석을 Python 스크립트 자체가 수행해야 함
4. **위임 구조 없음** — 현재는 같은 프로세스 안에서만 self-improve, 외부 에이전트 호출 불가
5. **cli.py 미연결** — `--self-improve` 플래그 아직 없음

## 목표 설계

```
┌────────────────────────────────────────────────────────────┐
│                   SelfImproveLoop (daemon)                  │
│                                                             │
│  while True:                                                │
│    1. attempt()  ← 설문 자동화 실행                         │
│       → 성공: return True                                   │
│       → unknown HTML 발견:                                  │
│          a. heuristic detection (빠른 정규식)                │
│          b. BeautifulSoup deep detection (느리지만 정확)     │
│          c. code generation + hot reload                     │
│          d. if still unknown → write_work_order()            │
│          e. retry                                            │
│                                                             │
│    2. process_work_orders()  ← 대기 중인 작업 확인           │
│       → work_order 파일 발견:                               │
│          a. HTML 심층 분석 (BS4 + CSS 셀렉터)                 │
│          b. parser extension 코드 생성                       │
│          c. extensions.py에 저장                              │
│          d. work_order 완료 처리                              │
│                                                             │
│    3. delegate_if_needed()  ← 처리 불가능한 패턴 위임        │
│       → agent_work_order 작성 → 외부 worker가 picks up      │
│       → 다음 루프에서 결과 확인                               │
│                                                             │
│    4. sleep + loop                                           │
└─────────────────────────────────────────────────────────────┘
```

## Architecture Decision Records

### ADR 1: 250라인 초과 → 모듈 분할 (필수)
- **현황**: `self_improve.py` 328라인 (250 초과)
- **분할 구조**:
  ```
  survey_auto/self_improve/
    ├── __init__.py          # SelfImproveLoop import 및 public API
    ├── loop.py              # SelfImproveLoop 메인 클래스 (attempt/run 로직)
    ├── detector.py          # _detect_new_patterns + BeautifulSoup deep analysis
    ├── generator.py         # _extend_parser_with_pattern + _apply_extensions
    └── work_order.py        # work order 파일 I/O + 위임 인터페이스
  cli.py → --self-improve 플래그 추가
  ```
- **각 파일 250라인 이하 유지**

### ADR 2: BeautifulSoup 도입
- **이유**: 정규식만으로는 중첩된 HTML 구조, 동적 렌더링 패턴 분석 불가
- **방법**: `bs4` 의존성 추가 → `pip install beautifulsoup4` (또는 lxml)
- **deep_detect(html)** 함수:
  1. `soup.find_all('select')` → dropdown 감지
  2. `soup.find_all('input', type=lambda t: t not in ('radio','checkbox','hidden','submit','button'))` → text/number/email/tel/date 등
  3. `soup.find_all('textarea')` → multi-line text
  4. `soup.select('[class*="rank"]')` → ranking widgets
  5. `soup.select('[class*="scale"]')` → scale/slider
  6. jQuery-style `$('.answerBox')` 내부 구조 분석
- **heuristic → BS4 fallback 구조**:
  ```python
  patterns = _detect_new_patterns(html)  # 빠른 정규식
  if not patterns:
      patterns = _deep_detect_bs4(html)   # 느리지만 정확한 BS4
  ```

### ADR 3: Work Order 시스템 (위임 메커니즘)
- **파일 기반 메시지 큐**: `.omo/work_orders/`
- **work_order 형식** (JSON):
  ```json
  {
    "id": "wo_20250712_001",
    "status": "pending",
    "created_at": "2025-07-12T16:00:00",
    "html_file": ".omo/unknown_patterns/page3_unknown_20250712_160000.html",
    "context": {
      "url": "https://...",
      "page": 3,
      "platform": "surveymachine",
      "detected_questions_before": 7,
      "failed_variables": []
    }
  }
  ```
- **상태**: `pending` → `analyzing` → `completed` / `failed`
- **worker_agent**: `analysis_done` → `True/False`
- **자동 위임 루프**: 
  1. heuristic + BS4 모두 실패 → work_order 생성 (status: `pending`)
  2. `SelfImproveLoop.delegate_if_needed()` 검사:
     - `.omo/work_orders/*.json` 에 `status: "pending"` 있는지 확인
     - 있으면: 자체 deep analysis 시도 (BS4 확장, CSS 셀렉터 조합)
     - 그래도 실패: `agent_type` 필드에 `"deep"` 설정 → 프롬프트/워커가 읽고 처리
  3. 다음 루프 iteration에서 `process_work_orders()`로 결과 확인

### ADR 4: Self-healing CLI 진입점
- `cli.py`에 `--self-improve` 플래그 추가
- 실행 시 `SelfImproveLoop`가 daemon 모드로 동작
- `--self-improve --daemon` 옵션: 무한 루프 + work_order 지속 감시
- `--self-improve` (단일): survey 1회 + 실패 시 self-improve 후 재시도 (max 20회)

### ADR 5: 외부 에이전트 위임 인터페이스
- oracle/momus가 tool 실행 불가능하므로 → **파일 기반 협업**
- `SelfImproveLoop`가 분석 불가능한 HTML 발견 시:
  1. HTML 스냅샷 저장 (이미 구현됨)
  2. `work_order` JSON 생성 (status: `pending`, needs: `deep_analysis`)
  3. `.omo/work_orders/` 에 기록
  4. Python 스크립트 종료 (exit code: 42 = "needs human/agent help")
  5. worker/Prometheus가 exit code 42 감지 → work_order 읽기 → 분석 → extensions.py 생성 → 재실행

## File-by-file 변경 계획

### 1. `survey_auto/self_improve/__init__.py` (NEW)
```python
from survey_auto.self_improve.loop import SelfImproveLoop

__all__ = ["SelfImproveLoop"]
```

### 2. `survey_auto/self_improve/detector.py` (NEW, ~200라인)
- `detect_new_patterns(html)` — 기존 정규식 기반 (self_improve.py에서 이관)
- `deep_detect_bs4(html)` — BeautifulSoup 기반 심층 분석
- `html_to_soup(html)` → BS4 파싱 유틸
- `detect_dropdowns(soup)` → select 태그 분석
- `detect_text_inputs(soup)` → input/textarea 분석
- `detect_radio_groups(soup)` → 라디오 버튼 그룹 분석
- `detect_checkbox_groups(soup)` → 체크박스 그룹 분석
- `detect_scale_widgets(soup)` → scale/slider 분석
- `detect_rank_widgets(soup)` → ranking 분석
- `detect_matrix_tables(soup)` → matrix/grid 분석 (새로운 패턴)

### 3. `survey_auto/self_improve/generator.py` (NEW, ~200라인)
- `extend_parser_with_pattern(html, patterns)` — 코드 생성 (self_improve.py에서 이관)
- `apply_extensions(html)` — 핫 리로드 + 실행 (self_improve.py에서 이관)
- `generate_parser_code(pattern)` — 패턴별 파서 코드 생성
- `merge_with_existing_extensions(new_code)` — 중복 방지 + 추가
- `validate_generated_code(code)` — 생성된 코드 문법 검증

### 4. `survey_auto/self_improve/work_order.py` (NEW, ~150라인)
- `WorkOrderStatus` enum: PENDING, ANALYZING, COMPLETED, FAILED
- `WorkOrder` dataclass: id, status, html_file, context, agent_type, result
- `create_work_order(html, context)` → work_order JSON 생성
- `load_pending_orders()` → 처리 대기 중인 work_order 목록
- `update_work_order(order_id, status, result)` → 상태 업데이트
- `process_delegation_results()` → 완료된 위임 결과 확인 및 extensions에 반영
- `needs_delegation()` → 현재 루프가 외부 도움 필요한지 확인

### 5. `survey_auto/self_improve/loop.py` (NEW, ~240라인)
- `SelfImproveLoop` 메인 클래스 (self_improve.py에서 이관)
- `run()` — 메인 루프
- `_attempt()` — 단일 설문 시도
- `_analyze_failure()` — 실패 분석 + 패턴 감지 + 확장
- `_process_work_orders()` — 대기 work_order 처리
- `_delegate_if_needed()` — 외부 위임
- `_handle_exit_code()` — exit code 42 처리 (worker/Prometheus용)

### 6. `survey_auto/cli.py` (수정, +15라인)
- `--self-improve` 플래그 추가
- `--self-improve --daemon` 모드 추가
- `SelfImproveLoop` import 및 라우팅

### 7. `pyproject.toml` (수정, +1라인)
- `beautifulsoup4` 의존성 추가

## Implementation Todos

### [T1] 모듈 분할 — self_improve/ 패키지 생성
- [ ] T1.1: `survey_auto/self_improve/` 디렉토리 생성
- [ ] T1.2: `__init__.py` 작성
- [ ] T1.3: `detector.py` — 기존 `_detect_new_patterns` 이관 + 개선
- [ ] T1.4: `generator.py` — 기존 `_extend_parser_with_pattern` + `_apply_extensions` 이관
- [ ] T1.5: `work_order.py` — 파일 기반 위임 시스템
- [ ] T1.6: `loop.py` — `SelfImproveLoop` 이관 (250라인 제한 준수)
- [ ] T1.7: 기존 `self_improve.py` 삭제

### [T2] BeautifulSoup 심층 분석 추가
- [ ] T2.1: `deep_detect_bs4()` 함수 구현
- [ ] T2.2: 각종 위젯 감지 함수 (dropdown, text, radio, checkbox, scale, rank, matrix)
- [ ] T2.3: heuristic → BS4 fallback 연결
- [ ] T2.4: `pyproject.toml`에 `beautifulsoup4>=4.12` 추가

### [T3] cli.py 업데이트
- [ ] T3.1: `--self-improve` Click 옵션 추가
- [ ] T3.2: `--self-improve --daemon` 모드 (work_order 지속 감시)
- [ ] T3.3: SelfImproveLoop import + 라우팅

### [T4] git commit + push
- [ ] T4.1: `git add survey_auto/self_improve/ survey_auto/cli.py pyproject.toml`
- [ ] T4.2: `git commit -m "feat(survey-auto): self-improving loop with auto-delegation"`
- [ ] T4.3: `git push origin main`

### [T5] 설치 + 검증
- [ ] T5.1: `pip install beautifulsoup4`
- [ ] T5.2: `python3 -c "from survey_auto.self_improve import SelfImproveLoop; print('OK')"`
- [ ] T5.3: `python3 -m survey_auto.cli --help`

## 종료 조건
- `--self-improve` 플래그가 CLI 도움말에 표시됨
- `SelfImproveLoop`가 heuristic 실패 시 BeautifulSoup fallback 동작
- unknown HTML 발견 시 work_order 생성 + 재시도
- 모든 파일 250라인 이하
- git commit + push 완료

## 실행자
Worker: `task(category="quick")`로 각 Todo 실행. T1→T2→T3 순차. T4+T5 병렬 가능.
