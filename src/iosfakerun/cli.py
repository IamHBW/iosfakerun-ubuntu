import argparse
import asyncio
import csv
import importlib.metadata
import json
import platform
import signal
import sys
from contextlib import contextmanager
from pathlib import Path

from .coordinates import Point, positive
from .jog import VENUES, make_jog_plan
from .route import Event, Plan, Route, load_points
from .runner import Control, cleanup, play


def parser():
    root = argparse.ArgumentParser(prog="iosfakerun", description="iOS 15 USB 局部路线回放；设备写操作仅用于自己的测试手机")
    commands = root.add_subparsers(dest="command", required=True, title="命令")
    for name, description in [("doctor", "只读诊断环境、USB 与现有配对"),
                              ("prepare", "解锁/信任指引及开发者镜像准备，可能联网下载"),
                              ("set", "WGS84 固定位置测试，结束后清除"),
                              ("reset", "独立连接并清除模拟定位"),
                              ("run", "按速度回放路线，或完全离线导出"),
                              ("jog", "英文场地标识 + 距离 + 配速，自动跑完并清理")]:
        sub = commands.add_parser(name, help=description, description=description)
        sub.add_argument("--udid", help="明确选择 USB 设备，多设备时必填")
        if name == "prepare":
            sub.add_argument("--image", type=Path, help="手动 DeveloperDiskImage.dmg 路径")
            sub.add_argument("--signature", type=Path, help="手动镜像签名路径，必须与 --image 同时指定")
            sub.add_argument("--ddi-version", help="自动镜像版本覆盖，例如 15.5，与手动路径互斥")
        elif name == "set":
            sub.add_argument("--lat", required=True, help="WGS84 纬度")
            sub.add_argument("--lon", required=True, help="WGS84 经度")
            sub.add_argument("--seconds", default="10", help="保持秒数，默认 10")
        elif name == "jog":
            sub.add_argument("venue", choices=VENUES, help="英文场地标识：yuquan = Zhejiang University Yuquan Track")
            sub.add_argument("--distance", required=True, help="目标距离（米），只输入数字，如 3000")
            sub.add_argument("--pace", required=True, help="每公里配速 M:SS，如 6:00")
            sub.add_argument("--dry-run", action="store_true", help="离线预览，不接触手机")
            sub.add_argument("--output", type=Path, help="dry-run 导出 CSV")
        elif name == "run":
            sub.add_argument("route", type=Path, help="JSON 路线文件，字段 lat/lng")
            sub.add_argument("--crs", choices=("bd09", "wgs84"), required=True, help="输入坐标系，必须明确选择")
            sub.add_argument("--speed", default="3", help="速度 m/s，默认 3")
            sub.add_argument("--loops", type=int, default=1, help="圈数，默认 1；多圈要求闭合")
            sub.add_argument("--hz", default="1", help="采样 Hz，默认 1；额外保留拐点与终点")
            sub.add_argument("--close-route", action="store_true", help="显式加入末点到起点的连接段")
            sub.add_argument("--max-seconds", help="限制有效运动秒数，不含暂停")
            sub.add_argument("--max-lateness", default="2", help="最大允许迟到秒数，默认 2")
            sub.add_argument("--dry-run", action="store_true", help="完全离线，不枚举设备、不联网")
            sub.add_argument("--output", type=Path, help="dry-run 导出 CSV 路径")
    return root


def validate(args):
    if args.command == "jog":
        args.plan, args.target_distance = make_jog_plan(args.venue, args.distance, args.pace)
        args.max_lateness = 2
        if args.output and not args.dry_run:
            raise ValueError("--output 仅用于 --dry-run")
    elif args.command == "run":
        points = load_points(args.route, args.crs)
        args.plan = Plan(Route(points, close=args.close_route), args.speed, args.loops, args.hz, args.max_seconds)
        args.max_lateness = positive(args.max_lateness, "最大迟到")
        if args.output and not args.dry_run:
            raise ValueError("--output 仅用于 --dry-run")
        if args.output and args.output.resolve() == args.route.resolve():
            raise ValueError("CSV 输出不能覆盖输入路线")
    elif args.command == "set":
        args.point = Point(args.lat, args.lon)
        args.seconds = positive(args.seconds, "保持时长")
    elif args.command == "prepare":
        if bool(args.image) != bool(args.signature):
            raise ValueError("--image 与 --signature 必须同时给出")
        if args.image and args.ddi_version:
            raise ValueError("--ddi-version 与手动镜像路径互斥")
        for path in (args.image, args.signature):
            if path and not path.is_file():
                raise ValueError(f"镜像或签名文件不存在：{path}")
        if args.ddi_version and (not args.ddi_version.startswith("15.")
                                 or not all(x.isdigit() for x in args.ddi_version.split("."))):
            raise ValueError("--ddi-version 必须是 iOS 15 的数字版本，如 15.5")


