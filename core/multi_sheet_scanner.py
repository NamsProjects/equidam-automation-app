"""
core/multi_sheet_scanner.py

Handles multi-sheet scanning and conflict detection for financial data imports.
Allows importing from multiple Excel sheets and intelligently merging data while
detecting conflicts that require user resolution.

"""

from typing import Dict, List, Tuple, Optional
from pathlib import Path
import logging

from core.importer import import_any
from core.logging_config import get_logger

logger = get_logger(__name__)

def scan_multiple_sheets(
    path: str,
    sheet_names: List[str],
    aliases_json_path: str,
    options: Optional[dict] = None
) -> Dict:
    """
    Scan multiple Excel sheets and organize results into conflicts vs. no-conflict data.
    
    Algorithm:
    1. Import each sheet using import_any()
    2. Collect all field data organized by sheet
    3. Collect all review items from each sheet
    4. Detect conflicts (same field, different values across sheets)
    5. Separate into auto-mergeable data vs. data needing user choice
    
    Parameters
    ----------
    path : str
        Path to Excel file
    sheet_names : List[str]
        List of sheet names to scan
    aliases_json_path : str
        Path to aliases.json configuration
    options : Optional[dict]
        Import options (has_previous_year, etc.)
    
    Returns
    -------
    Dict
        {
            'data': {field: {sheet: values}},           # All raw data
            'conflicts': {field: {sheet: values}},      # Needs user choice
            'no_conflict': {field: values},             # Auto-merge ready
            'balance_conflicts': {field: {sheet: val}}, # Balance conflicts
            'balance_no_conflict': {field: val},        # Balance auto-merge
            'review_items': [...],                      # Items needing review approval
            'intermediate_data': {sheet: {...}},        # For manual mapping support
            'metadata': {
                'sheets_scanned': [...],
                'fields_found': [...],
                'conflict_count': int,
                'review_count': int,
                'years_used': int,
                'scan_notes': [...]
            }
        }
    """
    options = options or {}
    
    # Initialize data structures
    discovered_financial = {}  # {field_name: {sheet_name: [y1, y2, ...]}}
    discovered_balance = {}    # {field_name: {sheet_name: value}}
    all_review_items = []      # Review items from all sheets
    intermediate_data = {}     # Store intermediate data for manual mapping
    scan_notes = []
    max_years = 0
    
    logger.info("[MULTI-SHEET SCAN] Starting scan of %d sheets...", len(sheet_names))
    
    # Step 1: Scan all sheets sequentially
    for sheet_name in sheet_names:
        logger.info("[MULTI-SHEET SCAN] Scanning sheet: %s", sheet_name)
        
        try:
            # Import this sheet
            sheet_options = options.copy()
            sheet_options['sheet_name'] = sheet_name
            
            result = import_any(path, aliases_json_path, sheet_options)
            
            years_used = result.get('years_used', 1)
            max_years = max(max_years, years_used)
            
            # ✅ CRITICAL FIX: Store intermediate data INCLUDING applied_mappings
            # This is needed so the review dialog can show auto-applied mappings
            intermediate_data[sheet_name] = {
                **result.get('intermediate_data', {}),  # Keep df, label_col, year_map, has_previous_year
                'applied_mappings': result.get('applied_mappings', [])  # ✅ ADD applied_mappings!
            }
            
            # Extract financial data
            financial_data = result.get('financial', {})
            for field, values in financial_data.items():
                # Skip if no meaningful values
                if not values or _is_empty_series(values):
                    continue
                
                # Store this sheet's data for this field
                if field not in discovered_financial:
                    discovered_financial[field] = {}
                discovered_financial[field][sheet_name] = values
            
            # Extract balance data
            balance_data = result.get('balance', {})
            for field, value in balance_data.items():
                # Skip if no meaningful value
                if value is None or value == "" or value == 0:
                    continue
                
                # Store this sheet's data for this field
                if field not in discovered_balance:
                    discovered_balance[field] = {}
                discovered_balance[field][sheet_name] = value
            
            # CRITICAL FIX: Collect review items from this sheet
            review_items = result.get('review', [])
            if review_items:
                logger.info("[MULTI-SHEET SCAN] Found %d review items in '%s'", len(review_items), sheet_name)
                for item in review_items:
                    # Add sheet name to each review item so we know which sheet it's from
                    item_with_sheet = item.copy()
                    item_with_sheet['sheet_name'] = sheet_name
                    all_review_items.append(item_with_sheet)
                    logger.debug("[MULTI-SHEET SCAN]   - %s → %s (%d%%, %s)",
                               item['source_label'], item['suggested_target'],
                               item['confidence'], item['section'])
            
            # Count what was found
            fin_count = len([k for k, v in financial_data.items() if not _is_empty_series(v)])
            bal_count = len([k for k, v in balance_data.items() if v])
            review_count = len(review_items)
            
            scan_notes.append(
                f"✓ Scanned '{sheet_name}': "
                f"Found {fin_count} financial fields, "
                f"{bal_count} balance fields, "
                f"{review_count} review items"
            )
            
        except Exception as e:
            scan_notes.append(f"✗ Error scanning '{sheet_name}': {str(e)}")
            logger.error("[MULTI-SHEET SCAN ERROR] Sheet '%s': %s", sheet_name, e)
            import traceback
            if logger.isEnabledFor(logging.DEBUG):
                traceback.print_exc()
            continue
    
    # Step 2: Categorize into conflicts vs. no-conflict
    fin_conflicts = {}
    fin_no_conflict = {}
    
    for field, sheet_data in discovered_financial.items():
        if len(sheet_data) == 1:
            # Only one sheet has this field → no conflict
            sheet_name = list(sheet_data.keys())[0]
            fin_no_conflict[field] = sheet_data[sheet_name]
            logger.debug("[MULTI-SHEET SCAN] '%s': No conflict (only in '%s')", field, sheet_name)
        else:
            # Multiple sheets have this field - check if values are identical
            all_values = list(sheet_data.values())
            
            if _all_identical(all_values):
                # All sheets have SAME values → no conflict, auto-merge
                fin_no_conflict[field] = all_values[0]
                sheets_str = ", ".join(sheet_data.keys())
                logger.debug("[MULTI-SHEET SCAN] '%s': No conflict (identical across %s)", field, sheets_str)
            else:
                # Different values → conflict!
                fin_conflicts[field] = sheet_data
                sheets_str = ", ".join(sheet_data.keys())
                logger.debug("[MULTI-SHEET SCAN] '%s': CONFLICT (%s)", field, sheets_str)
    
    # Same for balance sheet
    bal_conflicts = {}
    bal_no_conflict = {}
    
    for field, sheet_data in discovered_balance.items():
        if len(sheet_data) == 1:
            sheet_name = list(sheet_data.keys())[0]
            bal_no_conflict[field] = sheet_data[sheet_name]
        else:
            all_values = list(sheet_data.values())
            
            if _all_identical(all_values, is_balance=True):
                bal_no_conflict[field] = all_values[0]
            else:
                bal_conflicts[field] = sheet_data
    
    # Step 3: Build metadata
    all_fields_found = set(discovered_financial.keys()) | set(discovered_balance.keys())
    conflict_count = len(fin_conflicts) + len(bal_conflicts)
    review_count = len(all_review_items)
    
    logger.info("[MULTI-SHEET SCAN] Summary:")
    logger.info("  Total fields found: %d", len(all_fields_found))
    logger.info("  Financial conflicts: %d", len(fin_conflicts))
    logger.info("  Balance conflicts: %d", len(bal_conflicts))
    logger.info("  Auto-merged fields: %d", len(fin_no_conflict) + len(bal_no_conflict))
    logger.info("  Review items: %d", review_count)
    
    return {
        'data': {
            'financial': discovered_financial,
            'balance': discovered_balance
        },
        'conflicts': fin_conflicts,
        'no_conflict': fin_no_conflict,
        'balance_conflicts': bal_conflicts,
        'balance_no_conflict': bal_no_conflict,
        'review_items': all_review_items,  # NEW: Return review items
        'intermediate_data': intermediate_data,  # NEW: For manual mapping (with applied_mappings!)
        'metadata': {
            'sheets_scanned': sheet_names,
            'fields_found': sorted(all_fields_found),
            'conflict_count': conflict_count,
            'review_count': review_count,  # NEW: Count of review items
            'years_used': max_years,
            'scan_notes': scan_notes
        }
    }

