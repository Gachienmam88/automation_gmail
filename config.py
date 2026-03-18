"""
Gmail Automation Tool - Configuration
Central configuration for all modules.
"""

import os
import json
from pathlib import Path

# ─── Paths ───
BASE_DIR = Path(__file__).parent.resolve()
PROFILES_DIR = BASE_DIR / "firefox_profiles"
DOWNLOADS_DIR = BASE_DIR / "downloads"
EXPORTS_DIR = BASE_DIR / "exports"
CREDENTIALS_DIR = BASE_DIR / "credentials"
LOGS_DIR = BASE_DIR / "logs"

# Ensure dirs exist
for d in [PROFILES_DIR, DOWNLOADS_DIR, EXPORTS_DIR, CREDENTIALS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── Google API ───
GOOGLE_CREDENTIALS_FILE = CREDENTIALS_DIR / "client_secret.json"
GOOGLE_TOKEN_FILE = CREDENTIALS_DIR / "token.json"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# ─── Grid Columns (15 cột) ───
GRID_COLUMNS = [
    {"key": "stt", "label": "STT", "width": 40},
    {"key": "gmail", "label": "Gmail", "width": 200},
    {"key": "password", "label": "Password", "width": 120},
    {"key": "new_password", "label": "New Password", "width": 120},
    {"key": "recovery_email", "label": "Recovery Email", "width": 160},
    {"key": "recovery_phone", "label": "Recovery Phone", "width": 120},
    {"key": "twofa_secret", "label": "2FA Secret", "width": 120},
    {"key": "proxy", "label": "Proxy/IP", "width": 120},
    {"key": "profile_path", "label": "Profile Path", "width": 150},
    {"key": "action", "label": "Action", "width": 100},
    {"key": "display_mode", "label": "Display", "width": 70},
    {"key": "status", "label": "Status", "width": 80},
    {"key": "last_login", "label": "Last Login", "width": 120},
    {"key": "result", "label": "Result", "width": 150},
    {"key": "notes", "label": "Notes", "width": 150},
]

GRID_COLUMN_KEYS = [c["key"] for c in GRID_COLUMNS]

# ─── Actions ───
ACTIONS = [
    "Login",
    "Change Password",
    "Add/Change Recovery Email",
    "Add/Change Recovery Phone",
    "Add/Change 2FA",
    "Full Setup",  # Login + đổi pass + 2FA + recovery
]

DISPLAY_MODES = ["Visible", "Headless"]

# ─── Selenium / Firefox (GeckoDriver) ───
PAGE_LOAD_TIMEOUT = 60
IMPLICIT_WAIT = 10
ACTION_DELAY = (0.3, 0.8)  # Random delay range between actions (seconds)

# ─── 2FA ───
TWO_FA_LIVE_URL = "https://2fa.live/"
TOTP_DIGITS = 6
TOTP_INTERVAL = 30

# ─── Cloud Sync ───
SYNC_INTERVAL_MINUTES = 30  # Default auto-sync interval
AUTO_EXPORT_ENABLED = False

# ─── Captcha ───
CAPTCHA_SERVICE = "manual"  # "manual", "2captcha", "anticaptcha"
CAPTCHA_API_KEY = ""

# ─── Threading ───
MAX_THREADS = 3
THREAD_DELAY_BETWEEN = 2  # Seconds between starting threads


# ─── Settings persistence ───
SETTINGS_FILE = BASE_DIR / "settings.json"


def load_settings() -> dict:
    """Load saved settings from file."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_settings(settings: dict):
    """Save settings to file."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Save settings failed: {e}")


def apply_settings(settings: dict):
    """Apply loaded settings to global config."""
    global PROXY_ENABLED, PROXY_LIST, PROXY_ROTATE_EVERY_N
    global MAX_THREADS, CAPTCHA_SERVICE, CAPTCHA_API_KEY
    global SYNC_INTERVAL_MINUTES, AUTO_EXPORT_ENABLED

    PROXY_ENABLED = settings.get("proxy_enabled", PROXY_ENABLED)
    PROXY_LIST = settings.get("proxy_list", PROXY_LIST)
    PROXY_ROTATE_EVERY_N = settings.get("proxy_rotate_every_n", PROXY_ROTATE_EVERY_N)
    MAX_THREADS = settings.get("max_threads", MAX_THREADS)
    CAPTCHA_SERVICE = settings.get("captcha_service", CAPTCHA_SERVICE)
    CAPTCHA_API_KEY = settings.get("captcha_api_key", CAPTCHA_API_KEY)
    SYNC_INTERVAL_MINUTES = settings.get("sync_interval", SYNC_INTERVAL_MINUTES)
    AUTO_EXPORT_ENABLED = settings.get("auto_export", AUTO_EXPORT_ENABLED)
