"""
Gmail Actions Module
All Gmail-specific automation actions:
- Login
- Change Password
- Add/Change Recovery Email
- Add/Change Recovery Phone
- Handle Captcha
- Auto re-login
"""

import time
import random
import re
from typing import Optional
from urllib.parse import urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from core.engine import BrowserInstance, TaskResult
from security.two_factor import TwoFactorManager

# ─── URLs ───
GMAIL_LOGIN_URL = "https://accounts.google.com/signin"
GMAIL_MYACCOUNT_URL = "https://myaccount.google.com"
GMAIL_SECURITY_URL = "https://myaccount.google.com/security"
GMAIL_PASSWORD_URL = "https://myaccount.google.com/signinoptions/password"
GMAIL_RECOVERY_EMAIL_URL = "https://myaccount.google.com/recovery/email"
GMAIL_RECOVERY_PHONE_URL = "https://myaccount.google.com/signinoptions/rescuephone"
GMAIL_2FA_URL = "https://myaccount.google.com/signinoptions/two-step-verification"

twofa_manager = TwoFactorManager()


# ─── Helper Functions ───

# URL patterns that indicate successful login
_LOGGED_IN_URLS = [
    "myaccount.google.com",
    "mail.google.com",
    "drive.google.com",
    "accounts.google.com/SignOutOptions",
    "accounts.google.com/b/",
    "google.com/webhp",
]


def _url_host_path(url: str) -> str:
    """Return only host + path of URL (ignore query params)."""
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}"


def _is_logged_in(browser: BrowserInstance) -> bool:
    """Check if currently logged into Google account by URL."""
    try:
        if not browser.driver:
            return False
        current_url = browser.driver.current_url
        # Blank or empty page = not logged in
        if not current_url or current_url in ("about:blank", "data:,", "chrome://newtab/"):
            return False
        # Only check host+path, not query params (query may contain redirect URLs)
        host_path = _url_host_path(current_url)
        if any(p in host_path for p in _LOGGED_IN_URLS):
            return True
        # Not on accounts.google.com at all = logged in
        if "accounts.google.com" not in host_path:
            return True
        return False
    except Exception:
        return False


def _handle_captcha(browser: BrowserInstance, log) -> bool:
    """Handle CAPTCHA if present. Returns True if resolved (or no captcha)."""
    try:
        if not browser.driver:
            return True

        # Only detect CAPTCHA by visible elements, NOT by page source keywords
        # (Google pages always contain "captcha" in their JS/HTML)

        # Check for reCAPTCHA iframe
        iframes = browser.driver.find_elements(
            By.CSS_SELECTOR, 'iframe[src*="recaptcha"], iframe[src*="captcha"]'
        )
        visible_iframes = [f for f in iframes if f.is_displayed()]

        # Check for visible captcha challenge text
        visible_captcha = False
        try:
            challenge_els = browser.driver.find_elements(
                By.XPATH,
                '//*[contains(text(),"Verify you\'re not a robot") or '
                'contains(text(),"verify you\'re not a robot") or '
                'contains(text(),"Xác minh bạn không phải robot")]'
            )
            visible_captcha = any(el.is_displayed() for el in challenge_els)
        except Exception:
            pass

        if not visible_iframes and not visible_captcha:
            return True  # No captcha

        log("  [WARNING] CAPTCHA detected!")

        if visible_iframes:
            log("  [INFO] reCAPTCHA found. Đợi người dùng giải...")
            for _ in range(120):
                time.sleep(1)
                # Check if captcha iframe disappeared (page moved on)
                try:
                    remaining = browser.driver.find_elements(
                        By.CSS_SELECTOR,
                        'iframe[src*="recaptcha"], iframe[src*="captcha"]'
                    )
                    if not any(f.is_displayed() for f in remaining):
                        log("  [OK] CAPTCHA đã được giải!")
                        return True
                except Exception:
                    return True  # Page navigated away

                # Check for recaptcha response
                try:
                    response = browser.driver.execute_script(
                        'return document.getElementById("g-recaptcha-response")?.value'
                    )
                    if response:
                        log("  [OK] CAPTCHA đã được giải!")
                        return True
                except Exception:
                    pass

            log("  [ERROR] CAPTCHA timeout (120s)")
            return False

        # Visible text captcha challenge
        log("  [INFO] Captcha challenge. Đợi người dùng giải (60s)...")
        time.sleep(60)
        return True

    except Exception as e:
        log(f"  [ERROR] Handle captcha: {e}")
        return True  # Continue anyway


def _click_next_button(browser: BrowserInstance, log) -> bool:
    """Click the Next/Continue button on Google forms."""
    # Priority 1: Google's known button IDs (fastest, most reliable)
    for css_id in ['#identifierNext', '#passwordNext', '#signinconsolecontinue']:
        try:
            els = browser.driver.find_elements(By.CSS_SELECTOR, css_id)
            for el in els:
                if el.is_displayed():
                    el.click()
                    time.sleep(0.3)
                    return True
        except Exception:
            continue

    # Priority 2: submit button
    try:
        btns = browser.driver.find_elements(By.CSS_SELECTOR, 'button[type="submit"]')
        for btn in btns:
            if btn.is_displayed():
                btn.click()
                time.sleep(0.3)
                return True
    except Exception:
        pass

    # Priority 3: buttons with Next/Tiếp theo text
    try:
        all_buttons = browser.driver.find_elements(By.CSS_SELECTOR, 'button, div[role="button"]')
        for btn in all_buttons:
            if btn.is_displayed():
                txt = btn.text.strip().lower()
                if txt in ('next', 'tiếp theo', 'continue', 'tiếp tục', 'done', 'xong'):
                    btn.click()
                    time.sleep(0.3)
                    return True
    except Exception:
        pass

    # Fallback: Enter key
    try:
        active = browser.driver.switch_to.active_element
        active.send_keys(Keys.ENTER)
        time.sleep(0.3)
        return True
    except Exception:
        pass

    log("  [WARNING] Không tìm thấy nút Next")
    return False


def _wait_page_transition(browser: BrowserInstance, timeout: int = 10):
    """Wait for page to transition (loading indicator disappears)."""
    try:
        WebDriverWait(browser.driver, timeout, poll_frequency=0.3).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except (TimeoutException, Exception):
        pass


def _find_visible_password_input(browser: BrowserInstance, timeout: int = 15):
    """Find a VISIBLE password input by polling. Returns element or None.

    Google's login page may have multiple password inputs in the DOM
    (hidden ones from previous steps). element_to_be_clickable only checks
    the FIRST match, so we manually find all and pick the visible one.
    """
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            inputs = browser.driver.find_elements(
                By.CSS_SELECTOR, 'input[type="password"]'
            )
            for inp in inputs:
                try:
                    if inp.is_displayed() and inp.is_enabled():
                        return inp
                except Exception:
                    continue
        except Exception:
            pass
        time.sleep(0.5)
    return None


