"""
Firefox Profile Manager
- Tạo profile riêng cho mỗi Gmail
- Quản lý toàn bộ profiles
- Mỗi Gmail = 1 Firefox profile → tránh xung đột cookie/session
"""

import os
import shutil
from pathlib import Path
from typing import Optional

from config import PROFILES_DIR


class FirefoxProfileManager:
    """Manages Firefox profiles - one per Gmail account.
    """

    def __init__(self, profiles_dir: str = None, source_dir: str = None,
                 log_callback=None):
        self.profiles_dir = Path(profiles_dir) if profiles_dir else PROFILES_DIR
        self.log = log_callback or print
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    # ─── Profile Creation ───

    def create_profile(self, gmail: str) -> Optional[str]:
        """Create a new Chrome profile directory for a Gmail account.

        Returns the profile directory path.
        """
        profile_name = self._sanitize_name(gmail)
        profile_path = self.profiles_dir / profile_name

        if profile_path.exists():
            self.log(f"[INFO] Profile đã tồn tại: {profile_name}")
            return str(profile_path)

        try:
            profile_path.mkdir(parents=True, exist_ok=True)
            self.log(f"[OK] Tạo profile: {profile_name}")
            return str(profile_path)
        except Exception as e:
            self.log(f"[ERROR] Tạo profile thất bại: {e}")
            return None

    # ─── Profile Management ───

    def get_profile_path(self, gmail: str) -> Optional[str]:
        """Get profile directory for a Gmail account."""
        profile_name = self._sanitize_name(gmail)
        profile_path = self.profiles_dir / profile_name
        if profile_path.exists():
            return str(profile_path)
        return None

    def get_or_create_profile(self, gmail: str) -> Optional[str]:
        """Get existing profile or create new one."""
        path = self.get_profile_path(gmail)
        if path:
            return path
        return self.create_profile(gmail)

    def list_profiles(self) -> list:
        """List all profiles with their Gmail names."""
        profiles = []
        if not self.profiles_dir.exists():
            return profiles
        for item in sorted(self.profiles_dir.iterdir()):
            if item.is_dir() and not item.name.startswith('.'):
                profiles.append({
                    "gmail": item.name,
                    "path": str(item),
                    "size_mb": self._folder_size_mb(item),
                })
        return profiles

    def delete_profile(self, gmail: str) -> bool:
        """Delete a profile."""
        profile_name = self._sanitize_name(gmail)
        profile_path = self.profiles_dir / profile_name
        if profile_path.exists():
            try:
                shutil.rmtree(str(profile_path))
                self.log(f"[OK] Đã xóa profile: {profile_name}")
                return True
            except Exception as e:
                self.log(f"[ERROR] Xóa profile thất bại: {e}")
        return False

    def get_firefox_binary(self, profile_path: str) -> Optional[str]:
        """Not needed for Chrome - kept for backward compatibility."""
        return None

    # ─── Utilities ───

    @staticmethod
    def _sanitize_name(gmail: str) -> str:
        """Convert Gmail address to safe folder name."""
        name = gmail.strip().lower()
        name = name.replace("@gmail.com", "").replace("@", "_at_")
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, '_')
        return name

    @staticmethod
    def _folder_size_mb(folder: Path) -> float:
        """Calculate folder size in MB."""
        total = 0
        try:
            for f in folder.rglob('*'):
                if f.is_file():
                    total += f.stat().st_size
        except Exception:
            pass
        return round(total / (1024 * 1024), 1)
