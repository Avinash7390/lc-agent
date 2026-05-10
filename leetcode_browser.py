import os
import re
from html import unescape
from time import sleep
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

import constants
from util import get_logger

logger = get_logger(__name__)


def get_driver_delay():
    return int(os.getenv("MAX_DRIVER_DELAY_SEC", "15"))


def create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=options)
    return driver


def login(driver):
    """
    Logs into LeetCode using a session cookie when available, otherwise email/password.
    """
    now = datetime.now()

    session_cookie = os.getenv("LEETCODE_SESSION")
    if session_cookie:
        _login_with_session_cookie(driver, session_cookie, now)
        return

    driver.get(constants.LEETCODE_LOGIN_URL)

    WebDriverWait(driver, get_driver_delay()).until(
        EC.visibility_of_element_located((By.ID, "id_login"))
    )

    username = os.getenv("LC_USERNAME")
    password = os.getenv("LC_PASSWORD")

    username_field = driver.find_element(By.ID, "id_login")
    username_field.clear()
    username_field.send_keys(username)

    password_field = driver.find_element(By.ID, "id_password")
    password_field.clear()
    password_field.send_keys(password)

    try:
        WebDriverWait(driver, get_driver_delay()).until(
            EC.invisibility_of_element_located((By.ID, "initial-loading"))
        )
        login_btn = WebDriverWait(driver, get_driver_delay()).until(
            EC.element_to_be_clickable((By.ID, "signin_btn"))
        )
    except TimeoutException as exc:
        reason = _get_login_blocker(driver)
        raise TimeoutException(
            f"LeetCode sign-in button did not become clickable within {get_driver_delay()}s. {reason}"
        ) from exc

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", login_btn)
    login_btn.click()

    try:
        WebDriverWait(driver, get_driver_delay()).until(_login_finished)
    except TimeoutException as exc:
        reason = _get_login_blocker(driver)
        raise TimeoutException(
            f"LeetCode login did not complete within {get_driver_delay()}s. {reason}"
        ) from exc

    sleep(2)
    logger.info(
        "Login successful. Response after login: "
        f"url={driver.current_url}, title={driver.title!r}"
    )
    logger.info(f"Login successful. Time taken: {datetime.now() - now}")


def _login_with_session_cookie(driver, session_cookie, start_time):
    driver.get(constants.LEETCODE_BASE_URL)
    driver.add_cookie({
        "name": "LEETCODE_SESSION",
        "value": session_cookie,
        "domain": ".leetcode.com",
        "path": "/",
        "secure": True,
    })

    csrf_token = os.getenv("LEETCODE_CSRFTOKEN") or os.getenv("CSRFTOKEN")
    if csrf_token:
        driver.add_cookie({
            "name": "csrftoken",
            "value": csrf_token,
            "domain": ".leetcode.com",
            "path": "/",
            "secure": True,
        })

    driver.get(constants.LEETCODE_BASE_URL)
    try:
        WebDriverWait(driver, get_driver_delay()).until(_is_logged_in)
    except TimeoutException as exc:
        raise RuntimeError(
            "LEETCODE_SESSION cookie was set, but LeetCode still does not show a logged-in account. "
            "Refresh the cookie from your browser and update .env."
        ) from exc

    logger.info(
        "Login successful with session cookie. Response after login: "
        f"url={driver.current_url}, title={driver.title!r}"
    )
    logger.info(f"Login successful with session cookie. Time taken: {datetime.now() - start_time}")



def _login_finished(driver):
    current_url = driver.current_url.rstrip("/")
    login_url = constants.LEETCODE_LOGIN_URL.rstrip("/")
    if current_url != login_url and "/accounts/login" not in current_url:
        return True

    return _is_logged_in(driver)


def _is_logged_in(driver):
    account_selectors = [
        (By.CSS_SELECTOR, "[data-cy='navbar-user-menu']"),
        (By.CSS_SELECTOR, "a[href='/profile/']"),
        (By.XPATH, "//a[contains(@href, '/u/') or contains(@href, '/profile/')]"),
    ]
    if any(el.is_displayed() for by, selector in account_selectors for el in driver.find_elements(by, selector)):
        return True

    status = _get_user_status(driver)
    return bool(status and status.get("isSignedIn"))


