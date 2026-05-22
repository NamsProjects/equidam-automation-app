"""
template_loader.py
Handles loading a fresh copy of the official Equidam template.
We always write into a copy of this file to preserve Equidam’s original headers.
"""

from pathlib import Path
import shutil
from openpyxl import load_workbook

# Path to the official template (adjust if needed)
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "Equidam_Projections_Upload-Sample_Sheet.xlsx"


def get_template_copy(output_path: str):
    """
    Create a working copy of the official Equidam template.

    Parameters
    ----------
    output_path : str
        Where to save the copy that we’ll fill with user data.

    Returns
    -------
    wb : openpyxl.Workbook
        An openpyxl workbook loaded from the freshly-copied file.
    """
    src = TEMPLATE_PATH
    dst = Path(output_path)

    if not src.exists():
        raise FileNotFoundError(
            f"Equidam template not found at: {src}\n"
            "Make sure the official template file is present in /assets."
        )

    # Copy the pristine template to the target path
    shutil.copyfile(src, dst)

    # Load workbook from the copy (so we never modify the original)
    wb = load_workbook(dst)
    return wb
