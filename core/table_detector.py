"""
core/table_detector.py

Detects aggregate/TOTAL tables in multi-table spreadsheets.
Handles both column-based and row-based year layouts.
"""

from typing import Dict, List, Tuple, Optional
import re
import pandas as pd
from unidecode import unidecode
import datetime
import logging

from core.number_utils import looks_like_text, looks_like_year
from core.logging_config import get_logger

logger = get_logger(__name__)

def debug_table_detection(df: pd.DataFrame):
    """Temporary debug helper - logs what the detector sees"""
    if not logger.isEnabledFor(logging.DEBUG):
        return df
    
    logger.debug("=== TABLE DETECTION DEBUG ===")
    logger.debug("DataFrame shape: %s", df.shape)
    logger.debug("Column names: %s", df.columns.tolist()[:10])
    
    logger.debug("First 30 rows, first 3 columns:")
    for idx in range(min(30, len(df))):
        row_preview = [str(df.iloc[idx, c])[:30] for c in range(min(3, len(df.columns)))]
        logger.debug("  Row %d: %s", idx, row_preview)
    
    logger.debug("Searching for TOTAL markers in first column...")
    total_keywords = ["total", "totals", "sum", "aggregate", "consolidated"]
    first_col_lower = df.iloc[:, 0].astype(str).str.strip().str.lower()
    
    for idx, val in first_col_lower.items():
        if any(kw in val for kw in total_keywords):
            logger.debug("  ✓ Found TOTAL marker: '%s' at row %d", val, idx)
    
    logger.debug("=== END DEBUG ===")
    return df

def detect_aggregate_table(df: pd.DataFrame, cfg: dict) -> Tuple[pd.DataFrame, int, List[str]]:
    """
    Find and extract the aggregate/TOTAL table from a multi-table sheet.
    
    Strategy:
    1. Look for standalone "TOTAL" marker in RAW data FIRST
    2. If found, extract that section, THEN orient it
    3. If not found, orient whole table and use it
    
    Parameters
    ----------
    df : pd.DataFrame
        Raw imported DataFrame (no header yet)
    cfg : dict
        Configuration from aliases.json
    
    Returns
    -------
    Tuple[pd.DataFrame, int, List[str]]
        (detected_table, header_row_index, notes)
    """
    notes: List[str] = []

    # STEP 0: Drop section-sentinel rows (e.g., col 0 == 'X' marking a section break
    # in stacked multi-table sheets). These cause "Total Revenue" / "Total COGS"
    # to be summed multiple times when the same label appears in several sub-sections.
    if len(df) > 0 and len(df.columns) > 0:
        first_col_clean = df.iloc[:, 0].astype(str).str.strip().str.lower()
        sentinel_mask = first_col_clean.isin(['x', '*', '##'])
        n_sentinels = int(sentinel_mask.sum())
        if n_sentinels > 0:
            logger.debug("Dropping %d section-sentinel rows (col 0 in {'x','*','##'})", n_sentinels)
            df = df.loc[~sentinel_mask].reset_index(drop=True)
            notes.append(f"Removed {n_sentinels} section-sentinel row(s) from col 0.")

    # STEP 1: Look for TOTAL in RAW data BEFORE any orientation
    total_start, total_end = find_total_in_raw_data(df)
    
    if total_start is not None:
        logger.debug("Found TOTAL in raw data at rows %d-%d", total_start, total_end)
        # Extract just the TOTAL section from raw data
        df_section = df.iloc[total_start:total_end, :].copy().reset_index(drop=True)
        notes.append(f"Found 'TOTAL' section at raw row {total_start}.")
        
        # NOW orient this section
        df_oriented, header_idx, orient_note = detect_header_and_orient(df_section)
        if orient_note:
            notes.append(orient_note)
        
        return df_oriented, header_idx, notes
    
    # STEP 2: No TOTAL in raw data - orient whole table
    logger.debug("No TOTAL in raw data, orienting whole table")
    df_oriented, header_idx, orient_note = detect_header_and_orient(df)
    if orient_note:
        notes.append(orient_note)
    
    notes.append("No aggregate TOTAL section found; using entire table.")
    return df_oriented, header_idx, notes

