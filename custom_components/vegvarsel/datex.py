"""Statens vegvesen's DATEX II situation publication, read into plain
dataclasses.

Read without regard to namespace prefixes or the exact DATEX version: every
element is matched on its local name, and the record type on the local part
of its xsi:type. What a record says about place and time is gathered from
wherever it sits below the record, so small differences between DATEX 2.x and
3.x - and Statens vegvesen's own extensions - do not stop a record from being
read. Free of anything Home Assistant.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from functools import lru_cache
import logging
import re
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from .utm import utm33_to_latlon

_LOGGER = logging.getLogger(__name__)

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
NORWAY = ZoneInfo("Europe/Oslo")
# How far ahead recurring periods are unrolled when looking for the next start.
HORIZON = timedelta(days=14)
# Gap below which two stretches of validity count as one.
_TOUCHING = timedelta(seconds=2)

_DAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}  # fmt: skip

# Kinds, most severe first. The rank is what "severity" compares on.
KIND_RANK = {
    "closed": 5,
    "accident": 4,
    "convoy": 4,
    "obstruction": 3,
    "traffic": 3,
    "restriction": 2,
    "roadworks": 2,
    "conditions": 1,
    "info": 0,
}

_TYPE_KINDS = {
    "accident": "accident",
    "abnormaltraffic": "traffic",
    "maintenanceworks": "roadworks",
    "constructionworks": "roadworks",
    "roadworks": "roadworks",
    "vehicleobstruction": "obstruction",
    "animalpresenceobstruction": "obstruction",
    "generalobstruction": "obstruction",
    "environmentalobstruction": "obstruction",
    "infrastructuredamageobstruction": "obstruction",
    "obstruction": "obstruction",
    "poorenvironmentconditions": "conditions",
    "poorroadconditions": "conditions",
    "weatherrelatedroadconditions": "conditions",
    "nonweatherrelatedroadconditions": "conditions",
    "roadconditions": "conditions",
    "reroutingmanagement": "restriction",
    "speedmanagement": "restriction",
    "winterdrivingmanagement": "restriction",
    "roadorcarriagewayorlanemanagement": "restriction",
    "generalnetworkmanagement": "restriction",
    "networkmanagement": "restriction",
}

_PREFERRED_LANGS = ("no", "nb", "nn", "en")


@lru_cache(maxsize=4096)
def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xsi_type(el: ET.Element) -> str:
    return el.get(XSI_TYPE, "").rsplit(":", 1)[-1]


def _children(el: ET.Element, name: str) -> Iterator[ET.Element]:
    for child in el:
        if local(child.tag) == name:
            yield child


def _child(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    return next(_children(el, name), None)


def _text(el: ET.Element | None, name: str | None = None) -> str | None:
    if el is not None and name is not None:
        el = _child(el, name)
    if el is None or el.text is None:
        return None
    return el.text.strip() or None


def _descendants(el: ET.Element, name: str) -> Iterator[ET.Element]:
    for node in el.iter():
        if local(node.tag) == name:
            yield node


def parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=NORWAY)


# --- validity -----------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    """One validPeriod: optional bounds, optionally only at certain times of
    day and on certain weekdays (local Norwegian time)."""

    start: datetime | None = None
    end: datetime | None = None
    daily: tuple[tuple[time, time], ...] = ()
    weekdays: frozenset[int] = frozenset()

    def intervals(self, lo: datetime, hi: datetime, tz: tzinfo) -> Iterator[tuple[datetime, datetime]]:
        lo2 = max(lo, self.start) if self.start else lo
        hi2 = min(hi, self.end) if self.end else hi
        if lo2 >= hi2:
            return
        if not self.daily and not self.weekdays:
            yield (lo2, hi2)
            return
        daily = self.daily or ((time(0, 0), time(0, 0)),)
        day: date = lo2.astimezone(tz).date() - timedelta(days=1)
        last: date = hi2.astimezone(tz).date()
        while day <= last:
            if not self.weekdays or day.weekday() in self.weekdays:
                for t0, t1 in daily:
                    begin = datetime.combine(day, t0, tz)
                    finish = datetime.combine(day if t1 > t0 else day + timedelta(days=1), t1, tz)
                    a, b = max(begin, lo2), min(finish, hi2)
                    if a < b:
                        yield (a, b)
            day += timedelta(days=1)


@dataclass(frozen=True)
class Validity:
    status: str = "active"  # active | planned | suspended | definedByValidityTimeSpec
    start: datetime | None = None
    end: datetime | None = None
    periods: tuple[Period, ...] = ()

    def intervals(self, lo: datetime, hi: datetime, tz: tzinfo = NORWAY) -> list[tuple[datetime, datetime]]:
        """The concrete times within [lo, hi) the record applies."""
        if self.status == "suspended":
            return []
        lo2 = max(lo, self.start) if self.start else lo
        hi2 = min(hi, self.end) if self.end else hi
        if lo2 >= hi2:
            return []
        if not self.periods:
            return [(lo2, hi2)]
        out = sorted(iv for period in self.periods for iv in period.intervals(lo2, hi2, tz))
        # Statens vegvesen splits a night at midnight (22:00-23:59:59, then
        # 00:00-06:00): stretches that (nearly) touch are one stretch.
        merged: list[tuple[datetime, datetime]] = []
        for a, b in out:
            if merged and a <= merged[-1][1] + _TOUCHING:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        return merged

    def overlaps(self, lo: datetime, hi: datetime, tz: tzinfo = NORWAY) -> bool:
        return bool(self.intervals(lo, hi, tz))

    def active_at(self, moment: datetime, tz: tzinfo = NORWAY) -> bool:
        return self.overlaps(moment, moment + timedelta(seconds=1), tz)

    def next_start(self, after: datetime, tz: tzinfo = NORWAY) -> datetime | None:
        """When it next applies after `after` - `after` itself if it applies now."""
        found = self.intervals(after, after + HORIZON, tz)
        return found[0][0] if found else None

    def stretch_start(self, moment: datetime, tz: tzinfo = NORWAY) -> datetime | None:
        """When the stretch it applies in at `moment` began (None: since
        before anyone said, or it does not apply at `moment`)."""
        found = None
        for a, b in self.intervals(moment - HORIZON, moment + timedelta(seconds=1), tz):
            if a <= moment < b:
                found = a
        return None if found is None or found <= moment - HORIZON else found

    def current_end(self, moment: datetime, tz: tzinfo = NORWAY) -> datetime | None:
        """When the stretch it applies in at `moment` ends (None: open-ended)."""
        horizon = moment + HORIZON
        for a, b in self.intervals(moment, horizon, tz):
            if a <= moment:
                return b if b < horizon else None
        return None


def _parse_validity(record: ET.Element) -> Validity:
    validity = next(_descendants(record, "validity"), None)
    if validity is None:
        return Validity()
    status = _text(validity, "validityStatus") or "active"
    spec = _child(validity, "validityTimeSpecification")
    if spec is None:
        return Validity(status=status)
    periods = []
    for vp in _children(spec, "validPeriod"):
        daily = []
        for rec in _descendants(vp, "recurringTimePeriodOfDay"):
            try:
                t0 = time.fromisoformat(_text(next(_descendants(rec, "startTimeOfPeriod"), None)) or "")
                t1 = time.fromisoformat(_text(next(_descendants(rec, "endTimeOfPeriod"), None)) or "")
            except ValueError:
                continue
            daily.append((t0, t1))
        weekdays = {
            _DAY_NAMES[d.text.strip().lower()]
            for d in _descendants(vp, "applicableDay")
            if d.text and d.text.strip().lower() in _DAY_NAMES
        }
        periods.append(
            Period(
                start=parse_time(_text(vp, "startOfPeriod")),
                end=parse_time(_text(vp, "endOfPeriod")),
                daily=tuple(daily),
                weekdays=frozenset(weekdays),
            )
        )
    return Validity(
        status=status,
        start=parse_time(_text(spec, "overallStartTime")),
        end=parse_time(_text(spec, "overallEndTime")),
        periods=tuple(periods),
    )


# --- records ------------------------------------------------------------------

LatLon = tuple[float, float]
BBox = tuple[float, float, float, float]  # lat0, lon0, lat1, lon1


class Stretch:
    """One stretch (or single point) of road an incident covers.

    Given in latitude/longitude, or as UTM 33 metres - then only turned into
    latitude/longitude when something asks for its points: of the 150 000
    points in a national feed, only the few near a route ever are. Its box is
    worked out at once from the corners, which is all the first check needs.
    """

    __slots__ = ("_points", "_utm", "bbox")

    def __init__(self, points: list[LatLon] | None = None, utm: list[tuple[float, float]] | None = None) -> None:
        self._points = points
        self._utm = utm
        if points:
            lats = [p[0] for p in points]
            lons = [p[1] for p in points]
            self.bbox: BBox = (min(lats), min(lons), max(lats), max(lons))
        elif utm:
            es = [p[0] for p in utm]
            ns = [p[1] for p in utm]
            corners = [utm33_to_latlon(e, n) for e in (min(es), max(es)) for n in (min(ns), max(ns))]
            self.bbox = (
                min(c[0] for c in corners), min(c[1] for c in corners),
                max(c[0] for c in corners), max(c[1] for c in corners),
            )  # fmt: skip
        else:
            raise ValueError("an empty stretch")

    @property
    def points(self) -> list[LatLon]:
        if self._points is None:
            self._points = [utm33_to_latlon(e, n) for e, n in self._utm or ()]
        return self._points

    def __iter__(self):
        return iter(self.points)

    def __len__(self) -> int:
        return len(self._points) if self._points is not None else len(self._utm or ())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Stretch):
            return self.points == other.points
        return isinstance(other, list) and self.points == other

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"Stretch({len(self)} points, bbox={self.bbox})"


@dataclass
class Incident:
    """One situation record."""

    id: str
    situation_id: str
    version: str
    record_type: str
    subtypes: list[str]
    kind: str
    severity: str | None
    description: str
    road: str
    places: list[str]
    # Each stretch or point the record covers, apart: a record may name
    # several stretches of road, and the gaps between them are not part of it.
    lines: list[Stretch] = field(default_factory=list)
    display: LatLon | None = None  # where to put its marker
    validity: Validity = field(default_factory=Validity)
    version_time: datetime | None = None

    @property
    def rank(self) -> int:
        return KIND_RANK.get(self.kind, 0)

    @property
    def points(self) -> list[LatLon]:
        return [p for line in self.lines for p in line]

    @property
    def bbox(self) -> BBox | None:
        if not self.lines:
            return None
        boxes = [line.bbox for line in self.lines]
        return (
            min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes),
        )  # fmt: skip

    @property
    def position(self) -> LatLon | None:
        if self.display:
            return self.display
        return self.lines[0].points[0] if self.lines else None


_SPACE = re.compile(r"\s+")


def _comment(record: ET.Element) -> str:
    """Every public comment, in Norwegian where there is a choice: Statens
    vegvesen's generated summary ("Vegarbeid, vegen er stengt, gyldig
    mellom ...") first, then the free text ("Utrykningskjøretøy kan passere")."""
    notes: list[str] = []
    free: list[str] = []
    for holder in ("generalPublicComment", "nonGeneralPublicComment"):
        for gpc in _descendants(record, holder):
            texts: dict[str, str] = {}
            for value in _descendants(gpc, "value"):
                if value.text and value.text.strip():
                    lang = (value.get("lang") or value.get("{http://www.w3.org/XML/1998/namespace}lang") or "").lower()
                    # "|" is Statens vegvesen's line break inside a comment
                    texts.setdefault(lang, _SPACE.sub(" ", value.text.replace("|", " ")).strip())
            text = next((texts[lang] for lang in _PREFERRED_LANGS if lang in texts), next(iter(texts.values()), ""))
            if not text:
                continue
            target = notes if _text(gpc, "commentType") == "dataProcessingNote" else free
            if text not in notes and text not in free:
                target.append(text)
        if notes or free:
            break
    return " ".join(notes + free)


