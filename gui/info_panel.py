"""
info_panel.py
Interactive info/status display panel with wizard-style interactions.
Replaces popup dialogs with inline interactive widgets.

"""

import tkinter as tk
from tkinter import ttk

from gui.theme import COLORS, FONTS


# Map message types to theme colors
_MSG_COLORS = {
    "info":    COLORS["accent"],
    "success": COLORS["success"],
    "warning": COLORS["warning"],
    "error":   COLORS["danger"],
    "note":    COLORS["text_muted"],
}


class InfoPanel(ttk.Frame):
    """
    Interactive info/status display panel with wizard-style interactions.
    Replaces popup dialogs with inline interactive widgets.
    """

    def __init__(self, parent):
        # Card-style container — flat surface with subtle border via styled frame
        super().__init__(parent)

        # Use a raw tk.Frame for the surface so we get true background + border control
        self._surface = tk.Frame(
            self,
            background=COLORS["surface"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["border"],
            bd=0,
        )
        self._surface.pack(fill="both", expand=True)

        # Main container frame (cleared and rebuilt for each interaction)
        self.content_frame = tk.Frame(self._surface, background=COLORS["surface"])
        self.content_frame.pack(fill="both", expand=True, padx=14, pady=10)

        # Show welcome message
        self.set_welcome()

    def _clear_content(self):
        """Clear all widgets from content frame."""
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _label(self, parent, text, *, color=None, font=None, **pack_kwargs):
        """Helper to create a label that sits on the card surface cleanly."""
        lbl = tk.Label(
            parent,
            text=text,
            font=font or FONTS["body"],
            foreground=color or COLORS["text"],
            background=COLORS["surface"],
            anchor="w",
            justify="left",
        )
        if pack_kwargs:
            lbl.pack(**pack_kwargs)
        return lbl

    def set_welcome(self):
        """Display welcome message."""
        self._clear_content()

        self._label(
            self.content_frame,
            "Welcome to Equidam Projections Uploader",
            color=COLORS["text"],
            font=FONTS["h2"],
            anchor="w", pady=(0, 6),
        )

        self._label(
            self.content_frame,
            "📊  Click 'Import Table' to load your financial data from Excel or CSV.",
            color=COLORS["text_muted"],
            font=FONTS["body"],
            anchor="w", pady=2,
        )


    def show_message(self, message, msg_type="info"):
        """Display a simple message. msg_type: 'info', 'success', 'warning', 'error'."""
        self._clear_content()
        self._label(
            self.content_frame,
            message,
            color=_MSG_COLORS.get(msg_type, COLORS["accent"]),
            font=FONTS["body"],
            anchor="w",
        )

    def show_progress(self, messages):
        """Show a list of (text, type) progress messages."""
        self._clear_content()
        for msg, msg_type in messages:
            self._label(
                self.content_frame,
                msg,
                color=_MSG_COLORS.get(msg_type, COLORS["accent"]),
                font=FONTS["body"],
                anchor="w", pady=1,
            )

    def show_yes_no_question(self, question, on_yes, on_no, details=None):
        """Show a YES/NO question with buttons."""
        self._clear_content()

        self._label(
            self.content_frame,
            question,
            color=COLORS["text"],
            font=FONTS["h2"],
            anchor="w", pady=(0, 10),
        )

        if details:
            for detail in details:
                self._label(
                    self.content_frame,
                    f"• {detail}",
                    color=COLORS["text_muted"],
                    font=FONTS["small"],
                    anchor="w", pady=2, padx=18,
                )

        btn_frame = tk.Frame(self.content_frame, background=COLORS["surface"])
        btn_frame.pack(anchor="w", pady=(14, 0))

        ttk.Button(
            btn_frame, text="YES", command=on_yes, width=16, style="Accent.TButton"
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            btn_frame, text="NO", command=on_no, width=16
        ).pack(side="left")
    
    def show_sheet_selector(self, sheets, on_continue, on_cancel):
        """Show sheet selection with checkboxes."""
        self._clear_content()

        self._label(
            self.content_frame,
            f"📁  Select sheets to import  ({len(sheets)} found)",
            color=COLORS["text"],
            font=FONTS["h2"],
            anchor="w", pady=(0, 10),
        )

        check_vars = {}

        btn_frame = tk.Frame(self.content_frame, background=COLORS["surface"])
        select_all_btn = ttk.Button(btn_frame, width=15, style="Ghost.TButton")

        def update_button_state():
            all_selected = all(var.get() for var in check_vars.values())
            select_all_btn.configure(text="Unselect All" if all_selected else "Select All")

        def handle_toggle_all():
            all_selected = all(var.get() for var in check_vars.values())
            new_state = not all_selected
            for var in check_vars.values():
                var.set(new_state)
            update_button_state()

        # Create checkboxes for each sheet
        for sheet in sheets:
            var = tk.BooleanVar(value=False)
            check_vars[sheet] = var
            var.trace_add("write", lambda *_, u=update_button_state: u())

            cb = ttk.Checkbutton(
                self.content_frame,
                text=sheet,
                variable=var,
                style="Card.TCheckbutton",
            )
            cb.pack(anchor="w", pady=3, padx=20)

        btn_frame.pack(anchor="w", pady=(14, 0))

        select_all_btn.configure(command=handle_toggle_all)
        update_button_state()
        select_all_btn.pack(side="left", padx=(0, 10))

        def handle_continue():
            selected = [sheet for sheet, var in check_vars.items() if var.get()]
            if not selected:
                self.show_message("⚠ Please select at least one sheet", "warning")
                return
            on_continue(selected)

        ttk.Button(
            btn_frame, text="Continue", command=handle_continue, width=15, style="Accent.TButton"
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            btn_frame, text="Cancel", command=on_cancel, width=15
        ).pack(side="left")
    
    def show_review_table(self, review_items, on_apply, on_skip, applied_mappings=None):
        """
        Show review items with checkboxes for user to approve/reject.
        Auto-applied mappings are shown side-by-side for context.
        """
        self._clear_content()

        columns_frame = tk.Frame(self.content_frame, background=COLORS["surface"])
        columns_frame.pack(fill="both", expand=True)

        # ── LEFT COLUMN: auto-applied mappings ────────────────────────────
        if applied_mappings and len(applied_mappings) > 0:
            left_column = tk.Frame(columns_frame, background=COLORS["surface"])
            left_column.pack(side="left", fill="both", expand=True, padx=(0, 12))

            self._label(
                left_column,
                f"✓  {len(applied_mappings)} Auto-Applied Mappings (100% confidence)",
                color=COLORS["success"], font=FONTS["h2"],
                anchor="w", pady=(0, 4),
            )
            self._label(
                left_column,
                "Automatically mapped with high confidence.",
                color=COLORS["text_muted"], font=FONTS["small"],
                anchor="w", pady=(0, 10),
            )

            auto_scroll_frame = tk.Frame(left_column, background=COLORS["surface"])
            auto_scroll_frame.pack(fill="both", expand=True)

            auto_canvas = tk.Canvas(
                auto_scroll_frame,
                background=COLORS["surface"],
                highlightthickness=0,
                borderwidth=0,
            )
            auto_scrollbar = ttk.Scrollbar(auto_scroll_frame, orient="vertical", command=auto_canvas.yview)
            auto_scrollable = tk.Frame(auto_canvas, background=COLORS["surface"])

            auto_scrollable.bind(
                "<Configure>",
                lambda e: auto_canvas.configure(scrollregion=auto_canvas.bbox("all"))
            )

            auto_canvas.create_window((0, 0), window=auto_scrollable, anchor="nw")
            auto_canvas.configure(yscrollcommand=auto_scrollbar.set)

            for mapping in applied_mappings:
                source = mapping.get("source", "")
                target = mapping.get("target", "")
                section = mapping.get("section", "")
                self._label(
                    auto_scrollable,
                    f"✓  {source}  →  {target}   ({section})",
                    color=COLORS["success"], font=FONTS["small"],
                    anchor="w", pady=2, padx=4,
                )

            auto_canvas.pack(side="left", fill="both", expand=True)
            auto_scrollbar.pack(side="right", fill="y")

        # ── RIGHT COLUMN: review items ────────────────────────────────────
        right_column = tk.Frame(columns_frame, background=COLORS["surface"])
        right_column.pack(side="left", fill="both", expand=True)

        self._label(
            right_column,
            f"⚠  {len(review_items)} Items Need Manual Review",
            color=COLORS["warning"], font=FONTS["h2"],
            anchor="w", pady=(0, 4),
        )
        self._label(
            right_column,
            "Below the auto-map threshold. Check items to approve.",
            color=COLORS["text_muted"], font=FONTS["small"],
            anchor="w", pady=(0, 10),
        )

        review_scroll_frame = tk.Frame(right_column, background=COLORS["surface"])
        review_scroll_frame.pack(fill="both", expand=True)

        review_canvas = tk.Canvas(
            review_scroll_frame,
            background=COLORS["surface"],
            highlightthickness=0,
            borderwidth=0,
        )
        review_scrollbar = ttk.Scrollbar(review_scroll_frame, orient="vertical", command=review_canvas.yview)
        review_scrollable = tk.Frame(review_canvas, background=COLORS["surface"])

        review_scrollable.bind(
            "<Configure>",
            lambda e: review_canvas.configure(scrollregion=review_canvas.bbox("all"))
        )

        review_canvas.create_window((0, 0), window=review_scrollable, anchor="nw")
        review_canvas.configure(yscrollcommand=review_scrollbar.set)

        check_vars = {}

        for item in review_items:
            var = tk.BooleanVar(value=False)
            check_vars[item["source_label"]] = (var, item)

            text = (f"{item['source_label']}  →  {item['suggested_target']}"
                    f"   ({item['confidence']}%, {item['section']})")

            cb = ttk.Checkbutton(
                review_scrollable,
                text=text,
                variable=var,
                style="Card.TCheckbutton",
            )
            cb.pack(anchor="w", pady=3, padx=4)

        review_canvas.pack(side="left", fill="both", expand=True)
        review_scrollbar.pack(side="right", fill="y")

        # ── Action buttons ────────────────────────────────────────────────
        btn_frame = tk.Frame(self.content_frame, background=COLORS["surface"])
        btn_frame.pack(anchor="w", pady=(14, 0))

        def handle_apply():
            selected = [item for var, item in check_vars.values() if var.get()]
            if not selected:
                self.show_message("⚠ No items selected. Click 'Skip' to continue without applying.", "warning")
                return
            on_apply(selected)

        ttk.Button(
            btn_frame, text="Apply Selected", command=handle_apply, width=16, style="Accent.TButton"
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            btn_frame, text="Skip", command=on_skip, width=15
        ).pack(side="left")
    
    def show_conflict_resolution(self, conflicts, on_apply, on_cancel):
        """Show multi-sheet conflict resolution with radio buttons."""
        self._clear_content()

        self._label(
            self.content_frame,
            f"⚠  {len(conflicts)} Conflicts Found — Choose Values to Use",
            color=COLORS["warning"], font=FONTS["h2"],
            anchor="w", pady=(0, 4),
        )
        self._label(
            self.content_frame,
            "The same field was found in multiple sheets with different values.\n"
            "Select which sheet's data to use for each field:",
            color=COLORS["text_muted"], font=FONTS["small"],
            anchor="w", pady=(0, 10),
        )

        canvas = tk.Canvas(
            self.content_frame,
            height=300,
            background=COLORS["surface"],
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(self.content_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, background=COLORS["surface"])

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        radio_vars = {}

        for field_name, conflict_data in conflicts.items():
            field_type = conflict_data.get('type', 'financial')
            sheet_data = conflict_data.get('sheets', {})

            field_frame = ttk.LabelFrame(
                scrollable_frame,
                text=f"  {field_name}   ·   {field_type}  ",
                padding=10,
                style="Field.TLabelframe",
            )
            field_frame.pack(fill="x", padx=4, pady=8, anchor="w")

            var = tk.StringVar()
            radio_vars[field_name] = var

            default_sheet = self._suggest_best_sheet(sheet_data, field_type)
            var.set(default_sheet)

            for sheet_name, values in sheet_data.items():
                if field_type == 'financial':
                    if isinstance(values, list):
                        formatted = ", ".join([
                            f"Y{i+1}: {self._format_value(v)}"
                            for i, v in enumerate(values) if v is not None
                        ])
                    else:
                        formatted = str(values)
                else:
                    formatted = f"Current: {self._format_value(values)}"

                is_default = (sheet_name == default_sheet)
                display_text = f"{sheet_name}:  {formatted}" + ("   (recommended)" if is_default else "")

                ttk.Radiobutton(
                    field_frame,
                    text=display_text,
                    variable=var,
                    value=sheet_name,
                ).pack(anchor="w", pady=2)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        btn_frame = tk.Frame(self.content_frame, background=COLORS["surface"])
        btn_frame.pack(anchor="w", pady=(14, 0))

        def handle_apply():
            selections = {field: var.get() for field, var in radio_vars.items()}
            on_apply(selections)

        ttk.Button(
            btn_frame, text="Apply Selections", command=handle_apply, width=16, style="Accent.TButton"
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            btn_frame, text="Cancel", command=on_cancel, width=15
        ).pack(side="left")
    
    def _suggest_best_sheet(self, sheet_data, field_type):
        """Suggest which sheet to use by default (most complete data)."""
        best_sheet = list(sheet_data.keys())[0]
        best_score = 0
        
        for sheet_name, values in sheet_data.items():
            if field_type == 'financial':
                # Count non-None values
                if isinstance(values, list):
                    score = sum(1 for v in values if v is not None and v != 0)
                else:
                    score = 1 if values else 0
            else:
                # Balance - just check if value exists
                score = 1 if values else 0
            
            if score > best_score:
                best_score = score
                best_sheet = sheet_name
        
        return best_sheet
    
    def _format_value(self, value):
        """Format a numeric value for display."""
        if value is None:
            return "—"
        try:
            num = float(value)
            if abs(num) >= 1000:
                return f"${num:,.0f}"
            else:
                return f"${num:,.2f}"
        except:
            return str(value)