def find_total_in_raw_data(df: pd.DataFrame) -> Tuple[Optional[int], Optional[int]]:
    """
    Find standalone "TOTAL" marker in raw data before any processing.
    
    Returns (start_row, end_row) of TOTAL section, or (None, None).
    """
    total_keywords = ["total", "totals", "aggregate", "consolidated"]
    
    # Search first 3 columns for exact TOTAL keyword
    for col_idx in range(min(3, len(df.columns))):
        col_values = df.iloc[:, col_idx].astype(str).str.strip().str.lower()
        
        for idx, val in col_values.items():
            # Must be EXACTLY the keyword (not "Total Revenue")
            if val in total_keywords:
                logger.debug("Found exact TOTAL keyword '%s' at raw row %d, col %d", val, idx, col_idx)
                
                # Verify it's a section header (rest of row mostly empty)
                row_vals = df.iloc[idx, 1:].astype(str).str.strip()
                non_empty = sum(1 for v in row_vals if v and v.lower() != 'nan')
                
                if non_empty > 1:
                    logger.debug("Not a section header - has %d values", non_empty)
                    continue
                
                # Found it! Extract from next row onward
                start_idx = idx + 1
                end_idx = len(df)
                
                # Find section end
                for next_idx in range(start_idx, min(start_idx + 50, len(df))):
                    next_val = str(df.iloc[next_idx, col_idx]).strip().lower()
                    
                    # Empty rows indicate end
                    if next_val == '' or next_val == 'nan':
                        # Check if next 2 rows also empty
                        if next_idx < len(df) - 1:
                            this_empty = df.iloc[next_idx, :].astype(str).str.strip().isin(['', 'nan']).all()
                            if this_empty:
                                end_idx = next_idx
                                logger.debug("Section ends at row %d (empty)", end_idx)
                                break
                    
                    # Another section header (text-only, no numbers)
                    elif looks_like_text(next_val) and not any(c.isdigit() for c in next_val):
                        row_vals = df.iloc[next_idx, :].astype(str).str.strip()
                        non_empty = sum(1 for v in row_vals if v and v.lower() != 'nan')
                        if non_empty <= 2:
                            end_idx = next_idx
                            logger.debug("Section ends at row %d (next section)", end_idx)
                            break
                
                return start_idx, end_idx
    
    logger.debug("No standalone TOTAL found in raw data")
    return None, None

