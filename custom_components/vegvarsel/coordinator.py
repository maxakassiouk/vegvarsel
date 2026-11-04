"""One poll of the DATEX feed per account, shared by every route under it.

The feed covers all of Norway, so it is fetched once and every route's
monitor looks through the same incidents. The monitors run on every poll -
also when the feed has not changed - because what matters to a route moves
with the clock: a window opens, an evening preview is due.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any
from xml.etree.ElementTree import ParseError

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import DatexAuthError, DatexClient, DatexError
from .const import (
    CONF_CORRIDOR,
    CONF_DAYS,
    CONF_POINTS,
    CONF_PREVIEW,
    CONF_SCAN_MINUTES,
    CONF_WINDOWS,
    DATEX_SITUATION_URL,
    DEFAULT_CORRIDOR,
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
    EVENT_CLEARED,
    EVENT_DIGEST,
    EVENT_NEW,
    EVENT_UPDATED,
    FAILURES_FOR_REPAIR,
    SUBENTRY_ROUTE,
    kind_label,
)
from .datex import Incident, parse_situations
from .geo import RouteLine
from .monitor import Match, RouteConfig, RouteEvent, RouteMonitor, RouteState
from .schedule import Schedule

_LOGGER = logging.getLogger(__name__)

EVENT_TYPES = {"new": EVENT_NEW, "updated": EVENT_UPDATED, "cleared": EVENT_CLEARED}

type VegvarselConfigEntry = ConfigEntry[VegvarselCoordinator]


@dataclass
class FeedData:
    incidents: list[Incident] = field(default_factory=list)
    fetched_at: datetime | None = None
    routes: dict[str, RouteState] = field(default_factory=dict)


def route_config(subentry: ConfigSubentry) -> RouteConfig:
    data = subentry.data
    return RouteConfig(
        id=subentry.subentry_id,
        name=subentry.title,
        line=RouteLine([(float(p[0]), float(p[1])) for p in data[CONF_POINTS]]),
        corridor_m=float(data.get(CONF_CORRIDOR, DEFAULT_CORRIDOR)),
        schedule=Schedule.from_config(data.get(CONF_DAYS), data.get(CONF_WINDOWS), data.get(CONF_PREVIEW) or None),
    )


class VegvarselCoordinator(DataUpdateCoordinator[FeedData]):
    config_entry: VegvarselConfigEntry

    def __init__(self, hass: HomeAssistant, entry: VegvarselConfigEntry) -> None:
        minutes = int(entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} feed",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = DatexClient(
            async_get_clientsession(hass),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            entry.data.get(CONF_URL, DATEX_SITUATION_URL),
        )
        self.monitors: dict[str, RouteMonitor] = {}
        for subentry in entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_ROUTE:
                continue
            try:
                self.monitors[subentry.subentry_id] = RouteMonitor(route_config(subentry))
            except (KeyError, ValueError) as err:
                _LOGGER.warning("Route %s is not usable and is skipped: %s", subentry.title, err)
        self._incidents: list[Incident] = []
        self._fetched_at: datetime | None = None
        self._failures = 0

    @property
    def repair_issue_id(self) -> str:
        return f"feed_failing_{self.config_entry.entry_id}"

    # --- the clock ------------------------------------------------------------

    @callback
    def async_start_clock(self) -> None:
        """Poll at the exact minute a window opens or a preview is due, so
        those messages are on time whatever the poll interval."""
        moments: set[tuple[int, int]] = set()
        for monitor in self.monitors.values():
            schedule = monitor.config.schedule
            moments.update((start.hour, start.minute) for start, _ in schedule.windows)
            if schedule.preview:
                moments.add((schedule.preview.hour, schedule.preview.minute))
        if not moments:
            return

        @callback
        def _tick(now: datetime) -> None:
            if (now.hour, now.minute) in moments:
                self.hass.async_create_task(self.async_request_refresh())

        self.config_entry.async_on_unload(async_track_time_change(self.hass, _tick, second=2))

    # --- the poll -------------------------------------------------------------

    async def _async_update_data(self) -> FeedData:
        try:
            payload = await self.client.async_fetch()
            if payload is not None:
                self._incidents = await self.hass.async_add_executor_job(parse_situations, payload)
                self._fetched_at = dt_util.utcnow()
                _LOGGER.debug("DATEX: %d situation records", len(self._incidents))
        except DatexAuthError as err:
            raise ConfigEntryAuthFailed("Statens vegvesen refused the DATEX username or password") from err
        except (DatexError, ParseError) as err:
            self._failed(err)
            raise UpdateFailed(f"Could not read the DATEX feed: {err}") from err
        self._recovered()

        now = dt_util.now()
        routes: dict[str, RouteState] = {}
        for route_id, monitor in self.monitors.items():
            for event in monitor.update(self._incidents, now):
                self._fire(route_id, monitor, event)
            routes[route_id] = monitor.state
        return FeedData(incidents=self._incidents, fetched_at=self._fetched_at, routes=routes)

    def _failed(self, err: Exception) -> None:
        self._failures += 1
        if self._failures == FAILURES_FOR_REPAIR:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self.repair_issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="feed_failing",
                translation_placeholders={"count": str(self._failures), "reason": str(err)},
            )

    def _recovered(self) -> None:
        if self._failures >= FAILURES_FOR_REPAIR:
            ir.async_delete_issue(self.hass, DOMAIN, self.repair_issue_id)
        self._failures = 0

    # --- events ---------------------------------------------------------------

    def device_id(self, route_id: str) -> str | None:
        registry = dr.async_get(self.hass)
        if hasattr(registry, "async_get_device_by_identifier"):  # HA 2026.10+
            device = registry.async_get_device_by_identifier((DOMAIN, route_id), self.config_entry.entry_id)
        else:
            device = registry.async_get_device(identifiers={(DOMAIN, route_id)})
        return device.id if device else None

    def _route_payload(self, route_id: str, monitor: RouteMonitor) -> dict[str, Any]:
        return {
            "config_entry_id": self.config_entry.entry_id,
            "route_id": route_id,
            "route": monitor.config.name,
            "device_id": self.device_id(route_id),
        }

    def _fire(self, route_id: str, monitor: RouteMonitor, event: RouteEvent) -> None:
        base = self._route_payload(route_id, monitor)
        language = self.hass.config.language
        if event.type in EVENT_TYPES:
            for match in event.matches:
                self.hass.bus.async_fire(EVENT_TYPES[event.type], base | match_payload(match, language))
            return
        items = [match_payload(m, language) for m in event.matches]
        self.hass.bus.async_fire(
            EVENT_DIGEST,
            base
            | {
                "reason": event.reason,
                "window_start": event.window[0].isoformat() if event.window else None,
                "window_end": event.window[1].isoformat() if event.window else None,
                "count": len(items),
                "incidents": items,
                "summary": "\n".join(i["summary"] for i in items),
            },
        )


def _iso(value: datetime | None) -> str | None:
    return dt_util.as_local(value).isoformat() if value else None


def summary_text(incident: Incident, language: str | None) -> str:
    """One line: "Road closed · Fv658 / Ellingsøytunnelen · Hessa → Ellingsøya — <comment>"."""
    place = " → ".join(incident.places[:2])
    head = " · ".join(p for p in (kind_label(incident.kind, language), incident.road, place) if p)
    return f"{head} — {incident.description}" if incident.description else head


def match_payload(match: Match, language: str | None) -> dict[str, Any]:
    incident = match.incident
    position = incident.position
    return {
        "id": match.key,  # the situation: stable while its records change
        "record_id": incident.id,
        "situation_id": incident.situation_id,
        "kind": incident.kind,
        "kind_name": kind_label(incident.kind, language),
        "rank": incident.rank,
        "road": incident.road,
        "places": list(incident.places),
        "description": incident.description,
        "summary": summary_text(incident, language),
        "applies_now": match.applies_now,
        "start": _iso(match.start),
        "end": _iso(match.end),
        "distance_km": round(match.along_m / 1000, 1),
        "latitude": position[0] if position else None,
        "longitude": position[1] if position else None,
    }
