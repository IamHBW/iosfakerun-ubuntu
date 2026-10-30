import math

import pytest

from iosfakerun.cli import main
from iosfakerun.jog import make_jog_plan,parse_distance,parse_pace


@pytest.mark.parametrize('text,meters',[('3000',3000),('400',400),('1.5',1.5),(' .5 ',.5)])
def test_distance_meters(text,meters):assert parse_distance(text)==meters


@pytest.mark.parametrize('text',['0','-1','nan','inf','3km','400m','3mi','abc','1e309'])
def test_bad_distance(text):
    with pytest.raises(ValueError):parse_distance(text)


@pytest.mark.parametrize('text,speed',[('6:00',1000/360),('4:30',1000/270),('0:30',1000/30)])
def test_pace_conversion(text,speed):assert parse_pace(text)==speed


@pytest.mark.parametrize('text',['0:00','6:60','6','6:0','-1:00','inf:00'])
def test_bad_pace(text):
    with pytest.raises(ValueError):parse_pace(text)


def test_exact_target_distance_partial_last_lap_no_extra_distance():
    plan,meters=make_jog_plan('yuquan','1000','6:00')
    events=list(plan.events())
    assert plan.loops==3 and meters==1000
    assert plan.end_time==360
    assert events[-1].time==360
    assert events[-1].distance==pytest.approx(1000,abs=1e-8,rel=0)
    assert all(a.time<b.time for a,b in zip(events,events[1:]))
    assert all(event.distance<=1000 for event in events)


def test_named_preview_remains_offline(monkeypatch,tmp_path,capsys):
    from iosfakerun import device
    def forbidden(*args,**kwargs):raise AssertionError('设备调用')
    monkeypatch.setattr(device,'RealBackend',forbidden)
    assert main(['jog','yuquan','--distance','30','--pace','6:00','--dry-run','--output',str(tmp_path/'jog.csv')])==0
    assert '总距离 30.000000 m' in capsys.readouterr().out
    assert (tmp_path/'jog.csv').is_file()


def test_full_3000m_6min_pace_with_realistic_send_cost(clock):
    import asyncio
    from iosfakerun.device import FakeBackend
    from iosfakerun.runner import Control,play
    plan,meters=make_jog_plan('yuquan','3000','6:00')
    events=list(plan.events())
    assert plan.end_time==1080 and meters==3000 and plan.loops==7
    assert events[-1].distance==pytest.approx(3000,abs=1e-6,rel=0)
    assert all(a.time<b.time for a,b in zip(events,events[1:]))
    assert min(b.time-a.time for a,b in zip(events,events[1:]))>.8
    backend=FakeBackend(clock=clock,send_cost=.15)
    asyncio.run(play(backend,plan.events(),plan.end_time,control=Control(clock)))
    assert len(backend.sent)==len(events)
    assert max(abs(t-e.time) for (t,lat,lon),e in zip(backend.sent,events))<1e-7
    assert backend.calls[-2:]==['clear','close']
    for meters,point,lap in plan._corners():
        if meters<=3000:
            assert any(e.point==point and abs(e.distance-meters)<1e-6 for e in events)


@pytest.mark.parametrize('distance,pace',[('3km','6:00'),('0','6:00'),('300','6:60')])
def test_invalid_jog_input_never_connects(monkeypatch,distance,pace):
    from iosfakerun import device
    def forbidden(*args,**kwargs):raise AssertionError('设备调用')
    monkeypatch.setattr(device,'RealBackend',forbidden)
    assert main(['jog','yuquan','--distance',distance,'--pace',pace])==1
