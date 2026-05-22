"""
app.py
Main application orchestrator for Equidam Projections Uploader.
Handles high-level UI layout and delegates operations to specialized managers.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import logging

from core.data_handler import save_to_template
from core.importer import import_any, get_excel_sheet_names
from core.multi_sheet_scanner import (
    scan_multiple_sheets,
    apply_conflict_resolutions,
    format_scan_summary
)
from core.logging_config import get_logger, set_log_level

from gui.constants import FINANCIAL_ROWS, BALANCE_ROWS
from gui.widgets import ScrollableFrame, HorizontalScrollFrame
from gui.info_panel import InfoPanel
from gui.grid_manager import FinancialGridManager, BalanceGridManager
from gui.theme import apply_theme, COLORS, FONTS

logger = get_logger(__name__)

class EquidamApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Equidam Projections Uploader")
        self.geometry("1440x780")
        self.minsize(1100, 640)

        # Apply theme before any widgets are built so they pick up styles
        apply_theme(self)

        self.forecast_years = 3
        self.max_years = 5
        
        # Store last import result for manual mapping
        self.last_import_result = None
        
        # Store multi-sheet scan result for conflict resolution
        self.last_scan_result = None
        
        # Store import workflow state
        self.import_path = None
        self.selected_sheets = []  # Changed from single sheet to list
        self.has_previous = False

        # Create scrollable container
        self.scroll = ScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True)
        self.scroll.canvas.configure(background=COLORS["bg"])

        # Build UI sections
        self._build_header(self.scroll.body)
        self._build_forecast_controls(self.scroll.body)
        
        # Horizontally scrollable row so the two grids sit side-by-side and
        # the user can scroll right to reach the Balance Sheet if both grids
        # don't fit on screen.
        self.grids_scroll = HorizontalScrollFrame(self.scroll.body)
        self.grids_scroll.pack(fill="x", padx=4, pady=(0, 8), anchor="w")
        grids_row = self.grids_scroll.body

        self.fin_manager = FinancialGridManager(
            grids_row,
            FINANCIAL_ROWS,
            self.forecast_years
        )
        self.bal_manager = BalanceGridManager(
            grids_row,
            BALANCE_ROWS
        )

        # Re-pack the grid frames horizontally (managers default to vertical stacking)
        self.fin_manager.frame.pack_configure(side="left", anchor="n", padx=(10, 6), pady=4)
        self.bal_manager.frame.pack_configure(side="left", anchor="n", padx=(6, 10), pady=4)
        
        self._build_export_bar(self)
        
        # Log startup
        logger.info("App starting...")

    def _build_header(self, parent):
        """Build the application header with title, interactive info panel, and debug toggle."""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill="x", padx=14, pady=(10, 2))

        title_block = ttk.Frame(header_frame)
        title_block.pack(side="left")

        ttk.Label(
            title_block,
            text="Equidam Projections Uploader",
            style="H1.TLabel",
        ).pack(anchor="w")

        ttk.Label(
            title_block,
            text="Import, clean, and export financial projections",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        self.debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            header_frame,
            text="Detailed debug",
            variable=self.debug_var,
            command=self._on_toggle_debug,
        ).pack(side="right", padx=4)

        # Thin divider under the header
        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=14, pady=(6, 8))

        # Interactive info panel (replaces all dialogs)
        self.info_panel = InfoPanel(parent)
        self.info_panel.pack(fill="both", padx=14, pady=(0, 8))

    def _on_toggle_debug(self):
        """Handle debug toggle checkbox."""
        verbose = self.debug_var.get()
        set_log_level("DEBUG" if verbose else "INFO")
        logger.info("Log mode: %s", "Full (DEBUG)" if verbose else "Minimal (INFO)")

    def _build_forecast_controls(self, parent):
        """Build the control bar with import and add year buttons."""
        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=14, pady=(0, 8))

        ttk.Button(
            bar,
            text="Import Table",
            command=self._import_table,
            style="Accent.TButton",
        ).pack(side="left", padx=(0, 8))

        self.imported_file_var = tk.StringVar(value="")
        self.imported_file_label = ttk.Label(
            bar,
            textvariable=self.imported_file_var,
            style="Muted.TLabel",
        )
        self.imported_file_label.pack(side="left", padx=(0, 16))

        ttk.Button(
            bar,
            text="Convert Monthly → Yearly",
            command=self._convert_monthly,
        ).pack(side="left", padx=(0, 8))

        self.add_year_btn = ttk.Button(
            bar,
            text="+ Add Forecast Year",
            command=self._add_forecast_year,
            style="Ghost.TButton",
        )
        self.add_year_btn.pack(side="left")

        export_row = ttk.Frame(parent)
        export_row.pack(fill="x", padx=14, pady=(0, 10))

        ttk.Label(export_row, text="Output file", style="Muted.TLabel").pack(side="left", padx=(0, 8))

        self.output_path_var = tk.StringVar(
            value=str(Path.home() / "equidam_output.xlsx")
        )
        ttk.Entry(
            export_row,
            textvariable=self.output_path_var,
            width=50,
        ).pack(side="left", padx=(0, 10), fill="x", expand=False)

        ttk.Button(
            export_row,
            text="Browse...",
            command=self._choose_output_path,
            style="Ghost.TButton",
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            export_row,
            text="Export Formatted Excel",
            command=self._export,
            style="Accent.TButton",
        ).pack(side="left", padx=(0, 8))

    def _build_export_bar(self, parent):
        """Build the bottom export/clear control bar."""
        # Subtle top divider so the bar visually separates from the grids
        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=14)

        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=14, pady=8)

        ttk.Button(
            frame,
            text="Clear All",
            command=self._clear_all,
            style="Danger.TButton",
        ).pack(side="left")

    def _add_forecast_year(self):
        """Add an additional forecast year column (up to max)."""
        if self.forecast_years < self.max_years:
            self.forecast_years += 1
            self.fin_manager.set_forecast_years(self.forecast_years)
            
            # Update info panel
            self.info_panel.show_message(
                f"✓ Added Year {self.forecast_years} column",
                "success"
            )
            
        if self.forecast_years == self.max_years:
            self.add_year_btn.state(["disabled"])

    def _clear_all(self):
        """Clear all data from both grids."""
        if not messagebox.askyesno(
            "Clear All",
            "Clear all values in Financial and Balance Sheet grids?"
        ):
            return

        self.fin_manager.clear_grid()
        self.bal_manager.clear_grid()
        
        # Update info panel
        self.info_panel.show_message("✓ All grids cleared", "success")

    def _choose_output_path(self):
        """Choose where the formatted Equidam workbook will be exported."""
        current_path = Path(self.output_path_var.get().strip() or Path.home() / "equidam_output.xlsx")
        output_path = filedialog.asksaveasfilename(
            title="Export Formatted Equidam Excel As",
            defaultextension=".xlsx",
            initialdir=str(current_path.parent),
            initialfile=current_path.name,
            filetypes=[("Excel files", "*.xlsx")]
        )

        if output_path:
            self.output_path_var.set(output_path)

    # ==================== MONTHLY CONVERSION ====================
    
    def _convert_monthly(self):
        """Convert monthly data to yearly format."""
        from core.monthly_to_annual.monthly_to_yearly import convert_monthly_to_yearly
        
        # Step 1: Select input file
        input_path = filedialog.askopenfilename(
            title="Select Monthly Data File",
            filetypes=[
                ("Excel files", "*.xlsx *.xlsm"),
                ("All files", "*.*")
            ]
        )
        
        if not input_path:
            return
        
        # Step 2: Select output file
        default_output = str(Path(input_path).parent / f"{Path(input_path).stem}_yearly.xlsx")
        
        output_path = filedialog.asksaveasfilename(
            title="Save Yearly Data As",
            defaultextension=".xlsx",
            initialfile=Path(default_output).name,
            filetypes=[("Excel files", "*.xlsx")]
        )
        
        if not output_path:
            return
        
        # Step 3: Convert
        self.info_panel.show_message("⚙ Converting monthly data to yearly...", "info")
        self.update()  # Force UI update
        
        try:
            result = convert_monthly_to_yearly(input_path, output_path)
            
            if result['success']:
                messages = [
                    ("✓ Conversion Successful!", "success"),
                    ("", "info"),
                    (f"Created {result['years_created']} years from {result['months_processed']} months", "info"),
                    (f"Saved to: {output_path}", "note"),
                ]

                # Warn about all-zero rows (empty months injected as zeros)
                if result.get('zero_rows', 0) > 0:
                    messages.append(("", "info"))
                    messages.append((
                        f"⚠ {result['zero_rows']} row(s) have all-zero values — "
                        "their monthly data was empty. Review before importing.",
                        "warning"
                    ))

                if result['months_discarded'] > 0:
                    messages.append(("", "info"))
                    messages.append((
                        f"⚠ {result['months_discarded']} month(s) discarded "
                        "(not enough for a complete year)",
                        "warning"
                    ))

                # Show skipped sheets so user knows what was ignored
                if result.get('skipped_sheets'):
                    messages.append(("", "info"))
                    messages.append((f"Skipped {len(result['skipped_sheets'])} sheet(s):", "warning"))
                    for skip in result['skipped_sheets']:
                        messages.append((f"  • {skip['sheet']}: {skip['reason']}", "warning"))

                messages.append(("", "info"))
                messages.append(("💡 You can now import this yearly file using 'Import Table'", "note"))

                self.info_panel.show_progress(messages)

            else:
                messages = [("✗ Conversion Failed", "error"), ("", "info")]
                for error in result['errors']:
                    messages.append((f"• {error}", "error"))

                # Still show skipped sheets even on failure — helps diagnose why no sheets worked
                if result.get('skipped_sheets'):
                    messages.append(("", "info"))
                    messages.append((f"Sheets scanned but skipped:", "warning"))
                    for skip in result['skipped_sheets']:
                        messages.append((f"  • {skip['sheet']}: {skip['reason']}", "warning"))

                self.info_panel.show_progress(messages)
        
        except Exception as e:
            logger.error("Convert monthly failed: %s", e, exc_info=True)
            self.info_panel.show_message(
                f"✗ Conversion Failed\n\nError: {str(e)}",
                "error"
            )

    # ==================== IMPORT WORKFLOW (STEP-BY-STEP) ====================
    
    def _import_table(self):
        """Step 1: Select file and begin import workflow."""
        filetypes = [
            ("Excel files", "*.xlsx *.xlsm *.xltx *.xltm"),
            ("CSV files", "*.csv"),
            ("All files", "*.*"),
        ]
        path = filedialog.askopenfilename(
            title="Select a table to import",
            filetypes=filetypes
        )
        if not path:
            return

        # Store path for use in callbacks
        self.import_path = path
        self.imported_file_var.set(Path(path).name)

        # Show opening message
        self.info_panel.show_message("📂 Opening file...", "info")

        # Get sheet names (if Excel)
        sheet_names = get_excel_sheet_names(path)
        
        if sheet_names:
            if len(sheet_names) > 1:
                # Multiple sheets - show selector in panel
                self.info_panel.show_sheet_selector(
                    sheets=sheet_names,
                    on_continue=self._on_sheets_selected,
                    on_cancel=self._on_import_cancelled
                )
                return  # Wait for user selection
            else:
                # Single sheet - proceed directly
                self._continue_import_with_sheet([sheet_names[0]])
        else:
            # CSV file - no sheet selection needed
            self._continue_import_with_sheet([None])

    def _on_sheets_selected(self, selected_sheets):
        """Step 2: User selected sheets from the panel."""
        # Store selected sheets
        self.selected_sheets = selected_sheets
        
        # Detect single vs multi-sheet workflow
        if len(selected_sheets) == 1:
            # Single sheet - use existing workflow
            self._continue_import_with_sheet(selected_sheets)
        else:
            # Multi-sheet - NEW workflow
            self._start_multi_sheet_scan(selected_sheets)

    def _on_import_cancelled(self):
        """User cancelled sheet selection."""
        self.info_panel.show_message("⚠ Import cancelled", "warning")

    def _continue_import_with_sheet(self, sheet_list):
        """Step 3: Single sheet selected, now ask about previous year."""
        sheet_name = sheet_list[0]  # Single sheet
        self.selected_sheets = [sheet_name]
        
        # Show sheet confirmation if applicable
        if sheet_name:
            self.info_panel.show_message(
                f"📄 Selected sheet: {sheet_name}",
                "info"
            )
        
        # Ask about previous year structure (in panel, not popup)
        self.info_panel.show_yes_no_question(
            question="Does your data include a 'Previous Year' column?",
            on_yes=lambda: self._continue_import_with_previous(True),
            on_no=lambda: self._continue_import_with_previous(False),
            details=[
                "Select YES if your first data column is previous/historical year",
                "Select NO if all columns are forecasts only (Year 1, Year 2, etc.)"
            ]
        )

    def _continue_import_with_previous(self, has_previous):
        """Step 4: User answered previous year question, now process the import."""
        self.has_previous = has_previous
        
        # Show processing message
        self.info_panel.show_message("⚙ Processing data...", "info")
        
        # Find aliases.json
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        aliases_path = assets_dir / "aliases.json"
        
        if not aliases_path.exists():
            self.info_panel.show_message(
                f"✗ Configuration Error\naliases.json not found at:\n{aliases_path}",
                "error"
            )
            messagebox.showerror(
                "Missing Config",
                f"aliases.json not found at:\n{aliases_path}"
            )
            return
        
        try:
            # Import the data
            options = {
                "has_previous_year": has_previous,
                "sheet_name": self.selected_sheets[0]
            }
            
            logger.debug("Importing from: %s", self.import_path)
            logger.debug("Options: %s", options)
            
            res = import_any(self.import_path, str(aliases_path), options=options)
            
            # Store for manual mapping
            self.last_import_result = res

            # Update forecast years based on imported data
            years_used = int(res.get("years_used", 1))
            years_used = max(1, min(self.max_years, years_used))
            self.forecast_years = years_used
            
            logger.debug("Years used: %s", years_used)
            
            # Update grids
            self.fin_manager.set_forecast_years(years_used)
            self.fin_manager.fill_grid(
                res.get("financial", {}),
                years_used,
                has_previous
            )
            self.bal_manager.fill_grid(res.get("balance", {}))

            # Show feedback (may include review items)
            self._show_import_feedback(res, has_previous)

        except Exception as e:
            logger.error("Import failed: %s", e)
            import traceback
            if logger.isEnabledFor(logging.DEBUG):
                traceback.print_exc()
            
            self.info_panel.show_message(
                f"✗ Import Failed\nError: {str(e)}",
                "error"
            )
            messagebox.showerror("Import Failed", f"Could not import table:\n{e}")

    # ==================== MULTI-SHEET WORKFLOW ====================
    
    def _start_multi_sheet_scan(self, selected_sheets):
        """Step 3 (Multi): Multiple sheets selected, ask about previous year."""
        self.selected_sheets = selected_sheets
        
        # Show confirmation
        self.info_panel.show_message(
            f"📑 Selected {len(selected_sheets)} sheets for import",
            "info"
        )
        
        # Ask about previous year structure
        self.info_panel.show_yes_no_question(
            question="Does your data include a 'Previous Year' column?",
            on_yes=lambda: self._execute_multi_sheet_scan(True),
            on_no=lambda: self._execute_multi_sheet_scan(False),
            details=[
                "Select YES if your first data column is previous/historical year",
                "Select NO if all columns are forecasts only (Year 1, Year 2, etc.)"
            ]
        )
    
    def _execute_multi_sheet_scan(self, has_previous):
        """Step 4 (Multi): Execute multi-sheet scan and handle results."""
        self.has_previous = has_previous
        
        # Show processing message
        self.info_panel.show_message(
            f"⚙ Scanning {len(self.selected_sheets)} sheets...\nThis may take a moment.",
            "info"
        )
        self.update()  # Force UI update
        
        # Find aliases.json
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        aliases_path = assets_dir / "aliases.json"
        
        if not aliases_path.exists():
            self.info_panel.show_message(
                f"✗ Configuration Error\naliases.json not found at:\n{aliases_path}",
                "error"
            )
            messagebox.showerror(
                "Missing Config",
                f"aliases.json not found at:\n{aliases_path}"
            )
            return
        
        try:
            # Execute multi-sheet scan
            options = {"has_previous_year": has_previous}
            
            scan_result = scan_multiple_sheets(
                path=self.import_path,
                sheet_names=self.selected_sheets,
                aliases_json_path=str(aliases_path),
                options=options
            )
            
            # Store for conflict resolution
            self.last_scan_result = scan_result
            
            # CRITICAL FIX: Check for REVIEW ITEMS FIRST (before conflicts)
            review_items = scan_result.get('review_items', [])
            
            if review_items:
                logger.debug("[GUI] Found %d review items - showing review dialog", len(review_items))
                
                # ✅ CRITICAL FIX: Extract applied_mappings from each sheet's intermediate data
                all_applied_mappings = []
                intermediate_data = scan_result.get('intermediate_data', {})
                
                logger.debug("[GUI] Extracting applied mappings from %d sheets...", len(self.selected_sheets))
                
                for sheet_name in self.selected_sheets:
                    sheet_data = intermediate_data.get(sheet_name, {})
                    
                    # Each sheet's intermediate data now includes 'applied_mappings'
                    sheet_applied = sheet_data.get('applied_mappings', [])
                    
                    if sheet_applied:
                        logger.debug("[GUI]   Sheet '%s': Found %d applied mappings", sheet_name, len(sheet_applied))
                        
                        # Add sheet name to each mapping for tracking which sheet it came from
                        for mapping in sheet_applied:
                            mapping_with_sheet = mapping.copy()
                            mapping_with_sheet['sheet'] = sheet_name
                            all_applied_mappings.append(mapping_with_sheet)
                    else:
                        logger.debug("[GUI]   Sheet '%s': No applied mappings", sheet_name)
                
                logger.debug("[GUI] Total applied mappings extracted: %d", len(all_applied_mappings))
                
                # Show review dialog with applied mappings
                self.info_panel.show_review_table(
                    review_items=review_items,
                    applied_mappings=all_applied_mappings,  # ✅ NOW PASSING THIS!
                    on_apply=lambda selected: self._on_multi_review_applied(selected, scan_result),
                    on_skip=lambda: self._check_conflicts_or_apply(scan_result)
                )
                return  # STOP HERE and wait for user review
            
            # No review items - proceed to conflict check
            self._check_conflicts_or_apply(scan_result)
        
        except Exception as e:
            logger.error("Multi-sheet scan failed: %s", e)
            import traceback
            if logger.isEnabledFor(logging.DEBUG):
                traceback.print_exc()
            
            self.info_panel.show_message(
                f"✗ Multi-Sheet Scan Failed\nError: {str(e)}",
                "error"
            )
            messagebox.showerror("Scan Failed", f"Could not scan sheets:\n{e}")
    
    def _on_multi_review_applied(self, selected_items, scan_result):
        """Step 4.5 (Multi): User approved review items, apply them and continue."""
        if not selected_items:
            # User didn't select anything but clicked Apply - just continue
            self._check_conflicts_or_apply(scan_result)
            return
        
        try:
            from core.multi_sheet_scanner import apply_review_approvals
            from core.number_utils import sum_series, safe_add
            
            logger.debug("[GUI] Applying %d review items", len(selected_items))
            
            # Apply approved review items
            additional_financial, additional_balance = apply_review_approvals(
                scan_result,
                selected_items
            )
            
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[GUI] Review approvals returned:")
                logger.debug("  Financial fields: %s", list(additional_financial.keys()))
                logger.debug("  Balance fields: %s", list(additional_balance.keys()))
            
            # Merge additional data into scan_result
            no_conflict = scan_result.get('no_conflict', {}).copy()
            balance_no_conflict = scan_result.get('balance_no_conflict', {}).copy()
            
            # Merge approved review items into no_conflict data
            for field, values in additional_financial.items():
                if field in no_conflict:
                    logger.debug("[GUI] Merging '%s' with existing data", field)
                    no_conflict[field] = sum_series(no_conflict[field], values)
                else:
                    logger.debug("[GUI] Adding new field '%s'", field)
                    no_conflict[field] = values
            
            for field, value in additional_balance.items():
                if field in balance_no_conflict:
                    logger.debug("[GUI] Merging balance '%s' with existing data", field)
                    balance_no_conflict[field] = safe_add(balance_no_conflict[field], value)
                else:
                    logger.debug("[GUI] Adding new balance field '%s'", field)
                    balance_no_conflict[field] = value
            
            # Update scan_result
            scan_result['no_conflict'] = no_conflict
            scan_result['balance_no_conflict'] = balance_no_conflict
            
            # Update metadata
            metadata = scan_result.get('metadata', {})
            metadata['review_applied_count'] = len(selected_items)
            scan_result['metadata'] = metadata
            
            logger.debug("[GUI] Updated scan_result with %d review items", len(selected_items))
            logger.debug("[GUI] Total fields after merge: %d financial, %d balance",
                       len(no_conflict), len(balance_no_conflict))
            
            # Continue to conflict check
            self._check_conflicts_or_apply(scan_result)
        
        except Exception as e:
            logger.error("Apply review items failed: %s", e)
            import traceback
            if logger.isEnabledFor(logging.DEBUG):
                traceback.print_exc()
            
            self.info_panel.show_message(
                f"✗ Apply Review Failed\nError: {str(e)}",
                "error"
            )
            messagebox.showerror("Apply Failed", f"Could not apply review items:\n{e}")
    
    def _check_conflicts_or_apply(self, scan_result):
        """Step 5 (Multi): Check for conflicts, or apply results if none."""
        conflict_count = scan_result['metadata']['conflict_count']
        
        if conflict_count > 0:
            # Show conflict resolution dialog
            self._show_conflict_resolution(scan_result)
        else:
            # No conflicts - apply results directly
            self._apply_scan_results(scan_result, {})
    
    def _show_conflict_resolution(self, scan_result):
        """Step 5 (Multi): Show conflict resolution dialog."""
        conflicts = scan_result.get('conflicts', {})
        balance_conflicts = scan_result.get('balance_conflicts', {})
        
        # Combine all conflicts
        all_conflicts = {}
        
        # Financial conflicts
        for field, sheet_data in conflicts.items():
            all_conflicts[field] = {
                'type': 'financial',
                'sheets': sheet_data
            }
        
        # Balance conflicts
        for field, sheet_data in balance_conflicts.items():
            all_conflicts[field] = {
                'type': 'balance',
                'sheets': sheet_data
            }
        
        # Show conflict dialog in panel
        self.info_panel.show_conflict_resolution(
            conflicts=all_conflicts,
            on_apply=self._on_conflicts_resolved,
            on_cancel=lambda: self.info_panel.show_message("⚠ Import cancelled", "warning")
        )
    
    def _on_conflicts_resolved(self, user_selections):
        """Step 6 (Multi): User resolved conflicts, apply selections."""
        if not self.last_scan_result:
            self.info_panel.show_message("✗ Error: No scan data available", "error")
            return
        
        try:
            # Apply conflict resolutions
            self._apply_scan_results(self.last_scan_result, user_selections)
            
        except Exception as e:
            logger.error("Apply conflict resolutions failed: %s", e)
            import traceback
            if logger.isEnabledFor(logging.DEBUG):
                traceback.print_exc()
            
            self.info_panel.show_message(
                f"✗ Apply Failed\nError: {str(e)}",
                "error"
            )
            messagebox.showerror("Apply Failed", f"Could not apply selections:\n{e}")
    
    def _apply_scan_results(self, scan_result, user_selections):
        """Step 7 (Multi): Apply scan results and populate grids."""
        # Merge data based on user selections
        merged_fin, merged_bal = apply_conflict_resolutions(
            scan_result, user_selections
        )
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[GUI] Final merged data:")
            logger.debug("  Financial fields: %s", list(merged_fin.keys()))
            logger.debug("  Balance fields: %s", list(merged_bal.keys()))
        
        # Update forecast years
        years_used = scan_result['metadata']['years_used']
        years_used = max(1, min(self.max_years, years_used))
        self.forecast_years = years_used
        
        # Update grids
        self.fin_manager.set_forecast_years(years_used)
        self.fin_manager.fill_grid(merged_fin, years_used, self.has_previous)
        self.bal_manager.fill_grid(merged_bal)
        
        # Show summary
        self._show_scan_summary(scan_result, user_selections)
    
    def _show_scan_summary(self, scan_result, user_selections):
        """Step 8 (Multi): Show final scan summary."""
        summary_messages = format_scan_summary(scan_result, user_selections)
        self.info_panel.show_progress(summary_messages)

    # ==================== SINGLE-SHEET REVIEW (Existing) ====================

    def _show_import_feedback(self, res, has_previous):
        """Step 5: Show import results, potentially trigger review."""
        notes = res.get("notes", [])
        review = res.get("review", [])
        applied = res.get("applied_mappings", [])
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[GUI] _show_import_feedback called")
            logger.debug("Notes: %d, Review: %d, Applied: %d", len(notes), len(review), len(applied))
        
        # If there are review items, show review table in panel WITH applied mappings
        if review:
            self.info_panel.show_review_table(
                review_items=review,
                applied_mappings=applied,  # ✅ PASS auto-applied mappings
                on_apply=lambda selected: self._on_review_applied(selected, has_previous),
                on_skip=lambda: self._show_final_summary(notes, applied)
            )
        else:
            # No review needed - show final summary
            self._show_final_summary(notes, applied)

    def _on_review_applied(self, selected_items, has_previous):
        """Step 6: User selected items from review, apply them."""
        if not self.last_import_result:
            self.info_panel.show_message("✗ Error: No import data available", "error")
            messagebox.showerror("Error", "No import data available for manual mapping.")
            return
        
        intermediate = self.last_import_result.get("intermediate_data", {})
        if not intermediate:
            self.info_panel.show_message("✗ Error: Missing intermediate data", "error")
            messagebox.showerror("Error", "Import data missing intermediate information.")
            return
        
        try:
            from core.field_mapper import apply_manual_mappings
            
            logger.debug("Applying %d manual mappings", len(selected_items))
            
            # Prepare manual mapping list
            manual_mappings = [
                {
                    "source": item["source_label"],
                    "target": item["suggested_target"],
                    "section": item["section"]
                }
                for item in selected_items
            ]
            
            # Apply mappings
            updated_fin, updated_bal = apply_manual_mappings(
                df=intermediate["df"],
                label_col=intermediate["label_col"],
                year_map=intermediate["year_map"],
                years_used=self.last_import_result["years_used"],
                manual_mappings=manual_mappings,
                current_financial=self.last_import_result["financial"],
                current_balance=self.last_import_result["balance"]
            )
            
            # Update stored result
            self.last_import_result["financial"] = updated_fin
            self.last_import_result["balance"] = updated_bal
            
            # Refresh grids
            self.fin_manager.fill_grid(
                updated_fin,
                self.last_import_result["years_used"],
                has_previous
            )
            self.bal_manager.fill_grid(updated_bal)
            
            # Show final summary with review info
            notes = self.last_import_result.get("notes", [])
            applied = self.last_import_result.get("applied_mappings", [])
            
            # Add review confirmation to notes
            notes = list(notes)  # Make a copy
            notes.append(f"✓ Applied {len(manual_mappings)} manual mappings from review")
            
            self._show_final_summary(notes, applied)
            
        except Exception as e:
            logger.error("Apply manual mappings failed: %s", e)
            import traceback
            if logger.isEnabledFor(logging.DEBUG):
                traceback.print_exc()
            
            self.info_panel.show_message(
                f"✗ Apply Failed\nError: {str(e)}",
                "error"
            )
            messagebox.showerror("Apply Failed", f"Could not apply manual mappings:\n{e}")

    def _show_final_summary(self, notes, applied):
        """Step 7: Show final import summary in panel."""
        messages = [
            ("✓ Import Complete!", "success"),
            ("", "info"),
        ]
        
        # Add notes with appropriate styling
        if notes:
            for note in notes:
                note_str = str(note)
                if "warning" in note_str.lower() or "ignored" in note_str.lower():
                    messages.append((f"⚠ {note_str}", "warning"))
                else:
                    messages.append((f"• {note_str}", "info"))
        
        # Add applied mappings summary
        if applied:
            messages.append(("", "info"))
            messages.append((f"✓ Applied {len(applied)} automatic mappings", "success"))
            
            # Show first 5 mappings
            for mapping in applied[:5]:
                source = mapping.get("source", "")
                target = mapping.get("target", "")
                messages.append((f"  {source} → {target}", "info"))
            
            if len(applied) > 5:
                messages.append((f"  ... and {len(applied) - 5} more", "note"))
        
        # Display all messages
        self.info_panel.show_progress(messages)

    # ==================== EXPORT & OTHER ACTIONS ====================

    def _export(self):
        """Export current grid data to the formatted Equidam Excel template."""
        out_path = self.output_path_var.get().strip()
        
        try:
            save_to_template(
                out_path,
                self.fin_manager.get_data(),
                self.bal_manager.get_data(),
                self.forecast_years,
            )
            # Update info panel
            self.info_panel.show_message(
                f"✓ Export Successful!\nSaved to: {out_path}",
                "success"
            )
            
        except Exception as e:
            logger.error("Export failed: %s", e)
            import traceback
            if logger.isEnabledFor(logging.DEBUG):
                traceback.print_exc()
            
            # Update info panel
            self.info_panel.show_message(
                f"✗ Export Failed\nError: {str(e)}",
                "error"
            )
            # Also show popup for critical errors
            messagebox.showerror("Export Failed", f"Error:\n{e}")

def launch_app():
    """Launch the Equidam application."""
    app = EquidamApp()
    app.mainloop()

if __name__ == "__main__":
    launch_app()

