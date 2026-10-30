import asyncio
import os
import signal

import pytest

from iosfakerun.cli import controls
from iosfakerun.coordinates import Point
from iosfakerun.device import FakeBackend
from iosfakerun.route import Event, Plan, Route, load_points
from iosfakerun.runner import CleanupError, Control, play


def run(coro):
    return asyncio.run(coro)


def line_plan():
    return Plan(Route(load_points('examples/route_wgs84.json','wgs84')))


def test_absolute_schedule_300m_no_accumulating_drift(clock, acceptance):
    backend = FakeBackend(clock=clock, send_cost=.15)
    plan = line_plan()
    run(play(backend,plan.events(),plan.end_time,control=Control(clock)))
    assert len(backend.sent) == 101
    assert max(abs(send[0]-i) for i,send in enumerate(backend.sent)) <= acceptance['schedule_300m']['max_start_error_s']
    assert clock.now() == pytest.approx(100.15, abs=1e-7, rel=0)
    assert backend.calls[-2:] == ['clear','close']
    assert backend.sent[-1][1:] == (0.0,acceptance['degrees_for_300m_equator'])


def test_three_loops_complete_on_backend(clock, acceptance):
    degree = acceptance['degrees_for_300m_equator']
    route = Route([Point(0,0),Point(0,degree/3),Point(0,degree)],close=True)
    plan = Plan(route,loops=3)
    backend = FakeBackend(clock=clock)
    run(play(backend,plan.events(),plan.end_time,control=Control(clock)))
    assert clock.now() == pytest.approx(600,abs=1e-7)
    assert len(backend.sent) == 604
    assert backend.sent[-1][1:] == (0,0)
    for lap in range(3):
        assert any(abs(t-(200*lap+100/3))<1e-7 and lon==degree/3 for t,lat,lon in backend.sent)


def test_pause_freezes_progress_and_resume_does_not_catch_up(clock):
    control = Control(clock)
    paused = False
    resumed = False
    def hook(c):
        nonlocal paused,resumed
        if c.t >= .5 and not paused:
            paused = True
            control.command('p')
        if paused and not resumed and c.t >= 10.5-1e-9:
            resumed = True
            control.command('r')
    clock.hook = hook
    backend = FakeBackend(clock=clock)
    plan = Plan(line_plan().route,max_seconds=2)
    run(play(backend,plan.events(),plan.end_time,control=control))
    assert [t for t,_,_ in backend.sent] == pytest.approx([0,11,12],abs=1e-7,rel=0)
    assert control.elapsed() == pytest.approx(2,abs=1e-7)


def test_q_while_paused_is_bounded(clock):
    control = Control(clock)
    def hook(c):
        if c.t >= .2:
            control.command('p')
        if c.t >= .6:
            control.command('q')
    clock.hook = hook
    backend = FakeBackend(clock=clock)
    plan = line_plan()
    run(play(backend,plan.events(),plan.end_time,control=control))
    assert len(backend.sent) == 1
    assert clock.now() < .8
    assert backend.calls[-2:] == ['clear','close']


def test_late_over_two_seconds_aborts_no_burst(clock):
    jumped=False
    def hook(c):
        nonlocal jumped
        if not jumped and c.t >= 1-1e-9:
            jumped=True
            c.t += 2.1
    clock.hook=hook
    backend = FakeBackend(clock=clock)
    with pytest.raises(RuntimeError,match='迟到'):
        run(play(backend,line_plan().events(),100,control=Control(clock)))
    assert len(backend.sent)==1
    assert backend.calls[-2:]==['clear','close']


def test_dense_corners_fail_instead_of_burst(clock):
    route = Route([Point(0,0),Point(0,1e-7),Point(1e-7,1e-7)])
    backend=FakeBackend(clock=clock,send_cost=.15)
    with pytest.raises(RuntimeError,match='过密'):
        run(play(backend,Plan(route).events(),1,control=Control(clock)))
    assert len(backend.sent)==1
    assert backend.calls[-2:]==['clear','close']


def test_first_set_failure_still_clears(clock):
    backend=FakeBackend(clock=clock,fail_on=1)
    with pytest.raises(ConnectionError):
        run(play(backend,line_plan().events(),100,control=Control(clock)))
    assert backend.calls == ['connect','ready','set','clear','close']


def test_middle_set_failure_no_retry_or_switch(clock):
    backend=FakeBackend(clock=clock,fail_on=3)
    with pytest.raises(ConnectionError):
        run(play(backend,line_plan().events(),100,control=Control(clock)))
    assert backend.calls == ['connect','ready','set','set','set','clear','close']