_FLOAT = re.compile(r"-?\d+(?:\.\d+)?")
_UTM33 = ("25833", "32633", "5973")


def _lines(location: ET.Element | None) -> tuple[list[Stretch], LatLon | None]:
    """The stretches (GML lines) and points below a location, each apart,
    and the point meant for display. A line is in UTM 33 metres (srsName
    25833, as Statens vegvesen sends it) or in latitude/longitude."""
    if location is None:
        return [], None
    lines: list[Stretch] = []
    display: LatLon | None = None
    for node in location.iter():
        name = local(node.tag)
        if name == "gmlLineString":
            line = _pos_list(node)
            if line:
                lines.append(line)
        elif name == "coordinatesForDisplay" and display is None:
            display = _lat_lon_of(node)
    if not lines:
        # No GML: a TPEG stretch is its from/to points joined; any other
        # point stands on its own.
        for tpeg in _descendants(location, "tpegLinearLocation"):
            ends = [p for p in (_lat_lon_of(n) for n in tpeg.iter()) if p]
            if ends:
                lines.append(Stretch(list(dict.fromkeys(ends))))
        if not lines:
            seen: set[LatLon] = set()
            for node in location.iter():
                if local(node.tag) == "coordinatesForDisplay":
                    continue
                point = _lat_lon_of(node)
                if point and point not in seen:
                    seen.add(point)
                    lines.append(Stretch([point]))
    if not lines and display:
        lines.append(Stretch([display]))
    return lines, display