def _check_google_error(browser: BrowserInstance) -> str:
    """Check for visible Google error message on current page. Returns error text or ''."""
    # Google wraps inline errors in these specific classes
    # Login page: .o6cuMc, .dEOOab, .EjBTad, [jsname="B34EJ"]
    # MyAccount/password change: div with error/warning styles
    _ERROR_SELECTORS = (
        '.o6cuMc, .dEOOab, .EjBTad, [jsname="B34EJ"], '
        '.OyEIQ, .GQ8Pzc, .XkGNMe, '
        '[aria-live="polite"], [aria-live="assertive"], '
        '[role="alert"], '
        '.k3kKZc, .dMNVAe, .Ekjuhf, .LXRPh'
    )
    # Keywords that confirm the text is actually an error (EN + VI)
    _ERROR_KEYWORDS = [
        "couldn't find", "could not find", "không tìm thấy",
        "wrong password", "sai mật khẩu",
        "try again", "thử lại",
        "enter a valid", "nhập một",
        "too many", "quá nhiều",
        "this account", "tài khoản này",
        "was deleted", "đã bị xóa",
        "unable to sign", "không thể đăng nhập",
        "check your", "kiểm tra",
        "verify", "xác minh",
        "error", "lỗi",
        # Password change errors
        "đã sử dụng", "recently used", "used this password",
        "vui lòng chọn", "please choose", "choose a different",
        "too short", "quá ngắn", "too weak", "quá yếu",
        "at least", "ít nhất",
        "doesn't match", "không khớp", "không trùng",
        "mật khẩu khác", "different password",
    ]
    try:
        error_els = browser.driver.find_elements(By.CSS_SELECTOR, _ERROR_SELECTORS)
        for el in error_els:
            try:
                if el.is_displayed() and el.text.strip():
                    txt = el.text.strip()
                    txt_lower = txt.lower()
                    if any(kw in txt_lower for kw in _ERROR_KEYWORDS):
                        return txt
            except Exception:
                continue
    except Exception:
        pass

    # Fallback: tìm tất cả element có text khớp keyword lỗi (bất kể class)
    try:
        all_els = browser.driver.find_elements(By.CSS_SELECTOR, 'div, span, p')
        for el in all_els:
            try:
                if not el.is_displayed():
                    continue
                txt = el.text.strip()
                if not txt or len(txt) > 200:
                    continue
                txt_lower = txt.lower()
                if any(kw in txt_lower for kw in _ERROR_KEYWORDS):
                    # Kiểm tra màu đỏ (Google dùng màu đỏ cho lỗi)
                    color = el.value_of_css_property('color')
                    if color and ('198, 40' in color or '217, 48' in color
                                  or '211, 47' in color or 'd93025' in color
                                  or '(234,' in color or '(213,' in color
                                  or '(198,' in color):
                        return txt
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _enter_password_if_asked(browser: BrowserInstance, password: str,
                              log) -> bool:
    """If Google asks to re-enter password, handle it."""
    try:
        pw_input = browser.find_element_safe(
            By.CSS_SELECTOR,
            'input[type="password"][name="Passwd"], input[type="password"][name="password"]',
            timeout=5
        )
        if pw_input:
            log("  [INFO] Google yêu cầu nhập lại mật khẩu...")
            pw_input.clear()
            browser.type_human(pw_input, password)
            _click_next_button(browser, log)
            _wait_page_transition(browser)
            return True
    except Exception:
        pass
    return False


# ─── Main Actions ───

