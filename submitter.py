import os
from time import sleep
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException

from util import get_logger

logger = get_logger(__name__)


def get_driver_delay():
    return int(os.getenv("MAX_DRIVER_DELAY_SEC", "15"))



def ensure_editor_ready(driver):
    """Open the Code tab if needed and wait until the Monaco editor is mounted."""
    logger.info("Ensuring code editor is visible")
    if _has_editor(driver):
        logger.info("Code editor is already visible")
        return

    clicked = _click_code_tab(driver)
    if clicked:
        logger.info("Clicked Code tab to open editor")

    try:
        WebDriverWait(driver, get_driver_delay() * 2).until(lambda d: _has_editor(d))
        logger.info("Code editor is visible")
    except TimeoutException as exc:
        raise TimeoutException(
            "Could not find Monaco editor after opening Code tab. "
            f"Visible buttons={_visible_button_texts(driver)[:20]}, "
            f"url={driver.current_url}, title={driver.title!r}"
        ) from exc


def _has_editor(driver):
    return bool(driver.find_elements(By.CSS_SELECTOR, ".monaco-editor textarea, .monaco-editor .view-lines, .cm-content[contenteditable=\"true\"]"))


def _click_code_tab(driver):
    candidates = driver.find_elements(By.XPATH, "//*[normalize-space()='Code' or contains(normalize-space(), 'Code')]")
    for element in candidates:
        if not element.is_displayed():
            continue
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            element.click()
            sleep(1)
            return True
        except Exception:
            continue
    return False

def select_language(driver, language="cpp"):
    """Ensure the requested language is selected in the code editor."""
    language_labels = {
        "cpp": ["C++"],
        "python3": ["Python3", "Python 3"],
        "java": ["Java"],
        "javascript": ["JavaScript"],
    }
    target_labels = language_labels.get((language or "cpp").lower(), [language])
    logger.info(f"Before language selection: checking editor language target={target_labels[0]!r}")

    try:
        lang_btn = _find_language_button(driver, target_labels)
        if not lang_btn:
            button_texts = _visible_button_texts(driver)
            logger.warning(
                "Could not find language dropdown. Continuing because the editor may already be on the right language. "
                f"Visible buttons={button_texts[:20]}"
            )
            return

        current_lang = lang_btn.text.strip()
        if any(label in current_lang for label in target_labels):
            logger.info(f"After language selection: {target_labels[0]} already selected")
            return

        lang_btn.click()
        sleep(1)

        option_xpath = " | ".join(
            f"//*[self::li or self::div or self::span][contains(normalize-space(), '{label}')]"
            for label in target_labels
        )
        WebDriverWait(driver, get_driver_delay()).until(
            EC.visibility_of_element_located((By.XPATH, option_xpath))
        )
        language_option = driver.find_element(By.XPATH, option_xpath)
        language_option.click()

        sleep(1)
        logger.info(f"After language selection: selected {target_labels[0]}")
    except Exception as e:
        logger.warning(f"Could not select requested language {target_labels[0]!r} (may already be selected): {e}")


def _find_language_button(driver, target_labels):
    language_names = ["C++", "Python", "Python3", "Java", "JavaScript", "TypeScript", "C#", "Go", "Rust"]
    buttons = driver.find_elements(By.TAG_NAME, "button")
    visible_buttons = [button for button in buttons if button.is_displayed()]

    for button in visible_buttons:
        text = button.text.strip()
        if any(label in text for label in target_labels):
            return button

    for button in visible_buttons:
        text = button.text.strip()
        if any(name in text for name in language_names):
            return button

    return None


def _visible_button_texts(driver):
    texts = []
    for button in driver.find_elements(By.TAG_NAME, "button"):
        if button.is_displayed():
            text = button.text.strip()
            if text:
                texts.append(text)
    return texts

def clear_editor(driver):
    """Clear the existing code in the Monaco editor."""
    logger.info("Before clearing editor")
    ensure_editor_ready(driver)
    editor_selector = ".monaco-editor textarea, .monaco-editor .view-lines, .cm-content[contenteditable=\"true\"]"
    editor = WebDriverWait(driver, get_driver_delay()).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, editor_selector))
    )
    editor.click()
    sleep(0.5)

    # Select all and delete
    actions = ActionChains(driver)
    modifier = Keys.COMMAND if os.uname().sysname == "Darwin" else Keys.CONTROL
    actions.key_down(modifier).send_keys("a").key_up(modifier).perform()
    sleep(0.3)
    actions.send_keys(Keys.BACKSPACE).perform()
    sleep(0.5)
    logger.info("After clearing editor")