def detect_orientation(df: pd.DataFrame) -> Tuple[bool, str]:
    """
    Detect if years are in rows (vertical) or columns (horizontal).
    
    NOTE: This function expects the header to already be set as column names.
    
    Returns (needs_transpose, description)
    
    IMPROVED: Now checks column headers FIRST before checking data values.
    This prevents false positives where horizontal data is detected as vertical.
    """
    year_patterns = [
        r'y\s*[1-7]',
        r'year\s*[1-7]',
        r'20[0-9]{2}',
        r'19[0-9]{2}',
        r'previous',
        r'prev'
    ]
    
    # PRIORITY CHECK #1: Look for "Year 1", "Year 2", "Year 3" etc. in COLUMN HEADERS
    # If found, this is HORIZONTAL layout (years already as columns) - NO TRANSPOSE NEEDED
    logger.debug("PRIORITY CHECK #1: Checking for year patterns in column headers...")
    year_col_count = 0
    year_cols_found = []
    for col_name in df.columns:
        col_str = str(col_name).strip().lower()
        # Match "year 1", "year 2", "y1", "y2", or absolute years like "2025", "2026E"
        if (re.search(r'year\s*[1-7]', col_str) or
            re.search(r'y\s*[1-7]', col_str) or
            re.search(r'20[0-9]{2}', col_str)):
            year_col_count += 1
            year_cols_found.append(str(col_name))
    
    if year_col_count >= 2:
        logger.debug("✓ Found %d year columns in headers: %s", year_col_count, year_cols_found[:5])
        logger.debug("HORIZONTAL layout detected - years are already column headers")
        return False, "Years in columns (detected year headers) - no transpose needed"
    
    logger.debug("Only found %d year column(s) in headers - not conclusive", year_col_count)
    
    # PRIORITY CHECK #2: Look for "Year" column with Y1, Y2, Y3 as VALUES
    # This is the most reliable indicator of VERTICAL orientation
    logger.debug("PRIORITY CHECK #2: Checking for 'Year' column with year values...")
    for c in range(min(3, len(df.columns))):
        col_header = str(df.columns[c]).strip().lower()
        if 'year' in col_header:
            # Check if this column has Y1, Y2, Y3 as values
            col_vals = df.iloc[:, c].astype(str).str.strip().str.lower()
            year_value_count = sum(1 for v in col_vals if re.search(r'y\s*[1-7]', v))
            if year_value_count >= 2:
                logger.debug("✓ Found 'Year' column '%s' with Y1/Y2/Y3 values", df.columns[c])
                logger.debug("VERTICAL layout detected - need to transpose")
                return True, "Years in rows (detected 'Year' column with Y values) - transposed to columns"
    
    logger.debug("No 'Year' column with year values found")
    
    # Fallback: Score-based detection (only if priority checks are inconclusive)
    logger.debug("FALLBACK: Using score-based detection...")
    horizontal_score = 0
    for r in range(min(10, len(df))):
        row_vals = [str(v).strip().lower() for v in df.iloc[r, :]]
        year_cols = []
        
        for col_idx, val in enumerate(row_vals):
            if any(re.search(p, val, re.IGNORECASE) for p in year_patterns):
                year_cols.append(col_idx)
        
        if len(year_cols) >= 2:
            for i in range(len(year_cols) - 1):
                gap = year_cols[i+1] - year_cols[i]
                if gap <= 2:
                    horizontal_score += 1
    
    vertical_score = 0
    for c in range(min(5, len(df.columns))):
        col_vals = [str(v).strip().lower() for v in df.iloc[:, c]]
        year_rows = []
        
        for row_idx, val in enumerate(col_vals):
            if any(re.search(p, val, re.IGNORECASE) for p in year_patterns):
                year_rows.append(row_idx)
        
        if len(year_rows) >= 2:
            for i in range(len(year_rows) - 1):
                gap = year_rows[i+1] - year_rows[i]
                if gap <= 2:
                    vertical_score += 1
    
    logger.debug("Orientation scores - Horizontal: %d, Vertical: %d", horizontal_score, vertical_score)
    
    if vertical_score > horizontal_score:
        return True, "Years in rows (vertical layout) - transposed to columns"
    else:
        return False, "Years in columns (horizontal layout)"

