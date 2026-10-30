import json
import math
from itertools import islice
from pathlib import Path

import pytest

from iosfakerun.coordinates import Point, bd09_to_wgs84, distance, positive
from iosfakerun.route import Plan, Route, load_points


@pytest.mark.parametrize('text', [
    '[{"lat":0,"lng":0},{"lat":0,"lng":"0.001"}]',
    '  {"lat":0,"lng":0}, {"lat":0,"lng":0.001} \n',
    '\ufeff [{"lat":"0","lng":"0"},{"lat":0,"lng":0.001}]',
])
def test_json_compatibility(tmp_path, text):
    path = tmp_path/'route.json'
    path.write_text(text)
    points = load_points(path, 'wgs84')
    assert points == [Point(0, 0), Point(0, 0.001)]


@pytest.mark.parametrize('text,expected', [
    ('[]', '非空'), ('', '非空'), ('null', '第 1 点'),
    ('[true]', '第 1 点'), ('[{"lat":1}]', '第 1 点'),
    ('[{"lat":0,"lng":0},{"lat":true,"lng":0}]', '第 2 点'),
    ('[{"lat":NaN,"lng":0}]', '有限'),
    ('[{"lat":Infinity,"lng":0}]', '有限'),
    ('[{"lat":0,"lng":"-Infinity"}]', '有限'),
    ('[{"lat":null,"lng":0}]', '有限'),
    ('[{"lat":{},"lng":0}]', '有限'),
    ('[{"lat":[],"lng":0}]', '有限'),
    ('[{"lat":"abc","lng":0}]', '有限'),
    ('[{"lat":91,"lng":0}]', '越界'),
    ('[{"lat":0,"lng":181}]', '越界'),
    ('[{"lat":76,"lng":0}]', '75'),
    ('[{"lat":0 "lng":0}]', 'JSON 错误'),
])
def test_invalid_input_with_location(tmp_path, text, expected):
    path = tmp_path/'bad.json'
    path.write_text(text)
    with pytest.raises(ValueError, match=expected):
        load_points(path, 'wgs84')


def test_missing_file_and_unknown_crs(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_points(tmp_path/'missing', 'wgs84')
    with pytest.raises(ValueError, match='crs'):
        load_points('examples/route_wgs84.json', 'gcj02')


def test_wgs84_identity_and_bd09_independent_reference(acceptance, tmp_path):
    references = json.loads(Path('tests/fixtures/bd09_reference.json').read_text())
    for entry in references:
        original = Point(*entry['input'])
        actual = bd09_to_wgs84(original)
        assert actual.latitude == pytest.approx(entry['wgs84'][0], abs=acceptance['coordinate_tolerance_deg'], rel=0)
        assert actual.longitude == pytest.approx(entry['wgs84'][1], abs=acceptance['coordinate_tolerance_deg'], rel=0)
        path = tmp_path/'coords.json'
        path.write_text(json.dumps([dict(lat=original.latitude, lng=original.longitude)]))
        assert load_points(path, 'wgs84') == [original]
        assert load_points(path, 'bd09') == [actual]


@pytest.mark.parametrize('value', [0, -1, 'nan', 'inf', float('-inf'), True, None, {}, 10**400])
def test_invalid_positive_parameters(value):
    with pytest.raises(ValueError):
        positive(value, '参数')


@pytest.mark.parametrize('loops', [0, -1, 1.5, True, '3'])
def test_invalid_loops(loops):
    with pytest.raises(ValueError, match='圈数'):
        Plan(Route([Point(0, 0), Point(0, 0.001)]), loops=loops)


@pytest.mark.parametrize('option', ['speed', 'hz', 'max_seconds'])
@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), True])
def test_plan_parameter_validation(option, value):
    with pytest.raises(ValueError):
        Plan(Route([Point(0, 0), Point(0, 0.001)]), **{option:value})