def _pos_list(line: ET.Element) -> Stretch | None:
    pos_list = next(_descendants(line, "posList"), None)
    if pos_list is None:
        return None
    numbers = [float(n) for n in _FLOAT.findall(pos_list.text or "")]
    pairs = list(zip(numbers[0::2], numbers[1::2], strict=False))
    if not pairs:
        return None
    srs = (line.get("srsName") or pos_list.get("srsName") or "").lower()
    if any(code in srs for code in _UTM33) or abs(pairs[0][1]) > 1000:
        return Stretch(utm=pairs)
    return Stretch([_lat_lon(a, b) for a, b in pairs])


def _lat_lon_of(node: ET.Element) -> LatLon | None:
    lat, lon = _text(node, "latitude"), _text(node, "longitude")
    if lat is None or lon is None:
        return None
    try:
        return (float(lat), float(lon))
    except ValueError:
        return None


def _lat_lon(a: float, b: float) -> LatLon:
    """Norway lies at 57-72 N and 4-32 E, so a pair in the wrong order is
    told by its first number alone."""
    return (b, a) if a < 40 < b else (a, b)


def _places(location: ET.Element | None) -> list[str]:
    """Names the location carries: location descriptions, TPEG names."""
    if location is None:
        return []
    names: list[str] = []
    for holder in ("locationDescription", "descriptor", "tpegDescriptor", "name"):
        for node in _descendants(location, holder):
            for value in _descendants(node, "value"):
                text = _SPACE.sub(" ", value.text or "").strip()
                if text and text not in names:
                    names.append(text)
    return names


