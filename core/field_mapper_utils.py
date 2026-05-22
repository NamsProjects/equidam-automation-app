"""
core/field_mapper_utils.py

Utilities for fuzzy matching, normalization, and alias resolution.
Provides helper functions for string matching and field mapping.
"""

from typing import Dict, List, Tuple
import re
import unicodedata
from unidecode import unidecode
from rapidfuzz import fuzz
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


def make_normalizer(ncfg: dict):
    """
    Create a normalization function based on config.
    
    Parameters
    ----------
    ncfg : dict
        Normalization config from aliases.json
    
    Returns
    -------
    callable
        Function that normalizes strings for matching
    """
    replace_map = ncfg.get("replace_map", {
        "&": " and ", "/": " ", "_": " ", "-": " "
    })
    acronyms = ncfg.get("acronyms", {})
    strip_chars = set(ncfg.get("strip_chars", ["$", "%"]))
    lower = bool(ncfg.get("lower", True))
    ascii_fold = bool(ncfg.get("ascii_fold", True))
    
    compiled_acronyms = []
    for short, full in acronyms.items():
        pattern = re.compile(
            r"(?<![a-z0-9])" + re.escape(short) + r"(?![a-z0-9])",
            re.IGNORECASE
        )
        compiled_acronyms.append((pattern, f" {full} "))
    
    @lru_cache(maxsize=4096)
    def normalize(s: str) -> str:
        s = "" if s is None else str(s)
        s = s.strip()
        if ascii_fold:
            s = unidecode(unicodedata.normalize("NFKD", s))
        if lower:
            s = s.lower()
        for k, v in replace_map.items():
            s = s.replace(k, v)
        s = "".join(ch for ch in s if ch not in strip_chars)
        s2 = f" {s} "
        
        for pattern, replacement in compiled_acronyms:
            s2 = pattern.sub(replacement, s2)
        
        s = re.sub(r"\s+", " ", s2).strip()
        return s
    
    return normalize


def build_pref_map(alias_dict: dict, normalizer) -> Dict[str, str]:
    """
    Build preference map from aliases.
    
    Parameters
    ----------
    alias_dict : dict
        {canonical_name: [alias1, alias2, ...]}
    normalizer : callable
        Normalization function
    
    Returns
    -------
    Dict[str, str]
        {normalized_alias: canonical_name}
    """
    pref = {}
    for canon, alist in alias_dict.items():
        for a in alist:
            pref[normalizer(a)] = canon
        pref[normalizer(canon)] = canon
    return pref


def prefer_alias(
    norm_label: str,
    pref_fin: Dict[str, str],
    pref_bal: Dict[str, str]
) -> Tuple[str, str, bool]:
    """
    Check if label matches a preferred alias.
    
    Parameters
    ----------
    norm_label : str
        Normalized source label
    pref_fin : Dict[str, str]
        Financial preference map
    pref_bal : Dict[str, str]
        Balance sheet preference map
    
    Returns
    -------
    Tuple[str, str, bool]
        (target_name, section, hit)
    """
    if norm_label in pref_fin:
        return pref_fin[norm_label], "financial", True
    if norm_label in pref_bal:
        return pref_bal[norm_label], "balance", True
    return "", "", False


def fuzzy_best(
    norm_label: str,
    targets_norm: List[Tuple[str, str]],
    required_token_rules: Dict[str, List[List[str]]] = None
) -> Tuple[str, float]:
    """
    Find best fuzzy match from list of targets.
    
    Uses max of WRatio, token_set_ratio, and partial_ratio with safety caps:
    - partial_ratio capped at 85 to prevent substring false positives
    - token_set_ratio capped at 85 for strict subset matches
    - Overall score capped at 90 if token counts differ
    - Required token combinations enforced for specific fields
    
    Parameters
    ----------
    norm_label : str
        Normalized source label
    targets_norm : List[Tuple[str, str]]
        [(canonical_name, normalized_name), ...]
    required_token_rules : Dict[str, List[List[str]]], optional
        Rules from aliases.json requiring specific token combinations.
    
    Returns
    -------
    Tuple[str, float]
        (best_target_name, score)
    """
    best_target = targets_norm[0][0]
    best_score = -1.0
    
    source_tokens = set(norm_label.split())
    required_token_rules = required_token_rules or {}
    targets_with_requirements = set(required_token_rules.keys())
    
    for canon, canon_norm in targets_norm:
        if norm_label == canon_norm:
            if canon in targets_with_requirements:
                token_requirements = required_token_rules[canon]
                match_found = False
                
                for required_tokens in token_requirements:
                    if all(req_token in norm_label for req_token in required_tokens):
                        match_found = True
                        break
                
                if not match_found:
                    logger.debug("Exact match failed token requirement: '%s' → '%s'", 
                               norm_label, canon)
                    continue
            
            logger.debug("Perfect match: '%s' → '%s'", norm_label, canon)
            return canon, 100.0
    
    for canon, canon_norm in targets_norm:
        target_tokens = set(canon_norm.split())
        
        if canon in targets_with_requirements:
            token_requirements = required_token_rules[canon]
            match_found = False
            
            for required_tokens in token_requirements:
                if all(req_token in norm_label for req_token in required_tokens):
                    match_found = True
                    break
            
            if not match_found:
                logger.debug("Token requirement failed: '%s' → '%s'", norm_label, canon)
                continue
        
        s1 = fuzz.WRatio(norm_label, canon_norm)
        
        if s1 < 50:
            s = s1
        else:
            s2 = fuzz.token_set_ratio(norm_label, canon_norm)
            s3 = fuzz.partial_ratio(norm_label, canon_norm)
            
            s3_capped = min(s3, 85)
            
            if source_tokens and source_tokens < target_tokens:
                s2 = min(s2, 85)
            
            s = max(s1, s2, s3_capped)
        
        if len(source_tokens) != len(target_tokens):
            s = min(s, 90)
        
        if s > best_score:
            best_score = s
            best_target = canon
            
            if s >= 95:
                logger.debug("Near-perfect match: '%s' → '%s' (score: %.1f)", 
                           norm_label, canon, s)
                return best_target, float(best_score)
    
    logger.debug("Best match: '%s' → '%s' (score: %.1f)", 
                norm_label, best_target, best_score)
    
    return best_target, float(best_score)


