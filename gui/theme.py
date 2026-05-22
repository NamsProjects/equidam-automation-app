"""
theme.py
Centralized design tokens and ttk.Style configuration for a cleaner UI.

Importers should:
    from gui.theme import apply_theme, COLORS, FONTS
    apply_theme(root)
"""

from tkinter import ttk
import tkinter.font as tkfont


COLORS = {
    # Surfaces
    "bg":            "#f5f7fb",
    "surface":       "#ffffff",
    "surface_alt":   "#eef1f7",
    "surface_hover": "#e6ebf3",

    # Borders & dividers
    "border":        "#d8deea",
    "border_strong": "#b8c1d3",

    # Brand / semantic
    "accent":        "#2563eb",
    "accent_hover":  "#1d4ed8",
    "accent_soft":   "#dbe7ff",
    "success":       "#16a34a",
    "success_soft":  "#dcfce7",
    "warning":       "#d97706",
    "warning_soft":  "#fef3c7",
    "danger":        "#dc2626",
    "danger_soft":   "#fee2e2",

    # Text
    "text":          "#111827",
    "text_muted":    "#6b7280",
    "text_soft":     "#9aa3b2",
    "text_on_accent":"#ffffff",
}


# Font family preference (first available wins on the host OS)
_PREFERRED_FAMILIES = ("Segoe UI Variable", "Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", "Arial")


def _pick_family(root):
    """Return the first preferred family that exists on this system."""
    available = set(tkfont.families(root))
    for fam in _PREFERRED_FAMILIES:
        if fam in available:
            return fam
    return "TkDefaultFont"


# Filled in by apply_theme()
FONTS = {
    "family":     "Segoe UI",
    "h1":         ("Segoe UI", 16, "bold"),
    "h2":         ("Segoe UI", 12, "bold"),
    "body":       ("Segoe UI", 10),
    "body_bold":  ("Segoe UI", 10, "bold"),
    "small":      ("Segoe UI", 9),
    "tiny":       ("Segoe UI", 8),
    "mono":       ("Consolas", 10),
}


