"""
core/monthly_to_yearly.py

Converts monthly financial data to yearly aggregates.
Now includes support for previous fiscal year detection.

If multiple sheets in the workbook contain valid monthly data,
we aggregate EACH of them and write them all to the output file
as separate sheets.

INTEGRATION NOTE:
This module now uses aggregate_monthly_with_actuals to detect and handle
fiscal year columns (like FY 24/25) alongside monthly data. If no fiscal
year is detected, it falls back to standard monthly-only aggregation.
"""

import pandas as pd
import re
from typing import List, Tuple, Optional, Dict, Any
from core.logging_config import get_logger

# Import the actuals detection logic
try:
    # Try relative import first (same directory)
    from .aggregate_monthly_with_actuals import (
        _detect_fiscal_and_monthly_pattern,
        _find_fiscal_year_column,
        _is_previous_fiscal_year,
        _aggregate_with_actuals
    )
    HAS_ACTUALS_SUPPORT = True
except ImportError:
    try:
        # Fallback to direct import if not using package structure
        from aggregate_monthly_with_actuals import (
            _detect_fiscal_and_monthly_pattern,
            _find_fiscal_year_column,
            _is_previous_fiscal_year,
            _aggregate_with_actuals
        )
        HAS_ACTUALS_SUPPORT = True
    except ImportError:
        HAS_ACTUALS_SUPPORT = False
        logger = get_logger(__name__)
        logger.warning("aggregate_monthly_with_actuals not found - fiscal year detection disabled")

logger = get_logger(__name__)


