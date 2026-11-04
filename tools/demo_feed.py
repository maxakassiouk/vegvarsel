"""A stand-in for Statens vegvesen's DATEX II situation feed, for trying
Vegvarsel in a real Home Assistant before you have DATEX access.

It serves Statens vegvesen's own published sample of the national feed with
its dates moved to the present (by whole weeks, so weekday rules still fall
on the right days), plus a few made-up situations around Ålesund that you
switch on and off from a web page - an accident in Ellingsøytunnelen, convoy
driving, night closures - so you can watch Vegvarsel's sensors, map markers
and notifications react.

    python tools/demo_feed.py              # the full national sample (~30 MB, downloaded once)
    python tools/demo_feed.py --small      # a small excerpt from the tests instead
    python tools/demo_feed.py --port 9000

Then open the address it prints in a browser. Any username and password are
accepted. Only the standard library is used. NOT Statens vegvesen's live data:
for testing only.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import socket
import threading
import urllib.request
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")
ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(__file__).resolve().parent / ".demo_cache"
SAMPLE_URL = (
    "https://git.vegvesen.no/projects/DATEX2/repos/datex2-spesifications/raw/3.1/samples/"
    "roadTrafficInformation/situations.xml?at=refs%2Fheads%2Fmaster"
)
SMALL_SAMPLE = ROOT / "tests" / "fixtures" / "npra_sample_excerpt.xml"
FEED_PATH = "/datexapi/GetSituation/pullsnapshotdata"

_DATETIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})(T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z))")
_VERSION_TIME = re.compile(r"situationRecordVersionTime>(\d{4}-\d{2}-\d{2})")
_LAST_SITUATION = re.compile(r"</(?:[A-Za-z0-9_]+:)?situation>")

# --- moving the sample to the present -------------------------------------------


def week_shift(text: str, today: date) -> int:
    """Whole weeks (in days) from the sample's newest record to today."""
    newest = max((date.fromisoformat(d) for d in _VERSION_TIME.findall(text)), default=today)
    return round((today - newest).days / 7) * 7


def shift_times(text: str, days: int) -> str:
    """Every xsd:dateTime moved by a number of days; times of day, fractions
    and offsets are left as they are written."""
    if not days:
        return text

    def _move(m: re.Match) -> str:
        moved = date(int(m[1]), int(m[2]), int(m[3])) + timedelta(days=days)
        return f"{moved.isoformat()}{m[4]}"

    return _DATETIME.sub(_move, text)


# --- made-up situations around Ålesund ------------------------------------------

# Points along the road through Ellingsøytunnelen and on towards Vigra (lat lon).
ELLINGSOY_TUNNEL = [
    (62.473818, 6.17647), (62.474954, 6.176929), (62.476004, 6.178353), (62.47817, 6.183241),
    (62.479129, 6.184304), (62.480448, 6.184893), (62.481785, 6.184587), (62.491485, 6.179711),
]  # fmt: skip
VALDEROY_STRETCH = [(62.51149, 6.100602), (62.5160, 6.1002), (62.521289, 6.099852)]
PARALLEL_ROAD = [(62.4866, 6.1890)]  # ~340 m off the route: should NOT alert

SCENARIOS = {
    "night_closures": "Ellingsøytunnelen closed at night (22:00-06:00, Mon-Thu, three weeks)",
    "accident": "Accident in Ellingsøytunnelen, tunnel closed (from now, no end given)",
    "convoy": "Convoy driving on Fv658 towards Vigra (from now, for two hours)",
    "parallel_roadworks": "Roadworks on a road ~340 m from the route (should NOT alert)",
}
DEFAULT_ON = {"night_closures"}