def action_login(browser: BrowserInstance, task: dict, log, result: TaskResult):
    """Login to Gmail account."""
    gmail = task["gmail"]
    password = task["password"]
    twofa_secret = task.get("twofa_secret", "")

    log(f"[INFO] Đăng nhập: {gmail}")

    # ── Step 0: Clear old Google cookies to force fresh login ──
    try:
        browser.driver.get("https://accounts.google.com")
        time.sleep(1)
        browser.driver.delete_all_cookies()
        log("  [INFO] Đã xoá cookie Google cũ, buộc login mới")
    except Exception:
        pass

    # Not logged in → go to login page
    browser.navigate(GMAIL_LOGIN_URL)

    # Fix: Google may redirect to accountchooser (no email input)
    try:
        current_url = browser.driver.current_url
        if "accountchooser" in current_url or "AccountChooser" in current_url:
            log("  [INFO] Phát hiện AccountChooser, chuyển sang trang nhập email...")
            new_url = current_url.replace("/accountchooser", "/identifier").replace("/AccountChooser", "/identifier")
            browser.navigate(new_url)
            _wait_page_transition(browser, timeout=10)
    except Exception:
        pass

    # Fix: Google may show confirmidentifier page (email already known from profile)
    try:
        current_url = browser.driver.current_url
        if "confirmidentifier" in current_url:
            log("  [INFO] Phát hiện confirmidentifier, click Next để sang trang password...")
            _click_next_button(browser, log)
            _wait_page_transition(browser, timeout=10)
            skip_email_step = True
        else:
            skip_email_step = False
    except Exception:
        skip_email_step = False

    # ── Step 1: Enter email (skip if confirmidentifier already handled) ──
    if not skip_email_step:
        email_input = browser.find_clickable(
            By.CSS_SELECTOR, 'input[type="email"]', timeout=15
        )
        if not email_input:
            log("  [INFO] Không tìm thấy ô email, thử URL trực tiếp...")
            browser.navigate(
                "https://accounts.google.com/v3/signin/identifier?flowName=GlifWebSignIn&flowEntry=ServiceLogin"
            )
            _wait_page_transition(browser, timeout=10)
            email_input = browser.find_clickable(
                By.CSS_SELECTOR, 'input[type="email"]', timeout=10
            )
        if not email_input:
            result.error = "Không tìm thấy ô nhập email"
            return

        email_input.click()
        email_input.clear()
        email_input.send_keys(gmail)
        email_input.send_keys(Keys.ENTER)
        log(f"  [INFO] Đã nhập email + Enter")
        _wait_page_transition(browser, timeout=10)

    # Handle CAPTCHA (only real visible captcha, not false positives)
    if not _handle_captcha(browser, log):
        result.error = "CAPTCHA failed"
        return

    # Check for email error (wrong email, not found, etc.)
    time.sleep(0.5)
    email_error = _check_google_error(browser)
    if email_error:
        result.error = f"Email error: {email_error}"
        log(f"[ERROR] Lỗi email: {email_error}")
        return

    # Check: Google rejected/redirected back to identifier page
    try:
        post_email_url = browser.driver.current_url
        if "/identifier" in post_email_url and "signin" in post_email_url:
            if "/rejected" in post_email_url:
                result.error = "Google rejected login (quá nhiều request cùng IP)"
                log(f"[ERROR] {result.error}")
                return
            # Google redirect lại → retry tối đa 2 lần, mỗi lần đợi lâu hơn
            for retry in range(2):
                wait_secs = 5 * (retry + 1)
                log(f"  [WARNING] Google redirect lại trang email, đợi {wait_secs}s rồi thử lại (lần {retry+1})...")
                time.sleep(wait_secs)
                email_input2 = browser.find_clickable(
                    By.CSS_SELECTOR, 'input[type="email"]', timeout=10
                )
                if email_input2:
                    email_input2.click()
                    email_input2.clear()
                    email_input2.send_keys(gmail)
                    email_input2.send_keys(Keys.ENTER)
                    log(f"  [INFO] Đã nhập lại email + Enter")
                    _wait_page_transition(browser, timeout=10)
                    # Check if we got past identifier page
                    try:
                        new_url = browser.driver.current_url
                        if "/identifier" not in new_url:
                            break  # OK, moved to password page
                    except Exception:
                        break
    except Exception:
        pass

    # ── Step 2: Enter password ──
    log("  [INFO] Đang chờ ô nhập password...")
    pw_input = _find_visible_password_input(browser, timeout=20)

    if not pw_input:
        email_error = _check_google_error(browser)
        if email_error:
            result.error = f"Email error: {email_error}"
            log(f"[ERROR] Lỗi email: {email_error}")
        else:
            try:
                cur = browser.driver.current_url
                if "/rejected" in cur:
                    result.error = "Google rejected login (bot detection hoặc quá nhiều request)"
                elif "/identifier" in cur:
                    result.error = "Google không chấp nhận email, redirect lại trang identifier"
                else:
                    result.error = "Không tìm thấy ô nhập password"
            except Exception:
                result.error = "Không tìm thấy ô nhập password"
            log(f"[ERROR] {result.error}")
        return

    log("  [INFO] Tìm thấy ô password, đang nhập...")
    pw_input.click()
    pw_input.clear()
    pw_input.send_keys(password)
    url_before_pw = browser.driver.current_url
    pw_input.send_keys(Keys.ENTER)
    log(f"  [INFO] Đã nhập password + Enter")

    # Wait for URL to change OR error to appear after password submit
    log("  [INFO] Đang chờ xác thực password...")
    login_success = False
    login_error = ""

    for i in range(30):  # 30 x 0.5s = ~15s max
        time.sleep(0.5)
        try:
            current_url = browser.driver.current_url
        except Exception:
            break

        # URL changed from password page
        if current_url != url_before_pw:
            break

        # URL hasn't changed - check for error (wrong password)
        if i >= 4:
            pw_error = _check_google_error(browser)
            if pw_error:
                login_error = pw_error
                break

    _wait_page_transition(browser, timeout=10)

    # ── Verify result by URL ──
    if login_error:
        pass
    else:
        # Poll URL for up to 15s to detect final state
        for _ in range(30):  # 30 x 0.5s = ~15s max
            try:
                current_url = browser.driver.current_url
            except Exception:
                break

            # SUCCESS patterns (check host+path only, ignore query params)
            cur_host_path = _url_host_path(current_url)
            if any(p in cur_host_path for p in [
                "myaccount.google.com",
                "mail.google.com",
                "accounts.google.com/SignOutOptions",
                "accounts.google.com/b/",
                "drive.google.com",
                "google.com/webhp",
                "gds.google.com",
            ]):
                login_success = True
                break

            # STILL ON LOGIN: check for error message
            if "accounts.google.com" in current_url and "challenge" not in current_url:
                pw_error = _check_google_error(browser)
                if pw_error:
                    login_error = pw_error
                    break

            # 2FA CHALLENGE
            if "challenge" in current_url:
                log("  [INFO] Google yêu cầu xác thực 2FA...")

                try:
                    if not browser.is_alive():
                        login_error = "Browser đã đóng"
                        break

                    if "challenge/totp" not in current_url and twofa_secret:
                        log("  [INFO] Không phải trang TOTP, đổi URL sang authenticator...")
                        before, _, after = current_url.partition('/challenge/')
                        if after:
                            challenge_type, sep, params = after.partition('?')
                            totp_url = before + '/challenge/totp' + sep + params
                        else:
                            totp_url = current_url
                        browser.navigate(totp_url)
                        _wait_page_transition(browser, timeout=5)

                    twofa_input = None
                    for sel in [
                        'input[id="totpPin"]', 'input[name="totpPin"]',
                        'input[type="tel"]', 'input[id="idvPin"]',
                        'input[name="idvPin"]', 'input[autocomplete="one-time-code"]',
                    ]:
                        try:
                            els = browser.driver.find_elements(By.CSS_SELECTOR, sel)
                            for el in els:
                                if el.is_displayed() and el.is_enabled():
                                    twofa_input = el
                                    break
                            if twofa_input:
                                break
                        except Exception:
                            continue

                    if twofa_input and twofa_secret:
                        code = twofa_manager.get_2fa_code(twofa_secret)
                        if code:
                            log(f"  [INFO] Nhập mã 2FA: {code}")
                            twofa_input.clear()
                            twofa_input.send_keys(code + Keys.ENTER)
                            for _ in range(10):  # 5s max
                                time.sleep(0.5)
                                try:
                                    if "challenge" not in browser.driver.current_url:
                                        break
                                except Exception:
                                    break
                            continue
                        else:
                            login_error = "Không lấy được mã 2FA"
                            break
                    elif not twofa_secret:
                        log("  [WARNING] Cần 2FA nhưng không có secret! Đợi thủ công (60s)...")
                        time.sleep(60)
                        continue
                    else:
                        log("  [WARNING] Không tìm thấy ô nhập 2FA, đợi 10s...")
                        time.sleep(10)
                        continue

                except Exception as e:
                    login_error = f"Lỗi xử lý 2FA: {e}"
                    log(f"[ERROR] {login_error}")
                    break

            time.sleep(0.3)

    # ── Final result ──
    if login_success:
        result.success = True
        result.message = "Login OK"
        result.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log(f"[OK] Đăng nhập thành công: {gmail}")
    elif login_error:
        result.error = f"Login failed: {login_error}"
        log(f"[ERROR] {result.error}")
    else:
        try:
            final_url = browser.driver.current_url
            if "accounts.google.com" not in final_url:
                result.success = True
                result.message = "Login OK"
                result.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                log(f"[OK] Đăng nhập thành công: {gmail}")
            else:
                result.error = f"Login unclear - URL: {final_url}"
                log(f"[WARNING] {result.error}")
        except Exception:
            result.error = "Login verification failed"
            log(f"[ERROR] {result.error}")


def _skip_recovery_prompts(browser: BrowserInstance, log):
    """Skip Google's recovery/security prompts after login."""
    skip_texts = ['not now', 'skip', 'bỏ qua', 'để sau',
                  'remind me later', 'nhắc tôi sau', 'done', 'confirm']
    for _ in range(3):
        for text in skip_texts:
            try:
                elements = browser.driver.find_elements(By.XPATH,
                    f'//*[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
                    f'"abcdefghijklmnopqrstuvwxyz"),"{text}")]'
                )
                for el in elements:
                    if el.is_displayed() and el.tag_name in ('button', 'span', 'a', 'div'):
                        el.click()
                        time.sleep(0.5)
                        break
            except Exception:
                continue
        time.sleep(0.3)


