pipeline {
    agent {
        docker {
            image 'survey-dd:latest'
            args '-u root:root --network host --ipc=host'
        }
    }

    environment {
        PYTHONPATH = "${WORKSPACE}"
        DEEPSEEK_API_KEY = credentials('deepseek-api-key')
        SURVEY_URL = credentials('survey-test-url')
        MAX_ATTEMPTS = '5'
        MAX_PAGES = '500'
    }

    parameters {
        string(name: 'SURVEY_URL', defaultValue: '', description: 'Override survey URL (optional)')
        string(name: 'MAX_ATTEMPTS', defaultValue: '5', description: 'Max self-improve attempts')
        booleanParam(name: 'COMMIT_ON_SUCCESS', defaultValue: true, description: 'Commit strategy/checkpoint changes on success')
    }

    stages {
        stage('Build Image') {
            when {
                expression { return !fileExists('/app/survey_auto/cli.py') }
            }
            steps {
                sh 'docker build -t survey-dd:latest .'
            }
        }

        stage('Lint') {
            steps {
                sh '''
                    pip install ruff -q 2>/dev/null || true
                    ruff check survey_auto/ --output-format=concuse --ignore=E501,F841 || true
                '''
            }
        }

        stage('Run Survey') {
            steps {
                script {
                    def url = params.SURVEY_URL ?: env.SURVEY_URL
                    if (!url) {
                        error "SURVEY_URL is required - set via parameter or Jenkins credential"
                    }
                    sh """
                        echo "=== Running survey automation ==="
                        echo "URL: ${url}"
                        echo "Max attempts: ${env.MAX_ATTEMPTS}"
                        python -m survey_auto.cli \\
                            --self-improve \\
                            --verbose \\
                            -u "${url}" \\
                            --timeout 120 \\
                            --max-pages ${env.MAX_PAGES} \\
                            -o /tmp/survey_result.log 2>&1
                    """
                }
            }
            post {
                always {
                    archiveArtifacts artifacts: '/tmp/survey_result.log', allowEmptyArchive: true
                    sh 'cp /tmp/survey_result.log survey_result.log 2>/dev/null || true'
                    archiveArtifacts artifacts: 'error_page_*.png', allowEmptyArchive: true
                }
            }
        }

        stage('Check & Improve') {
            steps {
                sh '''
                    echo "=== Checking survey result ==="
                    if grep -q "completed successfully" /tmp/survey_result.log 2>/dev/null; then
                        echo "Survey completed successfully!"
                    elif grep -q "Pages solved by AI" /tmp/survey_result.log 2>/dev/null; then
                        echo "Survey partially completed with AI assistance"
                    else
                        echo "Survey FAILED - analyzing for improvements..."
                        # Extract failure reason
                        grep -i "error\\|fail\\|exception" /tmp/survey_result.log | tail -20 || true
                    fi
                '''
            }
        }

        stage('Commit Strategy Updates') {
            when {
                branch 'main'
                expression { params.COMMIT_ON_SUCCESS }
            }
            steps {
                withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
                    sh '''
                        set +x
                        git config user.name "survey-bot"
                        git config user.email "survey-bot@users.noreply.github.com"
                        git add strategies/ survey_auto/ -A
                        if git diff --cached --quiet; then
                            echo "No changes to commit"
                        else
                            git commit -m "auto: survey strategy update [skip ci]"
                            git remote set-url origin https://sjh146:${GH_TOKEN}@github.com/sjh146/survey_dd.git
                            git push origin HEAD:main
                        fi
                    '''
                }
            }
        }
    }

    post {
        failure {
            echo "=== Pipeline FAILED ==="
            sh 'cat /tmp/survey_result.log 2>/dev/null | tail -50 || true'
        }
        success {
            echo "=== Pipeline SUCCEEDED ==="
        }
        always {
            cleanWs()
        }
    }
}
