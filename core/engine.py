"""
Automation Engine
- Firefox Portable + Selenium (geckodriver 0.30)
- Stealth: dom.webdriver.enabled=False to hide navigator.webdriver
- Multi-thread task execution
- Thread pool management with pause/stop
"""

import os
import time
import random
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Optional

from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from config import (
    PAGE_LOAD_TIMEOUT, IMPLICIT_WAIT,
    ACTION_DELAY, MAX_THREADS, THREAD_DELAY_BETWEEN,
    BASE_DIR,
)


# Firefox Portable paths
FIREFOX_BINARY = str(BASE_DIR / "FirefoxPortableNightly" / "App" / "Firefox64" / "firefox.exe")
GECKODRIVER_PATH = str(BASE_DIR / "geckodriver_new.exe")

# Lock for browser start — must start browsers one at a time
_browser_start_lock = threading.Lock()


class BrowserInstance:
    """Manages a single Firefox browser instance."""

    def __init__(self, profile_path: str, headless: bool = False,
                 log_callback=None):
        self.profile_path = profile_path
        self.headless = headless
        self.log = log_callback or print
        self.driver = None

    def start(self) -> bool:
        """Start Firefox browser."""
        try:
            options = FirefoxOptions()
            options.binary_location = FIREFOX_BINARY

            # Profile
            options.add_argument("-profile")
            options.add_argument(self.profile_path)

            # Stealth: hide navigator.webdriver
            options.set_preference("dom.webdriver.enabled", False)
            options.set_preference("useAutomationExtension", False)
            options.set_preference("marionette.log.level", "Fatal")

            # Disable telemetry
            options.set_preference("toolkit.telemetry.reportingpolicy.firstRun", False)
            options.set_preference("datareporting.policy.dataSubmissionEnabled", False)

            # Disable first run
            options.set_preference("browser.shell.checkDefaultBrowser", False)
            options.set_preference("browser.startup.homepage_override.mstone", "ignore")

            # Download settings
            download_dir = os.path.join(os.getcwd(), "downloads")
            os.makedirs(download_dir, exist_ok=True)
            options.set_preference("browser.download.dir", download_dir)
            options.set_preference("browser.download.folderList", 2)
            options.set_preference("browser.download.useDownloadDir", True)

            # Session restore off
            options.set_preference("browser.sessionstore.resume_from_crash", False)

            if self.headless:
                options.add_argument("--headless")

            service = Service(executable_path=GECKODRIVER_PATH)

            with _browser_start_lock:
                self.driver = webdriver.Firefox(service=service, options=options)

            self.driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
            self.driver.implicitly_wait(0)

            self.log("[OK] Firefox da mo")
            return True

        except Exception as e:
            self.log(f"[ERROR] Mo Firefox that bai: {e}")
            return False

    def is_alive(self) -> bool:
        """Check if browser is still open."""
        if not self.driver:
            return False
        try:
            _ = self.driver.window_handles
            return True
        except Exception:
            return False

    def close(self):
        """Close browser."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def navigate(self, url: str, wait: float = 1.5):
        """Navigate to URL with wait."""
        self.driver.get(url)
        time.sleep(wait)

    def random_delay(self, min_s: float = None, max_s: float = None):
        """Random human-like delay."""
        mn = min_s or ACTION_DELAY[0]
        mx = max_s or ACTION_DELAY[1]
        time.sleep(random.uniform(mn, mx))

    def find_element_safe(self, by, value, timeout=10):
        """Find element with explicit wait, return None if not found."""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
        except TimeoutException:
            return None

    def find_clickable(self, by, value, timeout=10):
        """Find clickable element with explicit wait."""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
        except TimeoutException:
            return None

    def type_human(self, element, text: str, delay_range=(0.02, 0.06)):
        """Type text with human-like delays."""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(*delay_range))

    def wait_for_url_change(self, current_url: str, timeout: int = 15) -> bool:
        """Wait until URL changes from current."""
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.current_url != current_url
            )
            return True
        except TimeoutException:
            return False

    def screenshot(self, path: str):
        """Take screenshot for debugging."""
        try:
            self.driver.save_screenshot(path)
        except Exception:
            pass


class TaskResult:
    """Result of an automation task."""

    def __init__(self, gmail: str, action: str):
        self.gmail = gmail
        self.action = action
        self.success = False
        self.message = ""
        self.new_password = ""
        self.twofa_secret = ""
        self.error = ""
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "gmail": self.gmail,
            "action": self.action,
            "success": self.success,
            "message": self.message,
            "new_password": self.new_password,
            "twofa_secret": self.twofa_secret,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class AutomationEngine:
    """Multi-threaded automation engine for Gmail tasks."""

    def __init__(self, max_threads: int = None, log_callback=None,
                 progress_callback=None):
        self.max_threads = max_threads or MAX_THREADS
        self.log = log_callback or print
        self.progress_callback = progress_callback
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: list[Future] = []
        self._paused = threading.Event()
        self._paused.set()
        self._stopped = False
        self._lock = threading.Lock()
        self._active_browsers: list[BrowserInstance] = []

    def start_batch(self, tasks: list[dict], action_func: Callable):
        """Execute a batch of tasks with thread pool."""
        self._stopped = False
        self._paused.set()
        self._futures = []

        self._executor = ThreadPoolExecutor(
            max_workers=self.max_threads,
            thread_name_prefix="gmail-worker"
        )

        for i, task in enumerate(tasks):
            if self._stopped:
                break
            future = self._executor.submit(
                self._run_single_task, task, action_func, i
            )
            self._futures.append(future)
            time.sleep(THREAD_DELAY_BETWEEN)

    def _run_single_task(self, task: dict, action_func: Callable,
                         index: int) -> TaskResult:
        """Run a single task in its own thread with its own browser."""
        gmail = task.get("gmail", "unknown")
        action = task.get("action", "unknown")
        result = TaskResult(gmail, action)

        # Check pause/stop
        self._paused.wait()
        if self._stopped:
            result.error = "Stopped"
            return result

        # Update progress
        if self.progress_callback:
            self.progress_callback(gmail, "running", None)

        browser = None
        try:
            browser = BrowserInstance(
                profile_path=task.get("profile_path", ""),
                headless=task.get("headless", False),
                log_callback=lambda msg: self.log(f"[{gmail}] {msg}"),
            )

            if not browser.start():
                result.error = "Browser start failed"
                if self.progress_callback:
                    self.progress_callback(gmail, "error", result)
                return result

            with self._lock:
                self._active_browsers.append(browser)

            action_func(browser, task, self.log, result)

        except Exception as e:
            result.error = str(e)
            self.log(f"[{gmail}] [ERROR] {e}")

        finally:
            # Giữ trình duyệt mở - không tự đóng
            if browser:
                self.log(f"[{gmail}] [INFO] Task hoàn thành - giữ trình duyệt mở")

        # Update progress
        status = "done" if result.success else "error"
        if self.progress_callback:
            self.progress_callback(gmail, status, result)

        return result

    def pause(self):
        """Pause all tasks."""
        self._paused.clear()
        self.log("[INFO] Đã tạm dừng tất cả tasks")

    def resume(self):
        """Resume all tasks."""
        self._paused.set()
        self.log("[INFO] Đã tiếp tục tasks")

    def stop(self):
        """Stop all tasks and close browsers."""
        self._stopped = True
        self._paused.set()

        # Close all active browsers
        with self._lock:
            for browser in self._active_browsers[:]:
                browser.close()
            self._active_browsers.clear()

        # Shutdown executor
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

        self.log("[INFO] Đã dừng tất cả tasks")

    def is_running(self) -> bool:
        """Check if any tasks are still running."""
        return any(not f.done() for f in self._futures)

    def get_results(self) -> list[TaskResult]:
        """Get results from completed tasks."""
        results = []
        for f in self._futures:
            if f.done():
                try:
                    results.append(f.result())
                except Exception:
                    pass
        return results