def _get_user_status(driver):
    script = """
        const done = arguments[0];
        const csrf = document.cookie
            .split('; ')
            .find((item) => item.startsWith('csrftoken='))
            ?.split('=')[1] || '';

        fetch('/graphql', {
            method: 'POST',
            credentials: 'include',
            headers: {
                'content-type': 'application/json',
                'x-csrftoken': csrf,
            },
            body: JSON.stringify({
                query: 'query globalData { userStatus { isSignedIn username realName userSlug } }',
            }),
        })
            .then((response) => response.json())
            .then((payload) => done(payload?.data?.userStatus || null))
            .catch(() => done(null));
    """
    return driver.execute_async_script(script)


def _get_login_blocker(driver):
    messages = _visible_texts(driver, [
        (By.CSS_SELECTOR, ".text-red-s, .text-red-500, .text-red-600"),
        (By.CSS_SELECTOR, "[role='alert'], .error, .alert, .notification"),
        (By.XPATH, "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'captcha')]"),
        (By.XPATH, "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'verify')]"),
        (By.XPATH, "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'invalid')]"),
    ])
    if messages:
        return "Page message: " + " | ".join(messages[:3])

    turnstile_responses = driver.find_elements(By.CSS_SELECTOR, "input[name='cf-turnstile-response']")
    if any(not el.get_attribute("value") for el in turnstile_responses):
        return (
            "Cloudflare Turnstile did not complete, so LeetCode kept Sign In disabled. "
            "Headless password login is blocked; set LEETCODE_SESSION in .env from an already logged-in browser session."
        )

    captcha_elements = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='captcha'], iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='challenges.cloudflare.com']")
    if any(el.is_displayed() for el in captcha_elements):
        return "A CAPTCHA or bot check is visible. Complete login in a normal browser or use a saved session/cookies approach."

    sign_in_buttons = driver.find_elements(By.ID, "signin_btn")
    if sign_in_buttons and not sign_in_buttons[0].is_enabled():
        return "The sign-in button is still disabled. LeetCode may not have accepted the typed credentials yet, or the page is still loading."

    return f"Still on {driver.current_url}. Check credentials, CAPTCHA, or increase MAX_DRIVER_DELAY_SEC."


def _visible_texts(driver, selectors):
    texts = []
    for by, selector in selectors:
        for element in driver.find_elements(by, selector):
            if element.is_displayed():
                text = element.text.strip()
                if text and text not in texts:
                    texts.append(text)
    return texts




def get_live_contest_slugs(driver):
    """Return currently live/upcoming contest slugs visible on the contest landing page."""
    driver.get(f"{constants.LEETCODE_BASE_URL}/contest/")
    WebDriverWait(driver, get_driver_delay()).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    sleep(2)

    slugs = []
    for link in driver.find_elements(By.TAG_NAME, "a"):
        href = link.get_attribute("href") or ""
        match = re.search(r"/contest/((?:weekly|biweekly)-contest-\d+)/?", href)
        if match:
            slug = match.group(1)
            if slug not in slugs:
                slugs.append(slug)

    logger.info(f"Live/upcoming contest slugs visible on contest page: {slugs[:5]}")
    return slugs

def get_latest_past_contest_slug(driver):
    """Return the first unattempted past contest slug from the contest landing page."""
    driver.get(f"{constants.LEETCODE_BASE_URL}/contest/")
    WebDriverWait(driver, get_driver_delay()).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    sleep(2)

    first_virtual_slug = None
    for link in driver.find_elements(By.TAG_NAME, "a"):
        href = link.get_attribute("href") or ""
        text = link.text or ""
        match = re.search(r"/contest/((?:weekly|biweekly)-contest-\d+)/?", href)
        # if not match or "Virtual" not in text:
        #     continue

        slug = match.group(1)
        if first_virtual_slug is None:
            first_virtual_slug = slug

        if re.search(r"\b0\s*/\s*4\b", text):
            logger.info(f"Selected latest unattempted past contest from contest page: {slug}")
            return slug

    if first_virtual_slug:
        logger.warning(
            "Could not find a 0 / 4 unattempted contest on the first contest page; "
            f"falling back to latest virtual contest: {first_virtual_slug}"
        )
        return first_virtual_slug

    raise RuntimeError("Could not find a past contest with a Virtual entry on the LeetCode contest page")


