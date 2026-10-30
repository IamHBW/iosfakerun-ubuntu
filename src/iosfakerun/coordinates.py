"""局部路线坐标。BD-09 算法移植自 Mythologyli/iOSFakeRun。

2026-10-30: 将固定提交 3ecb4d3 的 CoordinateUtils.cs 翻译为 Python；
保留原近似公式及 R=6378137m，增加数值验证。LGPL-2.1，见 LICENSE。
"""
import math
from dataclasses import dataclass

EARTH_RADIUS = 6378137.0


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{label} 必须是有限数值")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} 必须是有限数值") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} 必须是有限数值")
    return result


def positive(value, label):
    result = number(value, label)
    if result <= 0:
        raise ValueError(f"{label} 必须大于 0")
    return result


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float

    def __post_init__(self):
        lat = number(self.latitude, "纬度")
        lon = number(self.longitude, "经度")
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("经纬度越界：纬度 [-90,90]，经度 [-180,180]")
        object.__setattr__(self, "latitude", lat)
        object.__setattr__(self, "longitude", lon)


def bd09_to_wgs84(point):
    pi = math.pi
    xpi = pi * 3000 / 180
    x, y = point.longitude - 0.0065, point.latitude - 0.006
    z = math.hypot(x, y) - 0.00002 * math.sin(y * xpi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * xpi)
    lat, lon = z * math.sin(theta), z * math.cos(theta)
    u, v = lat - 35, lon - 105
    dlat = -100 + 2*v + 3*u + 0.2*u*u + 0.1*v*u + 0.2*math.sqrt(abs(v))
    dlat += (20*math.sin(6*v*pi) + 20*math.sin(2*v*pi)) * 2/3
    dlat += (20*math.sin(u*pi) + 40*math.sin(u/3*pi)) * 2/3
    dlat += (160*math.sin(u/12*pi) + 320*math.sin(u*pi/30)) * 2/3
    dlon = 300 + v + 2*u + 0.1*v*v + 0.1*v*u + 0.1*math.sqrt(abs(v))
    dlon += (20*math.sin(6*v*pi) + 20*math.sin(2*v*pi)) * 2/3
    dlon += (20*math.sin(v*pi) + 40*math.sin(v/3*pi)) * 2/3
    dlon += (150*math.sin(v/12*pi) + 300*math.sin(v/30*pi)) * 2/3
    rad = lat / 180 * pi
    magic = 1 - 0.00669342162296594323 * math.sin(rad)**2
    root = math.sqrt(magic)
    dlon = dlon * 180 / (6378245 / root * math.cos(rad) * pi)
    dlat = dlat * 180 / (6378245 * (1 - 0.00669342162296594323) / (magic * root) * pi)
    return Point(2*lat - (lat+dlat), 2*lon - (lon+dlon))


def distance(a, b):
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * EARTH_RADIUS * math.asin(math.sqrt(min(1.0, max(0.0, h))))