def action_change_password(browser: BrowserInstance, task: dict,
                            log, result: TaskResult):
    """Change Gmail password."""
    gmail = task["gmail"]
    current_password = task["password"]
    new_password = task.get("new_password", "")
    twofa_secret = task.get("twofa_secret", "")

    if not new_password:
        result.error = "Chưa có mật khẩu mới (New Password trống)"
        log(f"[ERROR] {result.error}")
        return

    log(f"[INFO] Đổi mật khẩu: {gmail}")

    # ── Step 1: Navigate to password change page ──
    # Navigate directly — Google will redirect to login if not authenticated
    log("  [INFO] Truy cập trang đổi mật khẩu...")
    browser.navigate(GMAIL_PASSWORD_URL)
    _wait_page_transition(browser, timeout=10)

    # ── Step 2: Handle Google auth redirects (same as login flow) ──
    # Google may redirect to signin/confirmidentifier/accountchooser
    # Loop to handle chained redirects (e.g. confirmidentifier → password → password change)
    for _auth_attempt in range(5):
        try:
            current_url = browser.driver.current_url
            current_host_path = _url_host_path(current_url)
        except Exception:
            current_url = ""
            current_host_path = ""

        log(f"  [DEBUG] URL hiện tại: {current_url}")

        # Already on password change page → done with auth
        if "signinoptions/password" in current_host_path:
            log("  [INFO] Đã vào trang đổi mật khẩu")
            break

        # Handle /intro/ or myaccount pages (not password page)
        # → Google chưa xác thực đủ, chạy lại flow đăng nhập đầy đủ
        if "myaccount.google.com" in current_host_path and "signinoptions/password" not in current_host_path:
            log("  [INFO] Bị đá sang myaccount/intro, chạy flow đăng nhập...")
            # Navigate to login page (Google will remember continue URL)
            browser.navigate(GMAIL_LOGIN_URL)
            _wait_page_transition(browser, timeout=10)

            try:
                current_url = browser.driver.current_url
            except Exception:
                current_url = ""

            # Handle accountchooser
            if "accountchooser" in current_url.lower():
                new_url = current_url.replace("/accountchooser", "/identifier").replace("/AccountChooser", "/identifier")
                browser.navigate(new_url)
                _wait_page_transition(browser, timeout=10)
                try:
                    current_url = browser.driver.current_url
                except Exception:
                    current_url = ""

            # Handle confirmidentifier
            if "confirmidentifier" in current_url:
                log("  [INFO] Phát hiện confirmidentifier, click Next...")
                _click_next_button(browser, log)
                _wait_page_transition(browser, timeout=10)
                try:
                    current_url = browser.driver.current_url
                except Exception:
                    current_url = ""

            # Handle email input
            if "identifier" in current_url and "confirmidentifier" not in current_url:
                email_input = browser.find_element_safe(
                    By.CSS_SELECTOR, 'input[type="email"]', timeout=5
                )
                if email_input:
                    log("  [INFO] Nhập email...")
                    email_input.click()
                    time.sleep(0.2)
                    email_input.clear()
                    browser.type_human(email_input, gmail)
                    _click_next_button(browser, log)
                    _wait_page_transition(browser, timeout=10)
                    _handle_captcha(browser, log)
                    time.sleep(1)
                    email_error = _check_google_error(browser)
                    if email_error:
                        result.error = f"Email error: {email_error}"
                        log(f"[ERROR] {result.error}")
                        return
                    try:
                        current_url = browser.driver.current_url
                    except Exception:
                        current_url = ""

            # Handle password
            if any(p in current_url for p in ["challenge", "signin"]):
                pw_input = _find_visible_password_input(browser, timeout=10)
                if pw_input:
                    log("  [INFO] Nhập mật khẩu...")
                    pw_input.click()
                    time.sleep(0.2)
                    pw_input.clear()
                    browser.type_human(pw_input, current_password)
                    url_before = browser.driver.current_url
                    pw_input.send_keys(Keys.ENTER)
                    time.sleep(0.5)
                    for i in range(16):
                        time.sleep(0.5)
                        try:
                            if browser.driver.current_url != url_before:
                                break
                        except Exception:
                            break
                        if i >= 3:
                            err = _check_google_error(browser)
                            if err:
                                result.error = f"Mật khẩu sai: {err}"
                                log(f"[ERROR] {result.error}")
                                return
                    _wait_page_transition(browser, timeout=5)

                    # Handle 2FA challenge (giống hệt login flow)
                    try:
                        current_url = browser.driver.current_url
                    except Exception:
                        current_url = ""
                    if "challenge" in current_url:
                        log("  [INFO] Google yêu cầu xác thực 2FA...")
                        # Ưu tiên TOTP: đổi URL sang totp nếu đang ở challenge khác
                        if "challenge/totp" not in current_url and twofa_secret:
                            log("  [INFO] Đổi URL sang authenticator...")
                            before, _, after = current_url.partition('/challenge/')
                            if after:
                                challenge_type, sep, params = after.partition('?')
                                totp_url = before + '/challenge/totp' + sep + params
                            else:
                                totp_url = current_url
                            browser.navigate(totp_url)
                            _wait_page_transition(browser, timeout=5)

                        # Tìm ô nhập TOTP
                        twofa_input = None
                        for sel in [
                            'input[id="totpPin"]', 'input[name="totpPin"]',
                            'input[type="tel"]', 'input[id="idvPin"]',
                            'input[name="idvPin"]', 'input[autocomplete="one-time-code"]',
                        ]:
                            try:
                                els = browser.driver.find_elements(By.CSS_SELECTOR, sel)
                                for el in els:
                                    if el.is_displayed() and el.is_enabled():
                                        twofa_input = el
                                        break
                                if twofa_input:
                                    break
                            except Exception:
                                continue

                        if twofa_input and twofa_secret:
                            code = twofa_manager.get_2fa_code(twofa_secret)
                            if code:
                                log(f"  [INFO] Nhập mã 2FA: {code}")
                                twofa_input.clear()
                                twofa_input.send_keys(code)
                                twofa_input.send_keys(Keys.ENTER)
                                for _ in range(16):
                                    time.sleep(0.5)
                                    try:
                                        if "challenge" not in browser.driver.current_url:
                                            break
                                    except Exception:
                                        break
                                _wait_page_transition(browser, timeout=5)
                            else:
                                result.error = "Không lấy được mã 2FA"
                                log(f"[ERROR] {result.error}")
                                return
                        elif not twofa_secret:
                            log("  [WARNING] Cần 2FA nhưng không có secret!")
                            result.error = "Cần 2FA nhưng không có secret"
                            return

            # After login, navigate to password change page
            log("  [INFO] Đăng nhập xong, truy cập trang đổi mật khẩu...")
            browser.navigate(GMAIL_PASSWORD_URL)
            _wait_page_transition(browser, timeout=10)
            continue

        log("  [INFO] Google yêu cầu xác thực trước khi đổi mật khẩu...")

        # Handle AccountChooser redirect
        if "accountchooser" in current_url.lower():
            log("  [INFO] Phát hiện AccountChooser, chuyển sang trang nhập email...")
            new_url = current_url.replace("/accountchooser", "/identifier").replace("/AccountChooser", "/identifier")
            browser.navigate(new_url)
            _wait_page_transition(browser, timeout=10)
            try:
                current_url = browser.driver.current_url
            except Exception:
                current_url = ""

        # Handle confirmidentifier (Google already knows the account)
        if "confirmidentifier" in current_url:
            log("  [INFO] Phát hiện confirmidentifier, click Next...")
            _click_next_button(browser, log)
            _wait_page_transition(browser, timeout=10)
            try:
                current_url = browser.driver.current_url
            except Exception:
                current_url = ""

        # Handle email input page (need to enter email first)
        if "identifier" in current_url and "confirmidentifier" not in current_url:
            email_input = browser.find_element_safe(
                By.CSS_SELECTOR, 'input[type="email"]', timeout=5
            )
            if email_input:
                log("  [INFO] Nhập email để xác thực...")
                email_input.click()
                time.sleep(0.2)
                email_input.clear()
                browser.type_human(email_input, gmail)
                _click_next_button(browser, log)
                _wait_page_transition(browser, timeout=10)

                # Handle CAPTCHA after email
                _handle_captcha(browser, log)
                time.sleep(1)

                # Check email error
                email_error = _check_google_error(browser)
                if email_error:
                    result.error = f"Email error: {email_error}"
                    log(f"[ERROR] {result.error}")
                    return

                try:
                    current_url = browser.driver.current_url
                except Exception:
                    current_url = ""

        # Handle password re-auth page (challenge/pwd or signin with password)
        if any(p in current_url for p in ["challenge", "signin"]):
            log("  [INFO] Đang chờ ô nhập mật khẩu xác thực...")
            reauth_pw = _find_visible_password_input(browser, timeout=10)

            if reauth_pw:
                log("  [INFO] Nhập mật khẩu hiện tại để xác minh...")
                reauth_pw.click()
                time.sleep(0.2)
                reauth_pw.clear()
                browser.type_human(reauth_pw, current_password)
                url_before = browser.driver.current_url

                reauth_pw.send_keys(Keys.ENTER)
                time.sleep(0.5)

                # Wait for page to move past re-auth
                for i in range(16):  # 8s max
                    time.sleep(0.5)
                    try:
                        if browser.driver.current_url != url_before:
                            break
                    except Exception:
                        break
                    if i >= 3:
                        err = _check_google_error(browser)
                        if err:
                            result.error = f"Xác minh mật khẩu thất bại: {err}"
                            log(f"[ERROR] {result.error}")
                            return
                _wait_page_transition(browser, timeout=5)
            else:
                log("  [WARNING] Không tìm thấy ô nhập mật khẩu re-auth")
                result.error = "Không thể xác thực để vào trang đổi mật khẩu"
                return
    else:
        # Exhausted auth attempts
        try:
            final_auth_url = browser.driver.current_url
        except Exception:
            final_auth_url = "unknown"
        result.error = f"Không thể vào trang đổi mật khẩu sau nhiều lần thử. URL: {final_auth_url}"
        log(f"[ERROR] {result.error}")
        return

    # ── Step 4: Tìm ô nhập mật khẩu mới ──
    log("  [INFO] Đang tìm ô nhập mật khẩu mới...")
    time.sleep(1)

    # Poll for new password inputs (Google may take time to render)
    visible_inputs = []
    for _ in range(10):  # 5s max
        try:
            pw_inputs = browser.driver.find_elements(
                By.CSS_SELECTOR, 'input[type="password"]'
            )
            visible_inputs = [inp for inp in pw_inputs
                              if inp.is_displayed() and inp.is_enabled()]
            if visible_inputs:
                break
        except Exception:
            pass
        time.sleep(0.5)

    if not visible_inputs:
        # Maybe page didn't load or redirected elsewhere
        try:
            log(f"  [DEBUG] URL: {browser.driver.current_url}")
        except Exception:
            pass
        result.error = "Không tìm thấy ô nhập mật khẩu mới"
        return

    # ── Step 5: Nhập mật khẩu mới + xác nhận + Enter ──
    if len(visible_inputs) >= 2:
        log("  [INFO] Nhập mật khẩu mới + xác nhận...")
        visible_inputs[0].click()
        visible_inputs[0].clear()
        browser.type_human(visible_inputs[0], new_password)
        time.sleep(0.3)
        visible_inputs[1].click()
        visible_inputs[1].clear()
        browser.type_human(visible_inputs[1], new_password)
        visible_inputs[1].send_keys(Keys.ENTER)
        time.sleep(0.5)
    else:
        log("  [INFO] Nhập mật khẩu mới...")
        visible_inputs[0].click()
        visible_inputs[0].clear()
        browser.type_human(visible_inputs[0], new_password)
        visible_inputs[0].send_keys(Keys.ENTER)
        time.sleep(0.5)

    # ── Step 6: Check kết quả bằng URL hoặc lỗi ──
    _SUCCESS_PATTERNS = [
        "myaccount.google.com/security-checkup-welcome",
    ]
    for i in range(20):  # 10s max
        time.sleep(0.5)
        try:
            cur = browser.driver.current_url
            cur_hp = _url_host_path(cur)
        except Exception:
            break

        # Đổi mật khẩu thành công — Google redirect sang myaccount/security
        if any(p in cur_hp for p in _SUCCESS_PATTERNS):
            result.success = True
            result.message = "Password changed"
            result.new_password = new_password
            result.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            log(f"[OK] Đổi mật khẩu thành công: {gmail}")
            return

        # URL chưa đổi → check error sau 1.5s
        if i >= 3:
            err = _check_google_error(browser)
            if err:
                result.error = f"Đổi mật khẩu thất bại: {err}"
                log(f"[ERROR] {result.error}")
                return

    # Hết thời gian chờ — check lần cuối
    try:
        final_url = browser.driver.current_url
        final_hp = _url_host_path(final_url)
        if any(p in final_hp for p in _SUCCESS_PATTERNS):
            result.success = True
            result.message = "Password changed"
            result.new_password = new_password
            result.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            log(f"[OK] Đổi mật khẩu thành công: {gmail}")
        else:
            err = _check_google_error(browser)
            if err:
                result.error = f"Đổi mật khẩu thất bại: {err}"
            else:
                result.error = f"Đổi mật khẩu không rõ kết quả - URL: {final_url}"
            log(f"[ERROR] {result.error}")
    except Exception as e:
        result.error = f"Verify failed: {e}"
        log(f"[ERROR] {result.error}")


