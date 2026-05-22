"""
core/field_mapper.py

Handles field mapping logic for financial and balance sheet data.
Maps source table labels to canonical Equidam fields.
"""

from typing import Dict, List, Tuple, Optional
import logging
import re

from core.number_utils import parse_number_positive, safe_add, sum_series, safe_scalar
from core.field_mapper_utils import (
    make_normalizer,
    build_pref_map,
    prefer_alias,
    fuzzy_best,
    score_override,
    apply_exclusions
)
from core.logging_config import get_logger

logger = get_logger(__name__)

def find_aggregate_total_for_empty_row(
    df,
    row_idx: int,
    label_col: str,
    year_map: Dict[str, str],
    years_used: int
) -> Optional[List]:
    """
    When a category row has no data, look for a 'Total' row below it.
    Verify the Total matches the sum of intermediate rows.
    
    Returns the Total row's values if valid, else None.
    
    Parameters
    ----------
    df : pd.DataFrame
        The detected table section
    row_idx : int
        Index of the empty category row
    label_col : str
        Column name containing row labels
    year_map : Dict[str, str]
        Mapping from 'previous', 'y1', 'y2'... to actual column names
    years_used : int
        Number of forecast years (1-5)
    
    Returns
    -------
    Optional[List]
        List of values from Total row if validation passes, else None
    """
    # Look ahead up to 10 rows
    for offset in range(1, min(11, len(df) - row_idx)):
        check_row_idx = row_idx + offset
        
        # Safety check
        if check_row_idx >= len(df):
            break
        
        check_label = safe_scalar(df.iloc[check_row_idx][label_col])
        check_label_clean = str(check_label).strip().lower()
        
        # Found a "Total" row
        if check_label_clean == "total":
            logger.debug("Found 'Total' row at offset +%d", offset)
            
            # Extract Total row's values
            total_values = extract_row_values(
                df.iloc[check_row_idx],
                year_map,
                years_used
            )
            
            # Parse Total values
            total_parsed = []
            for v in total_values:
                num, _ = parse_number_positive(v)
                total_parsed.append(num if num is not None else 0)
            
            # Sum intermediate rows (between category and Total)
            intermediate_sum = [0] * len(total_parsed)
            for inter_offset in range(1, offset):
                inter_row_idx = row_idx + inter_offset
                
                # Safety check
                if inter_row_idx >= len(df):
                    break
                
                inter_label = safe_scalar(df.iloc[inter_row_idx][label_col])
                inter_label_clean = str(inter_label).strip().lower()
                
                # Skip if this is another category header or empty
                if inter_label_clean in ['', 'nan', 'total']:
                    continue
                
                # Extract and parse intermediate row
                inter_values = extract_row_values(
                    df.iloc[inter_row_idx],
                    year_map,
                    years_used
                )
                
                for i, v in enumerate(inter_values):
                    num, _ = parse_number_positive(v)
                    if num is not None and i < len(intermediate_sum):
                        intermediate_sum[i] += num
            
            # Verify: Total ≈ Sum (allow 1% tolerance)
            match = True
            for i in range(len(total_parsed)):
                total_val = total_parsed[i]
                sum_val = intermediate_sum[i]
                
                # Both zero - OK
                if total_val == 0 and sum_val == 0:
                    continue
                
                # One is zero, other isn't - check absolute difference
                if total_val == 0 or sum_val == 0:
                    if abs(total_val - sum_val) > 1:
                        match = False
                        break
                else:
                    # Both non-zero - check percentage difference
                    diff_pct = abs(total_val - sum_val) / max(total_val, sum_val)
                    if diff_pct > 0.01:  # 1% tolerance
                        logger.debug("Validation failed at column %d: Total=%s, Sum=%s (%.1f%% diff)",
                                   i, total_val, sum_val, diff_pct * 100)
                        match = False
                        break
            
            if match:
                logger.debug("✓ Aggregate Total validation passed - using Total values")
                # Return values (convert 0 back to None for empty cells)
                return [num for num in total_parsed]
            else:
                logger.debug("✗ Aggregate Total validation failed - sum doesn't match")
    
    logger.debug("No matching aggregate Total found")
    return None


