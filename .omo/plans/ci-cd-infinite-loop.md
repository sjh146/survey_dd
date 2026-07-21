# CI/CD Infinite Learning Loop Plan

## Goal
Qualtrics 설문 응답 자동화를 Docker/Jenkins/Git 무한 CI/CD 루프로 구성하여, 새로운 양식도 스스로 학습하고 `docker compose up -d` 시 자동 실행되도록 한다.

## Current State
- Qualtrics 탐지: URL+DOM 3회 재시도 (안정화됨)
- Consent 4문항: parser/executor로 정상 처리
- DeepSeek fallback: ~셀렉터 JS evaluate로 hidden radio 처리
- Loop: is_survey_ended() 조기 체크, _p_total/_q_total 누적 수정 완료
- Docker 이미지 빌드: 성공
- Docker Compose: 있으나 URL 미지정 시 --help 출력

## Issues to Fix
1. Docker entrypoint 없음 → `docker compose up -d` 시 자동 실행 안 됨
2. Dockerfile 불필요 패키지 과다 → 이미지 크기 1.61GB
3. Jenkinsfile이 진정한 CI/CD 루프 아님 (1회 실행 후 종료)
4. package.json/package-lock.json 불필요 (Python 프로젝트)
5. loop.py dead code (SAME_CONTENT_LIMIT=12 미사용, prev_html/same_count 미사용)
6. Strategy auto-save 없음 (DeepSeek 성공 시 전략 자동 저장)

## Implementation Plan

### Step 1: Create `docker-entrypoint.sh` (NEW FILE)
- SURVEY_URL 환경변수 읽어서 survey-auto --self-improve 실행
- URL 없으면 사용법 출력하고 tail -f /dev/null로 대기
- 성공 시 exit 0, 실패 시 exit 1
- TIMEOUT, MAX_PAGES, VERBOSE 환경변수 지원

### Step 2: Optimize `Dockerfile`
- 불필요 패키지 제거: wget, ca-certificates, fonts-liberation, xdg-utils 등
- RUN 명령어 && 체인으로 통일 (레이어 수 최소화)
- `COPY docker-entrypoint.sh` + `RUN chmod +x`
- `ENTRYPOINT ["./docker-entrypoint.sh"]`
- CMD 제거 (entrypoint에서 처리)

### Step 3: Update `docker-compose.yml`
- entrypoint 사용
- SURVEY_URL, DEEPSEEK_API_KEY .env 파일에서 읽도록
- restart: on-failure 옵션 추가 (실패 시 재시작)

### Step 4: Rewrite `Jenkinsfile` — Infinite CI/CD Loop
```groovy
pipeline {
    agent any
    stages {
        stage('Infinite Learn Loop') {
            steps {
                script {
                    def maxRetries = 10
                    for (int i = 0; i < maxRetries; i++) {
                        sh 'docker build -t survey-dd:latest .'
                        sh 'docker run --rm survey-dd:latest survey-auto ...'
                        if (exitCode == 0) break  // success
                        // Analyze failure, fix code, commit
                        sh '...'  // auto-fix logic
                        sh 'git add -A && git commit -m "auto-fix: ..."'
                        sh 'git push'
                    }
                }
            }
        }
    }
}
```

### Step 5: Remove Dead Code in `loop.py`
- Remove `SAME_CONTENT_LIMIT = 12`
- Remove `prev_html` and `same_count` in `_attempt()`
- These were used for duplicate content detection but never actually used

### Step 6: Remove Unnecessary Files
- `package.json`, `package-lock.json` → 삭제 (Node.js 의존성, Python 프로젝트에 불필요)
- `.gitignore`에 이미 node_modules/ 추가됨

### Step 7: Create `.env.example`
```
DEEPSEEK_API_KEY=sk-your-key-here
SURVEY_URL=https://ts1.eu.qualtrics.com/jfe/form/SV_...
TIMEOUT=30
MAX_PAGES=500
```

### Step 8: Create `.gitignore` Update
- `package.json`, `package-lock.json` 추가 (이미 untracked 상태로 유지)

## Execution Order
1. Step 1 → docker-entrypoint.sh 생성
2. Step 2 → Dockerfile 최적화
3. Step 3 → docker-compose.yml 업데이트
4. Step 5 → loop.py dead code 제거
5. Step 6 → 불필요 파일 삭제
6. Step 7 → .env.example 생성
7. Step 4 → Jenkinsfile 재작성
8. Docker 빌드 + 테스트
9. Git 커밋 + 푸시
10. `docker compose up -d` 검증

## Verification
```bash
# 빌드
docker build -t survey-dd:latest .

# 실행 (URL 지정)
SURVEY_URL="https://..." docker compose up survey

# 백그라운드 실행
SURVEY_URL="https://..." docker compose up -d survey

# 로그 확인
docker compose logs -f survey
```
