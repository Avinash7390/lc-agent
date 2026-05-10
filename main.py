import os
import random
from datetime import datetime
from pathlib import Path
from time import sleep

from dotenv import load_dotenv

from leetcode_browser import (
    create_driver,
    get_contest_questions,
    get_latest_past_contest_slug,
    get_live_contest_slugs,
    login,
    navigate_to_contest_problem,
    navigate_to_potd,
    scrape_potd_content,
    start_virtual_contest,
)
from solver import solve_problem, solve_problem_with_feedback, generate_flawed_solution, decide_attempt_strategy
from submitter import paste_and_submit
from util import get_logger

logger = get_logger(__name__)

MAX_ATTEMPTS = 3
CONTEST_MAX_ATTEMPTS = int(os.getenv("CONTEST_MAX_ATTEMPTS", "5"))
CONTEST_CORRECT_RETRIES = int(os.getenv("CONTEST_CORRECT_RETRIES", "5"))
TARGET_LANGUAGE = os.getenv("LEETCODE_LANGUAGE", "cpp")

# Short pause after a failed submission before human starts "thinking" (seconds)
POST_FAILURE_DELTA = 5
POST_SUCCESS_COOLDOWN = 10

# Simulates human "thinking time" between attempts (seconds)
THINK_TIME_RANGE = (10, 120)

BASE_DIR = Path(__file__).resolve().parent
REQUIRED_ENV_VARS = ("LC_USERNAME", "LC_PASSWORD")


def load_config():
    """Load project-local config and fail early when required values are missing."""
    env_path = BASE_DIR / ".env"
    load_dotenv(env_path, override=True)

    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        example_path = BASE_DIR / ".env.example"
        missing_vars = ", ".join(missing)
        raise RuntimeError(
            f"Missing required environment variable(s): {missing_vars}. "
            f"Create {env_path} from {example_path} and fill in the values."
        )


def read_optional_input(prompt):
    """Read optional CLI input, defaulting to blank when running non-interactively."""
    try:
        return input(prompt).strip()
    except EOFError:
        logger.info("No interactive input available; using default blank value")
        return ""


def human_delay(attempt_number):
    """
    Simulate the time a human would spend after a failed submission:
    1. A short 5s delta (staring at the error, reading the failed test case)
    2. Then a longer "thinking/debugging" period that increases with each attempt
    """
    # First: short pause — human reads the error result
    logger.info(f"Failed submission... waiting {POST_FAILURE_DELTA}s (reading error output)")
    sleep(POST_FAILURE_DELTA)

    # Then: longer thinking time that scales with attempt number
    base_min, base_max = THINK_TIME_RANGE
    factor = 1 + (attempt_number - 1) * 0.5
    delay = min(120, random.uniform(base_min * factor, base_max * factor))
    logger.info(f"Simulating human thinking time: {delay:.0f}s before attempt {attempt_number + 1}...")
    sleep(delay)