def values_are_identical(values1, values2, tolerance=0.01, is_balance=False) -> bool:
    """
    Compare two value series to determine if they're "the same".
    
    Allows for small rounding errors (1% by default).
    
    Parameters
    ----------
    values1, values2 : list or scalar
        Value series to compare (can be lists for financial or scalars for balance)
    tolerance : float
        Maximum percentage difference to still consider identical (default 1%)
    is_balance : bool
        If True, values1 and values2 are scalars (balance sheet values)
    
    Returns
    -------
    bool
        True if values are identical within tolerance
    """
    if is_balance:
        # Balance sheet values are scalars
        return _compare_single_values(values1, values2, tolerance)
    
    # Financial data - compare series
    if not isinstance(values1, list) or not isinstance(values2, list):
        return False
    
    # Must have same length
    if len(values1) != len(values2):
        return False
    
    # Compare each year
    for v1, v2 in zip(values1, values2):
        if not _compare_single_values(v1, v2, tolerance):
            return False
    
    return True

def _compare_single_values(v1, v2, tolerance=0.01) -> bool:
    """Compare two individual values with tolerance for rounding errors."""
    # Both None or empty
    if (v1 is None or v1 == "" or v1 == 0) and (v2 is None or v2 == "" or v2 == 0):
        return True
    
    # One is empty, other isn't
    if (v1 is None or v1 == "" or v1 == 0) or (v2 is None or v2 == "" or v2 == 0):
        return False
    
    # Both have values - compare with tolerance
    try:
        val1 = float(v1)
        val2 = float(v2)
        
        # Calculate percentage difference
        if val1 == 0 and val2 == 0:
            return True
        
        avg = (abs(val1) + abs(val2)) / 2
        if avg == 0:
            return True
        
        diff_pct = abs(val1 - val2) / avg
        return diff_pct <= tolerance
        
    except (ValueError, TypeError):
        # Can't convert to numbers - compare as strings
        return str(v1).strip() == str(v2).strip()