def action_change_recovery_email(browser: BrowserInstance, task: dict,
                                   log, result: TaskResult):
    """Add or change recovery email."""
    gmail = task["gmail"]
    recovery_email = task.get("recovery_email", "")
    password = task["password"]

    if not recovery_email:
        result.error = "Chưa có recovery email"
        return

    log(f"[INFO] Đổi recovery email: {gmail} → {recovery_email}")

    # Login if needed
    if not _is_logged_in(browser):
        action_login(browser, task, log, result)
        if not result.success:
            return
        result.success = False

    browser.navigate(GMAIL_RECOVERY_EMAIL_URL, wait=2)
    _enter_password_if_asked(browser, password, log)
    time.sleep(1)

    # Find email input
    email_inputs = browser.driver.find_elements(
        By.CSS_SELECTOR, 'input[type="email"], input[type="text"]'
    )
    target_input = None
    for inp in email_inputs:
        if inp.is_displayed():
            target_input = inp
            break

    if not target_input:
        # Try clicking "Add recovery email" link first
        try:
            add_links = browser.driver.find_elements(By.XPATH,
                '//*[contains(text(),"Add") or contains(text(),"Thêm")]'
            )
            for link in add_links:
                if link.is_displayed():
                    link.click()
                    time.sleep(1)
                    break
        except Exception:
            pass

        email_inputs = browser.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="email"], input[type="text"]'
        )
        for inp in email_inputs:
            if inp.is_displayed():
                target_input = inp
                break

    if not target_input:
        result.error = "Không tìm thấy ô nhập recovery email"
        return

    target_input.clear()
    browser.type_human(target_input, recovery_email)
    _click_next_button(browser, log)
    _wait_page_transition(browser)

    result.success = True
    result.message = f"Recovery email: {recovery_email}"
    log(f"[OK] Đã cập nhật recovery email: {gmail}")