def start_virtual_contest(driver, contest_slug):
    """Open a past contest and start its virtual practice when the prompt is shown."""
    contest_url = f"{constants.LEETCODE_BASE_URL}/contest/{contest_slug}/"
    logger.info(f"Opening contest page: {contest_url}")
    driver.get(contest_url)
    WebDriverWait(driver, get_driver_delay()).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    sleep(2)

    _click_button_by_text(driver, "Virtual Contest", required=False)
    sleep(1)
    clicked_start = _click_button_by_text(driver, "Start Practice", required=False)
    if clicked_start:
        logger.info(f"Started virtual practice for contest: {contest_slug}")
        sleep(3)
    else:
        logger.info(
            f"Virtual practice start button was not shown for {contest_slug}; "
            "continuing with contest problem pages."
        )

    return contest_url


def get_contest_questions(driver, contest_slug):
    """Fetch contest questions using LeetCode GraphQL."""
    query = """
        query contestQuestionList($contestSlug: String!) {
            contestQuestionList(contestSlug: $contestSlug) {
                questionId
                title
                titleSlug
                credit
            }
        }
    """
    payload = _leetcode_graphql(driver, query, {"contestSlug": contest_slug})
    questions = (payload.get("data") or {}).get("contestQuestionList") or []
    if not questions:
        raise RuntimeError(f"No contest questions returned for {contest_slug}: {payload}")

    logger.info(
        f"Fetched {len(questions)} contest questions for {contest_slug}: "
        + ", ".join(q.get("titleSlug", "") for q in questions)
    )
    return questions


def navigate_to_contest_problem(driver, contest_slug, title_slug):
    """Navigate to a problem inside the contest route."""
    url = f"{constants.LEETCODE_BASE_URL}/contest/{contest_slug}/problems/{title_slug}/description/"
    logger.info(f"Navigating to contest problem: {url}")
    driver.get(url)
    WebDriverWait(driver, get_driver_delay()).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    sleep(2)
    logger.info(f"Contest problem loaded: {driver.current_url}")
    return driver.current_url


def _click_button_by_text(driver, text, required=True):
    for button in driver.find_elements(By.TAG_NAME, "button"):
        if button.is_displayed() and text in (button.text or ""):
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
            button.click()
            return True

    if required:
        visible = [b.text.strip() for b in driver.find_elements(By.TAG_NAME, "button") if b.is_displayed() and b.text.strip()]
        raise RuntimeError(f"Could not find button containing {text!r}. Visible buttons={visible[:30]}")
    return False

def navigate_to_potd(driver):
    """
    Navigates to the POTD page using LeetCode's daily challenge GraphQL data.
    """
    logger.info("Fetching POTD metadata from LeetCode GraphQL")
    daily = _get_daily_challenge(driver)
    if not daily:
        raise RuntimeError("Could not fetch LeetCode daily challenge metadata from GraphQL")

    question = daily.get("question") or {}
    title_slug = question.get("titleSlug")
    link = daily.get("link")

    if link:
        potd_url = f"{constants.LEETCODE_BASE_URL}{link}"
    elif title_slug:
        potd_url = f"{constants.LEETCODE_BASE_URL}/problems/{title_slug}/description/"
    else:
        raise RuntimeError(f"Daily challenge response did not include a problem link or slug: {daily}")

    logger.info(
        "POTD metadata received: "
        f"title={question.get('title', 'N/A')!r}, slug={title_slug!r}, date={daily.get('date', 'N/A')!r}"
    )
    driver.get(potd_url)

    try:
        WebDriverWait(driver, get_driver_delay()).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-track-load='description_content']"))
        )
    except TimeoutException:
        logger.warning(
            "POTD page loaded, but description DOM selector was not found. "
            "Scraping will use GraphQL question data instead."
        )

    sleep(2)
    logger.info(f"Navigated to POTD: {driver.current_url}")

    return driver.current_url


