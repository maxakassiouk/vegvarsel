"""Route geometry: is a point within the corridor along a route, and how far
along the route is it.

Plain geometry on a flat projection around the route's mean latitude - good
to a few metres over the tens of kilometres a commute covers - and free of
anything Home Assistant, so it is tested on its own. Points are always
(latitude, longitude) in WGS84 degrees.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import cos, hypot, radians

_M_PER_DEG = 111_320.0
# Segments are filed in a grid of this size, in metres, so a point is only
# measured against the handful of segments near it.
_CELL_M = 500.0

LatLon = tuple[float, float]


def _point_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    """Distance from p to segment a-b, and where along it (0-1) the nearest point lies."""
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = ((px - ax) * dx + (py - ay) * dy) / length2 if length2 else 0.0
    t = max(0.0, min(1.0, t))
    return hypot(px - ax - t * dx, py - ay - t * dy), t


class RouteLine:
    """A route as a polyline measured in metres."""

    def __init__(self, points: Sequence[LatLon]) -> None:
        if len(points) < 2:
            raise ValueError("a route needs at least two points")
        lat0 = sum(p[0] for p in points) / len(points)
        self._k = cos(radians(lat0))
        self._xy = [self._project(p) for p in points]
        self._along = [0.0]
        for (ax, ay), (bx, by) in zip(self._xy, self._xy[1:], strict=False):
            self._along.append(self._along[-1] + hypot(bx - ax, by - ay))
        self._cells: dict[tuple[int, int], list[int]] = {}
        for i, ((ax, ay), (bx, by)) in enumerate(zip(self._xy, self._xy[1:], strict=False)):
            for cell in _cells_over(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)):
                self._cells.setdefault(cell, []).append(i)
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        self.bbox = (min(lats), min(lons), max(lats), max(lons))

    @property
    def length(self) -> float:
        return self._along[-1]

    def _project(self, p: LatLon) -> tuple[float, float]:
        return (p[1] * _M_PER_DEG * self._k, p[0] * _M_PER_DEG)

    def nearest(self, point: LatLon, within: float) -> tuple[float, float] | None:
        """(distance to the route, distance along it) for a point no further
        than `within` metres from the route; None for one further away."""
        px, py = self._project(point)
        best: tuple[float, float] | None = None
        seen: set[int] = set()
        for cell in _cells_over(px - within, py - within, px + within, py + within):
            for i in self._cells.get(cell, ()):
                if i in seen:
                    continue
                seen.add(i)
                (ax, ay), (bx, by) = self._xy[i], self._xy[i + 1]
                dist, t = _point_segment(px, py, ax, ay, bx, by)
                if dist <= within and (best is None or dist < best[0]):
                    best = (dist, self._along[i] + t * (self._along[i + 1] - self._along[i]))
        return best

    def match(self, lines: Iterable[Sequence[LatLon]], within: float) -> float | None:
        """Where a located thing first touches the corridor, as distance
        along the route in metres; None if it never does.

        `lines` are its stretches, each a point or a polyline, kept apart:
        each is densified on its own, so a long straight stretch that crosses
        the route between two of its points counts, but the gap between two
        separate stretches does not.
        """
        found: float | None = None
        for line in lines:
            for p in _densify(list(line), step_m=max(within, 50.0)):
                hit = self.nearest(p, within)
                if hit is not None and (found is None or hit[1] < found):
                    found = hit[1]
        return found

    def overlaps(self, bbox: tuple[float, float, float, float], margin_m: float) -> bool:
        """Cheap pre-filter: does a box (lat0, lon0, lat1, lon1) come within
        a margin of the route's box."""
        dlat = margin_m / _M_PER_DEG
        dlon = margin_m / (_M_PER_DEG * self._k)
        lat0, lon0, lat1, lon1 = self.bbox
        return not (
            bbox[2] < lat0 - dlat or bbox[0] > lat1 + dlat or bbox[3] < lon0 - dlon or bbox[1] > lon1 + dlon
        )

    def near_bbox(self, point: LatLon, margin_m: float) -> bool:
        """Cheap pre-filter: is the point within the route's box plus a margin."""
        dlat = margin_m / _M_PER_DEG
        dlon = margin_m / (_M_PER_DEG * self._k)
        lat0, lon0, lat1, lon1 = self.bbox
        return lat0 - dlat <= point[0] <= lat1 + dlat and lon0 - dlon <= point[1] <= lon1 + dlon


def _cells_over(x0: float, y0: float, x1: float, y1: float):
    for cx in range(int(x0 // _CELL_M), int(x1 // _CELL_M) + 1):
        for cy in range(int(y0 // _CELL_M), int(y1 // _CELL_M) + 1):
            yield (cx, cy)


def _densify(points: list[LatLon], step_m: float) -> list[LatLon]:
    """Points every `step_m` metres or so along a polyline (the points
    themselves included). A single point is returned as it is."""
    if len(points) < 2:
        return points
    out: list[LatLon] = [points[0]]
    for a, b in zip(points, points[1:], strict=False):
        k = cos(radians((a[0] + b[0]) / 2))
        d = hypot((b[0] - a[0]) * _M_PER_DEG, (b[1] - a[1]) * _M_PER_DEG * k)
        n = int(d // step_m)
        for i in range(1, n + 1):
            f = i / (n + 1)
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
        out.append(b)
    return out


def simplify(points: Sequence[LatLon], tolerance_m: float = 15.0) -> list[LatLon]:
    """Douglas-Peucker: drop points that change the line by less than the
    tolerance, so a route stored in a config entry stays small."""
    if len(points) < 3:
        return list(points)
    lat0 = sum(p[0] for p in points) / len(points)
    k = cos(radians(lat0))
    xy = [(p[1] * _M_PER_DEG * k, p[0] * _M_PER_DEG) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        ax, ay = xy[first]
        bx, by = xy[last]
        worst, index = 0.0, -1
        for i in range(first + 1, last):
            dist, _ = _point_segment(xy[i][0], xy[i][1], ax, ay, bx, by)
            if dist > worst:
                worst, index = dist, i
        if index != -1 and worst > tolerance_m:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, kept in zip(points, keep, strict=True) if kept]