def preview(args):
    plan = args.plan
    print(f"总距离 {getattr(args, 'target_distance', plan.total_distance):.6f} m；预计有效时长 {plan.end_time if args.command == 'jog' else plan.duration:.6f} s；圈数 {plan.loops}")
    if args.command != "jog" and plan.end_time < plan.duration:
        print(f"本次限制有效时长 {plan.end_time:g} s")
    if args.output:
        with args.output.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_s", "latitude", "longitude", "distance_m", "loop"])
            for event in plan.events():
                writer.writerow([event.time, event.point.latitude, event.point.longitude, event.distance, event.loop])
        print(f"已离线导出 {args.output}")
    return 0


@contextmanager
def controls(control, stdin=None):
    stdin = sys.stdin if stdin is None else stdin
    loop = asyncio.get_running_loop()
    previous = {}
    fd = None

    def stop(signum):
        control.exit_code = 128 + signum
        control.command("q")

    def read():
        text = stdin.readline()
        if text:
            control.command(text.strip().lower())
        else:
            loop.remove_reader(fd)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.getsignal(signum)
            loop.add_signal_handler(signum, stop, signum)
        if stdin.isatty():
            fd = stdin.fileno()
            loop.add_reader(fd, read)
            print("输入 p 回车暂停、r 回车继续、q 回车停止；Ctrl+C 同样会清理。")
        yield
    finally:
        if fd is not None:
            loop.remove_reader(fd)
        for signum, handler in previous.items():
            loop.remove_signal_handler(signum)
            signal.signal(signum, handler)


def show_info(info):
    print(json.dumps(info, ensure_ascii=False, sort_keys=True))


async def device_command(args):
    from .device import RealBackend, USBMUX_SOCKET
    backend = RealBackend(args.udid)
    if args.command in ("run", "set", "jog"):
        control = Control()
        with controls(control):
            if args.command in ("run", "jog"):
                plan = args.plan
                meters = getattr(args, "target_distance", plan.total_distance)
                seconds = plan.end_time if args.command == "jog" else plan.duration
                print(f"总距离 {meters:.6f} m；预计有效时长 {seconds:.6f} s")
                def progress(event, remaining):
                    print(f"圈 {event.loop}/{plan.loops}；已走 {event.distance:.2f} m；剩余 {remaining:.2f} s")
                await play(backend, plan.events(), plan.end_time, control=control,
                           max_lateness=args.max_lateness, progress=progress)
            else:
                await play(backend, [Event(0, args.point, 0, 1)], args.seconds, control=control)
        return getattr(control, "exit_code", 0)
    try:
        if args.command == "doctor":
            print(f"Python {platform.python_version()}；pymobiledevice3 {importlib.metadata.version('pymobiledevice3')}")
            print(f"usbmuxd 本地 socket {USBMUX_SOCKET}：{'存在' if Path(USBMUX_SOCKET).exists() else '不存在'}")
        if args.command == "prepare":
            print("请解锁手机；如出现信任提示，请在自己的手机上确认。prepare 允许配对与挂载，不改定位。")
        info = await asyncio.wait_for(backend.connect(autopair=args.command == "prepare"), 35 if args.command == "prepare" else 5)
        show_info(info)
        if args.command == "prepare":
            await backend.prepare(args.image, args.signature, args.ddi_version)
        elif args.command == "reset":
            # 在独立进程中 clear，即使 clear 报错也要有界关闭资源。
            await cleanup(backend, True)
            return 0
        elif not info["Paired"]:
            print("设备未配对；doctor 未请求信任或配对。请解锁后执行 prepare。")
            return 1
        return 0
    finally:
        await cleanup(backend, False)


def error_message(exc):
    name = type(exc).__name__
    detail = f"{name}: {exc}"
    if "Locked" in name or "Password" in name:
        return detail + "；请解锁手机后重试"
    if "Pair" in name or "Trust" in name:
        return detail + "；请解锁并运行 prepare，在手机确认信任"
    if "Image" in name or "Signature" in name or "Mount" in name:
        return detail + "；保留此错误，核对版本/签名，或 prepare --image 文件 --signature 签名；不要盲试版本"
    if "Service" in name:
        return detail + "；检查手机解锁、USB 连接与 DeveloperDiskImage，先执行 prepare"
    if "Timeout" in name:
        return detail + "；设备操作超时，检查 USB 与解锁状态"
    return detail


def main(argv=None):
    root = parser()
    args = root.parse_args(argv)
    try:
        validate(args)
        if args.command in ("run", "jog") and args.dry_run:
            return preview(args)
        return asyncio.run(device_command(args))
    except KeyboardInterrupt:
        print("已中断；若清理未返回，请重新连接后执行 iosfakerun reset。", file=sys.stderr)
        return 130
    except (Exception, asyncio.CancelledError) as exc:
        print("错误：" + error_message(exc), file=sys.stderr)
        return 1