def format_potd(potd):
    """Format scraped POTD into a readable output."""
    lines = [
        "=" * 60,
        f"  LeetCode Problem of the Day",
        "=" * 60,
        "",
        f"  Title: {potd.get('title', 'N/A')}",
        f"  Difficulty: {potd.get('difficulty', 'N/A')}",
        f"  URL: {potd.get('url', 'N/A')}",
        f"  Topics: {', '.join(potd.get('topics', [])) or 'N/A'}",
        f"  Likes: {potd.get('likes', 'N/A')} | Dislikes: {potd.get('dislikes', 'N/A')}",
        "",
        "-" * 60,
        "  Problem Description:",
        "-" * 60,
        "",
        potd.get("content_text", "Could not fetch content."),
        "",
    ]

    if potd.get("examples"):
        lines.append("-" * 60)
        lines.append("  Examples:")
        lines.append("-" * 60)
        for i, example in enumerate(potd["examples"], 1):
            lines.append(f"\n  Example {i}:")
            lines.append(f"  {example}")
        lines.append("")

    if potd.get("constraints"):
        lines.append("-" * 60)
        lines.append("  Constraints:")
        lines.append("-" * 60)
        for constraint in potd["constraints"]:
            lines.append(f"  • {constraint}")
        lines.append("")

    if potd.get("follow_up"):
        lines.append("-" * 60)
        lines.append("  Follow-up (expected complexity):")
        lines.append("-" * 60)
        lines.append(f"  {potd['follow_up']}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def format_attempt_result(attempt_number, solution, result):
    """Format a single attempt's result."""
    lines = [
        "",
        f"  --- Attempt {attempt_number} ---",
        f"  Status: {result['status']}",
    ]
    if result.get("details"):
        lines.append(f"  Details: {result['details']}")
    lines.append(f"  Solution:\n{solution[:200]}{'...' if len(solution) > 200 else ''}")
    return "\n".join(lines)


def process_potd():
    load_config()

    now = datetime.now()
    logger.info(f"Started at {now}")

    driver = None

    try:
        # Step 1: Launch headless browser and login
        logger.info("Step 1: Creating Selenium driver")
        driver = create_driver()
        logger.info("Step 1: Selenium driver created")

        logger.info("Step 1: Starting LeetCode login")
        login(driver)
        logger.info("Step 1: LeetCode login completed successfully")

        print("waiting")
        logger.info("Waiting 10 seconds after successful login before proceeding")
        sleep(10)

        # Step 2: Navigate to the POTD problem page
        logger.info("Step 2: Navigating to LeetCode POTD page")
        navigate_to_potd(driver)
        logger.info(f"Step 2: POTD page loaded: {driver.current_url}")

        # Step 3: Scrape the problem content from the page
        logger.info("Step 3: Starting POTD scrape")
        potd = scrape_potd_content(driver)
        logger.info(
            "Step 3: POTD scrape completed successfully: "
            f"title={potd.get('title', 'N/A')!r}, difficulty={potd.get('difficulty', 'N/A')!r}, "
            f"examples={len(potd.get('examples', []))}, constraints={len(potd.get('constraints', []))}"
        )
        print(format_potd(potd))

        # Step 4: Decide the attempt strategy
        logger.info("Step 4: Deciding attempt strategy")
        correct_attempt = decide_attempt_strategy(MAX_ATTEMPTS)
        logger.info(f"Strategy: will submit correct solution on attempt {correct_attempt} of {MAX_ATTEMPTS}")

        # Step 5: Generate the correct solution (cached for use on the winning attempt)
        logger.info("Step 5: Requesting correct solution from LLM")
        correct_solution = solve_problem(potd, language=TARGET_LANGUAGE)
        logger.info(f"Step 5: Correct solution ready ({len(correct_solution)} chars)")

        # Step 6: Multi-attempt submission loop
        logger.info("Step 6: Starting submission attempts")
        attempts = []
        previous_solution = None

        for attempt in range(1, correct_attempt + 1):
            is_final_correct_attempt = (attempt == correct_attempt)

            if is_final_correct_attempt:
                solution = correct_solution
                logger.info(f"Attempt {attempt}: Using cached correct solution")
            else:
                logger.info(f"Attempt {attempt}: Requesting deliberately flawed solution from LLM")
                solution = generate_flawed_solution(potd, attempt, previous_solution, language=TARGET_LANGUAGE)
                logger.info(f"Attempt {attempt}: Flawed solution ready ({len(solution)} chars)")

            # Submit
            logger.info(f"Attempt {attempt}: Submitting solution to LeetCode")
            result = paste_and_submit(driver, solution, language=TARGET_LANGUAGE)
            logger.info(f"Attempt {attempt}: Submission completed with status={result.get('status')!r}, details={result.get('details', '')!r}")
            attempts.append({"attempt": attempt, "solution": solution, "result": result})
            print(format_attempt_result(attempt, solution, result))

            if result.get("status") == "Accepted":
                logger.info(f"Attempt {attempt}: Accepted result received; stopping submission loop")
                break

            previous_solution = solution

            # If not the last attempt, simulate human thinking time
            if not is_final_correct_attempt:
                human_delay(attempt)

        # Step 7: Final summary
        print("\n" + "=" * 60)
        print("  FINAL SUMMARY")
        print("=" * 60)
        print(f"  Problem: {potd.get('title', 'N/A')}")
        print(f"  Total attempts: {len(attempts)}")
        print(f"  Final status: {attempts[-1]['result']['status']}")
        print("=" * 60)

        logger.info("Step 7: Final summary generated")
        logger.info(f"Completed in {datetime.now() - now}")

        return {"potd": potd, "attempts": attempts}

    except Exception as e:
        logger.error(f"Failed: {e}")
        raise
    finally:
        if driver:
            driver.quit()



def solve_contest_problem_with_retries(driver, potd, problem_number, max_attempts=5):
    """Solve one contest problem with probabilistic setup and deterministic correct retries."""
    correct_attempt = decide_attempt_strategy(MAX_ATTEMPTS)
    logger.info(
        f"Contest Problem {problem_number}: Probabilistic strategy chose correct attempt "
        f"{correct_attempt} using POTD odds 30/60/100"
    )
    logger.info(
        f"Contest Problem {problem_number}: Once correct phase starts, will retry up to "
        f"{max_attempts} corrected solution(s) without probability"
    )

    attempts = []
    previous_solution = None

    for attempt in range(1, correct_attempt):
        logger.info(f"Contest Problem {problem_number}, attempt {attempt}: Requesting human-like flawed solution")
        solution = generate_flawed_solution(potd, attempt, previous_solution, language=TARGET_LANGUAGE)
        logger.info(f"Contest Problem {problem_number}, attempt {attempt}: Flawed candidate ready ({len(solution)} chars)")

        logger.info(f"Contest Problem {problem_number}, attempt {attempt}: Submitting flawed candidate")
        result = paste_and_submit(driver, solution, language=TARGET_LANGUAGE)
        logger.info(
            f"Contest Problem {problem_number}, attempt {attempt}: Submission completed with "
            f"status={result.get('status')!r}, details={result.get('details', '')!r}"
        )
        attempts.append({"attempt": attempt, "phase": "probabilistic", "solution": solution, "result": result})
        print(format_attempt_result(attempt, solution, result))

        if result.get("status") == "Accepted":
            logger.info(f"Contest Problem {problem_number}, attempt {attempt}: Accepted early; stopping retries")
            logger.info(f"Contest Problem {problem_number}: Successful solve cooldown for {POST_SUCCESS_COOLDOWN}s")
            sleep(POST_SUCCESS_COOLDOWN)
            return attempts

        previous_solution = solution
        human_delay(attempt)

    previous_result = None
    for retry in range(1, max_attempts + 1):
        attempt_number = correct_attempt + retry - 1
        if retry == 1:
            logger.info(
                f"Contest Problem {problem_number}, attempt {attempt_number}: "
                "Entering correct phase; requesting correct solution"
            )
            solution = solve_problem(potd, language=TARGET_LANGUAGE)
        else:
            logger.info(
                f"Contest Problem {problem_number}, attempt {attempt_number}: "
                "Correct phase retry; requesting corrected solution from failed feedback"
            )
            solution = solve_problem_with_feedback(
                potd,
                previous_solution=previous_solution,
                previous_result=previous_result,
                language=TARGET_LANGUAGE,
            )

        logger.info(
            f"Contest Problem {problem_number}, attempt {attempt_number}: "
            f"Correct-phase solution ready ({len(solution)} chars)"
        )
        result = paste_and_submit(driver, solution, language=TARGET_LANGUAGE)
        logger.info(
            f"Contest Problem {problem_number}, attempt {attempt_number}: Correct-phase submission completed with "
            f"status={result.get('status')!r}, details={result.get('details', '')!r}"
        )
        attempts.append({"attempt": attempt_number, "phase": "correct", "retry": retry, "solution": solution, "result": result})
        print(format_attempt_result(attempt_number, solution, result))

        if result.get("status") == "Accepted":
            logger.info(
                f"Contest Problem {problem_number}, attempt {attempt_number}: Accepted in correct phase "
                f"on retry {retry}; stopping retries"
            )
            logger.info(f"Contest Problem {problem_number}: Successful solve cooldown for {POST_SUCCESS_COOLDOWN}s")
            sleep(POST_SUCCESS_COOLDOWN)
            return attempts

        previous_solution = solution
        previous_result = result
        if retry < max_attempts:
            logger.info(
                f"Contest Problem {problem_number}: Correct attempt failed; retrying corrected solution "
                f"({retry}/{max_attempts})"
            )
            human_delay(attempt_number)

    logger.warning(
        f"Contest Problem {problem_number}: Skipping after {max_attempts} failed correct-phase retries"
    )
    return attempts

def process_contest():
    load_config()

    now = datetime.now()
    logger.info(f"Contest mode started at {now}")

    contest_slug = os.getenv("CONTEST_SLUG") or read_optional_input(
        "Enter past contest slug, for example weekly-contest-500, or press Enter for latest past contest: "
    )

    max_problems = int(4)

    driver = None
    contest_results = []

    try:
        logger.info("Contest Step 1: Creating Selenium driver")
        driver = create_driver()
        logger.info("Contest Step 1: Selenium driver created")

        logger.info("Contest Step 1: Starting LeetCode login")
        login(driver)
        logger.info("Contest Step 1: LeetCode login completed successfully")

        print("waiting")
        logger.info("Waiting 10 seconds after successful login before proceeding")
        sleep(10)

        if not contest_slug:
            logger.info("Contest Step 2: No contest slug provided; selecting latest past contest")
            contest_slug = get_latest_past_contest_slug(driver)
        logger.info(f"Contest Step 2: Using contest slug {contest_slug!r}")

        logger.info("Contest Step 3: Opening and starting virtual contest practice")
        start_virtual_contest(driver, contest_slug)

        logger.info("Contest Step 4: Fetching contest question list")
        questions = get_contest_questions(driver, contest_slug)
        if max_problems is not None:
            questions = questions[:max_problems]
        logger.info(f"Contest Step 4: Will solve {len(questions)} problem(s)")

        for index, question in enumerate(questions, 1):
            title_slug = question["titleSlug"]
            logger.info(
                f"Contest Problem {index}/{len(questions)}: Starting {question.get('title', title_slug)!r} "
                f"({title_slug})"
            )

            navigate_to_contest_problem(driver, contest_slug, title_slug)
            potd = scrape_potd_content(driver)
            potd["contest_slug"] = contest_slug
            potd["contest_credit"] = question.get("credit")
            print(format_potd(potd))

            problem_attempts = solve_contest_problem_with_retries(
                driver,
                potd,
                problem_number=index,
                max_attempts=CONTEST_CORRECT_RETRIES,
            )
            contest_results.append({"question": question, "attempts": problem_attempts, "result": problem_attempts[-1]["result"]})

        print("\n" + "=" * 60)
        print("  CONTEST SUMMARY")
        print("=" * 60)
        print(f"  Contest: {contest_slug}")
        print(f"  Problems attempted: {len(contest_results)}")
        for item in contest_results:
            attempts_count = len(item.get("attempts", []))
            print(
                f"  {item['question'].get('title', item['question'].get('titleSlug'))}: "
                f"{item['result'].get('status')} ({attempts_count} attempt(s))"
            )
        print("=" * 60)

        logger.info(f"Contest mode completed in {datetime.now() - now}")
        return {"contest_slug": contest_slug, "results": contest_results}

    except Exception as e:
        logger.error(f"Contest mode failed: {e}")
        raise
    finally:
        if driver:
            driver.quit()


def process_live_contest_readonly():
    """Scrape live contest problems without solving, testing, or submitting anything."""
    load_config()

    now = datetime.now()
    logger.info(f"Live contest read-only mode started at {now}")

    contest_slug = os.getenv("LIVE_CONTEST_SLUG") or os.getenv("CONTEST_SLUG") or read_optional_input(
        "Enter live contest slug, for example weekly-contest-501, or press Enter for first visible live/upcoming contest: "
    )

    max_problems = int(4)

    driver = None
    scraped_problems = []

    try:
        logger.info("Live Readonly Step 1: Creating Selenium driver")
        driver = create_driver()
        logger.info("Live Readonly Step 1: Selenium driver created")

        logger.info("Live Readonly Step 1: Starting LeetCode login")
        try:
            login(driver)
            logger.info("Live Readonly Step 1: LeetCode login completed successfully")
        except Exception as exc:
            logger.warning(
                "Live Readonly Step 1: Login did not complete; continuing read-only as guest. "
                f"Reason: {exc}"
            )

        print("waiting")
        logger.info("Waiting 10 seconds before proceeding with read-only scrape")
        sleep(10)

        if not contest_slug:
            logger.info("Live Readonly Step 2: No contest slug provided; reading contest page")
            live_slugs = get_live_contest_slugs(driver)
            if not live_slugs:
                raise RuntimeError("Could not find any live/upcoming contest slug on the LeetCode contest page")
            contest_slug = live_slugs[0]

        logger.info(f"Live Readonly Step 2: Using contest slug {contest_slug!r}")

        logger.info("Live Readonly Step 3: Fetching contest question list")
        questions = get_contest_questions(driver, contest_slug)
        if max_problems is not None:
            questions = questions[:max_problems]
        logger.info(f"Live Readonly Step 3: Will scrape {len(questions)} problem(s)")

        for index, question in enumerate(questions, 1):
            title_slug = question["titleSlug"]
            logger.info(
                f"Live Readonly Problem {index}/{len(questions)}: Opening "
                f"{question.get('title', title_slug)!r} ({title_slug})"
            )

            navigate_to_contest_problem(driver, contest_slug, title_slug)
            problem = scrape_potd_content(driver)
            problem["contest_slug"] = contest_slug
            problem["contest_credit"] = question.get("credit")

            logger.info(
                f"Live Readonly Problem {index}/{len(questions)}: Scrape successful: "
                f"title={problem.get('title', 'N/A')!r}, difficulty={problem.get('difficulty', 'N/A')!r}, "
                f"content_chars={len(problem.get('content_text', ''))}"
            )
            print(format_potd(problem))
            scraped_problems.append({"question": question, "problem": problem})

        print("\n" + "=" * 60)
        print("  LIVE CONTEST READ-ONLY SUMMARY")
        print("=" * 60)
        print(f"  Contest: {contest_slug}")
        print(f"  Problems scraped: {len(scraped_problems)}")
        for item in scraped_problems:
            problem = item["problem"]
            print(f"  {problem.get('title', item['question'].get('titleSlug'))}: scraped")
        print("=" * 60)

        logger.info(f"Live contest read-only mode completed in {datetime.now() - now}")
        return {"contest_slug": contest_slug, "problems": scraped_problems}

    except Exception as e:
        logger.error(f"Live contest read-only mode failed: {e}")
        raise
    finally:
        if driver:
            driver.quit()


def choose_mode():
    mode = (os.getenv("LC_SOLVER_MODE") or "").strip().lower()
    if not mode:
        print("Select mode:")
        print("  1. POTD")
        print("  2. LeetCode past contest")
        print("  3. Live contest read-only")
        mode = input("Enter 1, 2, or 3: ").strip().lower()

    if mode in {"1", "potd", "daily"}:
        return "potd"
    if mode in {"2", "contest", "past-contest", "leetcode contest", "leetcode-contest"}:
        return "contest"
    if mode in {"3", "live", "live-contest", "live-readonly", "live-read-only", "readonly"}:
        return "live-readonly"

    raise ValueError(
        f"Unknown mode {mode!r}. Choose 1 for POTD, 2 for LeetCode past contest, "
        "or 3 for live contest read-only."
    )


def process():
    mode = choose_mode()
    if mode == "potd":
        return process_potd()
    if mode == "contest":
        return process_contest()
    return process_live_contest_readonly()


if __name__ == "__main__":
    process()
