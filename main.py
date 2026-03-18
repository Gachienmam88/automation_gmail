"""
Gmail Automation Tool - Main Entry Point
TechLaAI - Desktop app for Gmail account management automation.

Features:
- 15-column Grid UI (like Google Sheet)
- Selenium + GeckoDriver + Firefox Portable
- Multi-thread automation
- Fake IP via DCOM
- 2FA management (TOTP + 2fa.live)
- Google Sheet/Drive cloud sync
- Auto Firefox profile management

Usage:
    python main.py
"""

import sys
import os
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

from config import load_settings, apply_settings


def main():
    """Launch the Gmail Automation application."""
    # Load and apply saved settings
    settings = load_settings()
    apply_settings(settings)

    # Start the GUI application
    from ui.app import GmailAutomationApp
    app = GmailAutomationApp()
    app.run()


if __name__ == "__main__":
    main()
