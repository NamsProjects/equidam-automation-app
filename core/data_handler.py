"""
data_handler.py
Writes GUI data into a copy of the official Equidam template
while preserving headers/formatting.

Process:

Loads template: Gets a copy of the official Excel template
Maps rows: Scans column B to find where each financial metric is located (e.g., "Revenue" might be row 15)
Writes Financial Projections:

Clears old data in columns D-I and J
Writes Previous/Current year + up to 5 forecast years
Adds comments in column J

Writes Balance Sheet: Only fills column D (current year) for balance items
Saves the updated workbook

Column mapping (per official template):
  D = 4 : Current or Previous Year
  E = 5 : Year 1
  F = 6 : Year 2
  G = 7 : Year 3
  H = 8 : Year 4
  I = 9 : Year 5
  J = 10: Comments

NOTE: All numbers are coerced to POSITIVE values on export.
"""

from core.template_loader import get_template_copy
from core.number_utils import parse_number_positive

# These labels must match the template exactly
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

# Column indices (1-based, openpyxl style)
COL_PREV_OR_CURRENT = 4  # D
COL_Y1 = 5               # E
COL_Y5 = 9               # I
COL_COMMENTS = 10        # J


def save_to_template(
    output_path: str,
    financial_data: dict,
    balance_data: dict,
    forecast_years: int,
):
    """
    Parameters
    ----------
    output_path : str
        Destination .xlsx path.
    financial_data : dict
        { label: [PrevY, Y1, Y2, Y3, (Y4), (Y5), comment] }
    balance_data : dict
        { label: current_value }
    forecast_years : int
        3..5; how many forecast years are visible in the GUI.
    """

    # 1) Make a working copy of the official template and load it
    wb = get_template_copy(output_path)
    ws = wb.worksheets[0]  # first sheet

    # 2) Build a row lookup by scanning column B for our labels
    row_map = {}
    for r in range(1, ws.max_row + 1):
        val = ws.cell(row=r, column=2).value  # column B has the labels
        txt = (str(val).strip() if val is not None else "")
        if txt in FINANCIAL_ROWS or txt in BALANCE_ROWS:
            row_map[txt] = r

    # 3) Write Financial Projections
    #    Clear D..I and J first for every financial row, then write values.
    for label in FINANCIAL_ROWS:
        r = row_map.get(label)
        if not r:
            continue

        # Clear previous numbers in D..I and comments in J
        for c in range(COL_PREV_OR_CURRENT, COL_Y5 + 1):
            ws.cell(row=r, column=c, value=None)
        ws.cell(row=r, column=COL_COMMENTS, value=None)

        values = financial_data.get(label, [])

        # Write Prev/Current + forecast years
        # index 0 -> col D; 1 -> E; ...; up to 1+forecast_years -> D..(D+forecast_years)
        for i in range(0, forecast_years + 1):  # 0 = Prev/Current
            val = values[i] if i < len(values) else ""
            col = COL_PREV_OR_CURRENT + i
            ws.cell(row=r, column=col, value=_safe_number(val))

        # Comments (last entry in list, appended by GUI)
        if len(values) > forecast_years + 1:
            comment = values[forecast_years + 1]
            ws.cell(row=r, column=COL_COMMENTS, value=str(comment) if comment else None)

    # 4) Write Balance Sheet (current year only, column D)
    for label in BALANCE_ROWS:
        r = row_map.get(label)
        if not r:
            continue
        # Clear any existing value in D
        ws.cell(row=r, column=COL_PREV_OR_CURRENT, value=None)
        val = balance_data.get(label, "")
        ws.cell(row=r, column=COL_PREV_OR_CURRENT, value=_safe_number(val))

    # 5) Save the filled workbook
    wb.save(output_path)


def _safe_number(value):
    """
    Convert user text to a POSITIVE numeric type or None (to leave cell blank).
    Delegates to parse_number_positive for consistent handling across the pipeline.
    """
    result, _ = parse_number_positive(value)
    return result
