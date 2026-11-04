"""The card in the dashboards' own resource list.

A second way in, beside the extra module URL (see bundle.py): a dashboard
opened while Home Assistant is still starting is served before this
integration has added that URL, and would show "Configuration error" where the
card belongs until reloaded. A resource entry is read by the frontend from the
dashboards' own store after it connects, so it does not depend on timing. It is
the same URL character for character, so the browser imports one module.

Only the storage-mode list is written to; a YAML-mode list belongs to the
user's configuration. After the TomTom integration's lovelace_resource.py.
"""

from __future__ import annotations

from collections.abc import Iterable
import logging

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

LOVELACE_DOMAIN = "lovelace"
RESOURCE_TYPE_MODULE = "module"


def _collection(hass: HomeAssistant):
    data = hass.data.get(LOVELACE_DOMAIN)
    resources = getattr(data, "resources", None)
    if resources is None and isinstance(data, dict):
        resources = data.get("resources")
    # YAML mode has no create/update - which is also how the two are told apart.
    if resources is None or not hasattr(resources, "async_create_item"):
        return None
    return resources


def _ours(resources, paths: Iterable[str]) -> list[dict]:
    wanted = set(paths)
    return [item for item in resources.async_items() or [] if str(item.get("url", "")).split("?", 1)[0] in wanted]


async def async_register(hass: HomeAssistant, url: str, paths: Iterable[str]) -> None:
    """Leave the list with exactly one entry of ours, pointing at `url`."""
    resources = _collection(hass)
    if resources is None:
        return
    try:
        # Load the store first: items read before it reads as empty, and on
        # older Home Assistant a create on an unloaded list overwrote it.
        await resources.async_get_info()
        ours = _ours(resources, paths)
        if not ours:
            await resources.async_create_item({"res_type": RESOURCE_TYPE_MODULE, "url": url})
            return
        keep, *spares = ours
        if keep.get("url") != url or keep.get("type") != RESOURCE_TYPE_MODULE:
            await resources.async_update_item(keep["id"], {"res_type": RESOURCE_TYPE_MODULE, "url": url})
        for spare in spares:
            await resources.async_delete_item(spare["id"])
    except Exception:  # noqa: BLE001 - the card loads without this entry too
        _LOGGER.warning("Could not list the Vegvarsel card under the dashboard resources", exc_info=True)


async def async_unregister(hass: HomeAssistant, paths: Iterable[str]) -> None:
    """Take our entries back out, when the integration is removed."""
    resources = _collection(hass)
    if resources is None:
        return
    try:
        await resources.async_get_info()
        for item in _ours(resources, paths):
            await resources.async_delete_item(item["id"])
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Could not remove the Vegvarsel card from the dashboard resources", exc_info=True)