def convert_monthly_to_yearly(input_path: str, output_path: str, sheet_name: str = None) -> dict:
    """
    Convert monthly financial data to yearly aggregates.
    
    NOW SUPPORTS:
    - Fiscal year columns (FY 24/25, etc.) detected as "Previous Year"
    - Monthly columns (Month 1-12+) aggregated into Year 1, Year 2, etc.
    
    If sheet_name is None:
        - scan all sheets
        - for every sheet that has valid monthly data, aggregate it
        - write all aggregated sheets to output
    If sheet_name is given:
        - only process that sheet
    """
    result = {
        'success': False,
        'years_created': 0,
        'months_processed': 0,
        'months_discarded': 0,
        'has_previous_year': False,
        'errors': [],
        'warnings': [],
        'processed_sheets': [],
        'skipped_sheets': [],  # [{sheet, reason}] for sheets that failed detection
    }

    try:
        logger.info("Reading from: %s", input_path)
        excel_file = pd.ExcelFile(input_path)
        logger.info("Available sheets: %s", excel_file.sheet_names)

        aggregated_dfs: Dict[str, pd.DataFrame] = {}
        total_months_processed = 0
        total_months_discarded = 0
        max_years_created = 0

        sheets_to_check = [sheet_name] if sheet_name else excel_file.sheet_names

        for sname in sheets_to_check:
            logger.info("  Scanning sheet: %s", sname)
            df = pd.read_excel(excel_file, sheet_name=sname, header=None)
            if df.empty:
                logger.info("    Empty - skipping")
                result['skipped_sheets'].append({'sheet': sname, 'reason': 'Sheet is empty'})
                continue

            logger.info("    Size: %d rows x %d cols", len(df), len(df.columns))
            
            # STEP 1: Try to detect fiscal year + monthly pattern (NEW)
            detection = None
            if HAS_ACTUALS_SUPPORT:
                logger.info("    Attempting to detect fiscal year + monthly pattern...")
                detection = _detect_fiscal_and_monthly_pattern(df)
                
                if detection['found'] and detection.get('has_previous_year'):
                    logger.info("    ✓ Found fiscal year column + monthly data")
                    logger.info("      - Previous year: %s", detection.get('previous_year_label'))
                    logger.info("      - Monthly columns: %d months", detection['month_count'])
                elif detection['found']:
                    logger.info("    ✓ Found monthly data (no fiscal year)")
                else:
                    logger.info("    ✗ No fiscal year pattern found, trying standard detection...")
            
            # STEP 2: If no fiscal year found, fall back to standard monthly detection
            if detection is None or not detection['found']:
                logger.info("    Attempting standard monthly pattern detection...")
                detection = _detect_monthly_pattern(df)
                
                if not detection['found']:
                    logger.info("    ✗ No pattern found")
                    reason = detection.get('error', 'No monthly pattern detected (need 12+ consecutive months starting from 1)')
                    result['skipped_sheets'].append({'sheet': sname, 'reason': reason})
                    if sheet_name == sname:
                        result['errors'].append(f"Sheet '{sname}': {reason}")
                    continue
                
                logger.info("    Pattern found: %s, %d months", detection['orientation'], detection['month_count'])
                logger.info("    Month numbers: %s", detection['month_numbers'])
            
            # STEP 3: Validate the pattern
            validation = _validate_pattern(detection)
            if not validation['valid']:
                logger.info("    ✗ INVALID: %s", validation['error'])
                result['skipped_sheets'].append({'sheet': sname, 'reason': validation['error']})
                if sheet_name == sname:
                    result['errors'].append(f"Sheet '{sname}': {validation['error']}")
                continue

            # STEP 4: Aggregate the data
            logger.info("    ✓ VALID - aggregating")
            
            # Use the appropriate aggregation method
            if detection.get('has_previous_year') and HAS_ACTUALS_SUPPORT:
                # Use the actuals aggregation (includes Previous Year column)
                yearly_df, agg_info = _aggregate_with_actuals(df, detection)
            else:
                # Use standard aggregation (Year 1, Year 2, etc. only)
                yearly_df, agg_info = _aggregate_to_years(df, detection)

            aggregated_dfs[sname] = yearly_df

            # Count rows where every year column is 0 or blank — these likely came
            # from months that were all empty and will inject zeros into the import.
            year_cols = [c for c in yearly_df.columns if c != 'FieldName']
            zero_rows = int(
                yearly_df[year_cols]
                .apply(lambda r: all(v == 0 or v == '' for v in r), axis=1)
                .sum()
            ) if year_cols else 0

            sheet_info = {
                'sheet_name': sname,
                'years_created': agg_info['years_created'],
                'months_processed': agg_info.get('months_processed', agg_info['years_created'] * 12),
                'has_previous_year': agg_info.get('has_previous_year', False),
                'zero_rows': zero_rows,
            }
            
            # Track if we have discarded months (standard aggregation only)
            if 'months_discarded' in agg_info:
                sheet_info['months_discarded'] = agg_info['months_discarded']
                total_months_discarded += agg_info['months_discarded']
            
            result['processed_sheets'].append(sheet_info)

            total_months_processed += sheet_info['months_processed']
            max_years_created = max(max_years_created, agg_info['years_created'])
            
            if agg_info.get('has_previous_year'):
                result['has_previous_year'] = True

        if not aggregated_dfs:
            if not result['errors']:
                result['errors'].append("No valid monthly data found in any sheet")
            return result

        logger.info("Writing output to: %s", output_path)
        _write_multiple_yearly_excels(aggregated_dfs, output_path)

        result['success'] = True
        result['years_created'] = max_years_created
        result['months_processed'] = total_months_processed
        result['months_discarded'] = total_months_discarded
        result['zero_rows'] = sum(s.get('zero_rows', 0) for s in result['processed_sheets'])

        if total_months_discarded > 0:
            result['warnings'].append(
                f"Discarded {total_months_discarded} extra months across all sheets (not enough for complete year)"
            )

        logger.info(
            "Success! Processed %d sheets. Max years: %d, total months: %d, has previous year: %s",
            len(aggregated_dfs),
            max_years_created,
            total_months_processed,
            result['has_previous_year']
        )
        return result

    except Exception as e:
        logger.error("Conversion failed: %s", e, exc_info=True)
        result['errors'].append(str(e))
        return result


