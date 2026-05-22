"""
grid_manager.py
Managers for Financial and Balance Sheet grid operations.
Handles data manipulation, display, and interaction with tksheet grids.
"""

import tkinter.font as tkfont

from tkinter import ttk, messagebox
from tksheet import Sheet

from gui.constants import (
    FINANCIAL_GRID_HEIGHT,
    BALANCE_GRID_HEIGHT,
    SHEET_BINDINGS,
    BALANCE_SHEET_BINDINGS
)

# Per-column widths used to size the table widgets to their actual content
# (otherwise tksheet leaves blank space on the right of the columns).
_DATA_COL_WIDTH = 120
_BALANCE_DATA_COL_WIDTH = 140
_WIDGET_PADDING = 12   # small allowance for borders / gutter
_INDEX_CELL_PAD = 28   # cell-internal padding around the row-index label
_BALANCE_WIDGET_MIN_WIDTH = 440


def _compute_index_width(labels):
    """Pixel width to fit the widest row label, with cell padding."""
    try:
        f = tkfont.nametofont("TkDefaultFont")
        max_w = max(f.measure(str(lbl)) for lbl in labels)
    except Exception:
        # Fallback: rough monospace estimate
        max_w = max(len(str(lbl)) for lbl in labels) * 8
    return max_w + _INDEX_CELL_PAD


def _financial_width(years, index_w):
    """Pixel width that fits the financial table exactly for N forecast years.
    Columns are: Prev Y + Year 1..N + Comments  (= 2 + years data columns)."""
    return index_w + _DATA_COL_WIDTH * (2 + years) + _WIDGET_PADDING


def _balance_width(index_w):
    """Pixel width that fits the balance table (index + single data column)."""
    return max(
        _BALANCE_WIDGET_MIN_WIDTH,
        index_w + _BALANCE_DATA_COL_WIDTH + _WIDGET_PADDING,
    )


class FinancialGridManager:
    """
    Manages the Financial Projections grid.
    Handles column management, data filling, and retrieval.
    """
    
    def __init__(self, parent, row_labels, forecast_years):
        """
        Initialize the financial grid.
        
        Args:
            parent: Parent tkinter widget
            row_labels: List of row label strings
            forecast_years: Initial number of forecast year columns
        """
        self.row_labels = row_labels
        self.forecast_years = forecast_years
        
        # Create the container frame with fixed width
        self.frame = ttk.LabelFrame(parent, text="Financial projections to input into Equidam")
        self.frame.pack(fill="none", padx=10, pady=10, anchor="w")

        # Build initial headers
        headers = self._build_headers(forecast_years)

        # Auto-size the row-index column to the widest label
        self._index_w = _compute_index_width(row_labels)

        # Create the sheet sized to fit current columns; scrollbars hidden
        # because the row count is fixed and small enough to fit the height.
        self.sheet = Sheet(
            self.frame,
            total_rows=len(row_labels),
            total_columns=len(headers),
            headers=headers,
            row_index=row_labels,
            theme="light",
            height=FINANCIAL_GRID_HEIGHT,
            width=_financial_width(forecast_years, self._index_w),
            default_row_index_width=self._index_w,
            row_index_width=self._index_w,
            show_x_scrollbar=False,
            show_y_scrollbar=False,
        )
        self.sheet.enable_bindings(SHEET_BINDINGS)
        # Prevent paste from auto-extending the sheet beyond the header count,
        # which would leave unlabeled columns (H, I, J, ...) and push the
        # adjacent Balance Sheet panel off-screen.
        try:
            self.sheet.set_options(expand_sheet_if_paste_too_big=False)
        except Exception:
            pass
        self.sheet.pack(fill="both", expand=True)

    def _trim_to_headers(self, target_cols):
        """Delete any columns beyond target_cols (safety net for paste/etc)."""
        while self.sheet.total_columns() > target_cols:
            self.sheet.delete_column(self.sheet.total_columns() - 1)

    def _build_headers(self, years):
        """Build column headers based on number of forecast years."""
        return ["Prev Y"] + [f"Year {i}" for i in range(1, years + 1)] + ["Comments"]
    
    def set_forecast_years(self, years):
        """
        Update the number of forecast year columns.
        
        Args:
            years: New number of forecast years (1-5)
        """
        self.forecast_years = years
        headers = self._build_headers(years)
        current_cols = self.sheet.total_columns()
        target_cols = len(headers)

        if target_cols > current_cols:
            for _ in range(target_cols - current_cols):
                self.sheet.insert_column(self.sheet.total_columns())
        elif target_cols < current_cols:
            self._trim_to_headers(target_cols)

        self.sheet.headers(headers)

        # Grow/shrink the widget to match the new column count so we don't
        # leave blank space on the right (or clip the rightmost column).
        new_width = _financial_width(years, self._index_w)
        try:
            self.sheet.config(width=new_width)
        except Exception:
            pass

        self.sheet.refresh()
    
    def fill_grid(self, financial_dict, years_used, has_previous):
        """
        Fill the grid with imported financial data.
        
        Args:
            financial_dict: Dict mapping row labels to value lists
            years_used: Number of years in the data
            has_previous: Whether data includes a previous year column
        """
        # Safety net: a paste (or other tksheet op) could have extended the
        # sheet past our header count. Trim back before filling so we never
        # leave stray columns labelled H/I/J/... behind.
        self._trim_to_headers(len(self.sheet.headers()))

        rows = self.sheet.total_rows()
        cols = self.sheet.total_columns()

        for r, label in enumerate(self.row_labels):
            # Clear the row first
            for c in range(cols):
                self.sheet.set_cell_data(r, c, "")
            
            values = financial_dict.get(label, [])
            
            # Skip if values is None or empty
            if values is None:
                continue
            
            # Ensure values is a list
            if not isinstance(values, list):
                values = [values]
            
            if has_previous:
                # Data includes previous year: [prev, y1, y2, y3, ...]
                # Map directly to columns: [0(Prev Y), 1(Year 1), 2(Year 2), ...]
                for i in range(min(len(values), cols - 1)):  # -1 for comments column
                    val = values[i] if i < len(values) else None
                    self.sheet.set_cell_data(r, i, "" if val is None else str(val))
            else:
                # No previous year: [y1, y2, y3, y4, ...]
                # Skip column 0 (Prev Y), map to columns: [1(Year 1), 2(Year 2), ...]
                for i in range(min(len(values), years_used)):
                    val = values[i] if i < len(values) else None
                    col_idx = i + 1  # values[0](Y1) -> col 1
                    if col_idx < cols - 1:  # -1 for comments column
                        self.sheet.set_cell_data(r, col_idx, "" if val is None else str(val))
        
        self.sheet.refresh()
    
    def clear_grid(self):
        """Clear all values from the grid."""
        try:
            rows = self.sheet.total_rows()
            cols = self.sheet.total_columns()
            for r in range(rows):
                for c in range(cols):
                    self.sheet.set_cell_data(r, c, "")
            self.sheet.refresh()
        except Exception as e:
            messagebox.showwarning(
                "Clear Financial Failed", 
                f"Could not clear Financial grid:\n{e}"
            )
    
    def get_data(self):
        """
        Retrieve all data from the grid.
        
        Returns:
            Dict mapping row labels to lists of column values
        """
        try:
            data_matrix = self.sheet.get_sheet_data(return_copy=True)
        except TypeError:
            # Fallback for older tksheet versions
            data_matrix = [list(r) for r in self.sheet.get_sheet_data()]
        
        headers = list(self.sheet.headers())
        target_len = len(headers)
        
        out = {}
        for r, label in enumerate(self.row_labels):
            row_vals = data_matrix[r] if r < len(data_matrix) else []
            # Pad to target length
            row_vals = (row_vals + [""] * target_len)[:target_len]
            out[label] = row_vals
        
        return out