def detect_header_and_orient(df: pd.DataFrame) -> Tuple[pd.DataFrame, int, str]:
    """Detect header row and transpose if needed. Handles sub-header labels like 'Last year'."""
    
    # STEP 1: Find header row FIRST
    top = min(10, len(df))
    best_idx, best_score = 0, -1
    
    for r in range(top):
        row = df.iloc[r, :]
        txt_cnt = sum(looks_like_text(x) for x in row)
        yr_cnt = sum(looks_like_year(x) for x in row)
        uniq_cnt = len(set(str(x).strip().lower() for x in row if str(x).strip() != ""))
        score = txt_cnt + 1.5 * yr_cnt + 0.2 * uniq_cnt
        if score > best_score:
            best_score = score
            best_idx = r
    
    logger.debug("Header at row %d", best_idx)
    
    # STEP 2: Set the header
    df2 = df.copy()
    df2.columns = [str(c) for c in df2.iloc[best_idx, :].tolist()]
    df2 = df2.iloc[best_idx + 1:, :].reset_index(drop=True)
    df2 = make_columns_unique(df2)
    
    logger.debug("Columns after setting header: %s", df2.columns.tolist()[:10])
    
    # STEP 2.5: Check for "Last year" in BOTH column headers AND first data row
    previous_year_indicators = ['last year', 'lastyear', 'previous year', 'prior year', 'actual', 'last yr']
    marked_column = None
    
    # Strategy 1: Check column headers directly (handles case where "Last year" IS the header)
    for col_idx, col_name in enumerate(df2.columns):
        col_name_lower = str(col_name).strip().lower()
        col_name_lower = re.sub(r'\s+', ' ', col_name_lower)
        if any(indicator in col_name_lower for indicator in previous_year_indicators):
            marked_column = col_idx
            logger.debug("Found '%s' as column header at index %d - marking as previous year", col_name, col_idx)
            break
    
    # Strategy 2: Check first data row for "Last year" label (handles sub-header case)
    if marked_column is None and len(df2) > 0:
        first_row = df2.iloc[0, :]
        logger.debug("Checking first data row for 'Last year' indicator...")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("First row values: %s", [str(v)[:30] for v in first_row])
        
        for col_idx, val in enumerate(first_row):
            val_str = str(val).strip().lower()
            val_str = re.sub(r'\s+', ' ', val_str)
            
            if any(indicator in val_str for indicator in previous_year_indicators):
                marked_column = col_idx
                logger.debug("✓ Found '%s' in first data row at col %d - marking as previous year", val, col_idx)
                # Remove this sub-header row since it's not actual data
                df2 = df2.iloc[1:, :].reset_index(drop=True)
                break
        
        if marked_column is None:
            logger.debug("No 'Last year' indicator found in first data row")
    
    # If we found a "Last year" column, mark it BEFORE detecting orientation
    marked_col_name = None
    if marked_column is not None:
        old_col_name = df2.columns[marked_column]
        new_col_name = f"PREVIOUS_YEAR_MARKER_{old_col_name}"
        df2.columns.values[marked_column] = new_col_name
        marked_col_name = new_col_name
        logger.debug("✓ Renamed column %d from '%s' to '%s'", marked_column, old_col_name, new_col_name)
    else:
        logger.debug("No previous year column was marked")
    
    logger.debug("Columns after marking: %s", df2.columns.tolist()[:10])
    
    # STEP 3: NOW detect orientation (with proper column names)
    needs_transpose, orientation_msg = detect_orientation(df2)
    logger.debug("%s", orientation_msg)
    
    # STEP 4: Transpose if needed - CORRECTED DOUBLE TRANSPOSE for vertical layouts
    note = ""
    if needs_transpose:
        logger.debug("Performing CORRECTED double transpose for vertical layout...")
        
        # Save which column has the marker
        marker_index = None
        if marked_col_name:
            try:
                marker_index = list(df2.columns).index(marked_col_name)
                logger.debug("Marker at column index %d before transpose", marker_index)
            except ValueError:
                pass
        
        # NEW APPROACH: Use pandas pivot to properly restructure the data
        # Before:
        #   Columns: ['Year', 'Revenue (ARR)', 'COGS', ...]
        #   Row 0: ['Y1', 1900004, 490630.8, ...]
        #   Row 1: ['Y2', 5081943.48, ...]
        # 
        # After:
        #   Columns: ['FieldName', 'Y1', 'Y2', 'Y3', 'Y4']
        #   Row 0: ['Revenue (ARR)', 1900004, 5081943.48, ...]
        
        # Step 1: Identify the year column (first column that has year values)
        year_col = None
        for col in df2.columns:
            col_vals = df2[col].astype(str).str.strip().str.lower()
            year_value_count = sum(1 for v in col_vals if re.search(r'y\s*[1-7]|20\d{2}|previous|prev', v))
            if year_value_count >= 2:
                year_col = col
                logger.debug("Identified year column: '%s'", year_col)
                break
        
        if year_col is None:
            # Fallback: assume first column is year column
            year_col = df2.columns[0]
            logger.debug("No year column found, using first column: '%s'", year_col)
        
        # Step 2: Transpose using the year column as the new column headers
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Before pivot: %s", df2.shape)
            logger.debug("Year column: '%s'", year_col)
            logger.debug("Year values: %s", df2[year_col].tolist())
        
        # Set year column as index, transpose, then reset
        df2 = df2.set_index(year_col).transpose().reset_index()
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("After pivot: %s", df2.shape)
            logger.debug("New columns: %s", df2.columns.tolist()[:10])
        
        # Rename the first column to something meaningful
        df2.columns.values[0] = 'FieldName'
        
        # Clean up column names (the year values are now column names)
        new_cols = [df2.columns[0]]  # Keep 'FieldName'
        for col in df2.columns[1:]:
            # Clean up year column names
            col_str = str(col).strip().upper()
            new_cols.append(col_str)
        df2.columns = new_cols
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Final columns after transpose: %s", df2.columns.tolist()[:10])
            logger.debug("First column preview:")
            for i in range(min(5, len(df2))):
                logger.debug("  Row %d: %s", i, df2.iloc[i, 0])
        
        # Find and restore the marker in year columns if needed
        if marker_index is not None:
            for col_idx, col_name in enumerate(df2.columns[1:], start=1):
                col_name_clean = str(col_name).strip().lower()
                col_name_clean = re.sub(r'\s+', ' ', col_name_clean)
                if any(indicator in col_name_clean for indicator in previous_year_indicators):
                    new_col_name = f"PREVIOUS_YEAR_MARKER_{col_name}"
                    df2.columns.values[col_idx] = new_col_name
                    logger.debug("✓ Restored marker after transpose: column %d -> '%s'", col_idx, new_col_name)
                    break
        
        df2 = make_columns_unique(df2)
        note = orientation_msg + " (pivoted to horizontal format)"
    
    return df2, best_idx, note

