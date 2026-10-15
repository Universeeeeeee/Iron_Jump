"""Dark-theme tokens for the application shell and migrated pages.

Values preserve the existing UI. Domain/chart colors and legacy Dayu widgets
remain local until their own migration. This module has no Qt dependency.
"""

from string import Template


PALETTE = {
    "background": "#0c1119",
    "sidebar": "#0e141d",
    "surface": "#121923",
    "surface_hover": "#151d28",
    "surface_selected": "#171f2b",
    "control": "#1a2230",
    "control_hover": "#232d3c",
    "control_stepper": "#242e3c",
    "control_disabled": "#242c37",
    "history_disabled": "#151c26",
    "menu": "#242936",
    "border_sidebar": "#26303d",
    "border_card": "#293442",
    "border_control": "#354151",
    "border_disabled": "#303946",
    "border_divider": "#2b3746",
    "border_menu": "rgba(105, 115, 135, 0.38)",
    "text": "#e7ebf2",
    "text_dialog": "#e8edf5",
    "text_body": "#dfe5ee",
    "text_button": "#d9dee8",
    "text_heading": "#f5f7fb",
    "text_heading_hover": "#f4f6f9",
    "text_summary_heading": "#f2f5f9",
    "text_detail_heading": "#f2f5fa",
    "text_card_heading": "#f0f3f7",
    "text_field": "#dce2eb",
    "text_subject": "#eef2f8",
    "text_secondary": "#aeb7c5",
    "text_muted": "#8f9bad",
    "text_hint": "#7f8a9a",
    "text_summary": "#c7cfdb",
    "text_summary_label": "#aeb8c7",
    "text_filter_detail": "#9eabba",
    "text_disabled": "#6f7a89",
    "text_history_disabled": "#677386",
    "accent": "#ff7a00",
    "accent_hover": "#ff8a1f",
    "accent_text": "#ff9a3d",
    "on_accent": "white",
    "success": "#67c98b",
    "warning": "#f0a24a",
    "danger": "#f06a6a",
    "status_text": "#8ecf78",
    "status_surface": "#132219",
    "status_border": "#294b32",
    "selection_popup": "#34445a",
    "selection_table": "#273446",
    "selection_table_row": "#26364a",
    "selection_menu": "rgba(255, 133, 15, 0.22)",
    "hover_subtle": "rgba(255, 255, 255, 0.05)",
    "table_grid": "#26313f",
    "table_header_text": "#9da8b8",
    "table_header_border": "#2b3543",
    "scroll_track": "#0c131d",
    "scroll_handle": "#3a485a",
    "scroll_handle_hover": "#4b5b6f",
}

# Numeric values can be used by layouts as well as rendered into QSS.
RADIUS = {"compact": 5, "control": 6, "action": 7, "card": 8}
SPACE = {
    "xxs": 2,
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "input": 9,
    "control": 10,
    "button": 14,
    "card": 18,
    "dialog": 20,
    "page_bottom": 22,
}


def qss(source: str, **fragments: str) -> str:
    """Render named tokens; misspellings fail immediately instead of reaching Qt."""
    return Template(source).substitute(
        PALETTE,
        **{f"radius_{name}": f"{value}px" for name, value in RADIUS.items()},
        **{f"space_{name}": f"{value}px" for name, value in SPACE.items()},
        **fragments,
    )
