# lc-agent

`lc-agent` is a Python automation project for LeetCode practice. It uses Selenium to open LeetCode in a headless Chrome browser, scrape problem data, ask an LLM to generate a solution, paste the generated code into the LeetCode editor, and submit it.

The project supports three modes:

- Problem of the Day: logs in, opens the daily challenge, scrapes the problem, generates a solution, and submits it.
- Past contest practice: starts a virtual contest, solves contest problems one by one, and submits attempts.
- Live contest read-only: opens a live/upcoming contest and scrapes problem statements without solving or submitting.

Use this responsibly and follow LeetCode's rules. The live contest mode in this codebase is deliberately read-only.

## How It Works

1. `main.py` loads configuration from `.env` and asks which mode to run.
2. `leetcode_browser.py` creates a Selenium Chrome driver, logs in to LeetCode, navigates to POTD or contest pages, and scrapes problem metadata through LeetCode GraphQL with DOM fallback.
3. `solver.py` builds a detailed prompt containing the title, description, examples, constraints, follow-up, and starter code.
4. `llm_client.py` sends that prompt to OpenRouter and returns the generated code.
5. `submitter.py` selects the target language in the LeetCode editor, clears the existing starter code, pastes the generated solution, submits it, and reads the result.

## Project Structure

```text
.
|-- main.py               # Entry point and mode orchestration
|-- leetcode_browser.py   # Selenium login, navigation, GraphQL scraping, contest helpers
|-- solver.py             # Prompt construction, solution generation, retry strategy
|-- submitter.py          # Editor automation, language selection, submission result parsing
|-- llm_client.py         # OpenRouter chat completion client used by solver.py
|-- llm_client_v2.py      # Alternative OpenAI Responses API client
|-- constants.py          # LeetCode URL constants
|-- util.py               # Shared logger setup
|-- requirements.txt      # Python dependencies
|-- samples.yml           # Example environment variable values
`-- README.md
```

## Requirements

- Python 3.9+
- Google Chrome
- ChromeDriver support through Selenium Manager
- A LeetCode account
- An OpenRouter API key for the default LLM client

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root. `.env` is ignored by git.

Minimal configuration:

```env
LC_USERNAME=your_leetcode_username_or_email
LC_PASSWORD=your_leetcode_password
OPENROUTER_API_KEY=your_openrouter_key
```

Recommended cookie-based login when LeetCode blocks headless password login:

```env
LEETCODE_SESSION=your_browser_leetcode_session_cookie
LEETCODE_CSRFTOKEN=your_browser_csrftoken_cookie
```

Optional settings:

```env
# Mode: potd, contest, or live-readonly
LC_SOLVER_MODE=potd

# Solution language: cpp, python3, java, or javascript
LEETCODE_LANGUAGE=cpp

# OpenRouter model alias or full model id
LLM_MODEL=free

# Past contest selection
CONTEST_SLUG=weekly-contest-500
CONTEST_CORRECT_RETRIES=5

# Live contest read-only selection
LIVE_CONTEST_SLUG=weekly-contest-501

# Selenium wait timeout in seconds
MAX_DRIVER_DELAY_SEC=15

# Logging
LOG_LEVEL=INFO
```

`llm_client.py` is the active client imported by `solver.py`. It expects `OPENROUTER_API_KEY`. `llm_client_v2.py` is an alternate OpenAI SDK client and expects `OPENAI_API_KEY`, but it is not wired into `solver.py` by default.

## Running

Interactive mode selection:

```bash
python3 main.py
```

Run POTD directly:

```bash
LC_SOLVER_MODE=potd python3 main.py
```

Run a past contest virtual practice:

```bash
LC_SOLVER_MODE=contest CONTEST_SLUG=weekly-contest-500 python3 main.py
```

Scrape a live contest without solving or submitting:

```bash
LC_SOLVER_MODE=live-readonly LIVE_CONTEST_SLUG=weekly-contest-501 python3 main.py
```

## Modes

### POTD

POTD mode logs in, fetches the daily challenge metadata from LeetCode GraphQL, opens the problem, scrapes the full statement and starter code, asks the LLM for a complete solution, submits it, and prints a final summary.

### Past Contest

Past contest mode starts virtual practice for a contest slug, fetches the contest question list through GraphQL, navigates to each problem, generates solutions, submits them, and prints a contest summary.

If no `CONTEST_SLUG` is provided, the project tries to pick a recent past contest from the LeetCode contest page.

### Live Contest Read-Only

Live contest read-only mode opens a live or upcoming contest, scrapes up to four problem statements, and prints them. It does not call the solver and does not submit code.

## Supported Languages

The language is controlled by `LEETCODE_LANGUAGE`.

Supported values in the current code:

- `cpp`
- `python3`
- `java`
- `javascript`

The browser scraper selects matching LeetCode starter code for the chosen language and the submitter tries to select that language in the editor before pasting.

## Notes and Limitations

- LeetCode frequently changes its frontend. Selectors and submission result parsing may need updates over time.
- Headless username/password login may be blocked by CAPTCHA or Cloudflare checks. Cookie-based login is usually more reliable.
- The active solver path uses OpenRouter. To use `llm_client_v2.py`, update `solver.py` to import from `llm_client_v2` instead of `llm_client`.
- `CONTEST_MAX_ATTEMPTS` is defined but the current contest flow uses `CONTEST_CORRECT_RETRIES` for corrected solution retries.
- Generated solutions depend on the selected model and may still fail. The contest flow can retry corrected solutions using LeetCode feedback.

## Troubleshooting

If imports fail, reinstall dependencies:

```bash
python3 -m pip install -r requirements.txt
```

If login fails with a CAPTCHA or disabled sign-in button, set `LEETCODE_SESSION` and `LEETCODE_CSRFTOKEN` from an already logged-in browser session.

If Selenium times out while waiting for elements, increase:

```env
MAX_DRIVER_DELAY_SEC=30
```

If the LLM call fails, check that `OPENROUTER_API_KEY` is set and that `LLM_MODEL` is a valid OpenRouter model alias or full model id.