def test_geographic_limits_and_repeats():
    for points, message in [
        ([], '至少'), ([Point(0,0)]*3, '至少'),
        ([Point(75.01,0),Point(75.01,.001)], '75'),
        ([Point(0,179.9),Point(0,-179.9)], '日期变更线'),
        ([Point(0,0),Point(0,1)], '100 km'),
    ]:
        with pytest.raises(ValueError, match=message):
            Route(points)
    route = Route([Point(75,0),Point(75,0),Point(75,.001)])
    assert len(route.points) == 2


def test_300m_analytic_length_and_exact_endpoints(acceptance):
    route = Route(load_points('examples/route_wgs84.json', 'wgs84'))
    tol = acceptance['distance_tolerance_m']
    assert route.length == pytest.approx(300, abs=tol, rel=0)
    assert distance(Point(0,0),Point(acceptance['degrees_for_300m_equator'],0)) == pytest.approx(300, abs=tol, rel=0)
    assert route.position_at_distance(-1) == Point(0,0)
    assert route.position_at_distance(150) == Point(0,0.001347472926179282)
    assert route.position_at_distance(301) == route.points[-1]
    events = list(Plan(route).events())
    assert len(events) == acceptance['schedule_300m']['event_count']
    assert events[0].time == 0
    assert events[-1].time == pytest.approx(100, abs=acceptance['time_tolerance_s'], rel=0)
    assert events[-1].point == route.points[-1]


def test_short_segments_corners_and_fractional_endpoint(acceptance):
    degree = acceptance['degrees_for_300m_equator']/300
    route = Route([Point(0,0),Point(0,0),Point(0,degree),Point(degree,degree)])
    events = list(Plan(route, speed=3).events())
    assert len(events) == 3
    assert [e.point for e in events] == list(route.points)
    assert [e.time for e in events] == pytest.approx([0,1/3,2/3], abs=acceptance['time_tolerance_s'], rel=0)
    assert events[-1].distance == pytest.approx(2, abs=acceptance['distance_tolerance_m'], rel=0)


def test_many_turns_preserved_and_last_index_not_skipped(acceptance):
    unit = acceptance['degrees_for_300m_equator']/300
    points = [Point(0,0),Point(0,unit),Point(unit,unit),Point(unit,2*unit),Point(2*unit,2*unit)]
    events = list(Plan(Route(points), speed=3).events())
    assert all(point in [event.point for event in events] for point in points)
    assert events[-1].point == points[-1]


def test_closure_and_three_complete_loops(acceptance):
    degree = acceptance['degrees_for_300m_equator']
    points = [Point(0,0),Point(0,degree/3),Point(0,degree)]
    open_route = Route(points)
    with pytest.raises(ValueError, match='close-route'):
        Plan(open_route, loops=3)
    route = Route(points, close=True)
    assert route.points == tuple(points+[points[0]])
    assert Route(route.points, close=True).points == route.points
    plan = Plan(route, loops=3)
    assert plan.total_distance == pytest.approx(1800, abs=1e-6, rel=0)
    assert plan.duration == pytest.approx(600, abs=1e-7, rel=0)
    events = list(plan.events())
    assert len(events) == 604
    assert all(a.time < b.time for a,b in zip(events,events[1:]))
    for lap in range(3):
        for offset,point in [(100/3,points[1]),(100,points[2]),(200,points[0])]:
            hits = [e for e in events if abs(e.time-(200*lap+offset))<1e-7]
            assert len(hits) == 1
            assert hits[0].point == point
    assert events[-1].point == points[0]


def test_hz_global_sampling_max_seconds_and_streaming(acceptance):
    route = Route(load_points('examples/route_wgs84.json','wgs84'))
    assert [e.time for e in Plan(route, hz=2, max_seconds=1.2).events()] == [0,.5,1,1.2]
    assert list(Plan(route, max_seconds=1.2).events())[-1].distance == pytest.approx(3.6)
    plan = Plan(Route(route.points, close=True), loops=10**12)
    assert len(list(islice(plan.events(), 5))) == 5
    with pytest.raises(ValueError, match='数值范围'):
        Plan(route, speed=1e-320)
