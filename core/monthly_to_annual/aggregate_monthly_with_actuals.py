"""
aggregate_monthly_with_actuals.py

Handles conversion of monthly data to yearly aggregates WITH previous fiscal year data.
This module detects fiscal year columns (FY 24/25, FY2024/2025, etc.) and determines
if they represent "previous year" based on current date, then aggregates monthly data
into Year 1, Year 2, etc.
"""

import pandas as pd
import re
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any
from core.logging_config import get_logger

logger = get_logger(__name__)


def convert_monthly_with_actuals(input_path: str, output_path: str, sheet_name: str = None) -> dict:
    """
    Convert monthly financial data to yearly aggregates, including previous fiscal year.
    
    Detects:
    1. Fiscal year columns (FY 24/25, etc.) and determines if they're "previous year"
    2. Monthly columns (Month 1, Month 2, etc.)
    
    Output:
    - Previous Year column (from fiscal year data, if detected)
    - Year 1 (aggregate of Month 1-12)
    - Year 2 (aggregate of Month 13-24)
    - etc.
    """
    result = {
        'success': False,
        'years_created': 0,
        'months_processed': 0,
        'has_previous_year': False,
        'errors': [],
        'warnings': [],
        'processed_sheets': []
    }

    try:
        logger.info("Reading from: %s", input_path)
        excel_file = pd.ExcelFile(input_path)
        logger.info("Available sheets: %s", excel_file.sheet_names)

        aggregated_dfs: Dict[str, pd.DataFrame] = {}
        
        sheets_to_check = [sheet_name] if sheet_name else excel_file.sheet_names

        for sname in sheets_to_check:
            logger.info("  Scanning sheet: %s", sname)
            df = pd.read_excel(excel_file, sheet_name=sname, header=None)
            if df.empty:
                logger.info("    Empty - skipping")
                continue

            logger.info("    Size: %d rows x %d cols", len(df), len(df.columns))
            
            # Detect fiscal year and monthly patterns
            detection = _detect_fiscal_and_monthly_pattern(df)
            
            if not detection['found']:
                logger.info("    ✗ No valid pattern found")
                if sheet_name == sname:
                    result['errors'].append(f"No fiscal year or monthly pattern detected in sheet '{sname}'")
                continue

            logger.info("    Pattern found:")
            logger.info("      - Has previous year: %s", detection['has_previous_year'])
            if detection['has_previous_year']:
                logger.info("      - Previous year column: %d (%s)", 
                           detection['previous_year_col'], 
                           detection['previous_year_label'])
            logger.info("      - Monthly columns: %d months starting at col %d", 
                       detection['month_count'], 
                       detection['first_month_col'])

            # Validate the pattern
            validation = _validate_pattern(detection)
            if not validation['valid']:
                logger.info("    ✗ INVALID: %s", validation['error'])
                if sheet_name == sname:
                    result['errors'].append(f"Sheet '{sname}': {validation['error']}")
                continue

            logger.info("    ✓ VALID - aggregating")
            yearly_df, agg_info = _aggregate_with_actuals(df, detection)

            aggregated_dfs[sname] = yearly_df
            result['processed_sheets'].append({
                'sheet_name': sname,
                'years_created': agg_info['years_created'],
                'months_processed': agg_info['months_processed'],
                'has_previous_year': agg_info['has_previous_year']
            })

            if agg_info['has_previous_year']:
                result['has_previous_year'] = True

        if not aggregated_dfs:
            if not result['errors']:
                result['errors'].append("No valid data found in any sheet")
            return result

        logger.info("Writing output to: %s", output_path)
        _write_output(aggregated_dfs, output_path)

        result['success'] = True
        result['years_created'] = max(s['years_created'] for s in result['processed_sheets'])
        result['months_processed'] = sum(s['months_processed'] for s in result['processed_sheets'])

        logger.info("Success! Processed %d sheets", len(aggregated_dfs))
        return result

    except Exception as e:
        logger.error("Conversion failed: %s", e, exc_info=True)
        result['errors'].append(str(e))
        return result


def _detect_fiscal_and_monthly_pattern(df: pd.DataFrame) -> dict:
    """
    Detect both fiscal year column and monthly columns in the dataframe.
    
    Returns dict with:
    - found: bool
    - orientation: str ('horizontal')
    - has_previous_year: bool
    - previous_year_col: int (if found)
    - previous_year_label: str (if found)
    - first_month_col: int
    - month_count: int
    - month_cols: List[int]
    - month_indices: List[int] (alias for month_cols)
    - month_numbers: List[int]
    - header_row: int
    - data_start_row: int
    """
    
    # Scan all rows to find header row
    for row_idx in range(min(10, len(df))):  # Check first 10 rows
        row_data = df.iloc[row_idx]
        
        # Check for fiscal year column
        fiscal_year_info = _find_fiscal_year_column(row_data, row_idx)
        
        # Check for monthly columns
        monthly_info = _find_monthly_columns(row_data, row_idx)
        
        # If we found monthly columns, we have a valid pattern
        if monthly_info['found']:
            result = {
                'found': True,
                'orientation': 'horizontal',  # This function only detects horizontal patterns
                'header_row': row_idx,
                'data_start_row': row_idx + 1,
                'data_start': row_idx + 1,  # Alias for compatibility
                'first_month_col': monthly_info['first_col'],
                'month_count': monthly_info['count'],
                'month_cols': monthly_info['cols'],
                'month_indices': monthly_info['cols'],  # Alias for _aggregate_to_years compatibility
                'month_numbers': monthly_info['months'],  # For validation and aggregation
                'has_previous_year': fiscal_year_info['found'],
            }
            
            if fiscal_year_info['found']:
                result['previous_year_col'] = fiscal_year_info['col']
                result['previous_year_label'] = fiscal_year_info['label']
                result['is_previous_year'] = fiscal_year_info['is_previous']
            
            return result
    
    return {'found': False, 'error': 'No monthly pattern detected'}


