import asyncio
import math
import time

from .coordinates import positive


class SystemClock:
    now = staticmethod(time.monotonic)
    sleep = staticmethod(asyncio.sleep)


class Control:
    def __init__(self, clock=None):
        self.clock = clock or SystemClock()
        self.start = self.clock.now()
        self.paused_at = None
        self.paused_total = 0.0
        self.stopped = False

    def command(self, command):
        now = self.clock.now()
        if command == "p" and self.paused_at is None:
            self.paused_at = now
        elif command == "r" and self.paused_at is not None:
            self.paused_total += now - self.paused_at
            self.paused_at = None
        elif command == "q":
            self.stopped = True

    def elapsed(self):
        now = self.clock.now() if self.paused_at is None else self.paused_at
        return now - self.start - self.paused_total

    async def wait_until(self, deadline):
        while not self.stopped:
            remaining = deadline - self.elapsed()
            if self.paused_at is None and remaining <= 1e-10:
                return True
            await self.clock.sleep(0.1 if self.paused_at is not None else min(0.1, remaining))
        return False


class CleanupError(RuntimeError):
    pass


async def cleanup(backend, attempted, timeout=5, log=print):
    errors = []
    cancelled = False
    operations = [("clear", backend.clear_location)] if attempted else []
    operations.append(("close", backend.close))
    for name, operation in operations:
        task = asyncio.create_task(asyncio.wait_for(operation(), timeout))
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        try:
            task.result()
            if name == "clear":
                log("清除命令已返回；地图中的真实定位恢复仍需人工确认。")
        except (Exception, asyncio.CancelledError) as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    if errors:
        target = getattr(backend, "udid", None)
        suffix = f" --udid {target}" if target else ""
        raise CleanupError("未能确认已解除模拟定位或资源已关闭：" + "; ".join(errors)
                           + f"；重新连接后执行 uv run --locked iosfakerun reset{suffix}")
    if cancelled:
        raise asyncio.CancelledError


async def play(backend, events, duration, *, control=None, send_timeout=5,
               cleanup_timeout=5, max_lateness=2, log=print, progress=None):
    send_timeout = positive(send_timeout, "发送超时")
    cleanup_timeout = positive(cleanup_timeout, "清理超时")
    max_lateness = positive(max_lateness, "最大迟到")
    attempted = False
    try:
        info = await asyncio.wait_for(backend.connect(), 5)
        if info:
            log(f"USB 目标 {info['UDID']}；{info['Model']}；iOS {info['ProductVersion']} ({info['BuildVersion']})")
        await asyncio.wait_for(backend.ensure_location_service(), 5)
        control = control or Control()
        control.start = control.clock.now()
        control.paused_total = 0.0
        if control.paused_at is not None:
            control.paused_at = control.start
        previous_finish = -math.inf
        last_progress = -math.inf
        for event in events:
            if not await control.wait_until(event.time):
                break
            lateness = control.elapsed() - event.time
            if lateness > max_lateness:
                raise RuntimeError(f"迟到 {lateness:.3f}s 超过 {max_lateness:g}s，已停止，不补发积压点")
            if previous_finish > event.time + 1e-7:
                raise RuntimeError("相邻事件过密，发送耗时超过可用间隔；已停止，不补发或删除拐点")
            if lateness > 0.001:
                log(f"调度迟到 {lateness:.3f}s（软件时钟）")
            attempted = True
            await asyncio.wait_for(backend.set_location(event.point.latitude, event.point.longitude), send_timeout)
            previous_finish = control.elapsed()
            now = control.clock.now()
            if progress is not None and now - last_progress >= 1:
                progress(event, max(0, duration-event.time))
                last_progress = now
        if not control.stopped:
            await control.wait_until(duration)
    finally:
        await cleanup(backend, attempted, cleanup_timeout, log)
