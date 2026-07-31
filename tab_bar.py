from contextlib import suppress
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

_PACKAGE_DIR = Path(__file__).with_name("tab_bar")
_PACKAGE_NAME = "_kitty_tab_bar"


def _purge_previous() -> None:
    """Forget an earlier copy of the package so config reloads pick up edits.

    kitty re-runs this file on every ``load-config``, but the submodules stay
    cached in ``sys.modules``, so relative imports below would hand back the
    code as it was when kitty started. Dropping them makes
    ``kitten @ load-config`` a full reload of the tab bar. The old copy's
    repeating redraw timer is cancelled first, otherwise every reload would
    leave another one running.
    """
    stale = [
        name
        for name in sys.modules
        if name == _PACKAGE_NAME or name.startswith(f"{_PACKAGE_NAME}.")
    ]
    if not stale:
        return

    timer_id = getattr(sys.modules.get(f"{_PACKAGE_NAME}.layout"), "timer_id", None)
    if timer_id is not None:
        from kitty.fast_data_types import remove_timer

        with suppress(Exception):
            remove_timer(timer_id)

    for name in stale:
        del sys.modules[name]


_purge_previous()

_SPEC = spec_from_file_location(
    _PACKAGE_NAME,
    _PACKAGE_DIR / "__init__.py",
    submodule_search_locations=[str(_PACKAGE_DIR)],
)

if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load custom tab bar package from {_PACKAGE_DIR}")

_MODULE = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

draw_tab = _MODULE.draw_tab
