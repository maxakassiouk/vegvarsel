"""Websocket commands the dashboard card talks to."""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
import voluptuous as vol

from . import places
from .api import RoutingError, async_osrm_routes
from .bundle import CARD_VERSION_KEY
from .const import (
    CONF_CORRIDOR,
    CONF_DAYS,
    CONF_DESTINATION,
    CONF_DISTANCE,
    CONF_DURATION,
    CONF_POINTS,
    CONF_PREVIEW,
    CONF_START,
    CONF_VIAS,
    CONF_WINDOWS,
    DEFAULT_CORRIDOR,
    DOMAIN,
    SUBENTRY_ROUTE,
)
from .coordinator import VegvarselCoordinator, match_payload
from .datex import Incident
from .geo import RouteLine
from .geo_location import shown
from .monitor import Match, RouteConfig, RouteMonitor
from .route_data import clean_settings, route_line
from .schedule import Schedule


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_card_version)
    websocket_api.async_register_command(hass, ws_routes)
    websocket_api.async_register_command(hass, ws_search)
    websocket_api.async_register_command(hass, ws_where)
    websocket_api.async_register_command(hass, ws_plan)
    websocket_api.async_register_command(hass, ws_save_route)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/card_version"})
@callback
def ws_card_version(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The version the card is served under now - asked by the loader after
    every reconnect, to swap in a newer card without a page reload."""
    connection.send_result(msg["id"], {"version": (hass.data.get(DOMAIN) or {}).get(CARD_VERSION_KEY) or 0})


def _coordinators(hass: HomeAssistant) -> list[VegvarselCoordinator]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED and isinstance(getattr(entry, "runtime_data", None), VegvarselCoordinator)
    ]


def route_info(coordinator: VegvarselCoordinator, route_id: str) -> dict[str, Any]:
    """Everything the card shows about one route."""
    entry = coordinator.config_entry
    subentry = entry.subentries[route_id]
    data = subentry.data
    state = coordinator.data.routes.get(route_id) if coordinator.data else None
    language = coordinator.hass.config.language
    focus = state.focus if state else None
    closure = state.next_closure if state else None
    return {
        "route_id": route_id,
        "entry_id": entry.entry_id,
        "name": subentry.title,
        "device_id": coordinator.device_id(route_id),
        "start": data.get(CONF_START),
        "destination": data.get(CONF_DESTINATION),
        "vias": data.get(CONF_VIAS) or [],
        "points": data.get(CONF_POINTS) or [],
        "distance_m": data.get(CONF_DISTANCE),
        "duration_s": data.get(CONF_DURATION),
        "corridor_m": data.get(CONF_CORRIDOR, DEFAULT_CORRIDOR),
        "days": data.get(CONF_DAYS) or [],
        "windows": data.get(CONF_WINDOWS) or [],
        "preview": data.get(CONF_PREVIEW),
        "problem": bool(state and state.problem),
        "in_window": bool(state and state.in_window),
        "watching_from": focus[0].isoformat() if focus else None,
        "watching_until": focus[1].isoformat() if focus else None,
        "next_closure": match_payload(closure, language) if closure else None,
        "incidents": [match_payload(m, language) for m in shown(state)] if state else [],
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/routes"})
@callback
def ws_routes(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    routes = [
        route_info(coordinator, route_id)
        for coordinator in _coordinators(hass)
        for route_id, subentry in coordinator.config_entry.subentries.items()
        if subentry.subentry_type == SUBENTRY_ROUTE and route_id in coordinator.monitors
    ]
    result: dict[str, Any] = {"routes": routes}
    # Right after a restart the account is still on its first download:
    # say so, rather than "no routes".
    if any(entry.state is not ConfigEntryState.LOADED for entry in hass.config_entries.async_entries(DOMAIN)) and not routes:
        result["starting"] = True
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/search", vol.Required("text"): str, vol.Optional("limit", default=6): vol.All(int, vol.Range(1, 15))}
)
@websocket_api.async_response
async def ws_search(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    near = (hass.config.latitude, hass.config.longitude) if hass.config.latitude is not None else None
    found = await places.async_search(async_get_clientsession(hass), msg["text"], msg["limit"], near)
    connection.send_result(msg["id"], {"places": found})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/where",
        vol.Required("latitude"): vol.Coerce(float),
        vol.Required("longitude"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def ws_where(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The nearest address to a point - to name a stop picked on the map."""
    label = await places.async_where(async_get_clientsession(hass), msg["latitude"], msg["longitude"])
    connection.send_result(msg["id"], {"label": label})


# --- planning and saving ----------------------------------------------------------

PLACE = vol.Schema(
    {
        vol.Required("latitude"): vol.Coerce(float),
        vol.Required("longitude"): vol.Coerce(float),
        vol.Optional("label", default=""): str,
    },
    extra=vol.REMOVE_EXTRA,
)
POINT = vol.All([vol.Coerce(float)], vol.Length(min=2, max=2))


def _place(place: dict[str, Any]) -> dict[str, Any]:
    lat, lon = round(place["latitude"], 6), round(place["longitude"], 6)
    return {"latitude": lat, "longitude": lon, "label": place.get("label") or f"{lat:.5f}, {lon:.5f}"}


def _on_route(incidents: list[Incident], points: list[tuple[float, float]], corridor: float, now) -> list[Match]:
    """Every situation on a line within the coming two weeks, its most serious
    record each, in driving order."""
    monitor = RouteMonitor(RouteConfig("plan", "plan", RouteLine(points), corridor, Schedule()))
    monitor.update(incidents, now)
    best: dict[str, Match] = {}
    for m in monitor.state.on_route:
        if m.key not in best or m.incident.rank > best[m.key].incident.rank:
            best[m.key] = m
    return sorted(best.values(), key=lambda m: m.along_m)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/plan",
        vol.Required("stops"): [PLACE],
        vol.Optional("corridor_m", default=DEFAULT_CORRIDOR): vol.All(vol.Coerce(int), vol.Range(30, 1000)),
    }
)
@websocket_api.async_response
async def ws_plan(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """A route through the stops, with OSRM's alternatives, and what is on each."""
    stops = msg["stops"]
    if len(stops) < 2:
        connection.send_error(msg["id"], "invalid_stops", "A route needs a start and a destination")
        return
    try:
        routes = await async_osrm_routes(
            async_get_clientsession(hass), [(p["latitude"], p["longitude"]) for p in stops], alternatives=True
        )
    except RoutingError as err:
        connection.send_error(msg["id"], "no_route", f"No route found: {err}")
        return
    incidents: list[Incident] = []
    for coordinator in _coordinators(hass):
        if coordinator.data:
            incidents.extend(coordinator.data.incidents)
    now = dt_util.now()
    language = hass.config.language
    result = []
    for route in routes:
        line = route_line(route.points)
        matches = await hass.async_add_executor_job(
            _on_route, incidents, [(p[0], p[1]) for p in line], float(msg["corridor_m"]), now
        )
        result.append(
            {
                "points": line,
                "distance_m": round(route.distance_m),
                "duration_s": round(route.duration_s),
                "incidents": [match_payload(m, language) for m in matches],
            }
        )
    connection.send_result(msg["id"], {"routes": result})


def _entry_for(hass: HomeAssistant, route_id: str | None, entry_id: str | None) -> ConfigEntry | None:
    entries = [c.config_entry for c in _coordinators(hass)]
    if route_id:
        return next((e for e in entries if route_id in e.subentries), None)
    if entry_id:
        return next((e for e in entries if e.entry_id == entry_id), None)
    return entries[0] if entries else None


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save_route",
        vol.Optional("route_id"): str,
        vol.Optional("entry_id"): str,
        vol.Required("name"): vol.All(str, vol.Strip, vol.Length(min=1, max=80)),
        vol.Required("start"): PLACE,
        vol.Required("destination"): PLACE,
        vol.Optional("vias", default=list): [PLACE],
        vol.Required("points"): vol.All([POINT], vol.Length(min=2)),
        vol.Required("distance_m"): vol.Coerce(float),
        vol.Required("duration_s"): vol.Coerce(float),
        vol.Optional("corridor_m", default=DEFAULT_CORRIDOR): vol.Coerce(int),
        vol.Required("days"): [str],
        vol.Optional("windows", default=list): [str],
        vol.Optional("preview"): vol.Any(None, str),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_route(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Create a route, or update one in place (same route, same device - so
    automations pointing at it keep working)."""
    route_id = msg.get("route_id")
    entry = _entry_for(hass, route_id, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "No such Vegvarsel route or account")
        return
    settings, errors = clean_settings(
        {
            CONF_CORRIDOR: msg["corridor_m"],
            CONF_DAYS: msg["days"],
            CONF_WINDOWS: msg["windows"],
            CONF_PREVIEW: msg.get("preview"),
        }
    )
    if errors:
        detail = ", ".join(f"{field}: {code}" for field, code in errors.items())
        connection.send_error(msg["id"], "invalid_schedule", detail)
        return
    data = {
        CONF_START: _place(msg["start"]),
        CONF_DESTINATION: _place(msg["destination"]),
        CONF_VIAS: [_place(v) for v in msg["vias"]],
        CONF_POINTS: route_line(msg["points"]),
        CONF_DISTANCE: round(msg["distance_m"]),
        CONF_DURATION: round(msg["duration_s"]),
        **settings,
    }
    if route_id:
        subentry = entry.subentries[route_id]
        hass.config_entries.async_update_subentry(entry, subentry, title=msg["name"], data=data)
    else:
        subentry = ConfigSubentry(data=data, subentry_type=SUBENTRY_ROUTE, title=msg["name"], unique_id=None)
        hass.config_entries.async_add_subentry(entry, subentry)
        route_id = subentry.subentry_id
    connection.send_result(msg["id"], {"route_id": route_id})