def scrape_potd_content(driver):
    """
    Scrapes the POTD problem content from GraphQL first, then falls back to page DOM.
    Extracts: title, difficulty, description, examples, constraints, topics.
    """
    now = datetime.now()
    slug = _slug_from_current_url(driver.current_url)

    if slug:
        try:
            potd = _scrape_question_via_graphql(driver, slug)
            if potd and potd.get("content_text"):
                logger.info(
                    "Scraped POTD content via GraphQL: "
                    f"title={potd.get('title', 'N/A')!r}, difficulty={potd.get('difficulty', 'N/A')!r}, "
                    f"content_chars={len(potd.get('content_text', ''))}, time={datetime.now() - now}"
                )
                return potd
        except Exception as e:
            logger.warning(f"GraphQL POTD scrape failed, falling back to DOM scrape: {e}")

    potd = {}

    potd["url"] = driver.current_url
    potd["title_slug"] = slug or driver.current_url.rstrip("/").split("/problems/")[-1].split("/")[0]

    title_xpath = "//div[contains(@class, 'text-title-large')]//a"
    try:
        WebDriverWait(driver, get_driver_delay()).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-track-load='description_content']"))
        )
        title_el = driver.find_element(By.XPATH, title_xpath)
        potd["title"] = title_el.text.strip()
    except Exception:
        potd["title"] = driver.title.replace(" - LeetCode", "").strip()

    difficulty_xpath = "//div[contains(@class, 'text-difficulty')]"
    try:
        diff_el = driver.find_element(By.XPATH, difficulty_xpath)
        potd["difficulty"] = diff_el.text.strip()
    except Exception:
        potd["difficulty"] = "Unknown"

    content_selector = "[data-track-load='description_content']"
    try:
        content_el = driver.find_element(By.CSS_SELECTOR, content_selector)
        potd["content_html"] = content_el.get_attribute("innerHTML")
        potd["content_text"] = content_el.text
    except Exception:
        potd["content_html"] = ""
        potd["content_text"] = ""
        logger.error("Could not scrape problem description content")

    potd["examples"] = _extract_examples(driver)
    potd["constraints"] = _extract_constraints(driver)
    potd["follow_up"] = _extract_follow_up(driver)
    potd["starter_code"] = _scrape_starter_code_from_dom(driver)
    potd["code_snippets"] = _build_dom_code_snippets(potd["starter_code"])

    topics_xpath = "//a[contains(@href, '/tag/') and contains(@class, 'topic')]"
    try:
        topic_elements = driver.find_elements(By.XPATH, topics_xpath)
        potd["topics"] = [el.text.strip() for el in topic_elements if el.text.strip()]
    except Exception:
        potd["topics"] = []

    try:
        like_btn = driver.find_element(By.CSS_SELECTOR, "[data-icon='thumbs-up']")
        like_count = like_btn.find_element(By.XPATH, "..").text
        potd["likes"] = like_count.strip()
    except Exception:
        potd["likes"] = "N/A"

    try:
        dislike_btn = driver.find_element(By.CSS_SELECTOR, "[data-icon='thumbs-down']")
        dislike_count = dislike_btn.find_element(By.XPATH, "..").text
        potd["dislikes"] = dislike_count.strip()
    except Exception:
        potd["dislikes"] = "N/A"

    logger.info(
        "Scraped POTD content via DOM. "
        f"starter_code_chars={len(potd.get('starter_code') or '')}, time={datetime.now() - now}"
    )

    return potd


def _get_daily_challenge(driver):
    query = """
        query questionOfToday {
            activeDailyCodingChallengeQuestion {
                date
                link
                question {
                    title
                    titleSlug
                }
            }
        }
    """
    payload = _leetcode_graphql(driver, query)
    return (payload.get("data") or {}).get("activeDailyCodingChallengeQuestion")


def _scrape_question_via_graphql(driver, title_slug):
    query = """
        query questionData($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                title
                titleSlug
                content
                difficulty
                likes
                dislikes
                topicTags {
                    name
                    slug
                }
                codeSnippets {
                    lang
                    langSlug
                    code
                }
            }
        }
    """
    payload = _leetcode_graphql(driver, query, {"titleSlug": title_slug})
    question = (payload.get("data") or {}).get("question")
    if not question:
        raise RuntimeError(f"No question data returned for slug={title_slug!r}: {payload}")

    content_html = question.get("content") or ""
    content_text = _html_to_text(content_html)

    return {
        "url": driver.current_url,
        "title_slug": question.get("titleSlug") or title_slug,
        "title": question.get("title") or "N/A",
        "difficulty": question.get("difficulty") or "Unknown",
        "content_html": content_html,
        "content_text": content_text,
        "examples": _extract_examples_from_html(content_html, content_text),
        "constraints": _extract_constraints_from_text(content_text),
        "follow_up": _extract_follow_up_from_text(content_text),
        "topics": [tag.get("name") for tag in question.get("topicTags", []) if tag.get("name")],
        "code_snippets": question.get("codeSnippets", []),
        "starter_code": _select_starter_code(question.get("codeSnippets", []), os.getenv("LEETCODE_LANGUAGE", "cpp")),
        "likes": question.get("likes", "N/A"),
        "dislikes": question.get("dislikes", "N/A"),
    }