# Labels matching these patterns are dimensionless ratios / rates / growth factors
# and must NEVER be mapped to absolute currency fields.
_RATIO_PATTERNS = [
    re.compile(r'%'),                          # any literal "%"
    re.compile(r'\bas a %', re.IGNORECASE),    # "as a % of sales"
    re.compile(r'\b% of\b', re.IGNORECASE),    # "% of revenue"
    re.compile(r'\brate\b', re.IGNORECASE),    # "tax rate", "retention rate"
    re.compile(r'\bratio\b', re.IGNORECASE),
    re.compile(r'\bmargin\b', re.IGNORECASE),
    re.compile(r'\bgrowth\b', re.IGNORECASE),  # "wage growth", "utility growth"
    re.compile(r'\bmultiple\b', re.IGNORECASE),
    re.compile(r'\bper kg\b', re.IGNORECASE),  # unit prices, not totals
    re.compile(r'\bper unit\b', re.IGNORECASE),
    re.compile(r'\bper person\b', re.IGNORECASE),
]


def is_ratio_row(raw_label: str) -> bool:
    """Return True if a label looks like a ratio/rate/growth row that must be skipped."""
    if not raw_label:
        return False
    s = str(raw_label)
    for pat in _RATIO_PATTERNS:
        if pat.search(s):
            return True
    return False


