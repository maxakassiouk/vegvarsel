"""Every incident that matters to a route, as a marker on the map. The state
is how far along the route it lies, in km - markers read like the trip."""

from __future__ import annotations

from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import slugify

from .const import ATTRIBUTION, DOMAIN, KIND_ICONS, kind_label
from .coordinator import VegvarselConfigEntry, VegvarselCoordinator, match_payload
from .entity import route_device
from .monitor import Match


def shown(state) -> list[Match]:
    """What a route marks: what lies over the trip at hand, plus anything on
    the route that applies right now."""
    out = {m.key: m for m in state.matches}
    for m in state.on_route:
        if m.applies_now and (m.key not in out or m.incident.rank > out[m.key].incident.rank):
            out[m.key] = m
    return sorted(out.values(), key=lambda m: m.along_m)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VegvarselConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    known: dict[tuple[str, str], IncidentMarker] = {}

    @callback
    def _sync() -> None:
        data = coordinator.data
        if data is None:
            return
        current: set[tuple[str, str]] = set()
        for route_id in coordinator.monitors:
            state = data.routes.get(route_id)
            if state is None:
                continue
            new = []
            for match in shown(state):
                key = (route_id, match.key)
                if match.incident.position is None:
                    continue
                current.add(key)
                if key in known:
                    known[key].apply(match)
                else:
                    known[key] = IncidentMarker(coordinator, route_id, match)
                    new.append(known[key])
            if new:
                async_add_entities(new, config_subentry_id=route_id)
        # Markers whose incident is gone, from this run and earlier ones.
        prefix = f"{DOMAIN}-marker-"
        for reg in list(er.async_entries_for_config_entry(registry, entry.entry_id)):
            if reg.domain != "geo_location" or not reg.unique_id.startswith(prefix):
                continue
            route_id, _, incident_id = reg.unique_id[len(prefix):].partition("|")
            if (route_id, incident_id) in current:
                continue
            known.pop((route_id, incident_id), None)
            registry.async_remove(reg.entity_id)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()


class IncidentMarker(GeolocationEvent):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, coordinator: VegvarselCoordinator, route_id: str, match: Match) -> None:
        name = coordinator.monitors[route_id].config.name
        self._coordinator = coordinator
        self._attr_source = f"{DOMAIN}_{slugify(name)}"
        self._attr_unique_id = f"{DOMAIN}-marker-{route_id}|{match.key}"
        self._attr_device_info = route_device(route_id, name)
        self._extra: dict[str, Any] = {}
        self.apply(match, write=False)

    def apply(self, match: Match, write: bool = True) -> None:
        incident = match.incident
        language = self._coordinator.hass.config.language
        self._attr_name = " · ".join(p for p in (kind_label(incident.kind, language), incident.road) if p)
        self._attr_icon = KIND_ICONS.get(incident.kind, KIND_ICONS["info"])
        self._attr_latitude, self._attr_longitude = incident.position
        self._attr_distance = round(match.along_m / 1000, 1)
        self._extra = match_payload(match, language)
        if write and self.hass:
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra
