from kitty.fast_data_types import get_boss
from kitty.tab_bar import TabBarData

from . import config


def get_current_mode() -> str:
    return get_boss().mappings.current_keyboard_mode_name or ""


def is_zoomed(tab: TabBarData | None) -> bool:
    return tab is not None and getattr(tab, "layout_name", "") == "stack"


def get_mode_name(tab: TabBarData | None = None) -> str:
    mode = get_current_mode()
    if mode == "" and is_zoomed(tab):
        return "zoom"
    return config.MODE_LABELS.get(mode, mode or "normal")
