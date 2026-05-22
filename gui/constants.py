"""
constants.py
Configuration constants for the Equidam Projections Uploader.
These must match the official Equidam template structure.
"""

# Financial projection row labels (must match Equidam template exactly)
FINANCIAL_ROWS = [
    "Revenue",
    "Costs of Goods Sold",
    "Salaries",
    "Other Operating Expenses",
    "Total Depreciation & Amortization",
    "Interest",
    "Taxes",
    "Receivables",
    "Inventory",
    "Payables",
    "Capital Expenditures",
    "Debt",
    "Fundraising Plan",
]

# Balance sheet row labels (must match Equidam template exactly)
BALANCE_ROWS = [
    "Cash and Cash Equivalents",
    "Non Operating Cash",
    "Tangible Assets",
    "Intangible Assets",
    "Financial Assets",
    "Deferred Tax Assets",
    "Short-term Liabilities",
    "Long-term Liabilities",
    "Equity",
]

# Default forecast configuration
DEFAULT_FORECAST_YEARS = 3
MAX_FORECAST_YEARS = 7

# UI dimensions
DEFAULT_WINDOW_WIDTH = 1080
DEFAULT_WINDOW_HEIGHT = 740
FINANCIAL_GRID_HEIGHT = 340
BALANCE_GRID_HEIGHT = 260

# Grid bindings - what interactions are enabled on the sheets
SHEET_BINDINGS = (
    "single_select",
    "drag_select",
    "column_select",
    "row_select",
    "column_width_resize",
    "double_click_column_resize",
    "row_height_resize",
    "arrowkeys",
    "right_click_popup_menu",
    "copy",
    "paste",
    "cut",
    "undo",
    "redo",
    "edit_cell"
)

# Simplified bindings for balance sheet (no column operations needed)
BALANCE_SHEET_BINDINGS = (
    "single_select",
    "drag_select",
    "copy",
    "paste",
    "cut",
    "arrowkeys",
    "edit_cell",
    "row_height_resize",
    "column_width_resize"
)