def map_table_rows(
    df,
    label_col: str,
    year_map: Dict[str, str],
    years_used: int,
    cfg: dict,
    financial_rows: List[str],
    balance_rows: List[str]
) -> dict:
    """
    Map rows from source table to Equidam fields using fuzzy matching.
    
    Parameters
    ----------
    df : pd.DataFrame
        The detected table section
    label_col : str
        Column name containing row labels
    year_map : Dict[str, str]
        Mapping from 'previous', 'y1', 'y2'... to actual column names
    years_used : int
        Number of forecast years (1-5)
    cfg : dict
        Configuration from aliases.json
    financial_rows : List[str]
        Canonical financial projection row names
    balance_rows : List[str]
        Canonical balance sheet row names
    
    Returns
    -------
    dict
        {
            'financial': {row_name: [prev, y1, y2,...] or [y1, y2,...]},
            'balance': {row_name: value},
            'review': [...],
            'auto_map_log': [...],
            'aggregated_into': {...},
            'ignored_labels': [...],
            'coerced_negatives': int
        }
    """
    # Extract config
    ignore_terms = set([t.lower() for t in cfg.get("ignore_contains", [])])
    normalizer = make_normalizer(cfg.get("normalize", {}))
    agg_rules = cfg.get("aggregation_rules", [])
    exclusion_patterns = cfg.get("exclusion_patterns", {})
    
    thresholds = cfg.get("thresholds", {"auto_map": 99, "review_min": 75})
    auto_thr = int(thresholds.get("auto_map", 99))
    rev_thr = int(thresholds.get("review_min", 75))
    
    fin_aliases = cfg.get("financial_aliases", {})
    bal_aliases = cfg.get("balance_aliases", {})
    
    # Determine expected array length based on whether previous year exists
    has_previous = "previous" in year_map
    expected_len = (1 + years_used) if has_previous else years_used
    
    # Outputs
    financial_accum: Dict[str, List[Optional[float]]] = {
        k: [None] * expected_len for k in financial_rows
    }
    balance_values: Dict[str, Optional[float]] = {k: None for k in balance_rows}
    review: List[Dict[str, object]] = []
    
    # Audit accumulators
    auto_map_log: List[Tuple[str, str, int]] = []
    aggregated_into: Dict[str, List[str]] = {}
    ignored_labels: List[str] = []
    coerced_negatives = 0

    # Track (normalized_label, target) pairs already auto-applied so the same
    # label appearing in multiple sub-sections of a stacked sheet doesn't get
    # summed multiple times (root cause of 2x/4x revenue duplication on stacked sheets).
    seen_mappings: set = set()

    # Value-level dedup: if two DIFFERENT labels map to the same non-aggregator
    # target with identical year-value tuples, the second is almost certainly
    # a restatement of the first (e.g. P&L "D&A" line + waterfall
    # "Total Depreciation Expense" — same numbers, different labels). Skip
    # the duplicate. Only applied to non-aggregator targets so genuine
    # aggregators (Salaries, Other OpEx) can still sum multiple rows.
    aggregator_targets = set(
        r.get("map_to") for r in agg_rules if r.get("map_to")
    )
    target_value_tuples: Dict[str, List[tuple]] = {}
    
    # Precompute normalized canonical targets
    fin_targets_norm = [(t, normalizer(t)) for t in financial_rows]
    bal_targets_norm = [(t, normalizer(t)) for t in balance_rows]
    
    pref_map_fin = build_pref_map(fin_aliases, normalizer)
    pref_map_bal = build_pref_map(bal_aliases, normalizer)
    
    # Aggregation triggers (normalized)
    agg_triggers = []
    for rule in agg_rules:
        mto = rule.get("map_to")
        trigs = [normalizer(x) for x in rule.get("triggers", [])]
        if mto and trigs:
            agg_triggers.append((mto, trigs))
    
    # Iterate rows
    for idx, row in df.iterrows():
        raw_label = safe_scalar(row.get(label_col, ""))
        raw_label = str(raw_label).strip()
        if raw_label == "" or raw_label.lower() == "nan":
            continue
        
        norm_label = normalizer(raw_label)

        # Skip dimensionless ratio/rate/growth rows BEFORE mapping. These would
        # otherwise fuzzy-match against absolute fields like Revenue or Salaries
        # at 75-90% confidence and contaminate the review queue.
        if is_ratio_row(raw_label):
            logger.debug("[RATIO SKIP] '%s' looks like a ratio/rate row; ignoring.", raw_label)
            ignored_labels.append(raw_label)
            continue

        # Ignore by keywords
        if any(tok in norm_label for tok in ignore_terms):
            ignored_labels.append(raw_label)
            continue
        
        # Alias preference
        preferred_target, section, pref_hit = prefer_alias(
            norm_label, pref_map_fin, pref_map_bal
        )
        
        # Fuzzy scores
        fin_best, fin_score = fuzzy_best(norm_label, fin_targets_norm, cfg.get("required_token_rules", {}))
        bal_best, bal_score = fuzzy_best(norm_label, bal_targets_norm, cfg.get("required_token_rules", {}))
        
        # Aggregation hint
        agg_best = None
        agg_bonus = 0
        for map_to, triggers in agg_triggers:
            if any(t in norm_label for t in triggers):
                agg_best = map_to
                agg_bonus = 0
                break
        
        # Choose target
        if pref_hit:
            target = preferred_target
            chosen_section = section
            score = 100
            logger.debug("[MAPPING] '%s' -> Preference hit: %s, score: %d", raw_label, target, score)
        else:
            fin_score2 = fin_score + (
                agg_bonus if agg_best in financial_rows and fin_best == agg_best else 0
            )
            bal_score2 = bal_score + (
                agg_bonus if agg_best in balance_rows and bal_best == agg_best else 0
            )
            
            # Debug output
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[MAPPING] Processing: '%s'", raw_label)
                logger.debug("  Financial: best=%s, base_score=%.1f, bonus=%d, final=%.1f",
                           fin_best, fin_score, 
                           agg_bonus if agg_best in financial_rows and fin_best == agg_best else 0,
                           fin_score2)
                logger.debug("  Balance: best=%s, base_score=%.1f, bonus=%d, final=%.1f",
                           bal_best, bal_score,
                           agg_bonus if agg_best in balance_rows and bal_best == agg_best else 0,
                           bal_score2)
                logger.debug("  Aggregation hint: %s", agg_best)
            
            if fin_score2 >= bal_score2:
                target = fin_best
                chosen_section = "financial"
                score = int(fin_score2)
                if agg_best in financial_rows and score_override(
                  norm_label, target, agg_best, normalizer
                ):
                  logger.debug("  Score override triggered: %s -> %s", target, agg_best)
                  target = agg_best
                  score = max(score, 85)  # Changed from 95 to 85 - goes to review
            else:
                target = bal_best
                chosen_section = "balance"
                score = int(bal_score2)
                if agg_best in balance_rows and score_override(
                    norm_label, target, agg_best, normalizer
                ):
                    logger.debug("  Score override triggered: %s -> %s", target, agg_best)
                    target = agg_best
                    score = max(score, 95)
            
            logger.debug("  FINAL: target=%s, section=%s, score=%d", target, chosen_section, score)
        
        # Apply exclusion patterns - penalize score if excluded terms found
        if apply_exclusions(norm_label, target, exclusion_patterns):
            logger.debug("[EXCLUSION] '%s' excluded from '%s' - applying penalty", raw_label, target)
            score = max(0, score - 30)  # Heavy penalty, likely drops below threshold
        
        # Thresholds
        if score < rev_thr:
            ignored_labels.append(raw_label)
            continue
        elif rev_thr <= score < auto_thr:
            review.append({
                "source_label": raw_label,
                "suggested_target": target,
                "confidence": score,
                "section": chosen_section
            })
            continue

        # Dedup: if this exact (normalized_label, target) pair has already been
        # auto-applied in this import, skip it. Prevents the same logical line
        # (e.g. "Total Revenue") from being counted multiple times when it
        # appears in several stacked sub-tables on one sheet.
        dedup_key = (norm_label, target, chosen_section)
        if dedup_key in seen_mappings:
            logger.debug("[DEDUP] Skipping duplicate '%s' -> %s (already applied)",
                         raw_label, target)
            ignored_labels.append(raw_label)
            continue
        seen_mappings.add(dedup_key)

        # Extract values
        row_vals = extract_row_values(row, year_map, years_used)
        
        # NEW: Check if row has no numeric data (empty category header)
        has_data = any(
            parse_number_positive(v)[0] is not None 
            for v in row_vals
        )
        
        if not has_data:
            logger.debug("[AGGREGATE CHECK] '%s' has no data - looking for aggregate Total", raw_label)
            # Try to find aggregate Total below
            aggregate_vals = find_aggregate_total_for_empty_row(
                df=df,
                row_idx=df.index.get_loc(idx),
                label_col=label_col,
                year_map=year_map,
                years_used=years_used
            )
            
            if aggregate_vals:
                row_vals = aggregate_vals
                logger.debug("[AGGREGATE SUCCESS] Using aggregate Total for '%s'", raw_label)
            else:
                # No valid aggregate found - skip this row
                logger.debug("[AGGREGATE FAIL] No valid aggregate Total found for '%s'", raw_label)
                ignored_labels.append(raw_label)
                continue
        
        # Parse numbers -> positive
        parsed_vals: List[Optional[float]] = []
        for v in row_vals:
            num, coerced = parse_number_positive(v)
            parsed_vals.append(num)
            coerced_negatives += (1 if coerced else 0)

        # Value-level dedup for non-aggregator financial targets: if another row
        # already mapped to this target with year values that agree on every
        # overlapping (non-None) position, this row is a restatement of the
        # same data (e.g. P&L "D&A" line covering 5 forecast years + waterfall
        # "Total Depreciation Expense" covering 6 years — same numbers,
        # different gaps). Skip the duplicate.
        if chosen_section == "financial" and target not in aggregator_targets:
            val_tuple = tuple(
                round(v, 4) if v is not None else None for v in parsed_vals
            )
            non_none = sum(1 for v in val_tuple if v is not None)
            if non_none >= 2:
                existing = target_value_tuples.setdefault(target, [])
                is_duplicate = False
                for prev_tuple in existing:
                    # Compare overlapping (both non-None) positions
                    overlap = 0
                    conflict = False
                    for a, b in zip(val_tuple, prev_tuple):
                        if a is None or b is None:
                            continue
                        if abs(a - b) > 0.01:
                            conflict = True
                            break
                        overlap += 1
                    # Duplicate if at least 2 positions agree AND no conflicts
                    if not conflict and overlap >= 2:
                        is_duplicate = True
                        break
                if is_duplicate:
                    logger.debug(
                        "[VALUE DEDUP] '%s' agrees on year values with a prior "
                        "row already mapped to '%s'; skipping duplicate.",
                        raw_label, target
                    )
                    ignored_labels.append(raw_label)
                    continue
                existing.append(val_tuple)

        # Aggregate into outputs + audit
        auto_map_log.append((raw_label, target, chosen_section))
        
        if chosen_section == "financial":
            prev_and_years = financial_accum.setdefault(
                target, [None] * expected_len
            )
            financial_accum[target] = sum_series(prev_and_years, parsed_vals)
            
            # Record explicit aggregations
            if target == "Other Operating Expenses" and raw_label not in aggregated_into.get(target, []):
                aggregated_into.setdefault(target, []).append(raw_label)
        else:
            cur_val = parsed_vals[0] if parsed_vals else None
            if balance_values.get(target) is None:
                balance_values[target] = cur_val
            else:
                balance_values[target] = safe_add(balance_values[target], cur_val)
    
    return {
        'financial': financial_accum,
        'balance': balance_values,
        'review': review,
        'auto_map_log': auto_map_log,
        'aggregated_into': aggregated_into,
        'ignored_labels': ignored_labels,
        'coerced_negatives': coerced_negatives
    }

