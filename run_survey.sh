#!/usr/bin/env bash
set -euo pipefail

# ─── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

IMAGE_NAME="survey-dd:latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Defaults ────────────────────────────────────────────────────────────────
URL=""
PLATFORM="auto"
VISIBLE=false
TIMEOUT=120
MAX_PAGES=500
VERBOSE=false

# ─── Help ────────────────────────────────────────────────────────────────────
usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Docker-based survey automation launcher.

Options:
  -u, --url URL           Survey URL (prompts if omitted)
  -p, --platform PLATFORM Platform: auto, kiwi, surveymachine, nielseniq (default: auto)
      --visible           Show browser (headed mode)
      --timeout SECS      Page timeout in seconds (default: 120)
      --max-pages N       Max pages (default: 500)
  -v, --verbose           Debug logging
  -h, --help              Show this help

Examples:
  ./run_survey.sh -u "https://example.com/survey/abc123" -p surveymachine
  ./run_survey.sh   # interactive mode
EOF
  exit 0
}

# ─── Parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -u|--url)      URL="$2"; shift 2 ;;
    -p|--platform) PLATFORM="$2"; shift 2 ;;
    --visible)     VISIBLE=true; shift ;;
    --timeout)     TIMEOUT="$2"; shift 2 ;;
    --max-pages)   MAX_PAGES="$2"; shift 2 ;;
    -v|--verbose)  VERBOSE=true; shift ;;
    -h|--help)     usage ;;
    *)             echo -e "${RED}Unknown option: $1${NC}"; usage ;;
  esac
done

# ─── Interactive: URL ────────────────────────────────────────────────────────
if [[ -z "$URL" ]]; then
  if [[ -t 0 ]]; then
    echo -ne "${CYAN}Survey URL: ${NC}"
    read -r URL
  else
    echo -e "${RED}Error: No URL provided and stdin is not a terminal.${NC}" >&2
    exit 1
  fi
fi

if [[ -z "$URL" ]]; then
  echo -e "${RED}Error: URL is required.${NC}" >&2
  exit 1
fi

# ─── Interactive: Platform ───────────────────────────────────────────────────
if [[ "$PLATFORM" == "auto" && -t 0 ]]; then
  echo ""
  echo -e "${CYAN}Select platform:${NC}"
  echo "  1) auto (detect automatically)"
  echo "  2) surveymachine"
  echo "  3) nielseniq"
  echo "  4) kiwi"
  echo -ne "${CYAN}Choice [1]: ${NC}"
  read -r choice
  case "${choice:-1}" in
    1) PLATFORM="auto" ;;
    2) PLATFORM="surveymachine" ;;
    3) PLATFORM="nielseniq" ;;
    4) PLATFORM="kiwi" ;;
    *) echo -e "${RED}Invalid choice.${NC}"; exit 1 ;;
  esac
fi

# ─── Validate platform ──────────────────────────────────────────────────────
case "$PLATFORM" in
  auto|kiwi|surveymachine|nielseniq) ;;
  *) echo -e "${RED}Error: Invalid platform '$PLATFORM'. Use: auto, kiwi, surveymachine, nielseniq${NC}" >&2; exit 1 ;;
esac

# ─── API Key ─────────────────────────────────────────────────────────────────
if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  # Try .env file
  if [[ -f "$SCRIPT_DIR/.env" ]]; then
    export DEEPSEEK_API_KEY=$(grep -E '^DEEPSEEK_API_KEY=' "$SCRIPT_DIR/.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
  fi
fi

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  if [[ -t 0 ]]; then
    echo -ne "${YELLOW}DEEPSEEK_API_KEY not found. Enter key: ${NC}"
    read -rs DEEPSEEK_API_KEY
    echo ""
    export DEEPSEEK_API_KEY
  else
    echo -e "${RED}Error: DEEPSEEK_API_KEY not set and stdin is not a terminal.${NC}" >&2
    exit 1
  fi
fi

# ─── Build Docker image if needed ───────────────────────────────────────────
if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
  echo -e "${YELLOW}Building Docker image '$IMAGE_NAME'...${NC}"
  docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"
  if [[ $? -ne 0 ]]; then
    echo -e "${RED}Error: Docker build failed.${NC}" >&2
    exit 1
  fi
  echo -e "${GREEN}Docker image built successfully.${NC}"
fi

# ─── Build docker run command ───────────────────────────────────────────────
DOCKER_CMD=(
  docker run --rm
  -e DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY"
  -v "$SCRIPT_DIR":/app/data
  --name "survey-run-$(date +%s)"
  "$IMAGE_NAME"
  survey-auto
  -u "$URL"
  --self-improve
  --platform "$PLATFORM"
  --timeout "$TIMEOUT"
  --max-pages "$MAX_PAGES"
)

if [[ "$VISIBLE" == true ]]; then
  DOCKER_CMD+=(--visible)
fi

if [[ "$VERBOSE" == true ]]; then
  DOCKER_CMD+=(-v)
fi

# ─── Run ─────────────────────────────────────────────────────────────────────
echo -e "${CYAN}Running survey automation...${NC}"
echo -e "${CYAN}URL: $URL | Platform: $PLATFORM | Timeout: ${TIMEOUT}s | Max pages: $MAX_PAGES${NC}"
echo ""

"${DOCKER_CMD[@]}"
EXIT_CODE=$?

echo ""
if [[ $EXIT_CODE -eq 0 ]]; then
  echo -e "${GREEN}Survey completed successfully.${NC}"
else
  echo -e "${RED}Survey exited with code $EXIT_CODE.${NC}"
fi

exit $EXIT_CODE
