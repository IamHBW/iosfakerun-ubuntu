"""英文场地标识、距离与每公里配速；复用原路线/调度路径。"""
import math
import re
from importlib.resources import files

from .coordinates import positive
from .route import Event, Plan, Route, load_points

VENUES = {"yuquan": "Zhejiang University Yuquan Track"}


def parse_distance(text):
    return positive(text, "距离（米，只输入数字）")


def parse_pace(text):
    match = re.fullmatch(r"(\d+):([0-5]\d)", text)
    if not match:
        raise ValueError("配速格式应为 M:SS，每公里分钟数，例如 6:00")
    seconds = int(match[1])*60 + int(match[2])
    return 1000 / positive(seconds, "每公里配速秒数")


class JogPlan(Plan):
    def events(self):
        previous_time = 0.0
        for meters, point, lap in self._corners():
            corner_time = meters / self.speed
            if corner_time == 0:
                yield Event(0, point, 0, lap)
                continue
            end = min(corner_time, self.end_time)
            # 每段均匀采样到精确拐点，避免全局整秒采样与拐点挤在一起。
            count = max(1, math.ceil((end-previous_time)*self.hz))
            for index in range(1, count+1):
                seconds = end if index == count else previous_time + (end-previous_time)*index/count
                if index == count and end == corner_time:
                    yield Event(seconds, point, meters, lap)
                else:
                    yield self.event_at(seconds)
            if end == self.end_time:
                return
            previous_time = corner_time


def make_jog_plan(venue, distance_text, pace_text):
    if venue not in VENUES:
        raise ValueError("未知场地；当前可用英文标识：" + ", ".join(VENUES))
    meters = parse_distance(distance_text)
    speed = parse_pace(pace_text)
    resource = files("iosfakerun").joinpath("data", venue + ".json")
    route = Route(load_points(resource, "wgs84"))
    loops = max(1, math.ceil(meters / route.length))
    plan = JogPlan(route, speed=speed, loops=loops, max_seconds=meters/speed)
    return plan, meters