class BalanceGridManager:
    """
    Manages the Balance Sheet grid.
    Simpler than financial grid - single column only.
    """
    
    def __init__(self, parent, row_labels):
        """
        Initialize the balance sheet grid.
        
        Args:
            parent: Parent tkinter widget
            row_labels: List of row label strings
        """
        self.row_labels = row_labels
        
        # Create the container frame with fixed width
        self.frame = ttk.LabelFrame(parent, text="Balance Sheet (Current Year Only)")
        self.frame.pack(fill="none", padx=10, pady=10, anchor="w")

        # Auto-size the row-index column to the widest label
        self._index_w = _compute_index_width(row_labels)

        # Create the sheet (single column) sized to fit; scrollbars hidden
        # because the row count is fixed and fits the height.
        self.sheet = Sheet(
            self.frame,
            total_rows=len(row_labels),
            total_columns=1,
            headers=["Current"],
            row_index=row_labels,
            theme="light",
            height=BALANCE_GRID_HEIGHT,
            width=_balance_width(self._index_w),
            default_row_index_width=self._index_w,
            row_index_width=self._index_w,
            show_x_scrollbar=False,
            show_y_scrollbar=False,
        )
        self.sheet.enable_bindings(BALANCE_SHEET_BINDINGS)
        try:
            self.sheet.set_index_width(self._index_w, redraw=False)
            self.sheet.column_width(0, width=_BALANCE_DATA_COL_WIDTH, redraw=False)
        except Exception:
            pass
        self.sheet.pack(fill="both", expand=True)
    
    def fill_grid(self, balance_dict):
        """
        Fill the grid with balance sheet data.
        
        Args:
            balance_dict: Dict mapping row labels to single values
        """
        rows = self.sheet.total_rows()
        for r, label in enumerate(self.row_labels):
            val = balance_dict.get(label, None)
            self.sheet.set_cell_data(r, 0, "" if val is None else str(val))
        self.sheet.refresh()
    
    def clear_grid(self):
        """Clear all values from the grid."""
        try:
            rows = self.sheet.total_rows()
            cols = self.sheet.total_columns()
            for r in range(rows):
                for c in range(cols):
                    self.sheet.set_cell_data(r, c, "")
            self.sheet.refresh()
        except Exception as e:
            messagebox.showwarning(
                "Clear Balance Failed", 
                f"Could not clear Balance grid:\n{e}"
            )
    
    def get_data(self):
        """
        Retrieve all data from the grid.
        
        Returns:
            Dict mapping row labels to single values
        """
        try:
            data_matrix = self.sheet.get_sheet_data(return_copy=True)
        except TypeError:
            # Fallback for older tksheet versions
            data_matrix = [list(r) for r in self.sheet.get_sheet_data()]
        
        out = {}
        for r, label in enumerate(self.row_labels):
            val = ""
            if r < len(data_matrix) and len(data_matrix[r]) > 0:
                val = data_matrix[r][0]
            out[label] = val
        
        return out