def test_clear_failure_is_failure_not_restored(clock):
    backend=FakeBackend(clock=clock,clear_error=ConnectionError('断线'))
    output=[]
    with pytest.raises(CleanupError,match='未能确认已解除模拟定位.*reset'):
        run(play(backend,[Event(0,Point(0,0),0,1)],0,control=Control(clock),log=output.append))
    assert not output
    assert backend.calls[-2:]==['clear','close']


def test_send_timeout_first_attempt_is_cleared(clock):
    class Slow(FakeBackend):
        async def set_location(self,*args):
            self.calls.append('set')
            try:
                await asyncio.sleep(100)
            finally:
                self.calls.append('set_cancelled')
    backend=Slow(clock=clock)
    with pytest.raises(asyncio.TimeoutError):
        run(play(backend,line_plan().events(),100,control=Control(clock),send_timeout=.01))
    assert backend.calls[-3:]==['set_cancelled','clear','close']


def test_clear_timeout_still_closes(clock):
    class SlowClear(FakeBackend):
        async def clear_location(self):
            self.calls.append('clear')
            await asyncio.sleep(100)
    backend=SlowClear(clock=clock)
    with pytest.raises(CleanupError,match='TimeoutError'):
        run(play(backend,[Event(0,Point(0,0),0,1)],0,control=Control(clock),cleanup_timeout=.01))
    assert backend.calls[-2:]==['clear','close']


def test_async_cancellation_and_repeated_cancellation_protect_cleanup():
    async def scenario():
        clearing=asyncio.Event()
        class Cancelled(FakeBackend):
            async def set_location(self,*args):
                self.calls.append('set')
                asyncio.current_task().get_loop().call_soon(task.cancel)
                await asyncio.sleep(100)
            async def clear_location(self):
                self.calls.append('clear')
                clearing.set()
                await asyncio.sleep(.01)
                self.calls.append('cleared')
        backend=Cancelled()
        task=asyncio.create_task(play(backend,[Event(0,Point(0,0),0,1)],100))
        await clearing.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert backend.calls[-3:]==['clear','cleared','close']
    run(scenario())


@pytest.mark.parametrize('signum',[signal.SIGINT,signal.SIGTERM])
def test_actual_signal_handlers_stop_and_clear(signum):
    async def scenario():
        backend=FakeBackend()
        control=Control()
        with controls(control):
            asyncio.get_running_loop().call_later(.02,os.kill,os.getpid(),signum)
            await play(backend,[Event(0,Point(0,0),0,1)],100,control=control)
        assert control.stopped
        assert control.exit_code==128+signum
        assert backend.calls[-2:]==['clear','close']
    run(scenario())


def test_progress_at_most_once_per_second(clock):
    plan=Plan(line_plan().route,hz=10,max_seconds=2)
    backend=FakeBackend(clock=clock)
    emitted=[]
    run(play(backend,plan.events(),plan.end_time,control=Control(clock),progress=lambda e,r:emitted.append(clock.now())))
    assert all(b-a>=1 for a,b in zip(emitted,emitted[1:]))


def test_connection_and_service_failures_still_close(clock):
    for stage in ['connect','ensure_location_service']:
        backend=FakeBackend(clock=clock)
        async def failed():raise ConnectionError('连接/服务失败')
        setattr(backend,stage,failed)
        with pytest.raises(ConnectionError):
            run(play(backend,line_plan().events(),100,control=Control(clock)))
        assert 'clear' not in backend.calls
        assert backend.calls[-1]=='close'


def test_self_cancelled_clear_still_closes(clock):
    class CancelClear(FakeBackend):
        async def clear_location(self):
            self.calls.append('clear')
            raise asyncio.CancelledError()
    backend=CancelClear(clock=clock)
    with pytest.raises(CleanupError,match='未能确认'):
        run(play(backend,[Event(0,Point(0,0),0,1)],0,control=Control(clock)))
    assert backend.calls[-2:]==['clear','close']


def test_delayed_connect_does_not_consume_motion_time(clock):
    class SlowConnect(FakeBackend):
        async def connect(self):
            await super().connect()
            await clock.sleep(4)
    backend=SlowConnect(clock=clock)
    plan=Plan(line_plan().route,max_seconds=1)
    control=Control(clock)
    run(play(backend,plan.events(),plan.end_time,control=control))
    assert [t for t,_,_ in backend.sent]==pytest.approx([4,5],abs=1e-7,rel=0)
    assert control.elapsed()==pytest.approx(1,abs=1e-7)
