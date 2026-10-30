"""设备边界：延迟导入上游库，离线功能不会枚举或连接手机。"""
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

USBMUX_SOCKET = "/var/run/usbmuxd"


def select_usb(devices, requested=None):
    serials = sorted({d.serial for d in devices if d.connection_type == "USB"})
    if requested:
        if requested not in serials:
            raise RuntimeError(f"指定 USB 设备 {requested} 不可用；当前 USB：{', '.join(serials) or '无'}")
        return requested
    if not serials:
        raise RuntimeError("未发现 USB iPhone；检查数据线、解锁状态和 usbmuxd")
    if len(serials) > 1:
        raise RuntimeError("发现多台 USB 设备，请显式指定 --udid：" + ", ".join(serials))
    return serials[0]


class LocationProvider:
    """保留库的set/clear与每次新连接，只缩短无响应的TLS关闭握手。"""
    def __init__(self, lockdown):
        self.lockdown = lockdown

    def __getattr__(self, name):
        return getattr(self.lockdown, name)

    async def start_lockdown_developer_service(self, name):
        return self._service(name)

    @asynccontextmanager
    async def _service(self, name):
        from pymobiledevice3.service_connection import close_stream_writer
        service = await self.lockdown.start_lockdown_developer_service(name)
        try:
            yield service
        finally:
            # shortcut: 50ms TLS关闭宽限已针对本机iOS15校准，其他固件须重新测量。
            try:
                await close_stream_writer(service.writer, timeout=0.05)
            except asyncio.CancelledError:
                service.writer.transport.abort()
                raise


class RealBackend:
    def __init__(self, udid=None):
        self.udid = udid
        self.lockdown = None
        self.location = None
        self.cache = Path.cwd() / ".reference"

    async def connect(self, autopair=False):
        from pymobiledevice3.usbmux import list_devices
        from pymobiledevice3.lockdown import create_using_usbmux
        devices = await list_devices(usbmux_address=USBMUX_SOCKET)
        self.udid = select_usb(devices, self.udid)
        pairing_cache = self.cache / "pairing"
        pairing_cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        pairing_cache.chmod(0o700)
        self.lockdown = await create_using_usbmux(
            serial=self.udid, autopair=autopair, connection_type="USB",
            usbmux_address=USBMUX_SOCKET, pair_timeout=30,
            pairing_records_cache_folder=pairing_cache)
        actual = self.lockdown.udid
        if actual and actual != self.udid:
            raise RuntimeError(f"连接目标变化：请求 {self.udid}，返回 {actual}，已拒绝")
        if self.lockdown.product_version.split(".")[0] != "15":
            raise RuntimeError(f"本期仅支持 iOS 15，当前为 iOS {self.lockdown.product_version}")
        return self.info()

    def info(self):
        values = self.lockdown.all_values
        model = values.get("ProductType", "未知")
        name = "iPhone 6s" if model in ("iPhone8,1", "iPhone8,2") else model
        if model == "iPhone8,2":
            name = "iPhone 6s Plus"
        return {"UDID": self.udid, "Connection": "USB", "Model": name,
                "ProductType": model, "ProductVersion": values.get("ProductVersion"),
                "BuildVersion": values.get("BuildVersion"), "Paired": self.lockdown.paired}

    def require_paired(self):
        if not self.lockdown.paired:
            raise RuntimeError("设备未配对；请解锁并执行 prepare，在手机上选择信任电脑")

    async def image_mounted(self):
        from pymobiledevice3.services.mobile_image_mounter import DeveloperDiskImageMounter
        self.require_paired()
        async with DeveloperDiskImageMounter(self.lockdown) as mounter:
            return await mounter.is_image_mounted("Developer")

    async def ensure_location_service(self):
        from pymobiledevice3.services.simulate_location import DtSimulateLocation
        self.require_paired()
        if not await self.image_mounted():
            raise RuntimeError("未挂载 DeveloperDiskImage；请先执行 prepare，set/run 不会下载镜像")
        # 仅打开并关闭服务以核验可用性，不发送 set 或 clear。
        async with await self.lockdown.start_lockdown_developer_service(DtSimulateLocation.SERVICE_NAME):
            pass
        self.location = DtSimulateLocation(LocationProvider(self.lockdown))

    async def prepare(self, image=None, signature=None, ddi_version=None, log=print):
        from pymobiledevice3.services.mobile_image_mounter import DeveloperDiskImageMounter, auto_mount_developer
        self.require_paired()
        if await self.image_mounted():
            log("DeveloperDiskImage 已挂载，保留现有镜像；版本来源未知，不从文件名推断。")
        elif image:
            log(f"手动镜像：{Path(image).resolve()}；签名：{Path(signature).resolve()}")
            async with DeveloperDiskImageMounter(self.lockdown) as mounter:
                await mounter.mount(Path(image), Path(signature))
        else:
            version = ddi_version or ".".join(self.lockdown.product_version.split(".")[:2])
            log(f"将使用上游自动挂载，可能联网下载镜像；选择版本 {version}；缓存 {self.cache / 'Xcode.app'}")
            await auto_mount_developer(self.lockdown, xcode=str(self.cache / "Xcode.app"), version=version)
        await self.ensure_location_service()
        log("镜像已挂载，定位服务可打开；未发送定位命令。")

    async def set_location(self, latitude, longitude):
        await self.location.set(latitude, longitude)

    async def clear_location(self):
        # reset 可在独立新进程调用；复用当前 lockdown，不复用上游的短连接。
        from pymobiledevice3.services.simulate_location import DtSimulateLocation
        self.require_paired()
        location = self.location or DtSimulateLocation(LocationProvider(self.lockdown))
        await location.clear()

    async def close(self):
        if self.lockdown is not None:
            await self.lockdown.close()
            self.lockdown = None


class FakeBackend:
    """只用于离线测试；故障与耗时只在设备边界注入。"""
    def __init__(self, *, clock=None, send_cost=0, fail_on=None, clear_error=None):
        self.clock = clock
        self.send_cost = send_cost
        self.fail_on = fail_on
        self.clear_error = clear_error
        self.calls = []
        self.sent = []
        self.udid = "FAKE-USB"

    async def connect(self):
        self.calls.append("connect")

    async def ensure_location_service(self):
        self.calls.append("ready")

    async def set_location(self, latitude, longitude):
        self.calls.append("set")
        self.sent.append((self.clock.now() if self.clock else None, latitude, longitude))
        if self.clock and self.send_cost:
            await self.clock.sleep(self.send_cost)
        if len(self.sent) == self.fail_on:
            raise ConnectionError("模拟 USB 断开/部分发送失败")

    async def clear_location(self):
        self.calls.append("clear")
        if self.clear_error:
            raise self.clear_error

    async def close(self):
        self.calls.append("close")