def _select_starter_code(code_snippets, language):
    language = (language or "cpp").lower()
    aliases = {
        "cpp": {"cpp", "c++"},
        "python3": {"python3", "python", "py"},
        "java": {"java"},
        "javascript": {"javascript", "js"},
    }
    accepted = aliases.get(language, {language})

    for snippet in code_snippets or []:
        lang_slug = (snippet.get("langSlug") or "").lower()
        lang = (snippet.get("lang") or "").lower()
        if lang_slug in accepted or lang in accepted:
            return snippet.get("code") or ""

    return ""


def _scrape_starter_code_from_dom(driver):
    """Extract starter code from the visible LeetCode editor when GraphQL is unavailable."""
    try:
        WebDriverWait(driver, min(get_driver_delay(), 5)).until(
            lambda d: d.execute_script(
                """
                if (window.monaco?.editor?.getModels?.().length) return true;
                if (document.querySelector('.cm-content[contenteditable="true"]')) return true;
                if (document.querySelector('.monaco-editor textarea')) return true;
                return false;
                """
            )
        )
    except TimeoutException:
        logger.warning("Starter code editor was not visible during DOM fallback scrape")

    script = """
        const normalize = (value) => (value || '').replace(/\u00a0/g, ' ').trim();

        const monacoModels = window.monaco?.editor?.getModels?.() || [];
        for (const model of monacoModels) {
            const value = normalize(model.getValue?.());
            if (value) return value;
        }

        const codeMirror = document.querySelector('.cm-content[contenteditable="true"]');
        if (codeMirror) {
            const value = normalize(codeMirror.innerText || codeMirror.textContent);
            if (value) return value;
        }

        const monacoTextareas = [...document.querySelectorAll('.monaco-editor textarea')];
        for (const textarea of monacoTextareas) {
            const value = normalize(textarea.value || textarea.getAttribute('value'));
            if (value) return value;
        }

        const visibleCodeBlocks = [...document.querySelectorAll('pre, code')]
            .map((node) => normalize(node.innerText || node.textContent))
            .filter(Boolean);
        return visibleCodeBlocks.find((value) => /class\\s+Solution|def\\s+\\w+|public\\s+class\\s+Solution/.test(value)) || '';
    """
    starter_code = driver.execute_script(script) or ""
    if starter_code:
        logger.info(f"Scraped starter code via DOM ({len(starter_code)} chars)")
    return starter_code


def _build_dom_code_snippets(starter_code):
    if not starter_code:
        return []

    language = os.getenv("LEETCODE_LANGUAGE", "cpp").lower()
    language_meta = {
        "cpp": ("C++", "cpp"),
        "c++": ("C++", "cpp"),
        "python": ("Python3", "python3"),
        "python3": ("Python3", "python3"),
        "py": ("Python3", "python3"),
        "java": ("Java", "java"),
        "javascript": ("JavaScript", "javascript"),
        "js": ("JavaScript", "javascript"),
    }
    lang, lang_slug = language_meta.get(language, (language, language))
    return [{"lang": lang, "langSlug": lang_slug, "code": starter_code}]


def _leetcode_graphql(driver, query, variables=None):
    script = """
        const query = arguments[0];
        const variables = arguments[1] || {};
        const done = arguments[arguments.length - 1];
        const csrf = document.cookie
            .split('; ')
            .find((item) => item.startsWith('csrftoken='))
            ?.split('=')[1] || '';

        fetch('/graphql', {
            method: 'POST',
            credentials: 'include',
            headers: {
                'content-type': 'application/json',
                'x-csrftoken': csrf,
            },
            body: JSON.stringify({ query, variables }),
        })
            .then((response) => response.json())
            .then((payload) => done(payload))
            .catch((error) => done({ error: String(error) }));
    """
    payload = driver.execute_async_script(script, query, variables or {})
    if payload.get("error") or payload.get("errors"):
        raise RuntimeError(f"LeetCode GraphQL error: {payload}")
    return payload


