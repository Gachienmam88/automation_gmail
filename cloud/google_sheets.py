"""
Google Sheets Sync Module
- Nhập dữ liệu từ Google Sheet vào Tool (Input)
- Xuất dữ liệu từ Tool lên Google Sheet (Output)
- Đồng bộ 2 chiều
- Lịch xuất định kỳ
"""

import os
import time
import json
import threading
from typing import Optional
from pathlib import Path

from config import (
    GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE,
    GOOGLE_SCOPES, GRID_COLUMN_KEYS, SYNC_INTERVAL_MINUTES,
)


def _get_google_credentials():
    """Get Google API credentials with OAuth2 flow."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None

    if GOOGLE_TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(GOOGLE_TOKEN_FILE), GOOGLE_SCOPES
            )
        except Exception:
            pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            if not GOOGLE_CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Google credentials not found: {GOOGLE_CREDENTIALS_FILE}\n"
                    "Download client_secret.json from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token
        with open(str(GOOGLE_TOKEN_FILE), 'w') as f:
            f.write(creds.to_json())

    return creds


class GoogleSheetsSync:
    """Two-way sync between Google Sheets and the local tool."""

    def __init__(self, sheet_url: str = "", log_callback=None):
        self.sheet_url = sheet_url
        self.sheet_id = self._extract_sheet_id(sheet_url)
        self.log = log_callback or print
        self._service = None
        self._auto_sync_thread = None
        self._auto_sync_stop = threading.Event()

    @staticmethod
    def _extract_sheet_id(url: str) -> str:
        """Extract sheet ID from Google Sheets URL."""
        if not url:
            return ""
        # URL format: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit...
        import re
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
        if match:
            return match.group(1)
        # Maybe it's already just the ID
        if '/' not in url and len(url) > 20:
            return url
        return ""

    def connect(self) -> bool:
        """Establish connection to Google Sheets API."""
        try:
            from googleapiclient.discovery import build
            creds = _get_google_credentials()
            self._service = build('sheets', 'v4', credentials=creds)
            self.log("[OK] Kết nối Google Sheets API thành công")
            return True
        except FileNotFoundError as e:
            self.log(f"[ERROR] {e}")
            return False
        except Exception as e:
            self.log(f"[ERROR] Kết nối Google Sheets thất bại: {e}")
            return False

    def set_sheet_url(self, url: str):
        """Update sheet URL."""
        self.sheet_url = url
        self.sheet_id = self._extract_sheet_id(url)

    # ─── Import (Sheet → Tool) ───

    def import_data(self, sheet_name: str = "Sheet1") -> list[dict]:
        """Import all rows from Google Sheet into list of dicts.

        Returns list of dicts with keys matching GRID_COLUMN_KEYS.
        """
        if not self._service or not self.sheet_id:
            self.log("[ERROR] Chưa kết nối hoặc chưa có Sheet ID")
            return []

        try:
            range_name = f"{sheet_name}!A:O"  # 15 columns (A-O)
            result = self._service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=range_name
            ).execute()

            rows = result.get('values', [])
            if not rows:
                self.log("[WARNING] Sheet trống")
                return []

            # First row is header
            headers = rows[0] if rows else []
            data = []

            for i, row in enumerate(rows[1:], start=1):
                record = {"stt": str(i)}
                for j, key in enumerate(GRID_COLUMN_KEYS[1:], start=0):  # Skip STT
                    if j < len(row):
                        record[key] = row[j]
                    else:
                        record[key] = ""
                data.append(record)

            self.log(f"[OK] Đã import {len(data)} dòng từ Google Sheet")
            return data

        except Exception as e:
            self.log(f"[ERROR] Import thất bại: {e}")
            return []

    # ─── Export (Tool → Sheet) ───

    def export_data(self, data: list[dict], sheet_name: str = "Sheet1") -> bool:
        """Export data from tool to Google Sheet.

        Args:
            data: List of dicts with keys matching GRID_COLUMN_KEYS
            sheet_name: Target sheet name
        """
        if not self._service or not self.sheet_id:
            self.log("[ERROR] Chưa kết nối hoặc chưa có Sheet ID")
            return False

        try:
            # Build rows: header + data
            header = [col for col in GRID_COLUMN_KEYS]
            rows = [header]

            for record in data:
                row = [str(record.get(key, "")) for key in GRID_COLUMN_KEYS]
                rows.append(row)

            range_name = f"{sheet_name}!A1"
            body = {"values": rows}

            # Clear existing data first
            self._service.spreadsheets().values().clear(
                spreadsheetId=self.sheet_id,
                range=f"{sheet_name}!A:O",
                body={}
            ).execute()

            # Write new data
            self._service.spreadsheets().values().update(
                spreadsheetId=self.sheet_id,
                range=range_name,
                valueInputOption="RAW",
                body=body
            ).execute()

            self.log(f"[OK] Đã export {len(data)} dòng lên Google Sheet")
            return True

        except Exception as e:
            self.log(f"[ERROR] Export thất bại: {e}")
            return False

    def update_row_status(self, row_index: int, status: str,
                           result: str = "", sheet_name: str = "Sheet1") -> bool:
        """Update status and result for a specific row (0-based index)."""
        if not self._service or not self.sheet_id:
            return False

        try:
            # Status is column L (12th), Result is column N (14th)
            sheet_row = row_index + 2  # +1 for header, +1 for 0-based
            range_status = f"{sheet_name}!L{sheet_row}"
            range_result = f"{sheet_name}!N{sheet_row}"

            batch_data = [
                {"range": range_status, "values": [[status]]},
                {"range": range_result, "values": [[result]]},
            ]

            self._service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.sheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": batch_data
                }
            ).execute()
            return True

        except Exception as e:
            self.log(f"  [ERROR] Update row status: {e}")
            return False

    # ─── Auto Sync ───

    def start_auto_sync(self, interval_minutes: int = None,
                         get_data_func=None, set_data_func=None):
        """Start automatic periodic sync.

        Args:
            interval_minutes: Sync interval
            get_data_func: Function that returns current tool data
            set_data_func: Function to update tool with new data
        """
        interval = interval_minutes or SYNC_INTERVAL_MINUTES
        self._auto_sync_stop.clear()

        def sync_loop():
            while not self._auto_sync_stop.is_set():
                try:
                    # Export current data
                    if get_data_func:
                        data = get_data_func()
                        if data:
                            self.export_data(data)

                    self.log(f"[INFO] Auto-sync: đợi {interval} phút...")
                except Exception as e:
                    self.log(f"[ERROR] Auto-sync: {e}")

                self._auto_sync_stop.wait(timeout=interval * 60)

        self._auto_sync_thread = threading.Thread(
            target=sync_loop, daemon=True, name="auto-sync"
        )
        self._auto_sync_thread.start()
        self.log(f"[OK] Auto-sync bật (mỗi {interval} phút)")

    def stop_auto_sync(self):
        """Stop automatic sync."""
        self._auto_sync_stop.set()
        if self._auto_sync_thread:
            self._auto_sync_thread.join(timeout=5)
            self._auto_sync_thread = None
        self.log("[INFO] Auto-sync đã tắt")