def detect_year_columns(columns: List[str], cfg: dict) -> Tuple[Dict[str, str], int, List[str]]:
    """
    Map column names to 'previous', 'y1', 'y2', etc.

    Logic:
    1. Check for PREVIOUS_YEAR_MARKER_ prefix (marked "Last year" columns)
    2. Try date-aware matching for absolute years (2026, 2026E, FY2026, etc.)
    3. Try alias matching for relative years (Y1, Y2, Year 1, Year 2, etc.)
    4. Fallback: ensure y1 is always set
    """
    notes: List[str] = []
    yr_cfg = cfg.get("years", {})
    
    # Get current year from system clock
    current_year = datetime.datetime.now().year
    logger.debug("detect_year_columns - Current system year: %d", current_year)
    logger.debug("detect_year_columns received columns: %s", columns[:10])
    
    # Aliases for relative year patterns (Y1, Y2, Year 1, Year 2, etc.)
    aliases = {
        "previous": [x.lower() for x in yr_cfg.get("previous", [])],
        "y1": [x.lower() for x in yr_cfg.get("y1", [])],
        "y2": [x.lower() for x in yr_cfg.get("y2", [])],
        "y3": [x.lower() for x in yr_cfg.get("y3", [])],
        "y4": [x.lower() for x in yr_cfg.get("y4", [])],
        "y5": [x.lower() for x in yr_cfg.get("y5", [])],
        "y6": [x.lower() for x in yr_cfg.get("y6", [])],
        "y7": [x.lower() for x in yr_cfg.get("y7", [])],
    }
    
    def norm(s: str) -> str:
        s = unidecode(str(s or "")).lower()
        s = s.replace("&", " and ")
        s = re.sub(r"[/\_\-]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s
    
    cols_norm = [(c, norm(c)) for c in columns]
    year_map: Dict[str, str] = {}
    
    # STEP 1: Check for columns marked with PREVIOUS_YEAR_MARKER_ prefix
    logger.debug("STEP 1: Checking for PREVIOUS_YEAR_MARKER_ columns...")
    for orig in columns:
        if orig.startswith("PREVIOUS_YEAR_MARKER_"):
            year_map["previous"] = orig
            notes.append("Detected 'Last year' label; mapped to Previous Year.")
            logger.debug("✓ Mapped '%s' to 'previous' based on marker", orig)
            break
    
    if "previous" not in year_map:
        logger.debug("No PREVIOUS_YEAR_MARKER_ column found")
    
    # STEP 2: Date-aware absolute year detection (2026, 2026E, FY2026, etc.)
    # UPDATED PATTERN: Now matches "2026", "2026E", "2026e", "FY2026", "2026 E", etc.
    logger.debug("STEP 2: Checking for absolute year columns with date-aware mapping...")
    for orig in columns:
        if orig.startswith("PREVIOUS_YEAR_MARKER_"):
            continue
        
        # Skip if already mapped
        if orig in year_map.values():
            continue
        
        match = re.search(r'\b(20\d{2})\b(?:[Ee]|[\s\-\_]*[Ee])?', str(orig))
        if match:
            year_num = int(match.group(1))
            logger.debug("Found year %d in column '%s'", year_num, orig)
            
            # Map based on offset from current year
            if year_num == current_year - 1:
                if "previous" not in year_map:
                    year_map["previous"] = orig
                    logger.debug("✓ Mapped '%s' to 'previous' (year %d = current_year - 1)", orig, year_num)
                    notes.append(f"Detected {year_num} as previous year (system year: {current_year}).")
            elif year_num == current_year:
                if "y1" not in year_map:
                    year_map["y1"] = orig
                    logger.debug("✓ Mapped '%s' to 'y1' (year %d = current year)", orig, year_num)
                    notes.append(f"Detected {year_num} as Year 1 forecast (current FY).")
            elif year_num == current_year + 1:
                if "y2" not in year_map:
                    year_map["y2"] = orig
                    logger.debug("✓ Mapped '%s' to 'y2' (year %d = current_year + 1)", orig, year_num)
            elif year_num == current_year + 2:
                if "y3" not in year_map:
                    year_map["y3"] = orig
                    logger.debug("✓ Mapped '%s' to 'y3' (year %d = current_year + 2)", orig, year_num)
            elif year_num == current_year + 3:
                if "y4" not in year_map:
                    year_map["y4"] = orig
                    logger.debug("✓ Mapped '%s' to 'y4' (year %d = current_year + 3)", orig, year_num)
            elif year_num == current_year + 4:
                if "y5" not in year_map:
                    year_map["y5"] = orig
                    logger.debug("✓ Mapped '%s' to 'y5' (year %d = current_year + 4)", orig, year_num)
            elif year_num == current_year + 5:
                if "y6" not in year_map:
                    year_map["y6"] = orig
                    logger.debug("✓ Mapped '%s' to 'y6' (year %d = current_year + 5)", orig, year_num)
            elif year_num == current_year + 6:
                if "y7" not in year_map:
                    year_map["y7"] = orig
                    logger.debug("✓ Mapped '%s' to 'y7' (year %d = current_year + 6)", orig, year_num)
    
    # STEP 3: Do alias matching for relative years (Y1, Y2, Year 1, Year 2, etc.)
    logger.debug("STEP 3: Performing alias matching for relative year patterns...")
    for key, nms in aliases.items():
        if key in year_map:
            logger.debug("Skipping '%s' alias matching - already mapped", key)
            continue
        
        for orig, c in cols_norm:
            if orig.startswith("PREVIOUS_YEAR_MARKER_"):
                continue
            
            # Skip if this column was already mapped
            if orig in year_map.values():
                continue
                
            if any(nm in c for nm in nms):
                year_map[key] = orig
                logger.debug("✓ Mapped '%s' to '%s' via alias matching", orig, key)
                break
    
    # STEP 4: If we still haven't found y1, use fallback
    logger.debug("STEP 4: Fallback check - ensuring y1 is set...")
    if "y1" not in year_map:
        logger.debug("No y1 found, applying fallback...")
        # Try to find first column that's not 'previous', not 'FieldName', and not already mapped
        for orig in columns:
            if orig.startswith("PREVIOUS_YEAR_MARKER_"):
                continue
            # Skip the label column (usually 'FieldName', 'index', or first column)
            if str(orig).lower() in ['fieldname', 'index', 'field', 'label', 'item']:
                continue
            if orig in year_map.values():
                continue
            year_map["y1"] = orig
            logger.debug("✓ Set 'y1' = '%s' (fallback to first available column)", orig)
            break
    else:
        logger.debug("y1 already mapped to '%s'", year_map['y1'])
    
    # Count how many forecast years we found
    years_used = 0
    for k in ["y1", "y2", "y3", "y4", "y5", "y6", "y7"]:
        if k in year_map:
            years_used += 1

    # Equidam template currently supports only 5 forecast years.
    # Surface a clear warning when extra years are found so data loss isn't silent.
    if years_used > 5:
        dropped_keys = [k for k in ["y6", "y7"] if k in year_map]
        dropped_cols = [year_map[k] for k in dropped_keys]
        notes.append(
            f"Detected {years_used} forecast years but Equidam template supports 5; "
            f"dropping: {', '.join(str(c) for c in dropped_cols)}."
        )
        logger.warning("Truncating year_map from %d to 5 forecast years; dropping %s",
                       years_used, dropped_cols)
        for k in dropped_keys:
            year_map.pop(k, None)

    years_used = max(1, min(years_used, 5))  # Cap at 5 (Equidam template horizon)
    
    # Do not add a 'previous' fallback — if no previous-year column was detected,
    # leave it absent so downstream code can distinguish "no prior data" from
    # "prior data exists but happens to equal Y1".
    
    logger.debug("Final year_map: %s", year_map)
    logger.debug("Years used: %d", years_used)
    
    return year_map, years_used, notes

def pick_label_column(df: pd.DataFrame, excluded: set) -> str:
    """Choose the column most likely to contain row labels."""
    candidates = [c for c in df.columns if c not in excluded]
    if not candidates:
        return df.columns[0]
    
    logger.debug("pick_label_column - Initial candidates: %s", candidates[:5])
    
    # Check for common label column names
    label_column_names = ['fieldname', 'field', 'label', 'item', 'description', 'metric']
    for candidate in candidates:
        if str(candidate).lower() in label_column_names:
            logger.debug("Found label column by name: '%s'", candidate)
            return candidate
    
    # Check if 'index' column actually contains meaningful text
    # Only skip it if it's truly just row numbers
    index_candidates = [c for c in candidates if str(c).lower() == 'index']
    if index_candidates:
        index_col = index_candidates[0]
        # Check if this 'index' column has meaningful text
        col_vals = df[index_col].astype(str).head(20)
        meaningful_count = 0
        numeric_count = 0
        
        for val in col_vals:
            val_clean = str(val).strip().lower()
            if val_clean == 'nan' or val_clean == '':
                continue
            # Count if it's a number
            if val_clean.replace('.', '').replace('-', '').isdigit():
                numeric_count += 1
            else:
                # It's text - check if meaningful
                if len(val_clean) > 2:  # More than just "id" or similar
                    meaningful_count += 1
        
        logger.debug("'index' column analysis: %d meaningful, %d numeric", meaningful_count, numeric_count)
        
        # If mostly meaningful text, KEEP 'index' as candidate
        # If mostly numbers, REMOVE it from candidates
        if meaningful_count > numeric_count:
            logger.debug("Keeping 'index' column - it has meaningful field names")
        else:
            logger.debug("Removing 'index' column - it's just row numbers")
            candidates = [c for c in candidates if str(c).lower() != 'index']
    
    if not candidates:
        return df.columns[1] if len(df.columns) > 1 else df.columns[0]
    
    logger.debug("pick_label_column - Final candidates: %s", candidates[:5])
    
    # Find the column with the most meaningful text content (field names)
    best_col = candidates[0]
    best_score = -1.0
    
    for c in candidates:
        col = df[c].astype(str)
        # Count non-numeric, non-nan, non-junk text
        meaningful_count = 0
        for val in col.head(50):
            val_clean = str(val).strip().lower()
            # Skip if it's nan, a number, or looks like 'nan (2)'
            if val_clean == 'nan' or val_clean == '':
                continue
            if val_clean.replace('.', '').replace('-', '').isdigit():
                continue
            if re.match(r'^nan\s*\(\d+\)$', val_clean):
                continue
            meaningful_count += 1
        
        score = meaningful_count / max(1, len(col.head(50)))
        if score > best_score:
            best_score = score
            best_col = c
        
        logger.debug("  Candidate '%s': score = %.2f", c, score)
    
    logger.debug("pick_label_column chose '%s' with meaningful text score %.2f", best_col, best_score)
    return best_col

def make_columns_unique(df: pd.DataFrame) -> pd.DataFrame:
    """Make duplicate column names unique by appending (2), (3), etc."""
    seen = {}
    new_cols = []
    for c in df.columns:
        name = str(c)
        if name not in seen:
            seen[name] = 1
            new_cols.append(name)
        else:
            seen[name] += 1
            new_cols.append(f"{name} ({seen[name]})")
    df.columns = new_cols
    return df

def trim_blank_edges(df: pd.DataFrame) -> pd.DataFrame:
    """Remove completely empty rows and columns."""
    df2 = df.copy()
    df2 = df2.dropna(how='all').dropna(axis=1, how='all')
    df2.columns = [
        "" if (isinstance(c, float) and pd.isna(c)) else str(c)
        for c in df2.columns
    ]
    return df2