def _find_fiscal_year_column(row_data: pd.Series, row_idx: int) -> dict:
    """
    Find fiscal year column in the row and determine if it's "previous year".
    
    Looks for patterns like:
    - FY 24/25, FY24/25, FY 2024/2025
    - 24/25, 2024/2025, 24-25, 2024-2025
    - FY25, FY2025
    """
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    # Fiscal year patterns
    patterns = [
        r'(?:FY|fy)?\s*(\d{2})[/\-](\d{2})',           # FY24/25, 24-25
        r'(?:FY|fy)?\s*(\d{4})[/\-](\d{4})',           # FY2024/2025, 2024-2025
        r'(?:FY|fy)?\s*(\d{2})[/\-](\d{4})',           # FY24/2025
        r'(?:FY|fy)?\s*(\d{4})[/\-](\d{2})',           # FY2024/25
    ]
    
    for col_idx, cell_value in enumerate(row_data):
        if pd.isna(cell_value):
            continue
            
        cell_str = str(cell_value).strip()
        
        for pattern in patterns:
            match = re.search(pattern, cell_str, re.IGNORECASE)
            if match:
                year1, year2 = match.groups()
                
                # Normalize to 4-digit years
                year1 = _normalize_year(year1)
                year2 = _normalize_year(year2)
                
                # Determine if this is "previous year"
                is_previous = _is_previous_fiscal_year(year1, year2, current_year, current_month)
                
                logger.debug(f"Found fiscal year at col {col_idx}: {cell_str} -> {year1}/{year2}, is_previous={is_previous}")
                
                return {
                    'found': True,
                    'col': col_idx,
                    'label': cell_str,
                    'year_start': year1,
                    'year_end': year2,
                    'is_previous': is_previous
                }
    
    return {'found': False}


def _normalize_year(year_str: str) -> int:
    """Convert 2-digit or 4-digit year string to 4-digit year int."""
    year = int(year_str)
    if year < 100:
        # Assume 2000s for years 00-49, 1900s for 50-99
        if year < 50:
            year += 2000
        else:
            year += 1900
    return year


def _is_previous_fiscal_year(year_start: int, year_end: int, current_year: int, current_month: int) -> bool:
    """
    Determine if a fiscal year is "previous year" based on current date.
    
    Logic:
    - If year_end < current_year: definitely previous year
    - If year_end == current_year: previous year if we're past mid-year (July)
    - If year_end > current_year: definitely NOT previous year
    
    This handles most common fiscal year patterns (calendar year, April-March, July-June, etc.)
    """
    if year_end < current_year:
        return True
    elif year_end == current_year:
        # If we're past July, assume any FY ending this year has concluded
        return current_month >= 7
    else:
        return False


def _find_monthly_columns(row_data: pd.Series, row_idx: int) -> dict:
    """
    Find consecutive monthly columns (Month 1, Month 2, ..., M1, M2, ..., 1, 2, 3...).
    
    Returns first occurrence of at least 12 consecutive months starting from 1.
    """
    month_patterns = [
        r'^month\s*(\d+)$',
        r'^m(\d+)$',
        r'^(\d+)$'
    ]
    
    found_months = []
    found_cols = []
    
    for col_idx, cell_value in enumerate(row_data):
        if pd.isna(cell_value):
            # Reset if we hit a gap
            if found_months and len(found_months) >= 12:
                break  # We have enough, stop here
            found_months = []
            found_cols = []
            continue
        
        cell_str = str(cell_value).strip().lower()
        month_num = None
        
        for pattern in month_patterns:
            match = re.match(pattern, cell_str)
            if match:
                month_num = int(match.group(1))
                break
        
        if month_num is None:
            # Not a month column, reset if we had a sequence
            if found_months and len(found_months) >= 12:
                break
            found_months = []
            found_cols = []
            continue
        
        # Check if this continues our sequence
        if not found_months:
            # Start new sequence only if it's 1
            if month_num == 1:
                found_months = [1]
                found_cols = [col_idx]
        else:
            expected = found_months[-1] + 1
            if month_num == expected:
                found_months.append(month_num)
                found_cols.append(col_idx)
            else:
                # Sequence broken, restart if this is 1
                if len(found_months) >= 12:
                    break  # We already have enough
                if month_num == 1:
                    found_months = [1]
                    found_cols = [col_idx]
                else:
                    found_months = []
                    found_cols = []
    
    if len(found_months) >= 12:
        return {
            'found': True,
            'first_col': found_cols[0],
            'count': len(found_months),
            'cols': found_cols,
            'months': found_months
        }
    
    return {'found': False}


