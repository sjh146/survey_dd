# 병목 분석 및 해결 — Self-Improving Loop

## 발견된 7대 병목 (B1~B7)

### B1 — 브라우저 Cold Start (매 시도마다 Firefox 재시작)
**증상**: `_attempt()` 실행 시 `BrowserManager()` → `start()` → Firefox launch (2~5초) → navigate (1~3초). 실패 시 `close()` 후 재시도에서 또 다시 Cold Start.
**영향**: 1회 retry당 5~10초 낭비. 20회 시도 시 최대 200초 손실.

**해결: Browser Pool (connection reuse)**
```python
class BrowserPool:
    """재사용 가능한 브라우저 인스턴스 풀"""
    _instance = None
    _browser = None
    
    @classmethod
    def get_browser(cls, headless=True):
        if cls._browser is None:
            p = sync_playwright().start()
            cls._browser = p.firefox.launch(headless=headless)
            cls._playwright = p
        return cls._browser
    
    @classmethod
    def close(cls):
        if cls._browser:
            cls._browser.close()
            cls._playwright.stop()
```
→ 브라우저는 한 번만 띄우고, context/page만 재생성

### B2 — Full Restart on Failure (처음부터 재시도)
**증상**: 3페이지에서 실패 → retry → URL로 다시 navigate → 1페이지, 2페이지 다시 풀고 → 3페이지에서 또 실패. **이미 답한 페이지를 다시 푼다.**

**영향**: 중복 I/O + 중복 질문답변. 10페이지 설문이면 retry당 10배 손실.

**해결: Checkpoint Resume**
```python
class SurveyCheckpoint:
    """설문 상태를 저장하고 실패 지점부터 재개"""
    
    def save(self, page_num, questions_done, url, cookies):
        checkpoint = {
            "page": page_num,
            "questions_done": questions_done,
            "url": url,
            "timestamp": datetime.now().isoformat(),
        }
        Path("/tmp/survey_checkpoint.json").write_text(json.dumps(checkpoint))
    
    def load(self):
        path = Path("/tmp/survey_checkpoint.json")
        if path.exists():
            return json.loads(path.read_text())
        return None
    
    def clear(self):
        Path("/tmp/survey_checkpoint.json").unlink(missing_ok=True)
```
→ retry 시 checkpoint가 있으면 저장된 page부터 resume
→ 단, 이전에 답한 답변은 서버에 이미 저장되었으므로 navigate만 하면 됨

### B3 — 2-Phase Detection이 Sequential (heuristic → BS4)
**증상**: heuristic 실패해야 BS4 실행. heuristic이 빠르긴 하지만, BS4를 실행해야 하는 경우 항상 2배 시간 소요.

**영향**: 패턴 감지에 50~200ms 추가 (BS4 파싱).

**해결: Multi-Algorithm Parallel Detection (ThreadPoolExecutor)**
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def detect_patterns_parallel(html: str) -> list[dict]:
    """Run heuristic + BS4 in parallel, take first result"""
    with ThreadPoolExecutor(max_workers=2) as executor:
        fut_heuristic = executor.submit(detect_new_patterns, html)
        fut_bs4 = executor.submit(detect_bs4_deep, html)
        
        # heuristic이 먼저 결과를 내면 바로 반환
        for fut in as_completed([fut_heuristic, fut_bs4]):
            patterns = fut.result()
            if patterns:
                return patterns
    
    # 둘 다 실패
    return []
```
→ heuristic이 발견 못하면 BS4가 거의 동시에 완료됨 (wait 최소화)

### B4 — Generated Code 검증 없이 바로 사용
**증상**: `_extend_parser_with_pattern()`가 생성한 코드가 문법 오류 있거나 잘못된 로직이어도 `apply_extensions()`에서 try/except로만 처리. 실패하면 다시 heuristic으로 돌아가서 loop.

**영향**: 잘못된 extension 발견까지 1회 retry 낭비.

**해결: Pre-validation + Test Run**
```python
def validate_and_register(code: str, html: str) -> bool:
    """코드 문법 검증 + 실제 HTML로 테스트 실행"""
    try:
        compile(code, '<generated>', 'exec')
    except SyntaxError as e:
        logger.error("Generated code has syntax error: %s", e)
        return False
    
    # 임시 모듈로 import해서 실제 HTML 테스트
    spec = importlib.util.spec_from_loader('_test_ext', importlib.util.machinery.SourceFileLoader('_test_ext', '(null)'))
    # ... 모듈에 코드 추가 후 실행
    
    return True
```
→ 검증 통과한 코드만 extensions.py에 저장

### B5 — Work Order Polling Latency
**증상**: `process_work_orders()`가 2초마다 파일시스템 스캔. work_order가 작성되고 나서야 감지.

**영향**: 최대 2초 지연. 무한루프에서는 미미하나 실시간성이 필요한 경우 문제.

**해결: Watchdog 기반 File Monitoring + Immediate Processing**
```python
import time

def wait_for_work_order(timeout=30):
    """work_order 파일 생성까지 blocking wait"""
    start = time.time()
    while time.time() - start < timeout:
        orders = load_pending_orders()
        if orders:
            return orders[0]
        time.sleep(0.1)  # 100ms polling (기존 2초보다 20배 빠름)
    return None