def apply_manual_mappings(
    df,
    label_col: str,
    year_map: Dict[str, str],
    years_used: int,
    manual_mappings: List[dict],
    current_financial: dict,
    current_balance: dict
) -> Tuple[dict, dict]:
    """
    Apply user-approved mappings from the review dialog.
    
    Parameters
    ----------
    df : pd.DataFrame
        Original data table
    label_col : str
        Column with row labels
    year_map : Dict[str, str]
        Year column mapping
    years_used : int
        Number of forecast years
    manual_mappings : List[dict]
        User selections: [{"source": "Operations", "target": "Other Operating Expenses", "section": "financial"}, ...]
    current_financial : dict
        Existing financial data to update
    current_balance : dict
        Existing balance data to update
    
    Returns
    -------
    Tuple[dict, dict]
        (updated_financial, updated_balance)
    """
    has_previous = "previous" in year_map
    expected_len = (1 + years_used) if has_previous else years_used
    
    # Make copies to avoid modifying originals
    financial_data = {k: list(v) for k, v in current_financial.items()}
    balance_data = current_balance.copy()
    
    for mapping in manual_mappings:
        source_label = mapping["source"]
        target = mapping["target"]
        section = mapping["section"]
        
        # Find the row in the dataframe
        row_match = df[df[label_col].astype(str).str.strip() == source_label]
        if row_match.empty:
            logger.warning("Could not find row for '%s'", source_label)
            continue
        
        row = row_match.iloc[0]
        
        # Extract values
        row_vals = extract_row_values(row, year_map, years_used)
        
        # Parse numbers
        parsed_vals = []
        for v in row_vals:
            num, _ = parse_number_positive(v)
            parsed_vals.append(num)
        
        # Apply mapping
        if section == "financial":
            prev_vals = financial_data.get(target, [None] * expected_len)
            financial_data[target] = sum_series(prev_vals, parsed_vals)
            logger.debug("[MANUAL MAP] '%s' → '%s' (financial)", source_label, target)
        else:
            cur_val = parsed_vals[0] if parsed_vals else None
            if balance_data.get(target) is None:
                balance_data[target] = cur_val
            else:
                balance_data[target] = safe_add(balance_data[target], cur_val)
            logger.debug("[MANUAL MAP] '%s' → '%s' (balance)", source_label, target)
    
    return financial_data, balance_data

def extract_row_values(
    row,
    year_map: Dict[str, str],
    years_used: int
) -> List[object]:
    """
    Extract values for Previous + Y1..Yn from a row.
    
    Parameters
    ----------
    row : pd.Series
        DataFrame row
    year_map : Dict[str, str]
        Mapping from 'previous', 'y1', etc. to column names
    years_used : int
        Number of forecast years
    
    Returns
    -------
    List[object]
        [prev_val, y1_val, y2_val, ...] if 'previous' in year_map
        [y1_val, y2_val, ...] if 'previous' not in year_map
    """
    out = []
    
    # Only extract previous if it exists in the mapping
    if "previous" in year_map:
        prev_col = year_map.get("previous")
        out.append(row.get(prev_col, None))
    
    # Extract forecast years
    for i in range(1, years_used + 1):
        col = year_map.get(f"y{i}")
        out.append(row.get(col, None))
    
    return out