def _validate_pattern(detection: dict) -> dict:
    """
    Validate detected pattern (works for both fiscal year + monthly and monthly-only).
    """
    if not detection.get('found'):
        return {'valid': False, 'error': 'No pattern detected'}
    
    # If this is a fiscal year + monthly pattern
    if detection.get('has_previous_year'):
        if detection['month_count'] < 12:
            return {'valid': False, 'error': f'Need at least 12 months, found {detection["month_count"]}'}
        
        # Check if fiscal year is actually previous
        if not detection.get('is_previous_year'):
            return {
                'valid': False, 
                'error': f'Fiscal year "{detection.get("previous_year_label")}" is not a previous year'
            }
        
        return {'valid': True}
    
    # Standard monthly-only validation
    if 'month_numbers' in detection:
        month_numbers = detection['month_numbers']
        if not month_numbers or month_numbers[0] != 1:
            return {'valid': False, 'error': 'Months must start at 1'}

        for i in range(len(month_numbers) - 1):
            if month_numbers[i + 1] != month_numbers[i] + 1:
                return {'valid': False, 'error': f"Missing Month {month_numbers[i] + 1} - months must be consecutive"}

        if len(month_numbers) < 12:
            return {'valid': False, 'error': f"Need at least 12 consecutive months (found {len(month_numbers)})"}
    
    return {'valid': True}


# =========================
# Detection helpers (ORIGINAL LOGIC - for fallback)
# =========================
def _detect_monthly_pattern(df: pd.DataFrame) -> dict:
    """
    Detect if data has monthly patterns and determine orientation.
    Scans full sheet horizontally, then vertically.
    
    This is the ORIGINAL detection logic - used as fallback when
    fiscal year detection doesn't find anything.
    """
    MONTH_NAMES = [
        'january', 'february', 'march', 'april', 'may', 'june',
        'july', 'august', 'september', 'october', 'november', 'december'
    ]
    MONTH_ABBREV = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
                    'jul', 'aug', 'sep', 'oct', 'nov', 'dec']

    horizontal_result = _detect_horizontal_months(df, MONTH_NAMES, MONTH_ABBREV)
    if horizontal_result['found']:
        return horizontal_result

    vertical_result = _detect_vertical_months(df, MONTH_NAMES, MONTH_ABBREV)
    if vertical_result['found']:
        return vertical_result

    return {
        'found': False,
        'error': "No monthly pattern detected. Need at least 12 consecutive months starting from 1."
    }


def _cell_to_month(val, month_names: List[str], month_abbrev: List[str]) -> Optional[int]:
    """
    Convert a cell to a month number, if possible.
    Handles numeric cells like 1.0, 2.0 etc.
    """
    if isinstance(val, (int, float)):
        if pd.isna(val):
            return None
        as_int = int(val)
        if 1 <= as_int <= 84 and abs(val - as_int) < 1e-6:
            return as_int

    if val is None:
        return None

    val_str = str(val).strip().lower()
    if not val_str or val_str == 'nan':
        return None

    if val_str.isdigit():
        num = int(val_str)
        if 1 <= num <= 84:
            return num

    m = re.match(r'^m(?:onth)?\s*(\d+)$', val_str)
    if m:
        num = int(m.group(1))
        if 1 <= num <= 84:
            return num

    if val_str in month_names:
        return month_names.index(val_str) + 1

    if val_str in month_abbrev:
        return month_abbrev.index(val_str) + 1

    return None