_NS = (
    'xmlns:sit="http://datex2.eu/schema/3/situation" xmlns:com="http://datex2.eu/schema/3/common" '
    'xmlns:loc="http://datex2.eu/schema/3/locationReferencing" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
)
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _record(
    rid: str,
    xsi: str,
    subtype_tag: str,
    subtype: str,
    note: str,
    place: str,
    road: str,
    line: list[tuple[float, float]],
    validity: str,
    version_time: datetime,
) -> str:
    pos = " ".join(f"{lat} {lon}" for lat, lon in line)
    mid = line[len(line) // 2]
    geometry = (
        f'<loc:gmlLineString srsName="4326"><loc:posList>{pos}</loc:posList></loc:gmlLineString>'
        if len(line) > 1
        else f"<loc:pointByCoordinates><loc:pointCoordinates><loc:latitude>{mid[0]}</loc:latitude>"
        f"<loc:longitude>{mid[1]}</loc:longitude></loc:pointCoordinates></loc:pointByCoordinates>"
    )
    return f"""<sit:situationRecord xsi:type="sit:{xsi}" id="{rid}" version="1">
  <sit:situationRecordCreationTime>{_iso(version_time)}</sit:situationRecordCreationTime>
  <sit:situationRecordVersionTime>{_iso(version_time)}</sit:situationRecordVersionTime>
  <sit:probabilityOfOccurrence>certain</sit:probabilityOfOccurrence>
  <sit:validity>{validity}</sit:validity>
  <sit:generalPublicComment><sit:comment><com:values><com:value lang="no">{html.escape(note)}</com:value></com:values></sit:comment>
    <sit:commentType>dataProcessingNote</sit:commentType></sit:generalPublicComment>
  <sit:locationReference xsi:type="loc:LocationGroupByList">
    <loc:locationContainedInGroup xsi:type="loc:LinearLocation">
      <loc:coordinatesForDisplay><loc:latitude>{mid[0]}</loc:latitude><loc:longitude>{mid[1]}</loc:longitude></loc:coordinatesForDisplay>
      <loc:supplementaryPositionalDescription>
        <loc:locationDescription><com:values><com:value lang="no">{html.escape(place)}</com:value></com:values></loc:locationDescription>
        <loc:roadInformation><loc:roadNumber>{road}</loc:roadNumber></loc:roadInformation>
      </loc:supplementaryPositionalDescription>
      {geometry}
    </loc:locationContainedInGroup>
  </sit:locationReference>
  <sit:{subtype_tag}>{subtype}</sit:{subtype_tag}>
</sit:situationRecord>"""


def _span(start: datetime, end: datetime | None) -> str:
    end_xml = f"<com:overallEndTime>{_iso(end)}</com:overallEndTime>" if end else ""
    return (
        "<com:validityStatus>definedByValidityTimeSpec</com:validityStatus><com:validityTimeSpecification>"
        f"<com:overallStartTime>{_iso(start)}</com:overallStartTime>{end_xml}</com:validityTimeSpecification>"
    )


def _nightly(start: datetime, end: datetime) -> str:
    def period(p_start: datetime, p_end: datetime, t0: str, t1: str, days: tuple[str, ...]) -> str:
        applicable = "".join(f"<com:applicableDay>{d}</com:applicableDay>" for d in days)
        return (
            f"<com:validPeriod><com:startOfPeriod>{_iso(p_start)}</com:startOfPeriod>"
            f"<com:endOfPeriod>{_iso(p_end)}</com:endOfPeriod>"
            f"<com:recurringTimePeriodOfDay xsi:type=\"com:TimePeriodByHour\"><com:startTimeOfPeriod>{t0}</com:startTimeOfPeriod>"
            f"<com:endTimeOfPeriod>{t1}</com:endTimeOfPeriod></com:recurringTimePeriodOfDay>"
            f"<com:recurringDayWeekMonthPeriod>{applicable}</com:recurringDayWeekMonthPeriod></com:validPeriod>"
        )

    # As Statens vegvesen writes it: split at midnight.
    return (
        "<com:validityStatus>definedByValidityTimeSpec</com:validityStatus><com:validityTimeSpecification>"
        f"<com:overallStartTime>{_iso(start)}</com:overallStartTime><com:overallEndTime>{_iso(end)}</com:overallEndTime>"
        + period(start, end, "22:00:00", "23:59:59", _DAYS[0:4])
        + period(start, end, "00:00:00", "06:00:00", _DAYS[1:5])
        + "</com:validityTimeSpecification>"
    )


def scenario_situations(active: dict[str, datetime], now: datetime) -> str:
    """The made-up situations that are switched on, as DATEX II XML. `active`
    maps a scenario to when it was switched on."""
    out = []
    for name, since in active.items():
        sid = f"DEMO_{name.upper()}"
        if name == "night_closures":
            monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            start, end = monday.replace(hour=22), monday + timedelta(weeks=3, hours=6)
            records = [
                _record(f"{sid}_1", "MaintenanceWorks", "roadMaintenanceType", "roadworks",
                        "DEMO: Vegarbeid, vegen er stengt, gyldig mellom 22:00 og 06:00 mandag, tirsdag, onsdag og torsdag.",
                        "Fv. 658 Ellingsøytunnelen i Ålesund, Møre og Romsdal", "F658", ELLINGSOY_TUNNEL,
                        _nightly(start, end), since),
                _record(f"{sid}_2", "RoadOrCarriagewayOrLaneManagement", "roadOrCarriagewayOrLaneManagementType",
                        "roadClosed", "DEMO: Vegarbeid, vegen er stengt, gyldig mellom 22:00 og 06:00 mandag, tirsdag, onsdag og torsdag.",
                        "Fv. 658 Ellingsøytunnelen i Ålesund, Møre og Romsdal", "F658", ELLINGSOY_TUNNEL,
                        _nightly(start, end), since),
            ]  # fmt: skip
        elif name == "accident":
            records = [
                _record(f"{sid}_1", "Accident", "accidentType", "accident",
                        "DEMO: Trafikkulykke i Ellingsøytunnelen. Tunnelen er stengt.",
                        "Fv. 658 Ellingsøytunnelen i Ålesund, Møre og Romsdal", "F658", ELLINGSOY_TUNNEL,
                        _span(since, None), since),
                _record(f"{sid}_2", "RoadOrCarriagewayOrLaneManagement", "roadOrCarriagewayOrLaneManagementType",
                        "roadClosed", "DEMO: Trafikkulykke, vegen er stengt.",
                        "Fv. 658 Ellingsøytunnelen i Ålesund, Møre og Romsdal", "F658", ELLINGSOY_TUNNEL,
                        _span(since, None), since),
            ]  # fmt: skip
        elif name == "convoy":
            records = [
                _record(f"{sid}_1", "GeneralNetworkManagement", "generalNetworkManagementType", "trafficBeingManuallyDirected",
                        "DEMO: Kolonnekjøring på grunn av vegarbeid. Ventetid inntil 20 minutter.",
                        "Fv. 658 mot Vigra, Ålesund, Møre og Romsdal", "F658", VALDEROY_STRETCH,
                        _span(since - timedelta(minutes=5), since + timedelta(hours=2)), since),
            ]  # fmt: skip
        elif name == "parallel_roadworks":
            records = [
                _record(f"{sid}_1", "MaintenanceWorks", "roadMaintenanceType", "roadworks",
                        "DEMO: Vegarbeid. Lysregulering.", "Kommunal veg på Ellingsøya", "K1234", PARALLEL_ROAD,
                        _span(since - timedelta(hours=1), since + timedelta(days=7)), since),
            ]  # fmt: skip
        else:
            continue
        out.append(f'<sit:situation {_NS} id="{sid}">{"".join(records)}</sit:situation>')
    return "".join(out)


def build_feed(base: str, active: dict[str, datetime], now: datetime) -> bytes:
    """The shifted sample with the switched-on scenarios added after its last situation."""
    extra = scenario_situations(active, now)
    if not extra:
        return base.encode("utf-8")
    ends = [m.end() for m in _LAST_SITUATION.finditer(base)]
    if not ends:
        raise ValueError("the sample has no situations to add to")
    return (base[: ends[-1]] + extra + base[ends[-1] :]).encode("utf-8")


# --- the server -----------------------------------------------------------------


class DemoState:
    def __init__(self, base: str) -> None:
        self.base = base
        self.lock = threading.Lock()
        now = datetime.now(OSLO)
        self.active: dict[str, datetime] = {name: now for name in DEFAULT_ON}
        self.changed = now
        self.requests = 0

    def toggle(self, name: str) -> None:
        with self.lock:
            if name in self.active:
                del self.active[name]
            elif name in SCENARIOS:
                self.active[name] = datetime.now(OSLO)
            self.changed = datetime.now(OSLO)

    def feed(self) -> bytes:
        with self.lock:
            return build_feed(self.base, dict(self.active), datetime.now(OSLO))


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def make_handler(state: DemoState, port: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            print(f"  {self.address_string()} {fmt % args}", flush=True)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == FEED_PATH:
                return self._feed()
            if path == "/":
                return self._page()
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path.startswith("/toggle/"):
                state.toggle(self.path.removeprefix("/toggle/"))
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
                return
            self.send_error(404)

        def _feed(self) -> None:
            if not self.headers.get("Authorization", "").startswith("Basic "):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="demo"')
                self.end_headers()
                return
            since = self.headers.get("If-Modified-Since")
            if since:
                try:
                    if datetime.fromisoformat(since) >= state.changed:
                        self.send_response(304)
                        self.end_headers()
                        return
                except ValueError:
                    pass
            body = state.feed()
            state.requests += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _page(self) -> None:
            url = f"http://{_lan_ip()}:{port}{FEED_PATH}"
            rows = "".join(
                f"<tr><td>{html.escape(text)}</td><td><b>{'ON' if name in state.active else 'off'}</b></td>"
                f"<td><form method=post action='/toggle/{name}'><button>"
                f"{'Switch off' if name in state.active else 'Switch on'}</button></form></td></tr>"
                for name, text in SCENARIOS.items()
            )
            body = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>Vegvarsel demo feed</title>
<style>body{{font-family:system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;line-height:1.5}}
td{{padding:.4rem .6rem;border-bottom:1px solid #ddd}}code{{background:#eee;padding:.1rem .3rem;border-radius:3px}}
button{{padding:.3rem .8rem}}</style>
<h1>Vegvarsel demo feed</h1>
<p><b>Not live data.</b> Statens vegvesen's published sample of the national feed, moved to this week, plus the
made-up Ålesund situations below.</p>
<p>In Home Assistant (with <i>Advanced mode</i> on in your user profile), add Vegvarsel with any username and
password, and set <b>Feed address</b> to<br><code>{html.escape(url)}</code></p>
<table>{rows}</table>
<p>Vegvarsel checks every 2 minutes (1 is the minimum, under the integration's options). Changes here show up
on the next check. Feed served {state.requests} times.</p>"""
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def load_base(small: bool, today: date) -> str:
    if small:
        source = SMALL_SAMPLE
    else:
        source = CACHE / "situations.xml"
        if not source.exists():
            CACHE.mkdir(exist_ok=True)
            print(f"Downloading Statens vegvesen's sample feed (~30 MB) to {source} ...", flush=True)
            urllib.request.urlretrieve(SAMPLE_URL, source)
    text = source.read_text(encoding="utf-8")
    days = week_shift(text, today)
    print(f"Sample: {source.name}, moved {days} days ({days // 7} weeks) forward", flush=True)
    return shift_times(text, days)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--small", action="store_true", help="use the small excerpt from the tests")
    args = parser.parse_args()
    state = DemoState(load_base(args.small, date.today()))
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(state, args.port))
    print(f"\nControl page:  http://localhost:{args.port}/   (from other devices: http://{_lan_ip()}:{args.port}/)")
    print(f"Feed address:  http://{_lan_ip()}:{args.port}{FEED_PATH}\nCtrl+C to stop.\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