def score_override(
    norm_label: str,
    current: str,
    candidate: str,
    normalizer
) -> bool:
    """
    Check if candidate should override current target.
    
    Returns True if candidate scores significantly better (>5 points).
    
    Parameters
    ----------
    norm_label : str
        Normalized source label
    current : str
        Current best match
    candidate : str
        Candidate replacement
    normalizer : callable
        Normalization function
    
    Returns
    -------
    bool
        True if candidate should replace current
    """
    cur = normalizer(current)
    cand = normalizer(candidate)
    
    source_tokens = set(norm_label.split())
    cur_tokens = set(cur.split())
    cand_tokens = set(cand.split())
    
    s1_cur = fuzz.WRatio(norm_label, cur)
    s2_cur = fuzz.token_set_ratio(norm_label, cur)
    s3_cur = fuzz.partial_ratio(norm_label, cur)
    
    s3_cur_capped = min(s3_cur, 85)
    if source_tokens and source_tokens < cur_tokens:
        s2_cur = min(s2_cur, 85)
    
    s_cur = max(s1_cur, s2_cur, s3_cur_capped)
    
    if len(source_tokens) != len(cur_tokens):
        s_cur = min(s_cur, 90)
    
    s1_cand = fuzz.WRatio(norm_label, cand)
    s2_cand = fuzz.token_set_ratio(norm_label, cand)
    s3_cand = fuzz.partial_ratio(norm_label, cand)
    
    s3_cand_capped = min(s3_cand, 85)
    if source_tokens and source_tokens < cand_tokens:
        s2_cand = min(s2_cand, 85)
    
    s_cand = max(s1_cand, s2_cand, s3_cand_capped)
    
    if len(source_tokens) != len(cand_tokens):
        s_cand = min(s_cand, 90)
    
    return (s_cand - s_cur) > 5


def apply_exclusions(norm_label: str, target: str, exclusions: dict) -> bool:
    """
    Check if label should be excluded from mapping to target.
    
    Returns True if any exclusion pattern for this target is found in the label.
    
    Parameters
    ----------
    norm_label : str
        Normalized source label
    target : str
        Proposed target field name
    exclusions : dict
        {target_name: [exclusion_terms, ...]}
    
    Returns
    -------
    bool
        True if label should be excluded from this target
    """
    target_exclusions = exclusions.get(target, [])
    return any(excl in norm_label for excl in target_exclusions)


def is_junk_label(raw_label: str, norm_label: str) -> bool:
    """
    Check if a label is junk/garbage that should be filtered out early.
    
    Junk labels include:
    - Single digits: "0", "1", "2", etc.
    - Empty or whitespace-only strings
    - "nan", "null", "none"
    - Purely numeric strings (1-2 digits)
    
    Parameters
    ----------
    raw_label : str
        Original label before normalization
    norm_label : str
        Normalized label
    
    Returns
    -------
    bool
        True if label should be filtered out
    """
    if not raw_label or raw_label.isspace():
        return True
    
    if not norm_label:
        return True
    
    if len(norm_label) == 1 and norm_label.isdigit():
        return True
    
    JUNK_VALUES = {'nan', 'null', 'none', '#n/a', '#value', '#ref'}
    if norm_label in JUNK_VALUES:
        return True
    
    if norm_label.isdigit() and len(norm_label) <= 2:
        return True
    
    return False