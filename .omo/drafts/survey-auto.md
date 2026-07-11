---
slug: survey-auto
status: awaiting-approval
intent: clear
pending-action: write .omo/plans/survey-auto.md
approach: Python CLI (click) + Playwright Firefox + JSON/YAML strategy config
---

# Draft: survey-auto

## Components (topology ledger)
| id | outcome | status | evidence path |
|---|---|---|---|
| C1 Browser Engine | Playwright Firefox 초기화 및 관리 | active | `playwright 1.61.0` 설치 확인, `~/.cache/ms-playwright/firefox-*` |
| C2 Question Parser | DOM 분석 → 질문 유형/옵션 추출 | active | `Question.asp` HTML 분석: 단일(SM1/2/3), 다중(MM1/2/3/4), 개방형(OM1/2/3/4), 척도, 순위, 그룹 |
| C3 Answer Strategy | 설정 파일 기반 응답 생성 | active | 사용자 결정: JSON/YAML 설정 + 랜덤 폴백 |
| C4 Action Executor | DOM 조작 (클릭/입력) | active | `single.js`, `multi.js`, `open.js` DOM 패턴 분석 완료 |
| C5 Navigation Controller | 페이지 이동 흐름 | active | `#next` 버튼, AJAX POST → 페이지 리로드, hidden inputs (PAGENAME/NEXTPAGE) |
| C6 CLI Entry Point | Click 기반 CLI | active | 사용자 결정: Python CLI |

## Open assumptions (announced defaults)
| assumption | adopted default | rationale | reversible? |
|---|---|---|---|
| 전략 파일 포맷 | YAML (가독성, 주석 지원) | JSON보다 사람이 읽기 쉬움 | Yes |
| 파이어폭스 헤드리스 | 헤드리스 모드 기본, `--visible` 옵션으로 전환 | CI/자동화에 적합 | Yes |
| 텍스트 생성 | "테스트 응답입니다." + 질문 변수명 | 기타/주관식 최소 응답 | Yes |
| 질문 유형 감지 방식 | CSS 셀렉터 기반 (`input[type=radio]`, `input[type=checkbox]`, `input[type=text]`, `textarea`) | 모든 설문 유형 커버 | No (DOM 구조에 의존) |
| 진행률 | `#kiwi_progress` 프로그레스바 관찰 + 페이지 URL 변화 | 종료 감지 가능 | No |
| 최대 선택(max) | multi.js `etcCheck` 로직 참조, max 속성 확인 | 설정에 명시 가능 | Yes |

## Findings (cited - path:lines)

### 사이트 구조
- **URL**: `https://kon.kiwisurvey.kr/project/2606009_B/Question.asp`
- **프로젝트명**: "문화참여가 웰빙에 미치는 영향 국민 인식조사"
- **ASP 백엔드**: jQuery + Bootstrap 4 + AJAX 동기/비동기 통신
- **설문 데이터**: `./include/ajax.asp?COMMAND=GETDATA` 로딩, `./include/ajax.asp?COMMAND=QINFO` 문항 정보
- **제출 방식**: `#next` 클릭 → `page_logic()` 리턴 true → `kon.survey.save()` AJAX POST → 페이지 리로드 (`onsubmit=""` form submit)

### 질문 유형별 DOM 패턴
- **Single (radio)**:
  - `input[type=radio][name=VARIABLE]` - 값으로 선택
  - SM1: grid (col-md), SM2: list-group, SM3: table
  - 기타: `input[name=TVARIABLE_VALUE]` (disabled, 체크 시 활성화)
  - 출처: `https://kon.kiwisurvey.kr/module/Qmodule/single.js`
- **Multi (checkbox)**:
  - `input[type=checkbox][name=VARIABLE_VALUE]` - 개별 name
  - MM1: grid, MM2: list-group, MM3: % 합계(100), MM4: table
  - `data-none="1"`: "해당없음" 선택 시 다른 항목 비활성화
  - `max` 옵션: 최대 선택 개수 제한
  - 출처: `https://kon.kiwisurvey.kr/module/Qmodule/multi.js`
- **Open (text)**:
  - `input[type=text/number][name=VARIABLE_KEY]` 또는 `textarea`
  - `must="1"`: 필수 응답
  - `option="han/num/inputTelNumber/all/inputEnglishOnly"`: 입력 제약
  - 출처: `https://kon.kiwisurvey.kr/module/Qmodule/open.js`
- **기타 유형**: Scale, Rank, Combo, Group, Attr, Description - 각 `Qmodule/*.js` 참조

### 폼 hidden inputs
```html
<input name="USEPREV" type="hidden">
<input name="PAGENAME" type="hidden">
<input name="NEXTPAGE" type="hidden">
<input name="PCODE" value="2606009_B">
<input name="IDKEY" type="hidden">
...
```

### Playwright 초기화 상태
- `playwright 1.61.0` pip 설치 완료
- `firefox` 브라우저 바이너리 설치 완료 (__macOS/Linux ~/.cache/ms-playwright/firefox-*__)

## Decisions (with rationale)
1. **방식: Python CLI (click)** — 가장 단순하고 의존성 최소화
2. **전략: YAML 설정 파일 + 랜덤 폴백** — 유연성과 사용 편의성 균형
3. **브라우저: Firefox (Playwright)** — 사용자 요청, 크로스 브라우저 안정성
4. **질문 파싱: CSS 셀렉터 기반** — 사이트가 SPA가 아닌 ASP + jQuery 구조이므로 동적 렌더링 후 DOM 스냅샷 분석
5. **응답 전략 계층**: 전략 파일 > 질문 변수명 매칭 > 유형별 기본값 > 랜덤

## Scope IN
- 설문 URL 접속 → 질문 읽기 → 응답 자동 입력 → 다음 페이지 이동 반복 → 설문 종료까지 자동화
- Single (radio), Multi (checkbox), Open (text/number/textarea) 지원
- Scale, Rank, Group, Combo 기본 지원
- YAML 설정 파일로 질문별 응답 전략 지정
- CLI: `survey-auto --url <URL> --strategy <FILE> [--visible] [--headless]`
- 진행률 표시 및 완료 로그
- 오류 발생 시 재시도 및 graceful 종료
- 예외 상황 로깅

## Scope OUT (Must NOT have)
- ❌ 서드파티 API/웹 서비스 구축하지 않음 (순수 CLI)
- ❌ 데이터베이스 저장소 구축하지 않음
- ❌ captcha/봇 차단 우회 기능 (정상적인 자동화만)
- ❌ GUI/웹 대시보드
- ❌ 멀티 프로젝트 병렬 실행
- ❌ 설문 결과 수집/분석 기능

## Open questions
(모두 사용자 결정 완료)

## Approval gate
status: awaiting-approval
<!-- 사용자 승인 대기 중. 승인 시 plan 작성 완료 후 태스크 실행 가능. -->