```
+ 추가: `watchdog` 라이브러리로 OS-level file event 감지 (inotify on Linux)

### B6 — No Parallel URL Processing (단일 설문)
**증상**: 한 번에 하나의 URL만 처리. 복수의 설문 URL이 있어도 순차 처리.

**영향**: 여러 설문이 있을 때 처리량 = 1x.

**해결: URL Batch Processing**
```python
def run_batch(urls: list[str], max_workers=3):
    """여러 설문 URL을 병렬로 처리"""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(SelfImproveLoop(url).run): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                success = future.result()
                logger.info("%s: %s", url, "성공" if success else "실패")
            except Exception as e:
                logger.error("%s: 예외 %s", url, e)
```
→ `--batch urls.txt` 옵션으로 여러 설문 동시 처리

### B7 — Extension 충돌 (중복 함수명)
**증상**: 여러 번 self-improve하면 `extensions.py`에 중복 함수가 쌓임. `parse_select_q1`, `parse_select_q1_1` 등 이름 충돌.
+ 이전 패턴과 현재 HTML이 달라 extension이 잘못 적용됨.

**영향**: 확장 누적으로 성능 저하 + 잘못된 파싱.

**해결: Extension Versioning + Scope Isolation**
```python
# extensions.py 대신 version별 파일로 분리
# .omo/extensions/v001.py, v002.py, ...

def apply_extensions(html: str, version: str = None) -> list[Question]:
    """특정 버전 또는 모든 extension 로드"""
    ext_dir = UNKNOWN_DIR / "extensions"
    versions = sorted(ext_dir.glob("v*.py"))
    
    if version:
        versions = [ext_dir / f"v{version}.py"]
    
    for v in versions:
        questions = _load_and_run(v, html)
        if questions:
            return questions
    return []
```
→ 각 패턴별로 독립 파일 관리, 중복 방지

---

## 해결 우선순위

| 병목 | 영향도 | 해결 난이도 | 우선순위 | 적용 대상 |
|------|--------|-------------|---------|----------|
| B1 브라우저 Cold Start | 상 | 하 | **P0** | `browser.py` |
| B2 Full Restart | 상 | 중 | **P0** | `loop.py` |
| B4 코드 검증 누락 | 중 | 하 | **P1** | `generator.py` |
| B7 Extension 충돌 | 중 | 중 | **P1** | `generator.py` |
| B3 Sequential Detection | 하 | 중 | **P2** | `detector.py` |
| B6 단일 URL 처리 | 하 | 하 | **P3** | `loop.py` / `cli.py` |
| B5 Polling Latency | 하 | 상 | P3 | `work_order.py` |

## P0/P1 즉시 적용 (B1, B2, B4, B7)

### B1 Fix: `survey_auto/browser.py`에 BrowserPool 추가
```python
class BrowserPool:
    """Singleton browser pool for reusing Firefox instance across retry attempts."""
    _browser = None
    _playwright = None
    
    @classmethod
    def launch(cls, headless=True):
        if cls._browser is None:
            p = sync_playwright().start()
            cls._browser = p.firefox.launch(headless=headless)
            cls._playwright = p
        return cls._browser
    
    @classmethod
    def create_context(cls, headless=True):
        browser = cls.launch(headless)
        return browser.new_context(ignore_https_errors=True, ...)
    
    @classmethod
    def shutdown(cls):
        if cls._browser:
            cls._browser.close()
        if cls._playwright:
            cls._playwright.stop()
        cls._browser = None
        cls._playwright = None
```

`BrowserManager.start()` 수정:
```python
def start(self):
    self._playwright = sync_playwright().start()  # 제거
    context = BrowserPool.create_context(self.headless)  # pool 사용
    self._page = context.new_page()
```

### B2 Fix: Checkpoint 시스템을 loop.py에 추가
- `_attempt()` 시작 시 checkpoint 로드
- 각 페이지 완료 시 checkpoint 저장
- 실패 시 checkpoint를 통해 resume

### B4 Fix: generator.py에 validate_generated_code() 추가
```python
def validate_generated_code(code: str) -> bool:
    """Validate generated Python code with compile()"""
    try:
        compile(code, '<generated>', 'exec')
        return True
    except SyntaxError as e:
        logger.error("Code validation failed: %s", e)
        return False
```

### B7 Fix: Extension 파일 버저닝
- `extensions/v001.py` → `extensions/v002.py` 형식
- 각 파일이 독립적으로 로드/언로드 가능

---

## 업데이트된 계획 (Plan에 반영할 사항)

### ADR 6 추가: BrowserPool (B1 해결)
- Singleton 패턴으로 Firefox 인스턴스 재사용
- `BrowserPool.launch()`는 최초 1회만 실행
- `BrowserManager.start()`가 `BrowserPool` 사용

### ADR 7 추가: Checkpoint Resume (B2 해결)
- `/tmp/survey_checkpoint.json`에 진행 상태 저장
- 실패 시 checkpoint부터 resume (처음부터 재시도 방지)
- 성공 시 checkpoint 삭제

### Todo 업데이트
- `[T6]` BrowserPool 구현 (browser.py 수정)
- `[T7]` Checkpoint Resume 구현 (loop.py 수정)
- `[T8]` Code Validation + Extension Versioning (generator.py 수정)
