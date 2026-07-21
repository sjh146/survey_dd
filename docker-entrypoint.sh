#!/bin/sh
set -e

if [ -n "$SURVEY_URL" ]; then
    echo "=== Survey Auto-Learn Loop ==="
    echo "URL: $SURVEY_URL"

    survey-auto \
        -u "$SURVEY_URL" \
        --self-improve \
        --timeout "${TIMEOUT:-30}" \
        --max-pages "${MAX_PAGES:-500}" \
        ${VERBOSE:+--verbose} \
        2>&1

    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        echo "=== Survey completed successfully ==="
    else
        echo "=== Survey failed with exit code $EXIT_CODE ==="
    fi
    exit $EXIT_CODE
fi

echo "============================================"
echo "  Survey Auto-Learn Container"
echo "============================================"
echo ""
echo "Set SURVEY_URL environment variable to run:"
echo ""
echo "  docker compose run -e SURVEY_URL=\"https://...\" survey"
echo "  # or"
echo "  SURVEY_URL=\"https://...\" docker compose up survey"
echo ""
echo "Environment variables:"
echo "  SURVEY_URL       - Qualtrics survey URL"
echo "  DEEPSEEK_API_KEY - DeepSeek API key (for self-improve)"
echo "  TIMEOUT          - Page timeout in seconds (default: 30)"
echo "  MAX_PAGES        - Max pages to process (default: 500)"
echo "  VERBOSE          - Enable debug logging (set to 1)"
echo ""
echo "Container is idle. Press Ctrl+C to stop."
echo "============================================"

tail -f /dev/null