def type_solution(driver, solution_code):
    """
    Paste the solution code into the LeetCode Monaco editor.
    Uses clipboard paste for reliability with Monaco editor.
    """
    logger.info(f"Before pasting solution into editor ({len(solution_code)} chars)")
    ensure_editor_ready(driver)
    editor_target = WebDriverWait(driver, get_driver_delay()).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".monaco-editor textarea, .cm-content[contenteditable=\"true\"]"))
    )
    editor_target.click()
    sleep(0.5)

    # Use JavaScript to set clipboard and paste (Monaco doesn't work well with send_keys)
    # Instead, we use the Monaco editor's setValue API via JavaScript
    driver.execute_script("""
        const editor = document.querySelector('.monaco-editor');
        const monacoEditor = editor?.querySelector('.overflow-guard')?.parentElement;
        if (monacoEditor) {
            // Access the Monaco editor instance through the DOM
            const editorInstance = monacoEditor.__proto__?.constructor;
        }
    """)

    # Most reliable approach: use the editor's textarea with Ctrl+A, then type
    modifier = Keys.COMMAND if os.uname().sysname == "Darwin" else Keys.CONTROL

    actions = ActionChains(driver)
    actions.key_down(modifier).send_keys("a").key_up(modifier).perform()
    sleep(0.3)

    # Paste via JavaScript clipboard API
    escaped_code = solution_code.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    driver.execute_script(f"""
        const target = document.querySelector('.monaco-editor textarea') ||
            document.querySelector('.cm-content[contenteditable="true"]');
        if (target) {{
            target.focus();
            const dt = new DataTransfer();
            dt.setData('text/plain', `{escaped_code}`);
            const pasteEvent = new ClipboardEvent('paste', {{
                clipboardData: dt,
                bubbles: true,
                cancelable: true
            }});
            target.dispatchEvent(pasteEvent);
        }}
    """)

    sleep(1)
    logger.info("After pasting solution into editor")


def submit_solution(driver):
    """
    Click the Submit button and wait for the result.
    Returns a dict with submission status.
    """
    now = datetime.now()

    logger.info("Before submitting solution: locating Submit button")
    submit_btn_xpath = "//button[contains(@data-e2e-locator, 'console-submit-button')] | //button[.//text()='Submit']"
    WebDriverWait(driver, get_driver_delay()).until(
        EC.element_to_be_clickable((By.XPATH, submit_btn_xpath))
    )
    submit_btn = driver.find_element(By.XPATH, submit_btn_xpath)
    submit_btn.click()

    logger.info("After clicking Submit: waiting for result")

    try:
        result = WebDriverWait(driver, get_driver_delay() * 6).until(_submission_result_from_page)
    except TimeoutException as exc:
        diagnostic = _submission_timeout_diagnostic(driver)
        raise TimeoutException(
            f"Timed out waiting for LeetCode submission result after {get_driver_delay() * 6}s. {diagnostic}"
        ) from exc

    logger.info(
        f"After submission result: {result['status']}, details={result.get('details', '')!r}, "
        f"time={datetime.now() - now}"
    )
    return result


def _submission_result_from_page(driver):
    body_text = driver.find_element(By.TAG_NAME, "body").text
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]

    failure_statuses = [
        "Wrong Answer",
        "Time Limit Exceeded",
        "Runtime Error",
        "Memory Limit Exceeded",
        "Compile Error",
        "Output Limit Exceeded",
    ]

    for status in failure_statuses:
        for idx, line in enumerate(lines):
            if status in line:
                return {
                    "status": status,
                    "details": " | ".join(lines[idx:idx + 8])[:500],
                }

    for idx, line in enumerate(lines):
        if line == "Accepted" or line.startswith("Accepted"):
            nearby = " | ".join(lines[idx:idx + 10])
            nearby_lower = nearby.lower()
            static_problem_stats = "acceptance rate" in nearby_lower and "testcases passed" not in nearby_lower
            actual_result = any(token in nearby_lower for token in [
                "testcases passed",
                "runtime",
                "memory",
                "beats",
            ])
            if actual_result and not static_problem_stats:
                return {
                    "status": "Accepted",
                    "details": nearby[:500],
                }

    return False
def _submission_details_from_text(body_text, status):
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    try:
        idx = next(i for i, line in enumerate(lines) if status in line)
    except StopIteration:
        return ""
    return " | ".join(lines[idx:idx + 8])[:500]


def _submission_timeout_diagnostic(driver):
    body_text = ""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        pass

    interesting = []
    for line in body_text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if stripped and any(word in lowered for word in ["pending", "judging", "submit", "submitted", "error", "login", "captcha", "accepted", "wrong", "runtime", "compile"]):
            interesting.append(stripped)

    if interesting:
        return "Visible page hints: " + " | ".join(interesting[:12])
    return f"url={driver.current_url}, title={driver.title!r}"

def paste_and_submit(driver, solution_code, language="cpp"):
    """
    Full flow: select language, clear editor, paste solution, submit.
    Returns the submission result.
    """
    logger.info("Before paste_and_submit flow")
    ensure_editor_ready(driver)
    select_language(driver, language)
    clear_editor(driver)
    type_solution(driver, solution_code)
    sleep(1)
    logger.info("Before final submit_solution call")
    result = submit_solution(driver)
    logger.info(f"After paste_and_submit flow: status={result.get('status')!r}")
    return result
