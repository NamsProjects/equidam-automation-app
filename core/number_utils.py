"""
core/number_utils.py


Shared number parsing utilities used by both importer and data_handler.
Ensures consistent handling of currency symbols, separators, and negative values.
"""


from typing import Optional, List, Tuple
import re




def parse_number_positive(value) -> Tuple[Optional[float], bool]:
    """
    Parse a value into a positive float, handling various formats.
   
    Handles:
    - Currency symbols: $, €, £
    - Thousand separators: commas, dots (EU style)
    - Decimal separators: period, comma
    - Negative indicators: leading minus, parentheses
    - Spaces
   
    Parameters
    ----------
    value : any
        The value to parse (can be str, int, float, None)
   
    Returns
    -------
    tuple of (Optional[float], bool)
        - Parsed positive number (or None if unparseable)
        - Whether a negative was coerced to positive
   
    Examples
    --------
    >>> parse_number_positive("-5,000")
    (5000.0, True)
    >>> parse_number_positive("($1,200)")
    (1200.0, True)
    >>> parse_number_positive("1.234,56")  # EU style
    (1234.56, False)
    >>> parse_number_positive("invalid")
    (None, False)
    """
    coerced_negative = False
   
    if value is None:
        return None, coerced_negative


    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None, coerced_negative


    # Handle parentheses notation for negatives: (123) -> -123
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
        coerced_negative = True


    # Remove spaces and currency symbols
    s = s.replace(" ", "")
    s = s.replace("$", "").replace("€", "").replace("£", "")


    # Determine separator style
    # If both comma and dot exist, infer which is thousands vs decimal
    if "," in s and "." in s:
        # EU style: 1.234.567,89 (dots = thousands, comma = decimal)
        if s.find(".") < s.find(","):
            s = s.replace(".", "").replace(",", ".")
        # US style: 1,234,567.89 (commas = thousands, dot = decimal)
        else:
            s = s.replace(",", "")
    else:
        # Only one separator present
        # Check if it's likely a decimal separator (e.g., 12,5 or 12.5)
        # vs thousands separator (e.g., 1,000 or 1.000)
        if "," in s:
            # Pattern like 12,5 or 12,50 suggests decimal comma
            if re.match(r"^-?\d+,\d{1,2}$", s):
                s = s.replace(",", ".")
            else:
                # Otherwise assume thousands separator
                s = s.replace(",", "")
       
        # Handle multiple dots (thousands): 1.234.567 -> 1234567
        if s.count(".") > 1:
            s = s.replace(".", "")


    # Check for leading minus (not already caught by parentheses)
    if s.startswith("-"):
        coerced_negative = True
        s = s[1:]  # Remove the minus sign


    try:
        f = float(s)
        # Always return positive
        f = abs(f)
        # Return as int if it's a whole number
        return (int(f) if f.is_integer() else f), coerced_negative
    except (ValueError, TypeError):
        return None, coerced_negative




def safe_add(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """
    Add two values, treating None as "no value" (not zero).
   
    Parameters
    ----------
    a, b : Optional[float]
        Values to add
   
    Returns
    -------
    Optional[float]
        - None if both are None
        - a if b is None (and vice versa)
        - a + b otherwise
    """
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None:
        return a
    return a + b




def sum_series(a: List[Optional[float]], b: List[Optional[float]]) -> List[Optional[float]]:
    """
    Element-wise addition of two lists, using safe_add logic.
   
    Parameters
    ----------
    a, b : List[Optional[float]]
        Lists to add element-wise
   
    Returns
    -------
    List[Optional[float]]
        Result of element-wise addition, length = max(len(a), len(b))
   
    Examples
    --------
    >>> sum_series([1, 2, None], [3, None, 5])
    [4, 2, 5]
    """
    out = []
    n = max(len(a), len(b))
    for i in range(n):
        va = a[i] if i < len(a) else None
        vb = b[i] if i < len(b) else None
        out.append(safe_add(va, vb))
    return out




def safe_scalar(val):
    """
    Extract a scalar value from a pandas Series if needed.
   
    Sometimes pandas returns a Series when we expect a scalar.
    This helper extracts the first non-empty value from a Series,
    or returns the value as-is if it's already a scalar.
   
    Parameters
    ----------
    val : any
        Value that might be a Series or scalar
   
    Returns
    -------
    Scalar value (str, int, float, etc.) or empty string
    """
    # Check if it's a pandas Series (without importing pandas here)
    if hasattr(val, '__iter__') and hasattr(val, 'iloc'):
        # It's Series-like, extract first non-empty value
        for x in val:
            sx = str(x).strip()
            if sx != "" and sx.lower() != "nan":
                return x
        return ""
    return val




def looks_like_text(x) -> bool:
    """
    Check if a value looks like text (contains letters).
   
    Used to distinguish label columns from numeric columns.
   
    Parameters
    ----------
    x : any
        Value to check
   
    Returns
    -------
    bool
        True if value contains at least one letter
    """
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return False
    return bool(re.search(r"[A-Za-z]", s))




def looks_like_year(x) -> bool:
    """
    Check if a value looks like a year indicator.
   
    Matches patterns like:
    - "Year 1", "Y1", "year1"
    - "Previous", "Prev"
    - Absolute years: "2024", "2025"
   
    Parameters
    ----------
    x : any
        Value to check
   
    Returns
    -------
    bool
        True if value matches year patterns
    """
    s = str(x).strip().lower()
   
    # Named year patterns
    if re.search(r"\byear\s*\d\b", s) or re.search(r"\by\d\b", s):
        return True
    if "previous" in s or "prev" in s:
        return True
   
    # Absolute year (1900-2199)
    if re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", s):
        return True
   
    return False