def action_change_recovery_phone(browser: BrowserInstance, task: dict,
                                   log, result: TaskResult):
    """Add or change recovery phone number."""
    gmail = task["gmail"]
    phone = task.get("recovery_phone", "")
    current_password = task["password"]
    twofa_secret = task.get("twofa_secret", "")

    if not phone:
        result.error = "Chưa có recovery phone"
        log(f"[ERROR] {result.error}")
        return

    log(f"[INFO] Đổi recovery phone: {gmail} → {phone}")

    # ── Step 1: Navigate to recovery phone page ──
    log("  [INFO] Truy cập trang đổi số điện thoại khôi phục...")
    browser.navigate(GMAIL_RECOVERY_PHONE_URL)
    _wait_page_transition(browser, timeout=10)

    # ── Step 2: Handle Google auth redirects (giống hệt flow đổi mật khẩu) ──
    _SUCCESS_PATTERNS_PHONE = [
        "signinoptions/rescuephone",
        "recovery/phone",
    ]
    for _auth_attempt in range(5):
        try:
            current_url = browser.driver.current_url
            current_host_path = _url_host_path(current_url)
        except Exception:
            current_url = ""
            current_host_path = ""

        log(f"  [DEBUG] URL hiện tại: {current_url}")

        # Already on recovery phone page → done with auth
        if any(p in current_host_path for p in _SUCCESS_PATTERNS_PHONE):
            log("  [INFO] Đã vào trang đổi số điện thoại khôi phục")
            break

        # Handle myaccount/intro pages → chạy flow đăng nhập
        if "myaccount.google.com" in current_host_path and not any(p in current_host_path for p in _SUCCESS_PATTERNS_PHONE):
            log("  [INFO] Bị đá sang myaccount/intro, chạy flow đăng nhập...")
            browser.navigate(GMAIL_LOGIN_URL)
            _wait_page_transition(browser, timeout=10)

            try:
                current_url = browser.driver.current_url
            except Exception:
                current_url = ""

            # Handle accountchooser
            if "accountchooser" in current_url.lower():
                new_url = current_url.replace("/accountchooser", "/identifier").replace("/AccountChooser", "/identifier")
                browser.navigate(new_url)
                _wait_page_transition(browser, timeout=10)
                try:
                    current_url = browser.driver.current_url
                except Exception:
                    current_url = ""

            # Handle confirmidentifier
            if "confirmidentifier" in current_url:
                log("  [INFO] Phát hiện confirmidentifier, click Next...")
                _click_next_button(browser, log)
                _wait_page_transition(browser, timeout=10)
                try:
                    current_url = browser.driver.current_url
                except Exception:
                    current_url = ""

            # Handle email input
            if "identifier" in current_url and "confirmidentifier" not in current_url:
                email_input = browser.find_clickable(
                    By.CSS_SELECTOR, 'input[type="email"]', timeout=5
                )
                if email_input:
                    log("  [INFO] Nhập email...")
                    email_input.click()
                    time.sleep(0.2)
                    email_input.clear()
                    browser.type_human(email_input, gmail)
                    _click_next_button(browser, log)
                    _wait_page_transition(browser, timeout=10)
                    _handle_captcha(browser, log)
                    time.sleep(1)
                    email_error = _check_google_error(browser)
                    if email_error:
                        result.error = f"Email error: {email_error}"
                        log(f"[ERROR] {result.error}")
                        return
                    try:
                        current_url = browser.driver.current_url
                    except Exception:
                        current_url = ""

            # Handle password
            if any(p in current_url for p in ["challenge", "signin"]):
                pw_input = _find_visible_password_input(browser, timeout=10)
                if pw_input:
                    log("  [INFO] Nhập mật khẩu...")
                    pw_input.click()
                    time.sleep(0.2)
                    pw_input.clear()
                    browser.type_human(pw_input, current_password)
                    url_before = browser.driver.current_url
                    pw_input.send_keys(Keys.ENTER)
                    time.sleep(0.5)
                    for i in range(16):
                        time.sleep(0.5)
                        try:
                            if browser.driver.current_url != url_before:
                                break
                        except Exception:
                            break
                        if i >= 3:
                            err = _check_google_error(browser)
                            if err:
                                result.error = f"Mật khẩu sai: {err}"
                                log(f"[ERROR] {result.error}")
                                return
                    _wait_page_transition(browser, timeout=5)

                    # Handle 2FA
                    try:
                        current_url = browser.driver.current_url
                    except Exception:
                        current_url = ""
                    if "challenge" in current_url:
                        log("  [INFO] Google yêu cầu xác thực 2FA...")
                        if "challenge/totp" not in current_url and twofa_secret:
                            log("  [INFO] Đổi URL sang authenticator...")
                            before, _, after = current_url.partition('/challenge/')
                            if after:
                                challenge_type, sep, params = after.partition('?')
                                totp_url = before + '/challenge/totp' + sep + params
                            else:
                                totp_url = current_url
                            browser.navigate(totp_url)
                            _wait_page_transition(browser, timeout=5)

                        twofa_input = None
                        for sel in [
                            'input[id="totpPin"]', 'input[name="totpPin"]',
                            'input[type="tel"]', 'input[id="idvPin"]',
                            'input[name="idvPin"]', 'input[autocomplete="one-time-code"]',
                        ]:
                            try:
                                els = browser.driver.find_elements(By.CSS_SELECTOR, sel)
                                for el in els:
                                    if el.is_displayed() and el.is_enabled():
                                        twofa_input = el
                                        break
                                if twofa_input:
                                    break
                            except Exception:
                                continue

                        if twofa_input and twofa_secret:
                            code = twofa_manager.get_2fa_code(twofa_secret)
                            if code:
                                log(f"  [INFO] Nhập mã 2FA: {code}")
                                twofa_input.clear()
                                twofa_input.send_keys(code)
                                twofa_input.send_keys(Keys.ENTER)
                                for _ in range(16):
                                    time.sleep(0.5)
                                    try:
                                        if "challenge" not in browser.driver.current_url:
                                            break
                                    except Exception:
                                        break
                                _wait_page_transition(browser, timeout=5)
                            else:
                                result.error = "Không lấy được mã 2FA"
                                log(f"[ERROR] {result.error}")
                                return
                        elif not twofa_secret:
                            result.error = "Cần 2FA nhưng không có secret"
                            log(f"[ERROR] {result.error}")
                            return

            # After login, navigate to recovery phone page
            log("  [INFO] Đăng nhập xong, truy cập trang đổi số điện thoại...")
            browser.navigate(GMAIL_RECOVERY_PHONE_URL)
            _wait_page_transition(browser, timeout=10)
            continue

        log("  [INFO] Google yêu cầu xác thực...")

        # Handle AccountChooser
        if "accountchooser" in current_url.lower():
            new_url = current_url.replace("/accountchooser", "/identifier").replace("/AccountChooser", "/identifier")
            browser.navigate(new_url)
            _wait_page_transition(browser, timeout=10)
            try:
                current_url = browser.driver.current_url
            except Exception:
                current_url = ""

        # Handle confirmidentifier
        if "confirmidentifier" in current_url:
            log("  [INFO] Phát hiện confirmidentifier, click Next...")
            _click_next_button(browser, log)
            _wait_page_transition(browser, timeout=10)
            try:
                current_url = browser.driver.current_url
            except Exception:
                current_url = ""

        # Handle email input
        if "identifier" in current_url and "confirmidentifier" not in current_url:
            email_input = browser.find_clickable(
                By.CSS_SELECTOR, 'input[type="email"]', timeout=5
            )
            if email_input:
                log("  [INFO] Nhập email để xác thực...")
                email_input.click()
                time.sleep(0.2)
                email_input.clear()
                browser.type_human(email_input, gmail)
                _click_next_button(browser, log)
                _wait_page_transition(browser, timeout=10)
                _handle_captcha(browser, log)
                time.sleep(1)
                email_error = _check_google_error(browser)
                if email_error:
                    result.error = f"Email error: {email_error}"
                    log(f"[ERROR] {result.error}")
                    return
                try:
                    current_url = browser.driver.current_url
                except Exception:
                    current_url = ""

        # Handle password re-auth
        if any(p in current_url for p in ["challenge", "signin"]):
            reauth_pw = _find_visible_password_input(browser, timeout=10)
            if reauth_pw:
                log("  [INFO] Nhập mật khẩu xác thực...")
                reauth_pw.click()
                time.sleep(0.2)
                reauth_pw.clear()
                browser.type_human(reauth_pw, current_password)
                url_before = browser.driver.current_url
                reauth_pw.send_keys(Keys.ENTER)
                time.sleep(0.5)
                for i in range(16):
                    time.sleep(0.5)
                    try:
                        if browser.driver.current_url != url_before:
                            break
                    except Exception:
                        break
                    if i >= 3:
                        err = _check_google_error(browser)
                        if err:
                            result.error = f"Xác minh mật khẩu thất bại: {err}"
                            log(f"[ERROR] {result.error}")
                            return
                _wait_page_transition(browser, timeout=5)
            else:
                result.error = "Không tìm thấy ô nhập mật khẩu re-auth"
                log(f"[ERROR] {result.error}")
                return
    else:
        try:
            final_auth_url = browser.driver.current_url
        except Exception:
            final_auth_url = "unknown"
        result.error = f"Không thể vào trang đổi phone. URL: {final_auth_url}"
        log(f"[ERROR] {result.error}")
        return

    # ── Step 3: Click icon bút chì (edit) hoặc nút "Thêm" ──
    time.sleep(1)
    clicked_edit = False

    # Cách 1: Tìm button edit bằng aria-label
    try:
        edit_btns = browser.driver.find_elements(
            By.CSS_SELECTOR,
            'button[aria-label*="Chỉnh sửa"], button[aria-label*="Edit"], '
            'button[aria-label*="chỉnh sửa"], button[aria-label*="edit"]'
        )
        for btn in edit_btns:
            if btn.is_displayed():
                browser.driver.execute_script("arguments[0].click();", btn)
                clicked_edit = True
                log(f"  [INFO] Đã click nút edit: {btn.get_attribute('aria-label')}")
                time.sleep(1)
                break
    except Exception:
        pass

    # Cách 2: Fallback — tìm nút text "Thêm" / "Add"
    if not clicked_edit:
        try:
            btns = browser.driver.find_elements(
                By.CSS_SELECTOR, 'button, a[role="button"], div[role="button"]'
            )
            for btn in btns:
                if btn.is_displayed():
                    txt = btn.text.strip().lower()
                    if any(k in txt for k in [
                        'thêm số điện thoại', 'add recovery phone',
                        'cập nhật', 'update', 'đổi số', 'change phone',
                        'thêm', 'add',
                    ]):
                        btn.click()
                        clicked_edit = True
                        log(f"  [INFO] Đã click: {btn.text.strip()}")
                        time.sleep(1)
                        break
        except Exception:
            pass

    if not clicked_edit:
        log("  [WARNING] Không tìm thấy nút edit/thêm, thử tìm ô input trực tiếp...")

    # ── Step 4: Tìm ô nhập số điện thoại ──
    log("  [INFO] Đang tìm ô nhập số điện thoại...")
    target_input = None
    for _ in range(10):  # 5s polling
        try:
            phone_inputs = browser.driver.find_elements(
                By.CSS_SELECTOR, 'input[type="tel"], input[id="phoneNumberId"]'
            )
            for inp in phone_inputs:
                if inp.is_displayed() and inp.is_enabled():
                    target_input = inp
                    break
            if target_input:
                break
        except Exception:
            pass
        time.sleep(0.5)

    if not target_input:
        try:
            log(f"  [DEBUG] URL: {browser.driver.current_url}")
        except Exception:
            pass
        result.error = "Không tìm thấy ô nhập số điện thoại"
        log(f"[ERROR] {result.error}")
        return

    # ── Step 5: Nhập số điện thoại + click "Tiếp theo" ──
    log(f"  [INFO] Nhập số điện thoại: {phone}")
    target_input.click()
    time.sleep(0.2)
    target_input.clear()
    browser.type_human(target_input, phone)
    time.sleep(0.5)

    # Click nút "Tiếp theo" / "Next" trong modal
    next_btn_ref = None
    try:
        next_btns = browser.driver.find_elements(
            By.CSS_SELECTOR,
            'button[aria-label*="Tiếp theo"], button[aria-label*="tiếp theo"], '
            'button[aria-label*="Next"], button[aria-label*="next"]'
        )
        for btn in next_btns:
            if btn.is_displayed():
                next_btn_ref = btn
                browser.driver.execute_script("arguments[0].click();", btn)
                log("  [INFO] Đã click nút Tiếp theo")
                break
    except Exception:
        pass

    # Fallback: tìm button có text "Tiếp theo" / "Next"
    if not next_btn_ref:
        try:
            all_btns = browser.driver.find_elements(By.CSS_SELECTOR, 'button')
            for btn in all_btns:
                if btn.is_displayed():
                    txt = btn.text.strip()
                    if txt in ('Tiếp theo', 'Next', 'Tiếp tục', 'Continue'):
                        next_btn_ref = btn
                        browser.driver.execute_script("arguments[0].click();", btn)
                        log(f"  [INFO] Đã click nút: {txt}")
                        break
        except Exception:
            pass

    time.sleep(0.5)

    # Check: nút "Tiếp theo" vẫn visible + disabled → số điện thoại không hợp lệ
    if next_btn_ref:
        try:
            if next_btn_ref.is_displayed():
                is_disabled = (
                    next_btn_ref.get_attribute('disabled') is not None
                    or 'disabled' in (next_btn_ref.get_attribute('class') or '')
                    or next_btn_ref.get_attribute('aria-disabled') == 'true'
                )
                if is_disabled:
                    err = _check_google_error(browser)
                    if err:
                        result.error = f"Lỗi số điện thoại: {err}"
                    else:
                        result.error = "Số điện thoại không hợp lệ"
                    log(f"[ERROR] {result.error}")
                    return
        except Exception:
            pass  # Button biến mất → OK, đã chuyển sang bước tiếp

    # ── Step 5b: Tìm nút "Lưu" / "Save", click rồi check disabled ──
    save_btn_found = None
    try:
        save_btns = browser.driver.find_elements(
            By.CSS_SELECTOR,
            'button[aria-label*="Lưu"], button[aria-label*="Save"], '
            'button[aria-label*="lưu"], button[aria-label*="save"]'
        )
        for btn in save_btns:
            if btn.is_displayed():
                save_btn_found = btn
                break
    except Exception:
        pass

    if save_btn_found:
        # Click nút Lưu trước
        browser.driver.execute_script("arguments[0].click();", save_btn_found)
        log("  [INFO] Đã click nút Lưu, đang chờ kết quả...")
        time.sleep(3)

        # Check lại: nút Lưu vẫn còn visible + disabled → lỗi
        try:
            is_disabled = (
                save_btn_found.is_displayed()
                and (
                    save_btn_found.get_attribute('disabled') is not None
                    or 'disabled' in (save_btn_found.get_attribute('class') or '')
                    or save_btn_found.get_attribute('aria-disabled') == 'true'
                )
            )
            if is_disabled:
                log("  [WARNING] Nút Lưu bị disabled sau khi click")
                err = _check_google_error(browser)
                if err:
                    result.error = f"Lỗi số điện thoại: {err}"
                else:
                    result.error = "Số điện thoại không hợp lệ (nút Lưu bị disabled)"
                log(f"[ERROR] {result.error}")
                return
        except Exception:
            pass  # Button đã biến mất → modal đã đóng → OK

    # ── Step 6: Check kết quả ──
    # Check lỗi trước
    err = _check_google_error(browser)
    if err:
        result.error = f"Lỗi thêm số điện thoại: {err}"
        log(f"[ERROR] {result.error}")
        return

    # Check URL thành công
    _SUCCESS_URL_PHONE = [
        "myaccount.google.com/security",
        "myaccount.google.com/signinoptions",
        "myaccount.google.com/security-checkup",
        "myaccount.google.com",
    ]
    for i in range(20):  # 10s max
        time.sleep(0.5)
        try:
            cur = browser.driver.current_url
            cur_hp = _url_host_path(cur)
        except Exception:
            break

        if any(p in cur_hp for p in _SUCCESS_URL_PHONE):
            result.success = True
            result.message = f"Recovery phone: {phone}"
            result.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            log(f"[OK] Đã cập nhật recovery phone: {gmail} → {phone}")
            return

        if i >= 3:
            err = _check_google_error(browser)
            if err:
                result.error = f"Lỗi thêm số điện thoại: {err}"
                log(f"[ERROR] {result.error}")
                return

    # Final check
    try:
        final_url = browser.driver.current_url
        final_hp = _url_host_path(final_url)
        if any(p in final_hp for p in _SUCCESS_URL_PHONE):
            result.success = True
            result.message = f"Recovery phone: {phone}"
            result.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            log(f"[OK] Đã cập nhật recovery phone: {gmail} → {phone}")
        else:
            result.error = f"Không rõ kết quả - URL: {final_url}"
            log(f"[ERROR] {result.error}")
    except Exception as e:
        result.error = f"Verify failed: {e}"
        log(f"[ERROR] {result.error}")


