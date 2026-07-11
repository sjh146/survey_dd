# Add: SurveyMachine 플랫폼 지원

## TL;DR

지금까지 KiwiSurvey 전용이었던 툴을 SurveyMachine도 자동 감지해서 지원하도록 확장.
또 `--platform` CLI 옵션으로 강제 지정 가능.

### 구조 차이 (반영 필요)

| 기능 | KiwiSurvey | SurveyMachine |
|------|-----------|---------------|
| 질문 컨테이너 | `#question_body` | `#vb_application` |
| 질문 박스 | `<div>` 다양 | `.questionBox` + `.answerBox.radioset` |
| Radio name | `SQ01`, `MQ01` 등 | `Q3` |
| "다음" 버튼 | `#next` | `#btn_next` (onclick=`SurveyLoader.next()`) |
| "이전" 버튼 | 없음 | `#btn_prev` |
| 진행률 | `#kiwi_progress .progAct` | `.progressbar .bar` (width %) |
| Form submit | `<form>` submit + `#next` click | `SurveyLoader.next()` JS 호출 |

---

## Todos

- [ ] 1. `models.py` — `Platform` Enum + 컨테이너/셀렉터 정보 추가
  - `Platform.KIWI`, `Platform.SURVEY_MACHINE` Enum
  - `SurveyConfig` dataclass: `question_container_selector`, `next_button_selector`, `prev_button_selector`, `progress_selector` 등
  - `PLATFORM_CONFIGS: dict[Platform, SurveyConfig]` 상수 맵

- [ ] 2. `browser.py` — 플랫폼 자동 감지 + `wait_for_question` 개선
  - `detect_platform(page) -> Platform` 메서드: DOM에 `#vb_application` 존재 → SurveyMachine, `#question_body` 존재 → Kiwi
  - `wait_for_question()` → 감지된 플랫폼의 컨테이너 셀렉터 사용
  - SurveyMachine 컨테이너: `.answerBox.radioset, .answerBox.checkboxset, input[type=text]` 등 자식 요소 대기

- [ ] 3. `parser.py` — SurveyMachine 파서 추가
  - `SurveyMachineParser` 클래스 추가 (또는 `SurveyParser`를 리팩터)
  - SurveyMachine DOM 구조:
    ```html
    <div id="vb_application">
      <div class="questionBox">  <!-- 질문 제목 -->
        <div class="questionNum">Q3.</div>
        <div class="questionText">...</div>
      </div>
      <!-- 설명 (optional) -->
      <div class="panel panel-default description">...</div>
      <!-- 답변 영역 -->
      <div class="answerBox radioset">
        <table>...</table>  <!-- radio/checkbox grid -->
      </div>
    </div>
    ```
  - 감지 패턴:
    - `input[type=radio]` → SINGLE (radioset)
    - `input[type=checkbox]` → MULTI (checkboxset)
    - `input[type=text], textarea` → OPEN
    - `table.table-survey` + `input[type=radio]` 연속 5+개 → SCALE
  - 질문 변수명: `input[name]` 값 (예: `Q3`)
  - Option 추출: 각 `<td>`의 `<input value="1">` + label 텍스트

- [ ] 4. `navigator.py` — SurveyMachine 버튼 처리
  - `next_page()`: 플랫폼에 따라 `#next` 또는 `#btn_next` 클릭
  - SurveyMachine: `page.click('#btn_next')` → `SurveyLoader.next()` JS 실행 후 페이지 전환 대기
  - 종료 감지: `#btn_next` 사라짐 또는 `SurveyLoader.end()` 호출
  - 진행률: `.progressbar .bar`의 `width` 스타일 % 파싱

- [ ] 5. `cli.py` — `--platform` 옵션 추가 (auto/kiwi/surveymachine)
  - 기본값: `auto` (자동 감지)
  - `--platform kiwi`: KiwiSurvey 강제
  - `--platform surveymachine`: SurveyMachine 강제
  - 오케스트레이터 루프에 platform 전달

- [ ] 6. 통합 테스트 (SurveyMachine 1페이지 실행)
  - ```bash
    cd /home/dduckbeagy/survey && PYTHONPATH=. python3 main.py \
      -u "https://v3.surveymachine.co.kr/SM_NEW/?SURVEY_NUM=18636&START_TYPE=BANNER&UID=CLOUDPANEL2078160&VAR1=158509&VAR2=CLOUDPANEL&SEC_KEY=qwCUVuzeErsFYx0MZ09F8Zot9guSpe8mAjs9G59J3GQ%3D" \
      --visible --timeout 60 --max-pages 1 --verbose -o /tmp/sm_result.log
    ```
  - 기대 결과: Q3 (1~10 scale) 파싱 → 랜덤 값 선택 → "다음" 버튼 클릭까지

## 영향 범위

| 파일 | 변경 |
|------|------|
| `survey_auto/models.py` | `Platform` Enum + `SurveyConfig` dataclass 추가 |
| `survey_auto/browser.py` | `detect_platform()` + `wait_for_question()` 개선 |
| `survey_auto/parser.py` | SurveyMachine 파싱 로직 추가 (리팩터) |
| `survey_auto/navigator.py` | 플랫폼별 버튼/진행률 처리 |
| `survey_auto/cli.py` | `--platform` 옵션, 오케스트레이터에 platform 전달 |
| `survey_auto/executor.py` | 변경 불필요 (단순 click/fill이므로) |

## 완료 조건

1. `python main.py -u <SurveyMachine URL> --max-pages 1` 실행 시 Q3 1~10 scale 정상 파싱
2. 랜덤 응답 선택 후 "다음" 버튼까지 정상 클릭
3. KiwiSurvey URL에서도 기존 동작 그대로 유지 (회귀 방지)
