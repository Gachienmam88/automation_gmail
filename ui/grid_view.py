"""
Grid View - 15 Column Data Grid
- Giống Google Sheet
- Checkbox ẩn/hiện Firefox
- Multi-select dòng
- Right-click context menu
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Optional

from config import GRID_COLUMNS, GRID_COLUMN_KEYS, ACTIONS, DISPLAY_MODES


class GridView(ttk.Frame):
    """15-column data grid with multi-select and inline editing."""

    def __init__(self, parent, on_data_change: Callable = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_data_change = on_data_change
        self._data: list[dict] = []
        self._selected_rows: set = set()
        self._sort_column = ""
        self._sort_reverse = False

        self._build_ui()

    def _build_ui(self):
        """Build the grid UI."""
        # ── Toolbar ──
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=5, pady=(5, 0))

        self.select_all_var = tk.BooleanVar()
        ttk.Checkbutton(
            toolbar, text="Select All",
            variable=self.select_all_var,
            command=self._toggle_select_all
        ).pack(side=tk.LEFT)

        ttk.Button(toolbar, text="+ Add Row",
                    command=self._add_empty_row).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Delete Selected",
                    command=self._delete_selected).pack(side=tk.LEFT, padx=5)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(toolbar, text="Action:").pack(side=tk.LEFT)
        self.action_combo = ttk.Combobox(
            toolbar, values=ACTIONS, width=25, state="readonly"
        )
        self.action_combo.pack(side=tk.LEFT, padx=5)
        self.action_combo.set(ACTIONS[0])
        ttk.Button(toolbar, text="Set Selected",
                    command=self._set_action_selected).pack(side=tk.LEFT)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(toolbar, text="Display:").pack(side=tk.LEFT)
        self.display_combo = ttk.Combobox(
            toolbar, values=DISPLAY_MODES, width=10, state="readonly"
        )
        self.display_combo.pack(side=tk.LEFT, padx=5)
        self.display_combo.set(DISPLAY_MODES[0])

        # Row count label
        self.row_count_label = ttk.Label(toolbar, text="0 rows")
        self.row_count_label.pack(side=tk.RIGHT, padx=5)

        # ── Treeview with scrollbars ──
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)

        # Treeview
        columns = [c["key"] for c in GRID_COLUMNS]
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
        )

        vsb.config(command=self.tree.yview)
        hsb.config(command=self.tree.xview)

        # Grid layout
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # Configure columns
        for col_config in GRID_COLUMNS:
            key = col_config["key"]
            self.tree.heading(
                key, text=col_config["label"],
                command=lambda k=key: self._sort_by_column(k)
            )
            self.tree.column(key, width=col_config["width"], minwidth=40)

        # ── Tags for styling ──
        self.tree.tag_configure("success", background="#E8F5E9")
        self.tree.tag_configure("error", background="#FFEBEE")
        self.tree.tag_configure("running", background="#FFF3E0")
        self.tree.tag_configure("selected_row", background="#E3F2FD")
        self.tree.tag_configure("even", background="#FAFAFA")
        self.tree.tag_configure("odd", background="#FFFFFF")

        # ── Bindings ──
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Delete>", lambda e: self._delete_selected())

        # ── Context Menu ──
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Edit Cell",
                                       command=self._edit_selected_cell)
        self.context_menu.add_command(label="Copy Row",
                                       command=self._copy_selected)
        self.context_menu.add_command(label="Paste Row",
                                       command=self._paste_row)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Delete Row",
                                       command=self._delete_selected)
        self.context_menu.add_separator()
        for action in ACTIONS:
            self.context_menu.add_command(
                label=f"Set: {action}",
                command=lambda a=action: self._set_action_for_selected(a)
            )

    # ─── Data Management ───

    def load_data(self, data: list[dict]):
        """Load data into grid."""
        self._data = data
        self._refresh_tree()

    def get_data(self) -> list[dict]:
        """Get all data from grid."""
        return self._data.copy()

    def get_selected_data(self) -> list[dict]:
        """Get data for selected rows only."""
        selected = self.tree.selection()
        result = []
        for item_id in selected:
            idx = self.tree.index(item_id)
            if idx < len(self._data):
                result.append(self._data[idx])
        return result

    def get_selected_indices(self) -> list[int]:
        """Get indices of selected rows."""
        selected = self.tree.selection()
        return [self.tree.index(item_id) for item_id in selected]

    def update_row(self, index: int, data: dict):
        """Update a specific row."""
        if 0 <= index < len(self._data):
            self._data[index].update(data)
            self._refresh_row(index)

    def set_row_status(self, index: int, status: str, result: str = ""):
        """Update status and result for a row."""
        if 0 <= index < len(self._data):
            self._data[index]["status"] = status
            if result:
                self._data[index]["result"] = result
            self._refresh_row(index)

    def _refresh_tree(self):
        """Rebuild entire treeview from data."""
        self.tree.delete(*self.tree.get_children())
        for i, record in enumerate(self._data):
            record["stt"] = str(i + 1)
            values = [record.get(key, "") for key in GRID_COLUMN_KEYS]
            tag = self._get_row_tag(record, i)
            self.tree.insert("", tk.END, values=values, tags=(tag,))
        self.row_count_label.config(text=f"{len(self._data)} rows")

    def _refresh_row(self, index: int):
        """Refresh a single row."""
        children = self.tree.get_children()
        if index < len(children):
            item_id = children[index]
            record = self._data[index]
            values = [record.get(key, "") for key in GRID_COLUMN_KEYS]
            tag = self._get_row_tag(record, index)
            self.tree.item(item_id, values=values, tags=(tag,))

    def _get_row_tag(self, record: dict, index: int) -> str:
        """Get visual tag based on row status."""
        status = record.get("status", "").lower()
        if "ok" in status or "success" in status or "done" in status:
            return "success"
        elif "error" in status or "fail" in status:
            return "error"
        elif "running" in status or "processing" in status:
            return "running"
        return "even" if index % 2 == 0 else "odd"

    # ─── Row Operations ───

    def _add_empty_row(self):
        """Add a new empty row."""
        new_row = {key: "" for key in GRID_COLUMN_KEYS}
        new_row["stt"] = str(len(self._data) + 1)
        new_row["action"] = self.action_combo.get()
        new_row["display_mode"] = self.display_combo.get()
        self._data.append(new_row)
        self._refresh_tree()
        # Scroll to bottom
        children = self.tree.get_children()
        if children:
            self.tree.see(children[-1])

    def _delete_selected(self):
        """Delete selected rows."""
        selected = self.tree.selection()
        if not selected:
            return
        if not messagebox.askyesno("Xác nhận", f"Xóa {len(selected)} dòng?"):
            return
        indices = sorted(
            [self.tree.index(item) for item in selected],
            reverse=True
        )
        for idx in indices:
            if idx < len(self._data):
                self._data.pop(idx)
        self._refresh_tree()

    def _toggle_select_all(self):
        """Select or deselect all rows."""
        if self.select_all_var.get():
            self.tree.selection_set(self.tree.get_children())
        else:
            self.tree.selection_remove(*self.tree.get_children())

    def _set_action_selected(self):
        """Set action for selected rows."""
        action = self.action_combo.get()
        self._set_action_for_selected(action)

    def _set_action_for_selected(self, action: str):
        """Set action for all selected rows."""
        for item_id in self.tree.selection():
            idx = self.tree.index(item_id)
            if idx < len(self._data):
                self._data[idx]["action"] = action
        self._refresh_tree()

    # ─── Sorting ───

    def _sort_by_column(self, column: str):
        """Sort data by column."""
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False

        self._data.sort(
            key=lambda r: r.get(column, "").lower(),
            reverse=self._sort_reverse
        )
        self._refresh_tree()

    # ─── Inline Editing ───

    def _on_double_click(self, event):
        """Handle double-click for inline editing."""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        column = self.tree.identify_column(event.x)
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return

        col_index = int(column[1:]) - 1  # #1 → 0
        col_key = GRID_COLUMN_KEYS[col_index]

        if col_key == "stt":
            return  # Don't edit STT

        # Get cell bbox
        bbox = self.tree.bbox(item_id, column)
        if not bbox:
            return

        # Get current value
        idx = self.tree.index(item_id)
        current_value = self._data[idx].get(col_key, "")

        # Special handling for Action and Display columns
        if col_key == "action":
            self._show_combobox_editor(bbox, item_id, idx, col_key, ACTIONS, current_value)
            return
        elif col_key == "display_mode":
            self._show_combobox_editor(bbox, item_id, idx, col_key, DISPLAY_MODES, current_value)
            return

        # Regular text editor
        self._show_text_editor(bbox, item_id, idx, col_key, current_value)

    def _show_text_editor(self, bbox, item_id, row_idx, col_key, current_value):
        """Show inline text editor."""
        x, y, w, h = bbox
        entry = ttk.Entry(self.tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, current_value)
        entry.select_range(0, tk.END)
        entry.focus()

        def save_edit(event=None):
            new_value = entry.get()
            self._data[row_idx][col_key] = new_value
            self._refresh_row(row_idx)
            entry.destroy()
            if self.on_data_change:
                self.on_data_change()

        def cancel_edit(event=None):
            entry.destroy()

        entry.bind("<Return>", save_edit)
        entry.bind("<Escape>", cancel_edit)
        entry.bind("<FocusOut>", save_edit)

    def _show_combobox_editor(self, bbox, item_id, row_idx, col_key, values, current_value):
        """Show inline combobox editor."""
        x, y, w, h = bbox
        combo = ttk.Combobox(self.tree, values=values, state="readonly")
        combo.place(x=x, y=y, width=w, height=h)
        combo.set(current_value)
        combo.focus()

        def save_edit(event=None):
            self._data[row_idx][col_key] = combo.get()
            self._refresh_row(row_idx)
            combo.destroy()

        combo.bind("<<ComboboxSelected>>", save_edit)
        combo.bind("<Escape>", lambda e: combo.destroy())
        combo.bind("<FocusOut>", save_edit)

    # ─── Context Menu ───

    def _on_right_click(self, event):
        """Show context menu."""
        # Select the row under cursor
        item_id = self.tree.identify_row(event.y)
        if item_id:
            if item_id not in self.tree.selection():
                self.tree.selection_set(item_id)
            self._right_click_item = item_id
            self._right_click_column = self.tree.identify_column(event.x)
        self.context_menu.post(event.x_root, event.y_root)

    def _on_select(self, event):
        """Handle selection change."""
        count = len(self.tree.selection())
        self.row_count_label.config(
            text=f"{len(self._data)} rows ({count} selected)"
            if count else f"{len(self._data)} rows"
        )

    def _edit_selected_cell(self):
        """Edit the right-clicked cell."""
        if hasattr(self, '_right_click_item'):
            bbox = self.tree.bbox(
                self._right_click_item,
                self._right_click_column
            )
            if bbox:
                col_index = int(self._right_click_column[1:]) - 1
                col_key = GRID_COLUMN_KEYS[col_index]
                idx = self.tree.index(self._right_click_item)
                current = self._data[idx].get(col_key, "")
                self._show_text_editor(
                    bbox, self._right_click_item, idx, col_key, current
                )

    def _copy_selected(self):
        """Copy selected rows to clipboard."""
        selected = self.get_selected_data()
        if not selected:
            return
        lines = []
        for record in selected:
            line = "\t".join(record.get(key, "") for key in GRID_COLUMN_KEYS)
            lines.append(line)
        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)

    def _paste_row(self):
        """Paste rows from clipboard."""
        try:
            text = self.clipboard_get()
            lines = text.strip().split("\n")
            for line in lines:
                parts = line.split("\t")
                new_row = {key: "" for key in GRID_COLUMN_KEYS}
                for i, key in enumerate(GRID_COLUMN_KEYS):
                    if i < len(parts):
                        new_row[key] = parts[i]
                new_row["stt"] = str(len(self._data) + 1)
                self._data.append(new_row)
            self._refresh_tree()
        except Exception:
            pass