def _detect_horizontal_months(df: pd.DataFrame, month_names: List[str], month_abbrev: List[str]) -> dict:
    """
    Scan EVERY row and keep the longest 1..N run found in that row.
    Only accept if N >= 12.
    """
    total_rows = len(df)
    total_cols = len(df.columns)

    for header_row in range(total_rows):
        best_run_cols: List[int] = []
        best_run_months: List[int] = []

        current_run_cols: List[int] = []
        current_run_months: List[int] = []

        for col_idx in range(total_cols):
            raw_val = df.iat[header_row, col_idx]
            month_num = _cell_to_month(raw_val, month_names, month_abbrev)

            if month_num is None:
                # end current run
                if len(current_run_months) > len(best_run_months):
                    best_run_months = current_run_months
                    best_run_cols = current_run_cols
                current_run_cols = []
                current_run_months = []
                continue

            if not current_run_months:
                # start only on 1
                if month_num == 1:
                    current_run_cols = [col_idx]
                    current_run_months = [1]
                # else ignore
            else:
                expected = current_run_months[-1] + 1
                if month_num == expected:
                    current_run_cols.append(col_idx)
                    current_run_months.append(month_num)
                else:
                    # run broke; first save it
                    if len(current_run_months) > len(best_run_months):
                        best_run_months = current_run_months
                        best_run_cols = current_run_cols
                    # restart if this is 1
                    if month_num == 1:
                        current_run_cols = [col_idx]
                        current_run_months = [1]
                    else:
                        current_run_cols = []
                        current_run_months = []

        # end of row: check last run
        if len(current_run_months) > len(best_run_months):
            best_run_months = current_run_months
            best_run_cols = current_run_cols

        # if this row has a good run, return it
        if len(best_run_months) >= 12 and best_run_months[0] == 1:
            logger.debug(
                "Found horizontal pattern at row %d: %d consecutive months starting at 1",
                header_row,
                len(best_run_months),
            )
            return {
                'found': True,
                'orientation': 'horizontal',
                'month_indices': best_run_cols,
                'month_numbers': best_run_months,
                'month_count': len(best_run_months),
                'data_start': header_row + 1,
                'header_row': header_row
            }

    return {'found': False, 'error': 'No 12-month horizontal run found'}


def _detect_vertical_months(df: pd.DataFrame, month_names: List[str], month_abbrev: List[str]) -> dict:
    """
    Scan EVERY column and keep the longest 1..N run found in that column.
    Only accept if N >= 12.
    """
    total_rows = len(df)
    total_cols = len(df.columns)

    for label_col in range(total_cols):
        best_run_rows: List[int] = []
        best_run_months: List[int] = []

        current_run_rows: List[int] = []
        current_run_months: List[int] = []

        for row_idx in range(total_rows):
            raw_val = df.iat[row_idx, label_col]
            month_num = _cell_to_month(raw_val, month_names, month_abbrev)

            if month_num is None:
                if len(current_run_months) > len(best_run_months):
                    best_run_months = current_run_months
                    best_run_rows = current_run_rows
                current_run_rows = []
                current_run_months = []
                continue

            if not current_run_months:
                if month_num == 1:
                    current_run_rows = [row_idx]
                    current_run_months = [1]
            else:
                expected = current_run_months[-1] + 1
                if month_num == expected:
                    current_run_rows.append(row_idx)
                    current_run_months.append(month_num)
                else:
                    if len(current_run_months) > len(best_run_months):
                        best_run_months = current_run_months
                        best_run_rows = current_run_rows
                    if month_num == 1:
                        current_run_rows = [row_idx]
                        current_run_months = [1]
                    else:
                        current_run_rows = []
                        current_run_months = []

        if len(current_run_months) > len(best_run_months):
            best_run_months = current_run_months
            best_run_rows = current_run_rows

        if len(best_run_months) >= 12 and best_run_months[0] == 1:
            logger.debug(
                "Found vertical pattern in column %d: %d consecutive months starting at 1",
                label_col,
                len(best_run_months),
            )
            return {
                'found': True,
                'orientation': 'vertical',
                'month_indices': best_run_rows,
                'month_numbers': best_run_months,
                'month_count': len(best_run_months),
                'label_index': label_col,
                'data_start': 0
            }

    return {'found': False, 'error': 'No 12-month vertical run found'}


# =========================
# Validation (ORIGINAL)
# =========================
def _validate_months(detection: dict) -> dict:
    """Original validation function - kept for backward compatibility"""
    if not detection.get('found'):
        return {'valid': False, 'error': 'No pattern detected'}

    month_numbers = detection['month_numbers']
    if not month_numbers or month_numbers[0] != 1:
        return {'valid': False, 'error': 'Months must start at 1'}

    for i in range(len(month_numbers) - 1):
        if month_numbers[i + 1] != month_numbers[i] + 1:
            return {'valid': False, 'error': f"Missing Month {month_numbers[i] + 1} - months must be consecutive"}

    if len(month_numbers) < 12:
        return {'valid': False, 'error': f"Need at least 12 consecutive months (found {len(month_numbers)})"}

    return {'valid': True}