def _is_empty_series(values) -> bool:
    """Check if a value series is effectively empty (all None/0)."""
    if not values:
        return True
    
    if not isinstance(values, list):
        values = [values]
    
    for v in values:
        if v is not None and v != "" and v != 0:
            return False
    
    return True

def _all_identical(value_list, is_balance=False) -> bool:
    """
    Check if all values in a list are identical.
    
    Parameters
    ----------
    value_list : list
        List of value series (for financial) or scalars (for balance)
    is_balance : bool
        If True, comparing scalar balance sheet values
    
    Returns
    -------
    bool
        True if all values are identical
    """
    if len(value_list) < 2:
        return True
    
    first = value_list[0]
    for other in value_list[1:]:
        if not values_are_identical(first, other, is_balance=is_balance):
            return False
    
    return True

def format_scan_summary(scan_result: Dict, user_selections: Optional[Dict] = None) -> List[Tuple[str, str]]:
    """
    Generate human-readable summary messages for display in InfoPanel.
    
    Parameters
    ----------
    scan_result : Dict
        Result from scan_multiple_sheets()
    user_selections : Optional[Dict]
        User's conflict resolution choices: {field: selected_sheet}
    
    Returns
    -------
    List[Tuple[str, str]]
        List of (message, type) tuples for InfoPanel.show_progress()
        Types: 'info', 'success', 'warning', 'error', 'note'
    """
    messages = []
    
    metadata = scan_result.get('metadata', {})
    sheets = metadata.get('sheets_scanned', [])
    conflict_count = metadata.get('conflict_count', 0)
    review_count = metadata.get('review_count', 0)
    
    # Header
    messages.append(("✓ Multi-Sheet Scan Complete!", "success"))
    messages.append((f"Scanned {len(sheets)} sheets", "info"))
    messages.append(("", "info"))  # Blank line
    
    # Scan notes (from individual sheet imports)
    for note in metadata.get('scan_notes', []):
        note_type = "warning" if "Error" in note or "✗" in note else "info"
        messages.append((note, note_type))
    
    messages.append(("", "info"))  # Blank line
    
    # Review items summary
    if review_count > 0:
        messages.append((f"⚠ {review_count} items need review approval", "warning"))
    
    # Conflict resolution summary
    if conflict_count > 0:
        if user_selections:
            messages.append((f"✓ Resolved {len(user_selections)} conflicts", "success"))
            for field, sheet in user_selections.items():
                messages.append((f"  {field} ← {sheet}", "note"))
        else:
            messages.append((f"⚠ {conflict_count} conflicts detected (not yet resolved)", "warning"))
    else:
        messages.append(("✓ No conflicts detected - all data auto-merged", "success"))
    
    # Auto-merged fields
    no_conflict_count = len(scan_result.get('no_conflict', {})) + len(scan_result.get('balance_no_conflict', {}))
    if no_conflict_count > 0:
        messages.append(("", "info"))
        messages.append((f"✓ Auto-merged {no_conflict_count} non-conflicted fields", "success"))
    
    # Fields found
    fields_found = metadata.get('fields_found', [])
    if fields_found:
        messages.append(("", "info"))
        messages.append((f"Total fields: {len(fields_found)}", "info"))
        
        # Show first 5 fields
        for field in fields_found[:5]:
            messages.append((f"  • {field}", "note"))
        
        if len(fields_found) > 5:
            messages.append((f"  ... and {len(fields_found) - 5} more", "note"))
    
    return messages

