"""
2FA Management Module
- TOTP tích hợp sẵn (tự tính theo RFC 6238)
- Fallback: gọi API 2fa.live để lấy mã
- Thêm/đổi 2FA trên Gmail
"""

import time
import hmac
import hashlib
import struct
import base64
import urllib.request
import json as _json
from typing import Optional

from config import TWO_FA_LIVE_URL, TOTP_DIGITS, TOTP_INTERVAL


class TOTPGenerator:
    """Generate TOTP codes without external dependencies (RFC 6238)."""

    def __init__(self, secret: str, digits: int = TOTP_DIGITS,
                 interval: int = TOTP_INTERVAL):
        self.secret = self._normalize_secret(secret)
        self.digits = digits
        self.interval = interval

    @staticmethod
    def _normalize_secret(secret: str) -> str:
        """Clean and normalize base32 secret."""
        secret = secret.strip().upper().replace(' ', '').replace('-', '')
        # Remove non-base32 chars
        valid = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=')
        secret = ''.join(c for c in secret if c in valid)
        # Add padding if needed
        padding = 8 - (len(secret) % 8)
        if padding != 8:
            secret += '=' * padding
        return secret

    def generate(self, timestamp: float = None) -> str:
        """Generate current TOTP code."""
        if timestamp is None:
            timestamp = time.time()

        # Time step
        time_step = int(timestamp) // self.interval

        # HMAC-SHA1
        key = base64.b32decode(self.secret)
        msg = struct.pack('>Q', time_step)
        hmac_hash = hmac.new(key, msg, hashlib.sha1).digest()

        # Dynamic truncation
        offset = hmac_hash[-1] & 0x0F
        code_int = struct.unpack('>I', hmac_hash[offset:offset + 4])[0]
        code_int &= 0x7FFFFFFF
        code_int %= 10 ** self.digits

        return str(code_int).zfill(self.digits)

    def time_remaining(self) -> int:
        """Seconds remaining before code expires."""
        return self.interval - (int(time.time()) % self.interval)

    def generate_fresh(self, min_remaining: int = 5) -> str:
        """Generate code with at least min_remaining seconds of validity."""
        remaining = self.time_remaining()
        if remaining < min_remaining:
            # Wait for next code
            time.sleep(remaining + 1)
        return self.generate()


class TwoFactorManager:
    """Manages 2FA operations including TOTP and 2fa.live fallback."""

    def __init__(self, log_callback=None):
        self.log = log_callback or print

    def get_totp_code(self, secret: str) -> Optional[str]:
        """Get TOTP code from secret key."""
        if not secret:
            return None
        try:
            totp = TOTPGenerator(secret)
            code = totp.generate_fresh(min_remaining=5)
            remaining = totp.time_remaining()
            self.log(f"  [OK] TOTP: {code} (còn {remaining}s)")
            return code
        except Exception as e:
            self.log(f"  [ERROR] TOTP generate failed: {e}")
            return None

    def get_code_from_2fa_live(self, secret: str) -> Optional[str]:
        """Get 2FA code via 2fa.live API (HTTP request, no Selenium needed).

        API: GET https://2fa.live/tok/{secret}
        Response: {"token": "123456"}
        """
        if not secret:
            return None

        clean_secret = secret.strip().replace(' ', '').replace('-', '')
        api_url = f"https://2fa.live/tok/{clean_secret}"
        self.log(f"  [INFO] Lấy mã 2FA từ 2fa.live API...")

        try:
            req = urllib.request.Request(api_url, headers={
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json',
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode('utf-8'))

            token = data.get("token", "")
            # Token may contain extra info, extract 6-digit code
            code = token.strip()
            if code and code.isdigit() and len(code) == 6:
                self.log(f"  [OK] 2FA code từ 2fa.live: {code}")
                return code

            # Try to find 6-digit number in response
            import re
            match = re.search(r'\d{6}', str(data))
            if match:
                code = match.group()
                self.log(f"  [OK] 2FA code từ 2fa.live: {code}")
                return code

            self.log(f"  [WARNING] 2fa.live trả về không hợp lệ: {data}")
            return None

        except Exception as e:
            self.log(f"  [ERROR] 2fa.live API failed: {e}")
            return None

    def get_2fa_code(self, secret: str, driver=None) -> Optional[str]:
        """Get 2FA code: try local TOTP first (instant), fallback to 2fa.live API."""
        # Try local TOTP first — instant, no network delay
        if secret:
            try:
                totp = TOTPGenerator(secret.strip().replace(' ', '').replace('-', ''))
                code = totp.generate()  # No waiting, generate immediately
                self.log(f"  [OK] TOTP: {code}")
                return code
            except Exception:
                pass

        # Fallback to 2fa.live API
        code = self.get_code_from_2fa_live(secret)
        if code:
            return code

        self.log("  [ERROR] Không thể lấy mã 2FA")
        return None

    def setup_2fa_on_gmail(self, driver, secret: str = None) -> Optional[str]:
        """Navigate Gmail 2FA setup and configure it.

        If secret is provided, uses it. Otherwise, extracts the new secret
        from Gmail's 2FA setup page.

        Returns the 2FA secret key.
        """
        from selenium.webdriver.common.by import By
        import re

        self.log("  [INFO] Thiết lập 2FA trên Gmail...")

        try:
            # Navigate to 2FA settings
            driver.get("https://myaccount.google.com/signinoptions/two-step-verification")
            time.sleep(3)

            # If secret not provided, we need to extract it from the QR setup page
            if not secret:
                # Look for "Can't scan it?" or "Enter manually" link
                page_text = driver.page_source
                # Try to find the secret key shown on the page
                secret_match = re.search(
                    r'[A-Z2-7]{16,32}',
                    driver.find_element(By.TAG_NAME, 'body').text
                )
                if secret_match:
                    secret = secret_match.group()
                    self.log(f"  [INFO] Found 2FA secret: {secret[:8]}...")

            if secret:
                # Generate verification code
                code = self.get_totp_code(secret)
                if code:
                    # Find code input and enter it
                    inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input[type="tel"]')
                    for inp in inputs:
                        if inp.is_displayed():
                            inp.clear()
                            inp.send_keys(code)
                            break
                    time.sleep(1)

                    # Click verify/confirm button
                    buttons = driver.find_elements(By.TAG_NAME, 'button')
                    for btn in buttons:
                        text = btn.text.lower()
                        if any(w in text for w in ['verify', 'confirm', 'next', 'xác minh']):
                            btn.click()
                            break
                    time.sleep(3)

                    self.log(f"  [OK] Đã thiết lập 2FA")
                    return secret

        except Exception as e:
            self.log(f"  [ERROR] Setup 2FA failed: {e}")

        return secret