def action_setup_2fa(browser: BrowserInstance, task: dict,
                      log, result: TaskResult):
    """Add or change 2FA on Gmail account."""
    gmail = task["gmail"]
    password = task["password"]
    twofa_secret = task.get("twofa_secret", "")

    log(f"[INFO] Thiết lập 2FA: {gmail}")

    if not _is_logged_in(browser):
        action_login(browser, task, log, result)
        if not result.success:
            return
        result.success = False

    # Navigate to 2FA setup
    browser.navigate(GMAIL_2FA_URL, wait=2)
    _enter_password_if_asked(browser, password, log)
    time.sleep(1)

    # Check if 2FA is already enabled
    page_text = browser.driver.find_element(By.TAG_NAME, 'body').text.lower()

    if 'turn off' in page_text or 'tắt' in page_text:
        log("  [INFO] 2FA đã được bật. Thử thêm/đổi authenticator...")
        # Navigate to authenticator setup
        try:
            auth_links = browser.driver.find_elements(By.XPATH,
                '//*[contains(text(),"Authenticator") or contains(text(),"Trình xác thực")]'
            )
            for link in auth_links:
                if link.is_displayed():
                    link.click()
                    time.sleep(1)
                    break
        except Exception:
            pass

    # Look for "Set up" or "Get started" button
    setup_buttons = browser.driver.find_elements(By.XPATH,
        '//*[contains(text(),"Get started") or contains(text(),"Set up") '
        'or contains(text(),"Bắt đầu") or contains(text(),"Thiết lập")]'
    )
    for btn in setup_buttons:
        if btn.is_displayed():
            btn.click()
            time.sleep(1)
            break

    # Use 2FA manager to complete setup
    new_secret = twofa_manager.setup_2fa_on_gmail(browser.driver, twofa_secret)

    if new_secret:
        result.success = True
        result.twofa_secret = new_secret
        result.message = "2FA configured"
        log(f"[OK] 2FA đã thiết lập: {gmail}")
    else:
        result.error = "2FA setup incomplete"
        log(f"[WARNING] 2FA setup chưa hoàn thành: {gmail}")


