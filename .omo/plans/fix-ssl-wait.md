# Fix: SSL 인증서 오류 + 질문 body 로딩 문제

## TL;DR

**문제:** 2개 URL 모두 테스트 실패

| URL | 증상 | 원인 |
|---|---|---|
| `kon.kiwisurvey.kr` | `#question_body`가 `hidden`으로만 resolve | 설문 질문이 AJAX로 늦게 로딩되는데 `visible` state를 요구함 |
| `v3.surveymachine.co.kr` | `SEC_ERROR_UNKNOWN_ISSUER` | 자체 서명 SSL 인증서 → Firefox가 차단 |

**해결:** `browser.py`만 2군데 수정
1. `new_context()`에 `ignore_https_errors=True` 추가
2. `wait_for_question()`에서 `state="attached"` + children 조건을 분리/완화

---

## Todos

- [ ] 1. `browser.py` — SSL 오류 무시 설정
  - **파일:** `survey_auto/browser.py`
  - **변경:** `BrowserManager.start()`의 `self._context = self._browser.new_context(...)` 호출에 `ignore_https_errors=True` 추가
  - **세부:**
    ```python
    self._context = self._browser.new_context(
        ignore_https_errors=True,  # ← 이 줄 추가
        viewport={"width": 1280, "height": 900},
        user_agent=...,
    )
    ```
  - **이유:** 국내 설문 사이트는 자체 서명/Let's Encrypt 인증서를 사용하는 경우가 흔함. `ignore_https_errors=True`는 Firefox에서 이 차단을 우회함
  - **검증:** `python -c "from survey_auto.browser import BrowserManager; b=BrowserManager(headless=True); b.start(); b.navigate('https://v3.surveymachine.co.kr'); b.close(); print('OK')"` 실행 시 SSL 오류 없이 페이지 로딩

- [ ] 2. `browser.py` — 질문 body 대기 전략 개선
  - **파일:** `survey_auto/browser.py`
  - **변경:** `wait_for_question()` 메서드
  - **현재 문제:** `state="visible"` 조건이 실패 (요소는 DOM에 있지만 `display:none` 또는 `visibility:hidden` 상태에서 AJAX로 채워짐)
  - **수정 로직:**
    1. `state="attached"`로 `#question_body`가 DOM에 붙을 때까지 기다림 (visible일 필요 없음)
    2. 그 위에 `wait_for_function()`으로 `children.length > 0` 확인 (이미 되어 있음)
    3. 추가 안전장치: `wait_for_timeout(1000)` 1초 대기 후 children 재확인 (AJAX 지연 대응)
  - **검증:** `python main.py -u "https://kon.kiwisurvey.kr/project/2606009_B/Question.asp" --visible --max-pages 1` 실행 시 질문 로딩 성공

- [ ] 3. 재테스트 (두 URL 모두)
  - **SurveyMachine URL** (SSL 오류 확인)
    ```bash
    PYTHONPATH=. python3 main.py \
      -u "https://v3.surveymachine.co.kr/SM_NEW/?SURVEY_NUM=18636&START_TYPE=BANNER&UID=CLOUDPANEL2078160&VAR1=158509&VAR2=CLOUDPANEL&SEC_KEY=qwCUVuzeErsFYx0MZ09F8Zot9guSpe8mAjs9G59J3GQ%3D" \
      --visible --timeout 60 --max-pages 1 --verbose -o /tmp/sm_result.log
    ```
  - **KiwiSurvey URL** (wait_for_question 개선 확인)
    ```bash
    PYTHONPATH=. python3 main.py \
      -u "https://kon.kiwisurvey.kr/project/2606009_B/Question.asp" \
      --visible --timeout 30 --max-pages 1 --verbose -o /tmp/ks_result.log
    ```

## 영향 범위

- **수정 파일:** `survey_auto/browser.py` (1개 파일, 2군데)
- **영향:** BrowserManager에서만 사용하므로 parser/strategies/executor/navigator/cli에 영향 없음
- **회귀 위험:** 매우 낮음 — `ignore_https_errors=True`는 보안 연결을 약화시키지만 설문 자동화의 특성상 필요함

## 완료 조건

1. `python main.py -u <SurveyMachine URL> --max-pages 1` 실행 시 SSL 오류 없이 질문 페이지 로딩
2. `python main.py -u <KiwiSurvey URL> --max-pages 1` 실행 시 질문 body 정상 파싱
3. 두 경우 모두 `[INFO] Starting survey...`부터 `[INFO] Completed page 1`까지 로그 정상 출력
