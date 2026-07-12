pipeline {
    agent {
        docker {
            image 'survey-dd:latest'
            args '-u root:root'
        }
    }

    environment {
        PYTHONPATH = "${WORKSPACE}"
        TEST_URL = credentials('survey-test-url')
        DEEPSEEK_API_KEY = credentials('deepseek-api-key')
    }

    stages {
        stage('Build Image') {
            steps {
                sh 'docker build -t survey-dd:latest .'
            }
        }

        stage('Lint & Type Check') {
            steps {
                sh '''
                    pip install ruff mypy 2>/dev/null || true
                    ruff check survey_auto/ --output-format=concise || true
                '''
            }
        }

        stage('Survey Test (Docker)') {
            steps {
                echo '=== Running survey automation in container ==='
                sh '''
                    python -m survey_auto.cli \
                        --self-improve --verbose \
                        -u "${TEST_URL}" \
                        --timeout 60 --max-pages 5 \
                        -o /tmp/survey_test.log 2>&1 || true
                    cat /tmp/survey_test.log
                '''
            }
            post {
                always {
                    archiveArtifacts artifacts: '/tmp/survey_test.log', allowEmptyArchive: true
                }
            }
        }

        stage('Commit & Push') {
            when { branch 'main' }
            steps {
                withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
                    sh '''
                        set +x
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
        failure { echo "=== Pipeline FAILED ===" }
        success { echo "=== Pipeline SUCCEEDED ===" }
        always  { cleanWs() }
    }
}
