"""
Dialog Windows
- Settings Dialog
- Google Sheet Sync Dialog
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading

from config import (
    MAX_THREADS, CAPTCHA_SERVICE, CAPTCHA_API_KEY,
    SYNC_INTERVAL_MINUTES, AUTO_EXPORT_ENABLED,
    load_settings,
)


class SettingsDialog(tk.Toplevel):
    """Application settings dialog."""

    def __init__(self, parent, on_save=None):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("520x720")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.on_save = on_save
        self._settings = load_settings()

        self._build_ui()
        self._load_current()

    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ── General Tab ──
        general = ttk.Frame(notebook, padding=10)
        notebook.add(general, text="General")

        ttk.Label(general, text="Max Threads:").grid(
            row=0, column=0, sticky=tk.W, pady=5)
        self.threads_spin = ttk.Spinbox(general, from_=1, to=10, width=10)
        self.threads_spin.grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(general, text="Captcha Service:").grid(
            row=1, column=0, sticky=tk.W, pady=5)
        self.captcha_combo = ttk.Combobox(
            general,
            values=["manual", "2captcha", "anticaptcha"],
            state="readonly", width=15
        )
        self.captcha_combo.grid(row=1, column=1, sticky=tk.W, pady=5)

        ttk.Label(general, text="Captcha API Key:").grid(
            row=2, column=0, sticky=tk.W, pady=5)
        self.captcha_key_entry = ttk.Entry(general, width=40)
        self.captcha_key_entry.grid(row=2, column=1, sticky=tk.W, pady=5)

        # ── Cloud Tab ──
        cloud = ttk.Frame(notebook, padding=10)
        notebook.add(cloud, text="Cloud Sync")

        self.auto_export_var = tk.BooleanVar()
        ttk.Checkbutton(cloud, text="Auto Export after completion",
                          variable=self.auto_export_var).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=5)

        ttk.Label(cloud, text="Sync Interval (minutes):").grid(
            row=1, column=0, sticky=tk.W, pady=5)
        self.sync_interval_spin = ttk.Spinbox(
            cloud, from_=5, to=1440, width=10)
        self.sync_interval_spin.grid(row=1, column=1, sticky=tk.W, pady=5)

        # ── Buttons ──
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="Save",
                    command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel",
                    command=self.destroy).pack(side=tk.RIGHT, padx=5)

    def _load_current(self):
        self.threads_spin.set(self._settings.get("max_threads", MAX_THREADS))
        self.captcha_combo.set(
            self._settings.get("captcha_service", CAPTCHA_SERVICE))
        self.captcha_key_entry.insert(
            0, self._settings.get("captcha_api_key", CAPTCHA_API_KEY))
        self.auto_export_var.set(
            self._settings.get("auto_export", AUTO_EXPORT_ENABLED))
        self.sync_interval_spin.set(
            self._settings.get("sync_interval", SYNC_INTERVAL_MINUTES))

    def _save(self):
        settings = {
            "max_threads": int(self.threads_spin.get()),
            "captcha_service": self.captcha_combo.get(),
            "captcha_api_key": self.captcha_key_entry.get(),
            "auto_export": self.auto_export_var.get(),
            "sync_interval": int(self.sync_interval_spin.get()),
        }
        if self.on_save:
            self.on_save(settings)
        self.destroy()


class SheetSyncDialog(tk.Toplevel):
    """Google Sheet sync dialog."""

    def __init__(self, parent, sheets_sync, on_import, on_export,
                 log_callback=None):
        super().__init__(parent)
        self.title("Google Sheet Sync")
        self.geometry("550x350")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.sheets_sync = sheets_sync
        self.on_import = on_import
        self.on_export = on_export
        self.log = log_callback or print

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self, padding=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Sheet URL
        ttk.Label(main, text="Google Sheet URL:").pack(
            anchor=tk.W, pady=(0, 5))
        self.url_entry = ttk.Entry(main, width=60)
        self.url_entry.pack(fill=tk.X, pady=(0, 10))
        if self.sheets_sync.sheet_url:
            self.url_entry.insert(0, self.sheets_sync.sheet_url)

        # Sheet Name
        row = ttk.Frame(main)
        row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(row, text="Sheet Name:").pack(side=tk.LEFT)
        self.sheet_name_entry = ttk.Entry(row, width=20)
        self.sheet_name_entry.pack(side=tk.LEFT, padx=10)
        self.sheet_name_entry.insert(0, "Sheet1")

        # Status
        self.status_var = tk.StringVar(value="Not connected")
        ttk.Label(main, textvariable=self.status_var,
                   foreground="gray").pack(anchor=tk.W, pady=5)

        # Progress
        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=5)

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=10)

        ttk.Button(btn_frame, text="Connect",
                    command=self._connect).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Import (Sheet → Tool)",
                    command=self._import).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Export (Tool → Sheet)",
                    command=self._export).pack(side=tk.LEFT, padx=5)

        ttk.Separator(main).pack(fill=tk.X, pady=10)

        # Auto sync
        auto_frame = ttk.Frame(main)
        auto_frame.pack(fill=tk.X)

        self.auto_sync_var = tk.BooleanVar()
        ttk.Checkbutton(auto_frame, text="Auto Sync",
                          variable=self.auto_sync_var,
                          command=self._toggle_auto_sync).pack(side=tk.LEFT)
        ttk.Label(auto_frame, text="every").pack(side=tk.LEFT, padx=5)
        self.interval_spin = ttk.Spinbox(
            auto_frame, from_=5, to=1440, width=5)
        self.interval_spin.set(30)
        self.interval_spin.pack(side=tk.LEFT)
        ttk.Label(auto_frame, text="minutes").pack(side=tk.LEFT, padx=5)

    def _connect(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Nhập Google Sheet URL!")
            return

        self.sheets_sync.set_sheet_url(url)
        self.progress.start()
        self.status_var.set("Connecting...")

        def do_connect():
            success = self.sheets_sync.connect()
            self.after(0, lambda: self._on_connected(success))

        threading.Thread(target=do_connect, daemon=True).start()

    def _on_connected(self, success):
        self.progress.stop()
        if success:
            self.status_var.set("Connected ✓")
        else:
            self.status_var.set("Connection failed ✗")

    def _import(self):
        if not self.sheets_sync._service:
            messagebox.showwarning("Warning", "Kết nối trước!")
            return

        self.progress.start()
        self.status_var.set("Importing...")

        def do_import():
            sheet_name = self.sheet_name_entry.get() or "Sheet1"
            data = self.sheets_sync.import_data(sheet_name)
            self.after(0, lambda: self._on_imported(data))

        threading.Thread(target=do_import, daemon=True).start()

    def _on_imported(self, data):
        self.progress.stop()
        if data:
            self.on_import(data)
            self.status_var.set(f"Imported {len(data)} rows ✓")
        else:
            self.status_var.set("Import: no data")

    def _export(self):
        if not self.sheets_sync._service:
            messagebox.showwarning("Warning", "Kết nối trước!")
            return

        data = self.on_export()
        if not data:
            messagebox.showwarning("Warning", "Không có dữ liệu!")
            return

        self.progress.start()
        self.status_var.set("Exporting...")

        def do_export():
            sheet_name = self.sheet_name_entry.get() or "Sheet1"
            success = self.sheets_sync.export_data(data, sheet_name)
            self.after(0, lambda: self._on_exported(success, len(data)))

        threading.Thread(target=do_export, daemon=True).start()

    def _on_exported(self, success, count):
        self.progress.stop()
        if success:
            self.status_var.set(f"Exported {count} rows ✓")
        else:
            self.status_var.set("Export failed ✗")

    def _toggle_auto_sync(self):
        if self.auto_sync_var.get():
            interval = int(self.interval_spin.get())
            self.sheets_sync.start_auto_sync(
                interval_minutes=interval,
                get_data_func=self.on_export,
            )
            self.status_var.set(f"Auto-sync ON (every {interval}m)")
        else:
            self.sheets_sync.stop_auto_sync()
            self.status_var.set("Auto-sync OFF")