def _validate_pattern(detection: dict) -> dict:
    """Validate that the detected pattern is usable."""
    if not detection.get('found'):
        return {'valid': False, 'error': 'No pattern detected'}
    
    if detection['month_count'] < 12:
        return {'valid': False, 'error': f'Need at least 12 months, found {detection["month_count"]}'}
    
    # If we have a previous year column, verify it's actually "previous"
    if detection.get('has_previous_year') and not detection.get('is_previous_year'):
        return {
            'valid': False, 
            'error': f'Fiscal year column "{detection.get("previous_year_label")}" is not a previous year'
        }
    
    return {'valid': True}


def _aggregate_with_actuals(df: pd.DataFrame, detection: dict) -> Tuple[pd.DataFrame, dict]:
    """
    Aggregate data into yearly columns, including previous year if present.
    
    Output columns:
    - Previous Year (if has_previous_year)
    - Year 1 (sum of months 1-12)
    - Year 2 (sum of months 13-24)
    - etc.
    """
    header_row = detection['header_row']
    data_start = detection['data_start_row']
    month_cols = detection['month_cols']
    has_previous = detection.get('has_previous_year', False)
    
    # Calculate how many complete years we can create from months
    years_from_months = len(month_cols) // 12
    months_used = years_from_months * 12
    
    # Find label column (first non-data column)
    label_col = _find_label_column(df, header_row, month_cols, 
                                   detection.get('previous_year_col'))
    
    output_rows = []
    
    for row_idx in range(data_start, len(df)):
        row_label = str(df.iloc[row_idx, label_col]).strip()
        if not row_label or row_label == 'nan':
            continue
        
        yearly_values = [row_label]
        
        # Add previous year value if present
        if has_previous:
            prev_col = detection['previous_year_col']
            prev_val = df.iloc[row_idx, prev_col]
            try:
                prev_val = float(prev_val)
            except (TypeError, ValueError):
                prev_val = ''
            yearly_values.append(prev_val)
        
        # Aggregate months into years
        for year in range(years_from_months):
            start_month = year * 12
            end_month = start_month + 12
            year_cols = month_cols[start_month:end_month]
            
            year_sum = 0.0
            for col in year_cols:
                val = df.iloc[row_idx, col]
                try:
                    year_sum += float(val)
                except (TypeError, ValueError):
                    pass
            
            year_sum = round(year_sum, 2)
            yearly_values.append(year_sum if year_sum != 0 else '')
        
        output_rows.append(yearly_values)
    
    # Build column names
    columns = ['FieldName']
    if has_previous:
        columns.append('Previous Year')
    columns.extend([f'Year {i+1}' for i in range(years_from_months)])
    
    result_df = pd.DataFrame(output_rows, columns=columns)
    
    agg_info = {
        'years_created': years_from_months,
        'months_processed': months_used,
        'has_previous_year': has_previous
    }
    
    return result_df, agg_info


def _find_label_column(df: pd.DataFrame, header_row: int, month_cols: List[int], 
                       prev_year_col: Optional[int] = None) -> int:
    """
    Find the column that contains row labels (field names).
    Usually the first column that's not a month or previous year column.
    """
    exclude_cols = set(month_cols)
    if prev_year_col is not None:
        exclude_cols.add(prev_year_col)
    
    # Try to find a column with text labels
    for col_idx in range(len(df.columns)):
        if col_idx in exclude_cols:
            continue
        
        # Sample a few rows to see if this looks like labels
        sample_start = header_row + 1
        sample_end = min(sample_start + 5, len(df))
        sample_vals = df.iloc[sample_start:sample_end, col_idx].astype(str)
        
        # Check if these look like text labels (not all numbers)
        non_numeric = sum(1 for v in sample_vals 
                         if v.strip() != 'nan' and not v.replace('.', '').replace('-', '').isdigit())
        
        if non_numeric >= len(sample_vals) * 0.5:  # At least 50% are text
            return col_idx
    
    # Default to first column if nothing found
    return 0


def _write_output(dfs_by_sheet: Dict[str, pd.DataFrame], output_path: str):
    """Write aggregated dataframes to Excel file."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in dfs_by_sheet.items():
            safe_name = sheet_name[:31]  # Excel sheet name limit
            df.to_excel(writer, index=False, header=True, sheet_name=safe_name)
    
    logger.info("Wrote %d sheets to %s", len(dfs_by_sheet), output_path)


# Example usage
if __name__ == "__main__":
    # Test the function
    result = convert_monthly_with_actuals(
        input_path="input.xlsx",
        output_path="output_with_actuals.xlsx"
    )
    
    print("Result:", result)