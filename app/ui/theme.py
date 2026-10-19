"""Brand tokens taken from mcalignerdev.com (navy base, gold primary, periwinkle secondary).

Colors and fonts live only here, including the styling for ttk tables.
"""

import sys
from tkinter import ttk

import customtkinter as ctk

# Surfaces
BG = "#0B0F19"          # site background / MJC mark backdrop
SIDEBAR = "#070B14"     # site theme-color, a step darker
SURFACE = "#121826"
SURFACE_2 = "#182033"
BORDER = "#232C40"
BORDER_STRONG = "#334061"

# Text
TEXT = "#F2F4F8"
MUTED = "#8B93A7"
FAINT = "#5B6479"

# Brand
GOLD = "#D39A1A"
GOLD_HOVER = "#E6AE2F"
GOLD_SOFT = "#2A2213"   # gold tint on navy, for selected states
ON_GOLD = "#0B0F19"
BLUE = "#6E8CFF"
BLUE_SOFT = "#1A2240"

# Status
SUCCESS = "#3FB984"
WARNING = "#E8A33D"
DANGER = "#F0616D"
DANGER_HOVER = "#F47C86"
DANGER_SOFT = "#2C1519"

RADIUS = 10

if sys.platform == "win32":
    FAMILY, MONO = "Segoe UI", "Cascadia Mono"
elif sys.platform == "darwin":
    FAMILY, MONO = "SF Pro Text", "Menlo"
else:
    FAMILY, MONO = "DejaVu Sans", "DejaVu Sans Mono"


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)


def mono(size: int = 12) -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO, size=size)


def apply() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")


def style_tables(root) -> None:
    """Dark ttk.Treeview styling to match the CustomTkinter widgets."""
    scale = ctk.ScalingTracker.get_widget_scaling(root)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Cleaner.Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=TEXT, bordercolor=BORDER, lightcolor=SURFACE, darkcolor=SURFACE,
                    rowheight=int(30 * scale), font=(FAMILY, 10), borderwidth=0, relief="flat")
    style.map("Cleaner.Treeview",
              background=[("selected", GOLD_SOFT)], foreground=[("selected", TEXT)])
    style.configure("Cleaner.Treeview.Heading", background=SURFACE_2, foreground=MUTED,
                    bordercolor=BORDER, lightcolor=SURFACE_2, darkcolor=SURFACE_2,
                    relief="flat", font=(FAMILY, 9, "bold"), padding=(8, int(4 * scale)))
    style.map("Cleaner.Treeview.Heading", background=[("active", BORDER_STRONG)])
    style.layout("Cleaner.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])


# Row tags used by tables
TAGS = {
    "group": {"background": SURFACE_2, "foreground": TEXT, "font": (FAMILY, 10, "bold")},
    "marked": {"foreground": DANGER},
    "keep": {"foreground": SUCCESS},
    "muted": {"foreground": MUTED},
    "warn": {"foreground": WARNING},
    "undone": {"foreground": FAINT},
}

BAR_FULL, BAR_EMPTY = "█", "░"
