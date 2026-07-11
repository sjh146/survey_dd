pipeline {
    agent any

    environment {
        PATH = "/home/dduckbeagy/.npm-global/bin:/usr/bin:/bin"
        HOME = "/home/dduckbeagy"
        PYTHONPATH = "${WORKSPACE}"
        // SurveyMachine test URL (credential에 저장 권장)
        TEST_URL = "https://v3.surveymachine.co.kr/SM_NEW/?SURVEY_NUM=18636&START_TYPE=BANNER&UID=CLOUDPANEL2078160&VAR1=158509&VAR2=CLOUDPANEL&SEC_KEY=qwCUVuzeErsFYx0MZ09F8Zot9guSpe8mAjs9G59J3GQ%3D"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Plan') {
            steps {
                echo '=== Planning with OpenCode ==='
                sh 'opencode run --auto "Plan: review recent changes in survey-auto tool and create fix plan if needed"'
            }
            post {
                success {
                    archiveArtifacts artifacts: '.omo/plans/*.md', allowEmptyArchive: true
                }
            }
        }

        stage('Implement') {
            steps {
                echo '=== Executing plan with OpenCode ==='
                sh 'opencode run --command start-work --auto "Execute the latest plan in .omo/plans/"'
            }
        }

        stage('Test') {
            steps {
                echo '=== Running integration test ==='
                sh 'cd /home/dduckbeagy/survey && PYTHONPATH=. python3 main.py -u "${TEST_URL}" --max-pages 1 --timeout 60 --verbose -o /tmp/test_output.log 2>&1'
            }
            post {
                always {
                    archiveArtifacts artifacts: '/tmp/test_output.log', allowEmptyArchive: true
                }
            }
        }

        stage('Commit & Push') {
            when {
                branch 'main'
            }
            steps {
                withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
                    sh '''
                        set +x  # 토큰 노출 방지
                        git config user.name "dduckbeagy"
                        git config user.email "dduckbeagy@users.noreply.github.com"
                        git add -A
                        git diff --cached --quiet || git commit -m "auto: survey-auto update [skip ci]"
                        git remote set-url origin https://sjh146:${GH_TOKEN}@github.com/sjh146/survey_dd.git
                        git push origin HEAD:main
                    '''
                }
            }
        }
    }

    post {
        failure {
            echo "=== Pipeline FAILED ==="
            // Slack 알림 (선택)
            // slackSend(color: 'danger', message: "survey-auto Pipeline FAILED: ${env.BUILD_URL}")
        }
        success {
            echo "=== Pipeline SUCCEEDED ==="
            // slackSend(color: 'good', message: "survey-auto Pipeline SUCCEEDED: ${env.BUILD_URL}")
        }
        always {
            cleanWs()
        }
    }
}
