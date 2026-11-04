"""HTTP: the DATEX II feed, and OSRM for a route's line."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging

import aiohttp

from .const import DATEX_SITUATION_URL, OSRM_ROUTE_URL, USER_AGENT, VERSION

_LOGGER = logging.getLogger(__name__)

DATEX_TIMEOUT = aiohttp.ClientTimeout(total=90)
CLOCK_MARGIN = timedelta(seconds=30)

# Ways of asking for the feed, plainest last. All ask for any content type
# and only gzip/deflate: aiohttp on Python 3.14 also offers zstd by default,
# which not every server or firewall takes kindly to. The second is exactly
# what Statens vegvesen's own Python examples send; the last asks for no
# compression at all.
HEADER_PROFILES: tuple[dict[str, str], ...] = (
    {"Accept": "*/*", "Accept-Encoding": "gzip, deflate", "User-Agent": f"vegvarsel-homeassistant/{VERSION}"},
    {"Accept": "*/*", "Accept-Encoding": "gzip, deflate", "User-Agent": "python-requests/2.32.3"},
    {"Accept": "*/*", "Accept-Encoding": "identity", "User-Agent": "python-requests/2.32.3"},
)
OSRM_TIMEOUT = aiohttp.ClientTimeout(total=30)


class DatexError(Exception):
    """The feed could not be read."""


class DatexAuthError(DatexError):
    """The feed refused the username or password."""


class RoutingError(Exception):
    """No route could be found."""


class DatexClient:
    """Pulls the situation publication, only downloading it when it changed."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str, url: str = DATEX_SITUATION_URL) -> None:
        self._session = session
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        self._authorization = f"Basic {token}"
        self._url = url
        self._since: str | None = None
        self._etag: str | None = None
        self._profile = 0  # which of HEADER_PROFILES the server last accepted

    def _headers(self, profile: int) -> dict[str, str]:
        headers = {"Authorization": self._authorization, **HEADER_PROFILES[profile]}
        if self._since:
            headers["If-Modified-Since"] = self._since
        if self._etag:
            headers["If-None-Match"] = self._etag
        return headers

    async def async_fetch(self) -> bytes | None:
        """The publication, or None when it has not changed since the last fetch.

        Statens vegvesen answers 304 to If-Modified-Since with an ISO 8601
        time (as their own examples send it) when nothing changed since then,
        else the whole publication. The time sent is when the previous
        download began, less a margin for clocks that disagree: an update is
        then fetched twice at worst, never missed.

        A 406 (Not Acceptable) once the login has been accepted means the
        server - or a firewall in front of it - did not like the request's
        headers; the plainer profiles are tried in turn, and the one that
        works is kept.
        """
        started = datetime.now(UTC) - CLOCK_MARGIN
        last_status = 0
        for profile in range(self._profile, len(HEADER_PROFILES)):
            try:
                async with self._session.get(self._url, headers=self._headers(profile), timeout=DATEX_TIMEOUT) as resp:
                    last_status = resp.status
                    if resp.status in (401, 403):
                        raise DatexAuthError(f"HTTP {resp.status}")
                    if resp.status == 406:
                        _LOGGER.debug("DATEX answered 406 to header profile %d", profile)
                        continue
                    if resp.status == 304:
                        self._profile = profile
                        return None
                    if resp.status != 200:
                        raise DatexError(f"HTTP {resp.status}")
                    body = await resp.read()
            except (TimeoutError, aiohttp.ClientError) as err:
                raise DatexError(str(err) or type(err).__name__) from err
            if profile != self._profile:
                _LOGGER.info("DATEX accepted header profile %d", profile)
            self._profile = profile
            self._since = started.isoformat(timespec="seconds")
            self._etag = resp.headers.get("ETag")
            return body
        raise DatexError(f"HTTP {last_status} (the server refused every way of asking)")


@dataclass
class Route:
    points: list[tuple[float, float]]  # (lat, lon)
    distance_m: float
    duration_s: float


async def async_osrm_route(session: aiohttp.ClientSession, stops: list[tuple[float, float]], url: str = OSRM_ROUTE_URL) -> Route:
    """The fastest driving route through the stops, from OSRM's public server.

    Asked once when a route is set up (and when it is recalculated), never on
    every poll - the public server is a shared, best-effort service.
    """
    return (await async_osrm_routes(session, stops, alternatives=False, url=url))[0]


async def async_osrm_routes(
    session: aiohttp.ClientSession,
    stops: list[tuple[float, float]],
    alternatives: bool = True,
    url: str = OSRM_ROUTE_URL,
) -> list[Route]:
    """The fastest route through the stops, and with `alternatives` up to two
    others OSRM suggests (it only offers them between two stops)."""
    if len(stops) < 2:
        raise RoutingError("a route needs a start and a destination")
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in stops)
    params = {"overview": "full", "geometries": "geojson", "steps": "false"}
    if alternatives:
        params["alternatives"] = "true"
    try:
        async with session.get(
            url + coords, params=params, headers={"User-Agent": USER_AGENT}, timeout=OSRM_TIMEOUT
        ) as resp:
            if resp.status != 200:
                raise RoutingError(f"HTTP {resp.status}")
            data = await resp.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError) as err:
        raise RoutingError(str(err) or type(err).__name__) from err
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(str(data.get("message") or data.get("code") or "no route"))
    routes = []
    for route in data["routes"][:3]:
        points = [(float(lat), float(lon)) for lon, lat in route["geometry"]["coordinates"]]
        if len(points) >= 2:
            routes.append(Route(points=points, distance_m=float(route["distance"]), duration_s=float(route["duration"])))
    if not routes:
        raise RoutingError("the route has no line")
    return routes