def apply_conflict_resolutions(
    scan_result: Dict,
    user_selections: Dict[str, str]
) -> Tuple[Dict, Dict]:
    """
    Apply user's conflict resolution choices to merge final dataset.
    
    Parameters
    ----------
    scan_result : Dict
        Result from scan_multiple_sheets()
    user_selections : Dict[str, str]
        User's choices: {field_name: selected_sheet_name}
    
    Returns
    -------
    Tuple[Dict, Dict]
        (merged_financial, merged_balance) - ready to populate grids
    """
    # Start with no-conflict data
    merged_financial = scan_result.get('no_conflict', {}).copy()
    merged_balance = scan_result.get('balance_no_conflict', {}).copy()
    
    # Apply user selections for financial conflicts
    fin_conflicts = scan_result.get('conflicts', {})
    for field, selected_sheet in user_selections.items():
        if field in fin_conflicts:
            sheet_data = fin_conflicts[field]
            if selected_sheet in sheet_data:
                merged_financial[field] = sheet_data[selected_sheet]
                logger.debug("[CONFLICT RESOLUTION] '%s' ← '%s'", field, selected_sheet)
    
    # Apply user selections for balance conflicts
    bal_conflicts = scan_result.get('balance_conflicts', {})
    for field, selected_sheet in user_selections.items():
        if field in bal_conflicts:
            sheet_data = bal_conflicts[field]
            if selected_sheet in sheet_data:
                merged_balance[field] = sheet_data[selected_sheet]
                logger.debug("[CONFLICT RESOLUTION] '%s' (balance) ← '%s'", field, selected_sheet)
    
    return merged_financial, merged_balance

