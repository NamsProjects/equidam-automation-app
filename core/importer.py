"""
core/importer.py

Orchestrates the import process:
1. Detects aggregate table
2. Maps fields using fuzzy matching
3. Generates audit trail

Return dict:
  financial: {EquidamRow: [Prev, Y1..Yk]}
  balance:   {EquidamBSRow: current_value}
  years_used: int
  review:    [ ... borderline mappings ... ]
  notes:     [ ... human-readable summary of the import ... ]
  applied_mappings: [ ... automatically applied mappings ... ]
  intermediate_data: {df, label_col, year_map} - for manual mapping support

"""

from __future__ import annotations

import json
import traceback
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from core.table_detector import (
    detect_aggregate_table,
    detect_year_columns,
    pick_label_column,
    trim_blank_edges,
    debug_table_detection
)
from core.field_mapper import map_table_rows
from core.logging_config import get_logger

logger = get_logger(__name__)

# ---------------- Canonical Equidam rows (must match the template) ----------------
FINANCIAL_ROWS: List[str] = [
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

BALANCE_ROWS: List[str] = [
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

MAX_FORECAST = 5  # Keep at 5 for now (ignoring y6/y7 support)

@dataclass
class ImportResult:
    financial: Dict[str, List[Optional[float]]]
    balance: Dict[str, Optional[float]]
    years_used: int
    review: List[Dict[str, object]]
    notes: List[str]
    applied_mappings: List[Dict[str, str]]
    intermediate_data: Dict[str, object]

def _empty_result(notes: List[str]) -> dict:
    """Helper to return empty result structure"""
    return {
        "financial": {k: [] for k in FINANCIAL_ROWS},
        "balance": {k: None for k in BALANCE_ROWS},
        "years_used": 1,
        "review": [],
        "notes": notes,
        "applied_mappings": [],
        "intermediate_data": {}
    }

# ---------------------------------- Public API -----------------------------------
def get_excel_sheet_names(path: str) -> List[str]:
    """
    Get list of all sheet names in an Excel file.
    
    Parameters
    ----------
    path : str
        Path to Excel file
    
    Returns
    -------
    List[str]
        List of sheet names, or empty list if not an Excel file or error
    """
    p = Path(path)
    if not p.exists():
        return []
    
    if p.suffix.lower() not in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
        return []  # Not an Excel file
    
    try:
        xl = pd.ExcelFile(p, engine="openpyxl")
        return xl.sheet_names
    except Exception as e:
        logger.error("Could not read Excel file: %s", e)
        return []

def import_any(
    path: str,
    aliases_json_path: str,
    options: Optional[dict] = None
) -> Dict[str, object]:
    """
    Import CSV/XLSX and map to Equidam fields.
    
    Parameters
    ----------
    path : str
        Path to CSV or Excel file
    aliases_json_path : str
        Path to aliases.json configuration
    options : Optional[dict]
        Additional import options:
        - has_previous_year: bool - whether data includes a previous year column
        - sheet_name: str - specific Excel sheet to load
    
    Returns
    -------
    dict
        ImportResult as dict with financial/balance data, audit notes, and intermediate data
    """
    options = options or {}
    has_previous_year = options.get("has_previous_year", False)
    
    try:
        cfg = load_aliases(aliases_json_path)
    except Exception as e:
        logger.error("Failed to load aliases: %s", e)
        return _empty_result([f"Failed to load configuration: {e}"])
    
    # Read file
    df, notes = read_any_table(path, options)
    if df is None or df.empty:
        return _empty_result(notes if notes else ["Empty or unreadable table."])
    
    # DEBUG: Show what we're working with
    logger.info("="*60)
    logger.info("IMPORT - Initial table state")
    logger.info("="*60)
    logger.info("Initial DataFrame shape: %s", df.shape)
    df = debug_table_detection(df)
    
    # Detect aggregate table (handles TOTAL marker or sum-validation)
    try:
        df, header_row_idx, detect_notes = detect_aggregate_table(df, cfg)
        notes.extend(detect_notes)
    except Exception as e:
        logger.error("detect_aggregate_table failed: %s", e)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return _empty_result(notes + [f"Table detection failed: {e}"])
    
    # Safety check after detection
    if df is None or df.empty or len(df) == 0:
        logger.error("DataFrame is empty after aggregate detection")
        return _empty_result(notes + ["No data found after table detection."])
    
    logger.info("="*60)
    logger.info("IMPORT - After aggregate detection")
    logger.info("="*60)
    logger.info("Resulting DataFrame shape: %s", df.shape)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("First 5 rows of detected table:")
        try:
            logger.debug("\n%s", df.head().to_string())
        except Exception as e:
            logger.error("Could not display head: %s", e)
    logger.info("="*60)
    
    # Clean up
    try:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("BEFORE trim_blank_edges:")
            logger.debug("  Shape: %s", df.shape)
            logger.debug("  Columns: %s", df.columns.tolist()[:10])
            logger.debug("  First 3 rows:")
            for i in range(min(3, len(df))):
                logger.debug("    Row %d: %s", i, df.iloc[i, :5].tolist())
        
        df = trim_blank_edges(df)
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("AFTER trim_blank_edges:")
            logger.debug("  Shape: %s", df.shape)
            logger.debug("  Columns: %s", df.columns.tolist()[:10])
            logger.debug("  First 3 rows:")
            for i in range(min(3, len(df))):
                logger.debug("    Row %d: %s", i, df.iloc[i, :5].tolist())
    except Exception as e:
        logger.error("trim_blank_edges failed: %s", e)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return _empty_result(notes + [f"Failed to trim edges: {e}"])
    
    # Safety check after trimming
    if df.empty or len(df) == 0:
        logger.error("DataFrame is empty after trimming blank edges")
        return _empty_result(notes + ["Table became empty after removing blank rows/columns."])
    
    logger.debug("After trimming: %s", df.shape)
    
    # Detect year columns
    try:
        year_map, years_used, year_notes = detect_year_columns(df.columns, cfg)
        notes.extend(year_notes)
    except Exception as e:
        logger.error("detect_year_columns failed: %s", e)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return _empty_result(notes + [f"Year detection failed: {e}"])
    
    # CRITICAL VALIDATION: Ensure y1 exists
    if "y1" not in year_map:
        error_msg = "Year detection failed: Could not identify Year 1 column. Please ensure your data has clear year labels (Y1, Year 1, 2025, etc.)."
        logger.error(error_msg)
        return _empty_result(notes + [error_msg])
    
    # Adjust year mapping based on user selection
    if not has_previous_year and "previous" in year_map:
        # User says no previous year, but the detector mapped one (typically because
        # the system year heuristic flagged e.g. 2025 as "previous" when the user's
        # file actually starts forecasting from 2025).
        #
        # Don't silently drop that column. Shift everything up by one slot so the
        # detected "previous" column becomes y1, the old y1 becomes y2, etc.
        logger.debug("User indicated no previous year - shifting detected columns up by one slot")
        detected_cols = []
        for k in ["previous", "y1", "y2", "y3", "y4", "y5", "y6", "y7"]:
            if k in year_map:
                detected_cols.append(year_map[k])

        new_year_map = {}
        for i, col in enumerate(detected_cols[:5], start=1):
            new_year_map[f"y{i}"] = col

        dropped_cols = detected_cols[5:]
        year_map = new_year_map
        years_used = len(year_map)

        notes.append(
            "No previous year data: reassigned earliest detected column to Year 1 "
            "(no data dropped)."
        )
        if dropped_cols:
            notes.append(
                f"Excluded {len(dropped_cols)} column(s) beyond the 5-year horizon: "
                + ", ".join(str(c) for c in dropped_cols) + "."
            )
        logger.debug("Year map after shift: %s (years_used=%d)", year_map, years_used)
    
    logger.debug("Year mapping: %s", year_map)
    logger.debug("Years used: %s", years_used)
    
    # Pick label column
    try:
        label_col = pick_label_column(df, excluded=set(year_map.values()))
        logger.debug("Label column: '%s'", label_col)
    except Exception as e:
        logger.error("pick_label_column failed: %s", e)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return _empty_result(notes + [f"Label column detection failed: {e}"])
    
    # CRITICAL VALIDATION: Ensure label column is not in year_map
    if label_col in year_map.values():
        error_msg = f"Label column '{label_col}' cannot be a year column. Data structure may be invalid."
        logger.error(error_msg)
        return _empty_result(notes + [error_msg])
    
    # Map fields using fuzzy matching
    try:
        mapping_result = map_table_rows(
            df=df,
            label_col=label_col,
            year_map=year_map,
            years_used=years_used,
            cfg=cfg,
            financial_rows=FINANCIAL_ROWS,
            balance_rows=BALANCE_ROWS
        )
    except Exception as e:
        logger.error("map_table_rows failed: %s", e)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return _empty_result(notes + [f"Field mapping failed: {e}"])
    
    # Extract mapping results
    financial_accum = mapping_result['financial']
    balance_values = mapping_result['balance']
    review = mapping_result['review']
    auto_map_log = mapping_result['auto_map_log']
    aggregated_into = mapping_result['aggregated_into']
    ignored_labels = mapping_result['ignored_labels']
    coerced_negatives = mapping_result['coerced_negatives']
    
    # ---------------------- Build applied mappings list ----------------------
    applied_mappings = []
    for source_label, target_label, section in auto_map_log:
        # Convert section to readable string
        section_name = section if isinstance(section, str) else "Unknown"
        applied_mappings.append({
            "source": source_label,
            "target": target_label,
            "section": section_name
        })
    
    # ---------------------- Build human-readable notes ----------------------
    
    # Year mapping summary
    yr_parts = []
    for k in ["previous", "y1", "y2", "y3", "y4", "y5"]:
        if k in year_map:
            yr_parts.append(f"{k.title().replace('Y', 'Y ')} → {year_map[k]}")
    if yr_parts:
        notes.append("Year mapping: " + "; ".join(yr_parts) + ".")
    
    # Aggregation summary
    if aggregated_into:
        for tgt, sources in aggregated_into.items():
            # Collapse to unique sources, keep order
            seen, uniq = set(), []
            for s in sources:
                if s not in seen:
                    seen.add(s)
                    uniq.append(s)
            notes.append(
                f"Aggregated {len(uniq)} rows into '{tgt}': " + ", ".join(uniq) + "."
            )
    
    # Ignored rows summary
    if ignored_labels:
        preview = ", ".join(list(dict.fromkeys(ignored_labels))[:8])
        more = f" (+{len(ignored_labels)-8} more)" if len(ignored_labels) > 8 else ""
        notes.append(
            f"Ignored {len(ignored_labels)} non-mapped rows "
            f"(e.g., KPIs like Gross Profit/EBITDA): {preview}{more}."
        )
    
    # Auto-map coverage
    if auto_map_log:
        notes.append(f"Applied {len(auto_map_log)} automatic mappings (see table).")
    
    # Negatives coerced
    if coerced_negatives:
        notes.append(f"Converted {coerced_negatives} negative entries to positive.")
    
    # Ensure at least one note
    if not notes:
        notes.append("Imported table and applied mappings (no warnings).")
    
    # Pad/ensure ordering - adjust based on whether previous year exists
    financial_ordered: Dict[str, List[Optional[float]]] = {}
    for k in FINANCIAL_ROWS:
        if has_previous_year:
            # Include previous year: [prev, y1, y2, y3, ...]
            arr = financial_accum.get(k, [None] * (1 + years_used))
            arr = (arr + [None] * (1 + years_used))[: (1 + years_used)]
        else:
            # No previous year: just [y1, y2, y3, ...]
            arr = financial_accum.get(k, [None] * years_used)
            arr = (arr + [None] * years_used)[:years_used]
        financial_ordered[k] = arr
    
    return ImportResult(
        financial=financial_ordered,
        balance=balance_values,
        years_used=years_used,
        review=review,
        notes=notes,
        applied_mappings=applied_mappings,
        intermediate_data={
            "df": df.copy(),  # Make a copy to preserve data
            "label_col": label_col,
            "year_map": year_map.copy(),
            "has_previous_year": has_previous_year
        }
    ).__dict__

# ------------------------------- Internal helpers --------------------------------
def load_aliases(path: str) -> dict:
    """Load aliases.json configuration."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"aliases.json not found at: {path}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def read_any_table(path: str, options: dict):
    """
    Read CSV or Excel file into DataFrame.
    
    Parameters
    ----------
    path : str
        File path
    options : dict
        May contain 'sheet_name' for Excel files
    
    Returns
    -------
    Tuple[Optional[pd.DataFrame], List[str]]
        (dataframe, notes)
    """
    notes: List[str] = []
    p = Path(path)
    if not p.exists():
        return None, [f"File not found: {path}"]
    
    try:
        if p.suffix.lower() in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
            xl = pd.ExcelFile(p, engine="openpyxl")
            
            # Check if user specified a sheet
            sheet_name = options.get("sheet_name")
            
            if sheet_name:
                # User selected a specific sheet
                if sheet_name not in xl.sheet_names:
                    return None, [f"Sheet '{sheet_name}' not found in workbook."]
                df = xl.parse(sheet_name, header=None)
                notes.append(f"Loaded sheet: {sheet_name}")
            else:
                # Fallback: auto-select first non-empty sheet
                sheet_name = None
                for sh in xl.sheet_names:
                    tmp = xl.parse(sh, header=None)
                    if tmp.dropna(how="all").dropna(axis=1, how="all").shape[0] > 0:
                        sheet_name = sh
                        break
                
                if sheet_name is None:
                    return None, ["Workbook has no non-empty sheets."]
                
                df = xl.parse(sheet_name, header=None)
                notes.append(f"Auto-selected sheet: {sheet_name}")
        else:
            # CSV file
            df = pd.read_csv(p, header=None, sep=None, engine="python")
            notes.append("Loaded CSV.")
        
        return df, notes
    except Exception as e:
        return None, [f"Failed to read file: {e}"]