# Plan: Create `run_survey.sh` — Docker-based survey launcher

## Goal
Create a user-friendly shell script at `/home/dduckbeagy/survey_dd/run_survey.sh` that wraps `docker run` so the user can simply input a URL and platform type to run the survey automation.

## Specification

### Behavior
- Interactive mode: `./run_survey.sh` → prompts for URL + platform choice (1:auto, 2:surveymachine, 3:nielseniq, 4:kiwi)
- CLI mode: `./run_survey.sh -u "URL" -p surveymachine` → non-interactive
- Reads `DEEPSEEK_API_KEY` from env or `.env` file; prompts if missing
- Auto-builds Docker image if not present
- Runs with `survey-auto run -u URL --self-improve --platform PLATFORM`
- Shows real-time output, returns exit code

### Options
| Flag | Description |
|------|-------------|
| `-u / --url` | Survey URL |
| `-p / --platform` | auto / kiwi / surveymachine / nielseniq (default: auto) |
| `--visible` | Show browser (headed mode) |
| `--timeout` | Page timeout in seconds (default: 120) |
| `--max-pages` | Max pages (default: 500) |
| `-v / --verbose` | Debug logging |
| `-h / --help` | Help text |

### File to create
`/home/dduckbeagy/survey_dd/run_survey.sh` — executable shell script

### Edge cases
- No URL provided → prompt interactively
- No API key found → prompt for it
- Docker build fails → show error, exit non-zero
- Terminal vs piped stdin → both work

## Steps
1. Write `run_survey.sh` with all the logic above
2. `chmod +x run_survey.sh`
3. Test: `./run_survey.sh -h` shows help
4. Verify Docker build works: `./run_survey.sh -u "https://example.com"` (will fail at runtime but should build and attempt)

## Approval
User reviews and approves plan with `$approve`, then runs `$start-work`.