def _slug_from_current_url(url):
    if "/problems/" not in url:
        return None
    return url.rstrip("/").split("/problems/", 1)[-1].split("/", 1)[0]


def _html_to_text(content_html):
    text = re.sub(r"(?i)<br\s*/?>", "\n", content_html)
    text = re.sub(r"(?i)</p>|</div>|</li>|</pre>|</h\d>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_examples_from_html(content_html, content_text):
    examples = []
    for block in re.findall(r"(?is)<pre[^>]*>(.*?)</pre>", content_html):
        example = _html_to_text(block).strip()
        if example:
            examples.append(example)

    if examples:
        return examples

    example_blocks = re.findall(
        r"(Example \d+:.*?)(?=Example \d+:|Constraints:|Follow.up:|$)",
        content_text,
        re.DOTALL,
    )
    return [block.strip() for block in example_blocks if block.strip()]


def _extract_constraints_from_text(content_text):
    constraints_match = re.search(
        r"Constraints:\s*\n(.*?)(?=Follow.up:|$)",
        content_text,
        re.DOTALL,
    )
    if not constraints_match:
        return []

    raw = constraints_match.group(1).strip()
    return [line.strip() for line in raw.split("\n") if line.strip()]


def _extract_follow_up_from_text(content_text):
    follow_up_match = re.search(r"Follow.up:\s*(.*?)$", content_text, re.DOTALL)
    if follow_up_match:
        return follow_up_match.group(1).strip()
    return None

def _extract_examples(driver):
    """
    Extract examples (Input/Output/Explanation) from the problem description.
    LeetCode formats examples in <pre> tags or under 'Example' headings.
    """
    examples = []
    try:
        # Examples are typically in <pre> elements within the description
        example_elements = driver.find_elements(
            By.CSS_SELECTOR, "[data-track-load='description_content'] pre"
        )
        for el in example_elements:
            example_text = el.text.strip()
            if example_text:
                examples.append(example_text)

        # If no <pre> found, try extracting by "Example" pattern from full text
        if not examples:
            content_el = driver.find_element(
                By.CSS_SELECTOR, "[data-track-load='description_content']"
            )
            full_text = content_el.text
            import re
            example_blocks = re.findall(
                r'(Example \d+:.*?)(?=Example \d+:|Constraints:|Follow.up:|$)',
                full_text, re.DOTALL
            )
            examples = [block.strip() for block in example_blocks if block.strip()]

    except Exception as e:
        logger.warning(f"Could not extract examples: {e}")

    return examples


def _extract_constraints(driver):
    """
    Extract constraints section which typically includes:
    - Input size bounds (e.g., 1 <= n <= 10^5)
    - Value ranges
    - Implied time/space complexity requirements
    """
    constraints = []
    try:
        # Constraints are usually in a <ul> after "Constraints:" text
        content_el = driver.find_element(
            By.CSS_SELECTOR, "[data-track-load='description_content']"
        )
        full_text = content_el.text

        import re
        # Match everything after "Constraints:" until "Follow" or end
        constraints_match = re.search(
            r'Constraints:\s*\n(.*?)(?=Follow.up:|$)',
            full_text, re.DOTALL
        )
        if constraints_match:
            raw = constraints_match.group(1).strip()
            constraints = [line.strip() for line in raw.split("\n") if line.strip()]

    except Exception as e:
        logger.warning(f"Could not extract constraints: {e}")

    return constraints


def _extract_follow_up(driver):
    """
    Extract the Follow-up section which often hints at expected time/space complexity.
    E.g., "Can you solve it in O(n) time and O(1) space?"
    """
    try:
        content_el = driver.find_element(
            By.CSS_SELECTOR, "[data-track-load='description_content']"
        )
        full_text = content_el.text

        import re
        follow_up_match = re.search(
            r'Follow.up:\s*(.*?)$',
            full_text, re.DOTALL
        )
        if follow_up_match:
            return follow_up_match.group(1).strip()

    except Exception as e:
        logger.warning(f"Could not extract follow-up: {e}")

    return None