def action_full_setup(browser: BrowserInstance, task: dict,
                       log, result: TaskResult):
    """Full setup: Login + Change Pass + Recovery + 2FA."""
    gmail = task["gmail"]
    log(f"[INFO] Full setup: {gmail}")

    # Step 1: Login
    action_login(browser, task, log, result)
    if not result.success:
        return

    # Step 2: Change password if provided
    if task.get("new_password"):
        result.success = False
        action_change_password(browser, task, log, result)

    # Step 3: Recovery email if provided
    if task.get("recovery_email"):
        action_change_recovery_email(browser, task, log, result)

    # Step 4: Recovery phone if provided
    if task.get("recovery_phone"):
        action_change_recovery_phone(browser, task, log, result)

    # Step 5: 2FA if secret provided
    if task.get("twofa_secret"):
        action_setup_2fa(browser, task, log, result)

    result.success = True
    result.message = "Full setup completed"
    log(f"[OK] Full setup xong: {gmail}")


# ─── Action Router ───

ACTION_MAP = {
    "Login": action_login,
    "Change Password": action_change_password,
    "Add/Change Recovery Email": action_change_recovery_email,
    "Add/Change Recovery Phone": action_change_recovery_phone,
    "Add/Change 2FA": action_setup_2fa,
    "Full Setup": action_full_setup,
}


def execute_action(browser: BrowserInstance, task: dict, log, result: TaskResult):
    """Route to the correct action based on task config."""
    action_name = task.get("action", "Login")
    action_func = ACTION_MAP.get(action_name)

    if not action_func:
        result.error = f"Unknown action: {action_name}"
        return

    try:
        action_func(browser, task, log, result)
    except Exception as e:
        result.error = str(e)
        log(f"[ERROR] {action_name} failed: {e}")

    # Auto re-login on session expiry (only if browser still alive)
    if result.error and "session" in result.error.lower():
        if browser.is_alive():
            log("[INFO] Thử đăng nhập lại...")
            result.error = ""
            action_login(browser, task, log, result)
        else:
            log("[ERROR] Browser đã đóng, không thể retry")
