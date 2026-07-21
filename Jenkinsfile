pipeline {
    agent any

    environment {
        DEEPSEEK_API_KEY = credentials('deepseek-api-key')
    }

    parameters {
        string(name: 'SURVEY_URL', defaultValue: '', description: 'Qualtrics survey URL')
        string(name: 'MAX_RETRIES', defaultValue: '10', description: 'Max CI/CD loop retries')
    }

    stages {
        stage('Infinite Learn Loop') {
            steps {
                script {
                    def url = params.SURVEY_URL
                    if (!url) {
                        error 'SURVEY_URL parameter is required'
                    }

                    def maxRetries = params.MAX_RETRIES.toInteger()
                    def success = false

                    for (def attempt = 1; attempt <= maxRetries; attempt++) {
                        echo "=== CI/CD Loop Attempt ${attempt}/${maxRetries} ==="

                        // Step 1: Build Docker image
                        sh 'docker build -t survey-dd:latest .'

                        // Step 2: Run survey test
                        def exitCode = sh(
                            script: "docker run --rm -e DEEPSEEK_API_KEY=\"${DEEPSEEK_API_KEY}\" survey-dd:latest survey-auto -u \"${url}\" --self-improve --timeout 30 --max-pages 500 --verbose",
                            returnStatus: true
                        )

                        if (exitCode == 0) {
                            echo "=== Survey completed successfully on attempt ${attempt} ==="
                            success = true
                            break
                        }

                        echo "=== Attempt ${attempt} failed (exit code: ${exitCode}). Retrying... ==="

                        // Step 3: Commit any strategy changes from self-improve
                        sh '''
                            git add strategies/ -A 2>/dev/null || true
                            if ! git diff --cached --quiet 2>/dev/null; then
                                git commit -m "auto-learn: strategy update from attempt" || true
                                git push || true
                            fi
                        '''
                    }

                    if (!success) {
                        error "Survey failed after ${maxRetries} attempts"
                    }
                }
            }
        }
    }

    post {
        failure {
            echo '=== CI/CD Loop FAILED ==='
        }
        success {
            echo '=== CI/CD Loop SUCCEEDED ==='
        }
    }
}
