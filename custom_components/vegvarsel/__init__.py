"""Vegvarsel: Norwegian road incidents (Statens vegvesen DATEX II) along
your own routes, as sensors, map markers and events to notify from."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.setup import async_when_setup

from .bundle import async_install_blueprints, async_register_card
from .card_api import async_register_commands
from .const import DOMAIN
from .coordinator import VegvarselConfigEntry, VegvarselCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.GEO_LOCATION, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Once for the domain: the card's commands, the card itself (when the
    frontend is there to serve it), and the blueprint."""
    hass.data.setdefault(DOMAIN, {})
    async_register_commands(hass)
    await async_install_blueprints(hass)

    async def _serve_card(hass: HomeAssistant, _component: str) -> None:
        try:
            await async_register_card(hass)
        except Exception:  # noqa: BLE001 - the sensors and alerts do not need the card
            _LOGGER.warning("Could not set up the Vegvarsel dashboard card", exc_info=True)

    async_when_setup(hass, "frontend", _serve_card)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VegvarselConfigEntry) -> bool:
    coordinator = VegvarselCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.async_start_clock()
    _remove_stale_devices(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: VegvarselConfigEntry) -> None:
    """A route added, changed or removed, or new options: start over."""
    await hass.config_entries.async_reload(entry.entry_id)


def _remove_stale_devices(hass: HomeAssistant, entry: VegvarselConfigEntry) -> None:
    """Devices of routes that were deleted."""
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        route_ids = {value for domain, value in device.identifiers if domain == DOMAIN}
        if route_ids and not route_ids & set(entry.subentries):
            registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VegvarselConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