_ROAD_PREFIX = {"E": "E", "R": "Rv", "F": "Fv", "K": "Kv", "P": "Pv", "S": "Sv"}
_ROAD_NUMBER = re.compile(r"^([ERFKPS])\s*(\d+)$")


def road_label(number: str) -> str:
    """"F653" as "Fv653", "R15" as "Rv15", "E39" as it is."""
    m = _ROAD_NUMBER.match(number.strip().upper())
    return f"{_ROAD_PREFIX[m.group(1)]}{m.group(2)}" if m else number.strip()


def _road(record: ET.Element) -> str:
    numbers: list[str] = []
    for node in _descendants(record, "roadNumber"):
        text = road_label(node.text or "")
        if text and text not in numbers:
            numbers.append(text)
    if not numbers:
        for node in _descendants(record, "roadName"):
            text = (node.text or "").strip()
            if text and text not in numbers:
                numbers.append(text)
    return " / ".join(numbers)


# "...Type" fields that describe the message, not the incident.
_NOT_SUBTYPES = {
    "validityStatus", "probabilityOfOccurrence", "informationStatus", "subdivisionType",
    "commentType", "sourceType", "mobilityType", "applicableForTrafficType", "vehicleType",
}  # fmt: skip


def _subtypes(record: ET.Element) -> list[str]:
    """The record's own "...Type" fields - roadClosed, convoyService,
    roadworks - wherever they sit below it."""
    found = []
    for node in record.iter():
        name = local(node.tag)
        if name.endswith("Type") and name not in _NOT_SUBTYPES and node.text and node.text.strip():
            value = node.text.strip()
            if value not in found and not _looks_like_number(value):
                found.append(value)
    return found


