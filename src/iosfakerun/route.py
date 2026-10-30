import bisect
import json
import math
from dataclasses import dataclass
from pathlib import Path

from .coordinates import Point, bd09_to_wgs84, distance, positive


def load_points(path, crs):
    if crs not in ("bd09", "wgs84"):
        raise ValueError("--crs 必须是 bd09 或 wgs84")
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    if not text.startswith("["):
        text = "[" + text + "]"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}:{exc.lineno}:{exc.colno}: JSON 错误：{exc.msg}") from exc
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path}: 路线必须是非空对象数组")
    points = []
    for index, obj in enumerate(data, 1):
        if not isinstance(obj, dict) or "lat" not in obj or "lng" not in obj:
            raise ValueError(f"{path}: 第 {index} 点必须包含 lat 和 lng 字段")
        try:
            point = Point(obj["lat"], obj["lng"])
            if abs(point.latitude) > 75:
                raise ValueError("局部路线要求纬度绝对值 ≤75°")
            if crs == "bd09":
                point = bd09_to_wgs84(point)
        except ValueError as exc:
            raise ValueError(f"{path}: 第 {index} 点：{exc}") from exc
        if not points or point != points[-1]:
            points.append(point)
    return points


class Route:
    def __init__(self, points, close=False):
        clean = []
        for point in points:
            if abs(point.latitude) > 75:
                raise ValueError("局部路线要求纬度绝对值 ≤75°")
            if not clean or point != clean[-1]:
                clean.append(point)
        if len(clean) < 2:
            raise ValueError("去除相邻重合点后，路线至少需要两个有效点")
        if max(p.longitude for p in clean) - min(p.longitude for p in clean) > 180:
            raise ValueError("局部路线不支持跨日期变更线")
        if any(distance(clean[0], point) > 100000 for point in clean):
            raise ValueError("任意点距起点不得超过 100 km")
        if close and clean[-1] != clean[0]:
            clean.append(clean[0])
        self.points = tuple(clean)
        self.cumulative = [0.0]
        for a, b in zip(clean, clean[1:]):
            self.cumulative.append(self.cumulative[-1] + distance(a, b))
        self.length = self.cumulative[-1]
        if not math.isfinite(self.length) or self.length <= 0:
            raise ValueError("路线长度必须为有限正数")
        self.closed = clean[0] == clean[-1]

    def position_at_distance(self, meters):
        if meters <= 0:
            return self.points[0]
        if meters >= self.length:
            return self.points[-1]
        index = bisect.bisect_right(self.cumulative, meters) - 1
        fraction = (meters - self.cumulative[index]) / (self.cumulative[index+1] - self.cumulative[index])
        a, b = self.points[index:index+2]
        return Point(a.latitude + (b.latitude-a.latitude)*fraction,
                     a.longitude + (b.longitude-a.longitude)*fraction)


@dataclass(frozen=True)
class Event:
    time: float
    point: Point
    distance: float
    loop: int


class Plan:
    def __init__(self, route, speed=3, loops=1, hz=1, max_seconds=None):
        self.route = route
        self.speed = positive(speed, "速度")
        self.hz = positive(hz, "频率")
        if isinstance(loops, bool) or not isinstance(loops, int) or loops <= 0:
            raise ValueError("圈数必须为正整数")
        if loops > 1 and not route.closed:
            raise ValueError("开放路线多圈需要 --close-route，圈间不得瞬移")
        self.loops = loops
        try:
            self.total_distance = route.length * loops
            self.duration = self.total_distance / self.speed
            finite = math.isfinite(self.duration) and math.isfinite(self.duration*self.hz)
        except OverflowError:
            finite = False
        if not finite or self.duration <= 0:
            raise ValueError("路线总距离/时长/采样数超出数值范围")
        self.end_time = min(self.duration, positive(max_seconds, "最大时长")) if max_seconds is not None else self.duration

    def _corners(self):
        yield 0.0, self.route.points[0], 1
        for lap in range(self.loops):
            offset = lap * self.route.length
            for meters, point in zip(self.route.cumulative[1:], self.route.points[1:]):
                yield offset + meters, point, lap+1

    def event_at(self, seconds):
        meters = min(seconds*self.speed, self.total_distance)
        lap = min(self.loops, max(1, math.ceil(meters/self.route.length)))
        within = meters - (lap-1)*self.route.length
        return Event(seconds, self.route.position_at_distance(within), meters, lap)

    def events(self):
        corners = self._corners()
        corner = next(corners, None)
        tick = 0
        last_time = -1.0
        while True:
            tick_time = tick / self.hz
            corner_time = corner[0]/self.speed if corner is not None else math.inf
            if min(tick_time, corner_time) > self.end_time:
                break
            # 同一时刻的采样与拐点只发一次，并保留精确拐点坐标。
            same = math.isclose(tick_time, corner_time, rel_tol=0, abs_tol=1e-9)
            if corner_time <= tick_time or same:
                event = Event(corner_time, corner[1], corner[0], corner[2])
                corner = next(corners, None)
                if same:
                    tick += 1
            else:
                event = self.event_at(tick_time)
                tick += 1
            if event.time > self.end_time:
                break
            last_time = event.time
            yield event
        if last_time < self.end_time:
            yield self.event_at(self.end_time)