def apply_review_approvals(
    scan_result: Dict,
    approved_items: List[Dict]
) -> Tuple[Dict, Dict]:
    """
    Apply user-approved review items to the dataset.
    
    For each approved item, we need to:
    1. Find which sheet it came from
    2. Get the intermediate data for that sheet
    3. Apply the manual mapping
    4. Merge into the final dataset
    
    Parameters
    ----------
    scan_result : Dict
        Result from scan_multiple_sheets() with intermediate_data
    approved_items : List[Dict]
        User-approved review items (each has 'sheet_name', 'source_label', 'suggested_target', 'section')
    
    Returns
    -------
    Tuple[Dict, Dict]
        (additional_financial, additional_balance) - data to merge with existing results
    """
    from core.field_mapper import apply_manual_mappings
    
    # Group approved items by sheet
    items_by_sheet = {}
    for item in approved_items:
        sheet_name = item.get('sheet_name')
        if sheet_name not in items_by_sheet:
            items_by_sheet[sheet_name] = []
        items_by_sheet[sheet_name].append(item)
    
    # Initialize accumulators
    additional_financial = {}
    additional_balance = {}
    
    # Process each sheet's approved items
    intermediate_data = scan_result.get('intermediate_data', {})
    
    for sheet_name, sheet_items in items_by_sheet.items():
        logger.info("[REVIEW APPROVAL] Processing %d items from '%s'", len(sheet_items), sheet_name)
        
        # Get intermediate data for this sheet
        sheet_intermediate = intermediate_data.get(sheet_name, {})
        if not sheet_intermediate:
            logger.warning("No intermediate data for sheet '%s'", sheet_name)
            continue
        
        df = sheet_intermediate.get('df')
        label_col = sheet_intermediate.get('label_col')
        year_map = sheet_intermediate.get('year_map')
        has_previous = sheet_intermediate.get('has_previous_year', False)
        
        if df is None or label_col is None or year_map is None:
            logger.warning("Incomplete intermediate data for sheet '%s'", sheet_name)
            continue
        
        # Determine years_used from year_map
        years_used = sum(1 for k in ['y1', 'y2', 'y3', 'y4', 'y5', 'y6', 'y7'] if k in year_map)
        
        # Format items for apply_manual_mappings
        manual_mappings = []
        for item in sheet_items:
            manual_mappings.append({
                'source': item['source_label'],
                'target': item['suggested_target'],
                'section': item['section']
            })
            logger.debug("[REVIEW APPROVAL]   %s → %s (%s)",
                       item['source_label'], item['suggested_target'], item['section'])
        
        # Apply manual mappings for this sheet
        try:
            sheet_financial, sheet_balance = apply_manual_mappings(
                df=df,
                label_col=label_col,
                year_map=year_map,
                years_used=years_used,
                manual_mappings=manual_mappings,
                current_financial={},  # Start fresh
                current_balance={}
            )
            
            # Merge this sheet's results into accumulators
            for field, values in sheet_financial.items():
                if values and not _is_empty_series(values):
                    if field in additional_financial:
                        # Already have data for this field from another sheet - need to aggregate
                        from core.number_utils import sum_series
                        additional_financial[field] = sum_series(additional_financial[field], values)
                    else:
                        additional_financial[field] = values
            
            for field, value in sheet_balance.items():
                if value is not None and value != "" and value != 0:
                    if field in additional_balance:
                        # Already have data for this field - add
                        from core.number_utils import safe_add
                        additional_balance[field] = safe_add(additional_balance[field], value)
                    else:
                        additional_balance[field] = value
        
        except Exception as e:
            logger.error("Failed to apply manual mappings for sheet '%s': %s", sheet_name, e)
            import traceback
            if logger.isEnabledFor(logging.DEBUG):
                traceback.print_exc()
            continue
    
    return additional_financial, additional_balance