def _looks_like_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


_CLOSED = {"roadclosed", "carriagewayclosures", "closed", "closedpermanentlyfortheseason"}
# Closures that come and go - blasting, short stops for machinery - hold you
# up for minutes, not for good.
_SHORT_CLOSURES = {"intermittentshorttermclosures"}
_CONVOY_TEXT = re.compile(r"\bkolonne", re.IGNORECASE)


def classify(record_type: str, subtypes: Iterable[str], text: str = "") -> str:
    """One kind from the record's type, subtypes and - for convoy driving,
    which Statens vegvesen often only writes out - its text."""
    lowered = [s.lower() for s in subtypes]
    if any(v in _CLOSED for v in lowered):
        return "closed"
    if any("convoy" in v for v in lowered) or _CONVOY_TEXT.search(text):
        return "convoy"
    if any(v in _SHORT_CLOSURES for v in lowered):
        return "restriction"
    if any("closure" in v and "lane" not in v for v in lowered):
        return "closed"
    return _TYPE_KINDS.get(record_type.lower(), "info")


def parse_situations(payload: bytes | str) -> list[Incident]:
    """Every situation record in a DATEX II situation publication."""
    root = ET.fromstring(payload)
    incidents: list[Incident] = []
    for situation in _descendants(root, "situation"):
        situation_id = situation.get("id") or ""
        for record in _children(situation, "situationRecord"):
            try:
                incidents.append(_parse_record(situation_id, record))
            except Exception:  # noqa: BLE001 - one odd record must not cost the rest
                _LOGGER.debug("Skipped an unreadable situation record in %s", situation_id, exc_info=True)
    return incidents


def _parse_record(situation_id: str, record: ET.Element) -> Incident:
    record_type = _xsi_type(record) or "SituationRecord"
    subtypes = _subtypes(record)
    location = next(_descendants(record, "locationReference"), None)
    if location is None:
        location = next(_descendants(record, "groupOfLocations"), None)
    description = _comment(record)
    lines, display = _lines(location)
    return Incident(
        id=record.get("id") or situation_id,
        situation_id=situation_id,
        version=record.get("version") or "",
        record_type=record_type,
        subtypes=subtypes,
        kind=classify(record_type, subtypes, description),
        severity=_text(record, "severity"),
        description=description,
        road=_road(record),
        places=_places(location),
        lines=lines,
        display=display,
        validity=_parse_validity(record),
        version_time=parse_time(_text(record, "situationRecordVersionTime")),
    )
