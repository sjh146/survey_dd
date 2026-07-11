# Jenkins + OpenCode 자동화 루프

## 목표

Git Push → Jenkins 자동 실행 → OpenCode로 계획/구현/테스트 → 결과 커밋

```
[Git Push] → [Jenkins Pipeline] → [OpenCode CLI] → [Code Edit] → [Test] → [Git Commit] → [Slack/Email]
```

---

## 전제 조건

| 항목 | 상태 |
|------|------|
| Jenkins (Docker) | ✅ 이미 실행 중 |
| OpenCode CLI | ✅ `/home/dduckbeagy/.npm-global/bin/opencode` |
| Playwright Firefox | ✅ `~/.cache/ms-playwright/firefox-*` |
| survey-auto repo | ✅ `/home/dduckbeagy/survey/` |
| GitHub Token | ❌ Jenkins Credentials에 등록 필요 |

---

## Todos

- [ ] 1. **Jenkinsfile** 생성 — `survey/Jenkinsfile`
  - Declarative Pipeline
  - Agent: `none` (Jenkins master/node에서 직접 실행, 또는 별도 에이전트)
  - 환경변수: `PATH=$PATH:/home/dduckbeagy/.npm-global/bin` (opencode PATH)
  - Stages:

    ```groovy
    pipeline {
        agent any
        environment {
            PATH = "/home/dduckbeagy/.npm-global/bin:$PATH"
            HOME = "/home/dduckbeagy"
        }
        stages {
            stage('Checkout') {
                steps { checkout scm }
            }
            stage('Plan') {
                steps {
                    sh 'opencode run --auto "Plan: review recent changes and create fix plan"'
                }
            }
            stage('Implement') {
                steps {
                    sh 'opencode run --command start-work --auto "Execute the plan"'
                }
            }
            stage('Test') {
                steps {
                    sh 'cd survey && PYTHONPATH=. python3 main.py -u "$TEST_URL" --max-pages 1 --timeout 60 --verbose'
                }
            }
            stage('Commit & Push') {
                steps {
                    withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
                        sh '''
                            git add -A
                            git commit -m "auto: survey-auto update [skip ci]"
                            git push https://dduckbeagy:${GH_TOKEN}@github.com/... HEAD:main
                        '''
                    }
                }
            }
        }
        post {
            failure { slackSend(color: 'danger', message: "Pipeline failed: ${env.BUILD_URL}") }
            success { slackSend(color: 'good', message: "Pipeline succeeded: ${env.BUILD_URL}") }
        }
    }
    ```

- [ ] 2. **opencode.jsonc** 설정 — 비대화형 자동 승인
  - 현재 `/home/dduckbeagy/.config/opencode/opencode.jsonc` 파일 확인
  - 내용:
    ```jsonc
    {
      "language": "ko",
      "plan-approval": "auto",     // ← plan 승인 자동화
      "permissions": {
        "auto": true               // ← 모든 권한 자동 승인
      }
    }
    ```
  - `opencode run --auto` 플래그가 권한을 자동 승인하므로 config 수정은 최소화 가능

- [ ] 3. **GitHub Webhook** 설정
  - Jenkins에 GitHub Webhook Plugin 설치
  - GitHub repo → Settings → Webhooks → Add webhook
  - Payload URL: `http://<jenkins-server>/github-webhook/`
  - Content type: `application/json`
  - Events: `Just the push event`
  - Jenkins Job 설정: "Build when a change is pushed to GitHub"

- [ ] 4. **Jenkins Credentials** — GitHub Token 저장
  - Jenkins 대시보드 → Manage Jenkins → Credentials → Global
  - Kind: "Secret text"
  - Secret: `<your-github-token>`
  - ID: `github-token`
  - Description: `GitHub PAT for dduckbeagy`

- [ ] 5. **Playwright Firefox in Jenkins** — 테스트 환경 설정
  - Jenkins가 Firefox 바이너리에 접근 가능해야 함
  - Firefox가 설치된 경로 확인:
    ```bash
    ls ~/.cache/ms-playwright/firefox-*/firefox/firefox
    ```
  - 필요시 Jenkins Pipeline에서:
    ```groovy
    sh '''
        python3 -m playwright install firefox
        python3 -m pip install -e /home/dduckbeagy/survey/
    '''
    ```
  - System dependencies (Docker 컨테이너에 필요):
    ```
    libgtk-3-0 libx11-xcb1 libdbus-glib-1-2 libxtst6 libnss3 libasound2
    ```

- [ ] 6. **보안 처리** — 중요!
  - `opencode.jsonc`와 Jenkins Credentials에 토큰 저장 (절대 코드 내 하드코딩 금지)
  - Jenkins Console Output에 토큰 노출 방지: `set +x` / `withCredentials` 사용
  - `.gitignore`에 `.omo/` 제외할지 결정 (plan은 repo에 포함 or 제외)

## 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────┐
│  GitHub                                                     │
│  ┌──────────┐   Push   ┌──────────────┐                    │
│  │ survey-  │─────────▶│  Webhook     │                    │
│  │ auto repo│          └──────┬───────┘                    │
│  └──────────┘                 │                            │
└──────────────────────────────┼────────────────────────────┘
                               │
┌──────────────────────────────┼────────────────────────────┐
│  Jenkins (Docker)            │                            │
│                              ▼                            │
│  ┌─────────────────────────────────────────┐              │
│  │  Pipeline (Jenkinsfile)                  │              │
│  │                                          │              │
│  │  checkout ─→ plan ─→ implement ─→ test ─→ commit/push │
│  │                                │                      │
│  │                    ┌───────────┴──────────┐           │
│  │                    │  opencode run --auto  │           │
│  │                    │  opencode run         │           │
│  │                    │  --command start-work │           │
│  │                    └──────────────────────┘           │
│  │                                          │              │
│  │  Firefox (Playwright)                    │              │
│  │  ~/.cache/ms-playwright/firefox-*       │              │
│  └─────────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────┘
```

## 완료 조건

1. Git push → Jenkins 자동 트리거
2. OpenCode가 plan 생성 → 자동 승인 → 코드 수정
3. `python3 main.py -u <URL> --max-pages 1` 통과
4. 수정 결과가 GitHub에 자동 커밋/Push
5. 실패 시 Slack/Email 알림
