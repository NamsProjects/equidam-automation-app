"""
core/sheet_scanner.py

Scans Excel sheets to detect which contain financial/balance data.
Used for multi-sheet import workflow.
"""

from pathlib import Path
from typing import Dict, List, Tuple
import pandas as pd

from core.importer import load_aliases, read_any_table
from core.table_detector import (
    detect_aggregate_table,
    detect_year_columns,
    pick_label_column,
    trim_blank_edges
)
from core.field_mapper_utils import make_normalizer, fuzzy_best


def scan_all_sheets(file_path: str, aliases_json_path: str) -> Dict[str, Dict]:
    """
    Scan all sheets in an Excel file and detect which contain financial data.
    
    Parameters
    ----------
    file_path : str
        Path to Excel file
    aliases_json_path : str
        Path to aliases.json
    
    Returns
    -------
    Dict[str, Dict]
        {
            sheet_name: {
                'detected_fields': [list of detected field names],
                'field_count': int,
                'has_data': bool
            }
        }
    """
    from core.importer import FINANCIAL_ROWS, BALANCE_ROWS
    
    # Load configuration
    try:
        cfg = load_aliases(aliases_json_path)
    except Exception as e:
        print(f"[ERROR] Failed to load aliases: {e}")
        return {}
    
    # Get all sheet names
    p = Path(file_path)
    if p.suffix.lower() not in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
        return {}  # Not Excel - can't scan multiple sheets
    
    try:
        xl = pd.ExcelFile(p, engine="openpyxl")
        sheet_names = xl.sheet_names
    except Exception as e:
        print(f"[ERROR] Could not read Excel file: {e}")
        return {}
    
    print(f"\n[SCANNER] Scanning {len(sheet_names)} sheets...")
    
    results = {}
    
    for sheet_name in sheet_names:
        print(f"\n[SCANNER] Analyzing sheet: {sheet_name}")
        
        try:
            # Read sheet
            df = xl.parse(sheet_name, header=None)
            
            if df.empty or df.dropna(how='all').empty:
                print(f"[SCANNER]   → Empty sheet, skipping")
                results[sheet_name] = {
                    'detected_fields': [],
                    'field_count': 0,
                    'has_data': False
                }
                continue
            
            # Try to detect fields
            detected = scan_sheet_for_fields(
                df=df,
                cfg=cfg,
                financial_rows=FINANCIAL_ROWS,
                balance_rows=BALANCE_ROWS
            )
            
            results[sheet_name] = detected
            
            if detected['has_data']:
                print(f"[SCANNER]   ✓ Found {detected['field_count']} fields: {', '.join(detected['detected_fields'][:5])}")
                if len(detected['detected_fields']) > 5:
                    print(f"[SCANNER]     ... and {len(detected['detected_fields']) - 5} more")
            else:
                print(f"[SCANNER]   → No relevant financial data")
        
        except Exception as e:
            print(f"[SCANNER]   → Error scanning sheet: {e}")
            results[sheet_name] = {
                'detected_fields': [],
                'field_count': 0,
                'has_data': False
            }
    
    return results


def scan_sheet_for_fields(
    df: pd.DataFrame,
    cfg: dict,
    financial_rows: List[str],
    balance_rows: List[str]
) -> Dict:
    """
    Scan a single sheet and detect which financial/balance fields it contains.
    
    Parameters
    ----------
    df : pd.DataFrame
        Raw sheet data
    cfg : dict
        Configuration from aliases.json
    financial_rows : List[str]
        Canonical financial field names
    balance_rows : List[str]
        Canonical balance field names
    
    Returns
    -------
    Dict
        {
            'detected_fields': [list of field names],
            'field_count': int,
            'has_data': bool
        }
    """
    try:
        # Process sheet (same as normal import)
        df, _, _ = detect_aggregate_table(df, cfg)
        df = trim_blank_edges(df)
        
        if df.empty:
            return {'detected_fields': [], 'field_count': 0, 'has_data': False}
        
        # Detect year columns
        year_map, years_used, _ = detect_year_columns(df.columns, cfg)
        
        # Pick label column
        label_col = pick_label_column(df, excluded=set(year_map.values()))
        
        # Setup normalizer
        normalizer = make_normalizer(cfg.get("normalize", {}))
        
        # Prepare targets
        all_targets = financial_rows + balance_rows
        targets_norm = [(t, normalizer(t)) for t in all_targets]
        
        # Scan rows and match to known fields
        detected_fields = []
        
        for _, row in df.iterrows():
            raw_label = str(row.get(label_col, "")).strip()
            if not raw_label or raw_label.lower() == "nan":
                continue
            
            norm_label = normalizer(raw_label)
            
            # Try fuzzy match
            best_match, score = fuzzy_best(norm_label, targets_norm)
            
            # Accept if score is decent (lower threshold for scanning)
            if score >= 70 and best_match not in detected_fields:
                detected_fields.append(best_match)
        
        return {
            'detected_fields': detected_fields,
            'field_count': len(detected_fields),
            'has_data': len(detected_fields) > 0
        }
    
    except Exception as e:
        print(f"[SCANNER ERROR] {e}")
        return {'detected_fields': [], 'field_count': 0, 'has_data': False}