def apply_theme(root):
    """Apply the cleaner ttk theme to the given root window."""
    family = _pick_family(root)
    FONTS["family"]    = family
    FONTS["h1"]        = (family, 16, "bold")
    FONTS["h2"]        = (family, 12, "bold")
    FONTS["body"]      = (family, 10)
    FONTS["body_bold"] = (family, 10, "bold")
    FONTS["small"]     = (family, 9)
    FONTS["tiny"]      = (family, 8)

    # Replace Tk's default fonts so untyped widgets pick up the new family
    for default_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont",
                         "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont",
                         "TkIconFont", "TkTooltipFont"):
        try:
            tkfont.nametofont(default_name).configure(family=family, size=10)
        except Exception:
            pass

    root.configure(background=COLORS["bg"])

    style = ttk.Style(root)
    # 'clam' lets us actually re-skin most ttk widgets on Windows
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # ── Base ───────────────────────────────────────────────────────────────
    style.configure(".",
        background=COLORS["bg"],
        foreground=COLORS["text"],
        fieldbackground=COLORS["surface"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        font=FONTS["body"],
    )

    # ── Frames ─────────────────────────────────────────────────────────────
    style.configure("TFrame",     background=COLORS["bg"])
    style.configure("Card.TFrame", background=COLORS["surface"], relief="flat", borderwidth=1)

    # ── Labels ─────────────────────────────────────────────────────────────
    style.configure("TLabel",       background=COLORS["bg"],     foreground=COLORS["text"], font=FONTS["body"])
    style.configure("Card.TLabel",  background=COLORS["surface"], foreground=COLORS["text"], font=FONTS["body"])
    style.configure("H1.TLabel",    background=COLORS["bg"],     foreground=COLORS["text"], font=FONTS["h1"])
    style.configure("H2.TLabel",    background=COLORS["bg"],     foreground=COLORS["text"], font=FONTS["h2"])
    style.configure("Muted.TLabel", background=COLORS["bg"],     foreground=COLORS["text_muted"], font=FONTS["small"])
    style.configure("Success.TLabel", background=COLORS["surface"], foreground=COLORS["success"], font=FONTS["body"])
    style.configure("Warning.TLabel", background=COLORS["surface"], foreground=COLORS["warning"], font=FONTS["body"])
    style.configure("Danger.TLabel",  background=COLORS["surface"], foreground=COLORS["danger"],  font=FONTS["body"])
    style.configure("Info.TLabel",    background=COLORS["surface"], foreground=COLORS["accent"],  font=FONTS["body"])
    style.configure("Note.TLabel",    background=COLORS["surface"], foreground=COLORS["text_muted"], font=FONTS["small"])

    # ── Buttons ────────────────────────────────────────────────────────────
    style.configure("TButton",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        focuscolor=COLORS["accent"],
        padding=(14, 7),
        font=FONTS["body"],
        relief="flat",
        borderwidth=1,
    )
    style.map("TButton",
        background=[("active", COLORS["surface_hover"]), ("disabled", COLORS["surface_alt"])],
        bordercolor=[("active", COLORS["border_strong"]), ("focus", COLORS["accent"])],
        foreground=[("disabled", COLORS["text_soft"])],
    )

    # Primary button
    style.configure("Accent.TButton",
        background=COLORS["accent"],
        foreground=COLORS["text_on_accent"],
        bordercolor=COLORS["accent"],
        padding=(16, 8),
        font=FONTS["body_bold"],
        relief="flat",
        borderwidth=0,
    )
    style.map("Accent.TButton",
        background=[("active", COLORS["accent_hover"]), ("disabled", COLORS["border"])],
        foreground=[("disabled", COLORS["text_soft"])],
    )

    # Subtle/ghost button
    style.configure("Ghost.TButton",
        background=COLORS["bg"],
        foreground=COLORS["text_muted"],
        bordercolor=COLORS["border"],
        padding=(12, 6),
        font=FONTS["body"],
        relief="flat",
        borderwidth=1,
    )
    style.map("Ghost.TButton",
        background=[("active", COLORS["surface_alt"])],
        foreground=[("active", COLORS["text"])],
        bordercolor=[("active", COLORS["border_strong"])],
    )

    # Danger button (used for Clear All)
    style.configure("Danger.TButton",
        background=COLORS["surface"],
        foreground=COLORS["danger"],
        bordercolor=COLORS["border"],
        padding=(14, 7),
        font=FONTS["body"],
        relief="flat",
        borderwidth=1,
    )
    style.map("Danger.TButton",
        background=[("active", COLORS["danger_soft"])],
        bordercolor=[("active", COLORS["danger"])],
    )

    # ── Inputs ─────────────────────────────────────────────────────────────
    style.configure("TEntry",
        fieldbackground=COLORS["surface"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        padding=6,
        insertcolor=COLORS["accent"],
    )
    style.map("TEntry",
        bordercolor=[("focus", COLORS["accent"])],
        lightcolor=[("focus", COLORS["accent"])],
        darkcolor=[("focus", COLORS["accent"])],
    )

    style.configure("TCombobox",
        fieldbackground=COLORS["surface"],
        background=COLORS["surface"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        arrowcolor=COLORS["text_muted"],
        padding=5,
    )

    # ── Checkbutton / Radiobutton ──────────────────────────────────────────
    style.configure("TCheckbutton",
        background=COLORS["bg"],
        foreground=COLORS["text"],
        font=FONTS["body"],
        focuscolor=COLORS["accent"],
    )
    style.map("TCheckbutton",
        background=[("active", COLORS["bg"])],
        foreground=[("disabled", COLORS["text_soft"])],
    )
    style.configure("Card.TCheckbutton",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        font=FONTS["body"],
    )
    style.map("Card.TCheckbutton",
        background=[("active", COLORS["surface"])],
    )

    style.configure("TRadiobutton",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        font=FONTS["body"],
    )
    style.map("TRadiobutton",
        background=[("active", COLORS["surface"])],
    )

    # ── LabelFrame ─────────────────────────────────────────────────────────
    style.configure("TLabelframe",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        relief="solid",
        borderwidth=1,
        padding=10,
    )
    style.configure("TLabelframe.Label",
        background=COLORS["bg"],
        foreground=COLORS["text"],
        font=FONTS["body_bold"],
        padding=(4, 0),
    )

    # Conflict-resolution field card
    style.configure("Field.TLabelframe",
        background=COLORS["surface_alt"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        relief="solid",
        borderwidth=1,
        padding=10,
    )
    style.configure("Field.TLabelframe.Label",
        background=COLORS["bg"],
        foreground=COLORS["accent"],
        font=FONTS["body_bold"],
    )

    # ── Scrollbar ──────────────────────────────────────────────────────────
    style.configure("Vertical.TScrollbar",
        background=COLORS["bg"],
        troughcolor=COLORS["bg"],
        bordercolor=COLORS["bg"],
        arrowcolor=COLORS["text_muted"],
        gripcount=0,
    )
    style.map("Vertical.TScrollbar",
        background=[("active", COLORS["border_strong"]), ("!active", COLORS["border"])],
    )
    style.configure("Horizontal.TScrollbar",
        background=COLORS["bg"],
        troughcolor=COLORS["bg"],
        bordercolor=COLORS["bg"],
        arrowcolor=COLORS["text_muted"],
        gripcount=0,
    )
    style.map("Horizontal.TScrollbar",
        background=[("active", COLORS["border_strong"]), ("!active", COLORS["border"])],
    )

    # ── Separator ──────────────────────────────────────────────────────────
    style.configure("TSeparator", background=COLORS["border"])

    return style
