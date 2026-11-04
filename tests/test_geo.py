from custom_components.vegvarsel.geo import RouteLine, simplify

TUNNEL_MID = (62.486635, 6.182149)  # inside Ellingsøytunnelen
PARALLEL = (62.4866, 6.1890)  # ~340 m east of the tunnel
OSLO = (59.91, 10.75)


def test_length_matches_osrm(route_points):
    line = RouteLine(route_points)
    assert 16_500 < line.length < 17_500  # OSRM says 17 147 m


def test_point_on_route_is_found_with_distance_along(route_points):
    line = RouteLine(route_points)
    dist, along = line.nearest(TUNNEL_MID, 150)
    assert dist < 10
    assert 3_000 < along < 3_600


def test_parallel_road_outside_corridor(route_points):
    line = RouteLine(route_points)
    assert line.nearest(PARALLEL, 150) is None
    assert line.nearest(PARALLEL, 400) is not None


def test_far_away_point(route_points):
    line = RouteLine(route_points)
    assert not line.near_bbox(OSLO, 500)
    assert line.match([[OSLO]], 150) is None


def test_linear_location_crossing_route_between_its_ends(route_points):
    """A stretch whose two ends are both off the route, but which crosses it."""
    line = RouteLine(route_points)
    west, east = (62.4866, 6.1700), (62.4866, 6.1950)
    assert line.nearest(west, 150) is None and line.nearest(east, 150) is None
    assert line.match([[west, east]], 150) is not None


def test_separate_stretches_are_not_joined(route_points):
    """Two stretches either side of the route: the gap between them is not part of the incident."""
    line = RouteLine(route_points)
    west, east = (62.4866, 6.1700), (62.4866, 6.1950)
    assert line.match([[west], [east]], 150) is None


def test_match_reports_first_touch(route_points):
    line = RouteLine(route_points)
    along = line.match([[(62.4738, 6.1765), (62.4915, 6.1797)]], 150)
    assert along is not None and 1_500 < along < 2_000


def test_simplify_keeps_shape_and_ends():
    zigzag = [(62.0, 6.0 + i * 0.001) for i in range(100)]
    simple = simplify(zigzag, 5)
    assert simple[0] == zigzag[0] and simple[-1] == zigzag[-1]
    assert len(simple) == 2
    bend = [(62.0, 6.0), (62.0, 6.01), (62.01, 6.01)]
    assert simplify(bend, 5) == bend