# =========================
# Aggregation (ORIGINAL - for fallback)
# =========================
def _aggregate_to_years(df: pd.DataFrame, detection: dict) -> Tuple[pd.DataFrame, dict]:
    orientation = detection['orientation']
    month_count = detection['month_count']

    years_created = month_count // 12
    months_used = years_created * 12
    months_discarded = month_count - months_used

    if orientation == 'horizontal':
        yearly_df = _aggregate_horizontal(df, detection, years_created)
    else:
        yearly_df = _aggregate_vertical(df, detection, years_created)

    return yearly_df, {
        'years_created': years_created,
        'months_processed': months_used,
        'months_discarded': months_discarded,
    }


def _aggregate_horizontal(df: pd.DataFrame, detection: dict, years_created: int) -> pd.DataFrame:
    data_start = detection['data_start']
    month_cols = detection['month_indices']

    # find a label column (first non-month)
    label_col = None
    for col_idx in range(len(df.columns)):
        if col_idx not in month_cols:
            sample_vals = df.iloc[data_start:data_start + 5, col_idx].astype(str)
            if any(not v.replace('.', '').replace('-', '').isdigit() for v in sample_vals if v.strip() != 'nan'):
                label_col = col_idx
                break
    if label_col is None:
        label_col = 0

    output_rows = []
    for row_idx in range(data_start, len(df)):
        row_label = str(df.iloc[row_idx, label_col]).strip()
        if not row_label or row_label == 'nan':
            continue

        yearly_values = [row_label]
        for year in range(years_created):
            start = year * 12
            end = start + 12
            cols_for_year = month_cols[start:end]
            year_sum = 0.0
            for mc in cols_for_year:
                val = df.iloc[row_idx, mc]
                try:
                    year_sum += float(val)
                except (TypeError, ValueError):
                    pass
            year_sum = round(year_sum, 2)
            yearly_values.append(year_sum if year_sum != 0 else '')
        output_rows.append(yearly_values)

    columns = ['FieldName'] + [f'Year {i+1}' for i in range(years_created)]
    return pd.DataFrame(output_rows, columns=columns)


def _aggregate_vertical(df: pd.DataFrame, detection: dict, years_created: int) -> pd.DataFrame:
    label_col = detection['label_index']
    month_rows = detection['month_indices']

    field_cols = [i for i in range(len(df.columns)) if i != label_col]

    field_names = []
    first_month_row = month_rows[0]
    for col_idx in field_cols:
        field_name = None
        for r in range(first_month_row):
            val = str(df.iloc[r, col_idx]).strip()
            if val and val != 'nan' and not val.isdigit():
                field_name = val
                break
        if not field_name:
            field_name = f'Field_{col_idx}'
        field_names.append((col_idx, field_name))

    output_rows = []
    for col_idx, field_name in field_names:
        yearly_values = [field_name]
        for year in range(years_created):
            start = year * 12
            end = start + 12
            rows_for_year = month_rows[start:end]
            year_sum = 0.0
            for mr in rows_for_year:
                val = df.iloc[mr, col_idx]
                try:
                    year_sum += float(val)
                except (TypeError, ValueError):
                    pass
            year_sum = round(year_sum, 2)
            yearly_values.append(year_sum if year_sum != 0 else '')
        output_rows.append(yearly_values)

    columns = ['FieldName'] + [f'Year {i+1}' for i in range(years_created)]
    return pd.DataFrame(output_rows, columns=columns)


# =========================
# Write multiple sheets
# =========================
def _write_multiple_yearly_excels(dfs_by_sheet: Dict[str, pd.DataFrame], output_path: str):
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in dfs_by_sheet.items():
            safe_name = sheet_name[:31]
            df.to_excel(writer, index=False, header=True, sheet_name=safe_name)
    logger.info("Wrote %d aggregated sheets to %s", len(dfs_by_sheet), output_path)