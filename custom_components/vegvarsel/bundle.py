"""What the download brings with it: the dashboard card and the blueprint.

Both ship inside the integration folder and are put in place here, so an
installation has them the moment it has the integration - nothing to copy into
"www", no resource to add by hand, no blueprint to import. After the TomTom
integration's bundle.py.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.setup import async_when_setup

from .const import CARD_URL_BASE, DOMAIN
from .lovelace_resource import LOVELACE_DOMAIN, async_register as async_register_resource

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"
CARD_FILE = "vegvarsel-card.js"
CARD_LOADER_FILE = "vegvarsel-card-loader.js"
CARD_RESOURCE_PATHS = (f"{CARD_URL_BASE}/{CARD_FILE}", f"{CARD_URL_BASE}/{CARD_LOADER_FILE}")
CARD_VERSION_KEY = "card_version"

BLUEPRINT_SOURCE = Path(__file__).parent / "blueprints"
BLUEPRINT_STORE_KEY = f"{DOMAIN}.blueprints"
BLUEPRINT_STORE_VERSION = 1


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card and its loader, and have every dashboard load it."""
    card = FRONTEND_DIR / CARD_FILE
    loader = FRONTEND_DIR / CARD_LOADER_FILE
    if not card.is_file() or not loader.is_file():
        _LOGGER.warning("The Vegvarsel dashboard card is missing from %s; everything else works", FRONTEND_DIR)
        return
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(f"{CARD_URL_BASE}/{CARD_FILE}", str(card), False),
            StaticPathConfig(f"{CARD_URL_BASE}/{CARD_LOADER_FILE}", str(loader), False),
        ]
    )

    # The version is the files' modification time, not the release: a card
    # copied in by hand changes it too, so browsers fetch the new file.
    def _newest() -> int:
        return int(max(card.stat().st_mtime, loader.stat().st_mtime))

    version = await hass.async_add_executor_job(_newest)
    hass.data.setdefault(DOMAIN, {})[CARD_VERSION_KEY] = version
    url = f"{CARD_URL_BASE}/{CARD_LOADER_FILE}?v={version}"
    add_extra_js_url(hass, url)

    async def _as_resource(hass: HomeAssistant, _component: str) -> None:
        await async_register_resource(hass, url, CARD_RESOURCE_PATHS)

    async_when_setup(hass, LOVELACE_DOMAIN, _as_resource)


# --- the blueprint ----------------------------------------------------------------


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def async_install_blueprints(hass: HomeAssistant, source_root: Path | None = None) -> None:
    """Put every bundled blueprint where Home Assistant looks.

    A missing one is installed. One already there is replaced by a newer
    shipped version only while it is still exactly what this integration put
    there; a copy the user changed is theirs and left alone.
    """
    source_root = source_root or BLUEPRINT_SOURCE
    target_root = Path(hass.config.path("blueprints"))
    store: Store[dict] = Store(hass, BLUEPRINT_STORE_VERSION, BLUEPRINT_STORE_KEY)
    known = (await store.async_load() or {}).get("installed") or {}
    seen = await hass.async_add_executor_job(_install, source_root, target_root, dict(known))
    if seen != known:
        await store.async_save({"installed": seen})


def _install(source_root: Path, target_root: Path, known: dict[str, str]) -> dict[str, str]:
    """`known` maps a blueprint's relative path to the digest of what we last
    wrote there; what comes back replaces it."""
    seen: dict[str, str] = {}
    for source in sorted(source_root.rglob("*.yaml")):
        relative = source.relative_to(source_root).as_posix()
        target = target_root / relative
        shipped = source.read_text(encoding="utf-8")
        try:
            if target.is_file():
                current = target.read_text(encoding="utf-8")
                ours = known.get(relative)
                if current == shipped or ours is None or _digest(current) != ours:
                    # identical, or not known to be ours (an old install, or
                    # edited by the user): leave it
                    seen[relative] = _digest(current) if current == shipped else known.get(relative, "")
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(shipped, encoding="utf-8")
            seen[relative] = _digest(shipped)
            _LOGGER.info("Installed blueprint %s", target)
        except OSError as err:
            _LOGGER.warning("Could not install blueprint %s: %s", target, err)
    return {k: v for k, v in seen.items() if v}
