import asyncio
from types import SimpleNamespace

import pytest

from iosfakerun.device import RealBackend,USBMUX_SOCKET,select_usb


def run(coro):
    return asyncio.run(coro)


def mux(serial,kind='USB'):
    return SimpleNamespace(serial=serial,connection_type=kind)


def test_usb_only_multiple_devices_and_explicit_selection():
    assert select_usb([mux('wifi','Network'),mux('usb')])=='usb'
    assert select_usb([mux('same','Network'),mux('same')],'same')=='same'
    for devices,requested in [([],None),([mux('a'),mux('b')],None),([mux('wifi','Network')],'wifi'),([mux('a')],'missing')]:
        with pytest.raises(RuntimeError): select_usb(devices,requested)
    assert select_usb([mux('a'),mux('b')],'b')=='b'


class Lockdown:
    def __init__(self,udid='usb',version='15.8.3',paired=True):
        self.udid=udid
        self.product_version=version
        self.paired=paired
        self.all_values=dict(ProductType='iPhone8,1',ProductVersion=version,BuildVersion='19H386')
        self.closed=False
    async def close(self): self.closed=True


def install_boundary(monkeypatch,devices,lockdown):
    from pymobiledevice3 import usbmux
    from pymobiledevice3 import lockdown as ld
    observed=[]
    async def discover(**kwargs):
        observed.append(('discover',kwargs))
        return devices
    async def connect(**kwargs):
        observed.append(('connect',kwargs))
        return lockdown
    monkeypatch.setattr(usbmux,'list_devices',discover)
    monkeypatch.setattr(ld,'create_using_usbmux',connect)
    return observed


def test_real_connect_locks_usb_udid_and_disables_pairing(monkeypatch):
    ld=Lockdown()
    observed=install_boundary(monkeypatch,[mux('usb'),mux('usb','Network')],ld)
    backend=RealBackend()
    info=run(backend.connect())
    assert info['Model']=='iPhone 6s'
    assert info['ProductVersion']=='15.8.3' and info['BuildVersion']=='19H386'
    assert observed[0][1]['usbmux_address']==USBMUX_SOCKET
    kwargs=observed[1][1]
    assert kwargs['serial']=='usb' and kwargs['connection_type']=='USB' and kwargs['autopair'] is False
    assert kwargs['usbmux_address']==USBMUX_SOCKET
    run(backend.close())
    assert ld.closed
    observed.clear()
    install_boundary(monkeypatch,[mux('other')],Lockdown('other'))
    with pytest.raises(RuntimeError,match='usb'):
        run(backend.connect())
    assert backend.udid=='usb'


@pytest.mark.parametrize('ld,expected',[(Lockdown('different'),'目标变化'),(Lockdown(version='16.0'),'仅支持 iOS 15')])
def test_incorrect_device_or_version_refused(monkeypatch,ld,expected):
    install_boundary(monkeypatch,[mux('usb')],ld)
    backend=RealBackend('usb')
    with pytest.raises(RuntimeError,match=expected):run(backend.connect())
    run(backend.close())
    assert ld.closed


def test_unpaired_device_reported_without_implicit_pair(monkeypatch):
    ld=Lockdown(paired=False)
    observed=install_boundary(monkeypatch,[mux('usb')],ld)
    backend=RealBackend()
    info=run(backend.connect())
    assert info['Paired'] is False and observed[1][1]['autopair'] is False
    with pytest.raises(RuntimeError,match='未配对'):
        run(backend.ensure_location_service())
    run(backend.close())


def test_doctor_is_read_only_and_prepare_only_pairing(monkeypatch,capsys):
    from iosfakerun.cli import main
    from pymobiledevice3.services.mobile_image_mounter import DeveloperDiskImageMounter
    from pymobiledevice3.services.simulate_location import DtSimulateLocation
    def forbidden(*args,**kwargs): raise AssertionError('doctor 写操作')
    monkeypatch.setattr(DeveloperDiskImageMounter,'mount',forbidden)
    monkeypatch.setattr(DtSimulateLocation,'set',forbidden)
    monkeypatch.setattr(DtSimulateLocation,'clear',forbidden)
    observed=install_boundary(monkeypatch,[mux('usb')],Lockdown(paired=False))
    assert main(['doctor'])==1
    assert observed[1][1]['autopair'] is False
    assert '未请求信任或配对' in capsys.readouterr().out


def test_real_set_clear_argument_order_and_close(monkeypatch):
    from pymobiledevice3.services import simulate_location as sim
    calls=[]
    class Location:
        def __init__(self,lockdown): calls.append(('init',lockdown))
        async def set(self,lat,lon): calls.append(('set',lat,lon))
        async def clear(self): calls.append(('clear',))
    monkeypatch.setattr(sim,'DtSimulateLocation',Location)
    backend=RealBackend('usb')
    ld=Lockdown()
    backend.lockdown=ld
    backend.location=Location(ld)
    run(backend.set_location(30,120))
    run(backend.clear_location())
    assert calls[1:]==[('set',30,120),('clear',)]
    backend.location=None
    run(backend.clear_location())
    assert calls[-1]==('clear',)
    run(backend.close())
    assert ld.closed


def image_boundary(monkeypatch,mounted):
    from pymobiledevice3.services import mobile_image_mounter as module
    calls=[]
    class Mounter:
        def __init__(self,lockdown): calls.append(('mounter',lockdown.udid))
        async def __aenter__(self): return self
        async def __aexit__(self,*args): calls.append(('mounter_close',))
        async def is_image_mounted(self,image_type):
            calls.append(('query',image_type))
            return mounted
        async def mount(self,image,signature): calls.append(('mount',image,signature))
    async def auto(lockdown,**kwargs):calls.append(('auto',lockdown.udid,kwargs))
    monkeypatch.setattr(module,'DeveloperDiskImageMounter',Mounter)
    monkeypatch.setattr(module,'auto_mount_developer',auto)
    return calls


def probe_lockdown():
    ld=Lockdown()
    ld.probes=[]
    class Service:
        async def __aenter__(self):return self
        async def __aexit__(self,*args): ld.probes.append('close_service')
    async def start(name):
        ld.probes.append(name)
        return Service()
    ld.start_lockdown_developer_service=start
    return ld


def test_set_run_missing_image_no_download_or_location(monkeypatch):
    calls=image_boundary(monkeypatch,False)
    backend=RealBackend('usb')
    backend.lockdown=probe_lockdown()
    with pytest.raises(RuntimeError,match='先执行 prepare'):
        run(backend.ensure_location_service())
    assert not any(c[0] in ('auto','mount') for c in calls)
    assert not backend.lockdown.probes
    run(backend.close())


def test_prepare_existing_image_no_upload_and_service_probe(monkeypatch):
    calls=image_boundary(monkeypatch,True)
    backend=RealBackend('usb')
    ld=probe_lockdown()
    backend.lockdown=ld
    run(backend.prepare())
    assert not any(c[0] in ('auto','mount') for c in calls)
    assert ld.probes==['com.apple.dt.simulatelocation','close_service']
    run(backend.close())


def test_prepare_manual_and_automatic_use_locked_session(monkeypatch,tmp_path):
    from pymobiledevice3.services import mobile_image_mounter as module
    calls=[]
    mounted=False
    class Mounter:
        def __init__(self,lockdown):assert lockdown.udid=='usb'
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def is_image_mounted(self,kind):return mounted
        async def mount(self,image,signature):
            nonlocal mounted
            calls.append(('mount',image,signature))
            mounted=True
    async def auto(lockdown,**kwargs):
        nonlocal mounted
        assert lockdown.udid=='usb'
        calls.append(('auto',kwargs))
        mounted=True
    monkeypatch.setattr(module,'DeveloperDiskImageMounter',Mounter)
    monkeypatch.setattr(module,'auto_mount_developer',auto)
    backend=RealBackend('usb')
    backend.lockdown=probe_lockdown()
    image,signature=tmp_path/'i.dmg',tmp_path/'i.signature'
    run(backend.prepare(image,signature))
    assert calls==[('mount',image,signature)]
    mounted=False
    calls.clear()
    run(backend.prepare(ddi_version='15.5'))
    assert calls==[('auto',dict(xcode=str(backend.cache/'Xcode.app'),version='15.5'))]
    run(backend.close())


def test_prepare_auto_failure_preserves_error_without_version_retry(monkeypatch):
    from pymobiledevice3.services import mobile_image_mounter as module
    calls=image_boundary(monkeypatch,False)
    async def failed(lockdown,**kwargs):
        calls.append(('failed',kwargs['version']))
        raise ConnectionError('原始镜像下载失败')
    monkeypatch.setattr(module,'auto_mount_developer',failed)
    backend=RealBackend('usb')
    backend.lockdown=probe_lockdown()
    with pytest.raises(ConnectionError,match='原始镜像下载失败'):
        run(backend.prepare())
    assert [c for c in calls if c[0]=='failed']==[('failed','15.8')]
    run(backend.close())


def test_prepare_explicitly_allows_pairing_and_reset_fresh_session(monkeypatch):
    from iosfakerun.cli import main
    from pymobiledevice3.services import simulate_location as sim
    ld=probe_lockdown()
    observed=install_boundary(monkeypatch,[mux('usb')],ld)
    image_boundary(monkeypatch,True)
    calls=[]
    class Location:
        SERVICE_NAME='com.apple.dt.simulatelocation'
        def __init__(self,lockdown): calls.append(('init',lockdown.udid))
        async def clear(self): calls.append(('clear',))
    monkeypatch.setattr(sim,'DtSimulateLocation',Location)
    assert main(['prepare'])==0
    assert observed[1][1]['autopair'] is True
    ld=Lockdown()
    observed=install_boundary(monkeypatch,[mux('usb')],ld)
    calls.clear()
    assert main(['reset','--udid','usb'])==0
    assert observed[1][1]['autopair'] is False
    assert calls==[('init','usb'),('clear',)]
    assert ld.closed


def test_location_provider_uses_library_close_timeout_without_reusing_socket():
    from iosfakerun.device import LocationProvider
    from pymobiledevice3.services.simulate_location import DtSimulateLocation
    class Writer:
        def __init__(self):self.events=[];self.done=asyncio.get_running_loop().create_future();self.transport=self
        def close(self):self.events.append('close')
        async def wait_closed(self):await self.done
        def abort(self):
            self.events.append('abort')
            if not self.done.done():self.done.set_result(None)
    class Service:
        def __init__(self):self.writer=Writer();self.sent=[];self.closed=False
        async def sendall(self,payload):self.sent.append(payload)
        async def close(self):
            await self.writer.wait_closed()
            self.closed=True
    class Device:
        def __init__(self):self.services=[]
        async def start_lockdown_developer_service(self,name):
            assert name=='com.apple.dt.simulatelocation'
            service=Service();self.services.append(service);return service
    async def scenario():
        device=Device()
        location=DtSimulateLocation(LocationProvider(device))
        await asyncio.wait_for(location.set(30,120),.5)
        await asyncio.wait_for(location.clear(),.5)
        assert len(device.services)==2
        assert all(s.writer.done.done() and s.writer.events==['close','abort'] for s in device.services)
        assert device.services[0].sent==[b'\0\0\0\0',b'\0\0\0\x0230',b'\0\0\0\x03120']
        assert device.services[1].sent==[b'\0\0\0\1']
    run(scenario())


def test_location_provider_cancellation_aborts_transport():
    from iosfakerun.device import LocationProvider
    from pymobiledevice3.services.simulate_location import DtSimulateLocation
    async def scenario():
        closing=asyncio.Event()
        class Writer:
            def __init__(self):self.transport=self;self.aborted=False
            def close(self):closing.set()
            async def wait_closed(self):await asyncio.sleep(100)
            def abort(self):self.aborted=True
        writer=Writer()
        class Service:
            async def sendall(self,payload):pass
        service=Service();service.writer=writer
        class Device:
            async def start_lockdown_developer_service(self,name):return service
        location=DtSimulateLocation(LocationProvider(Device()))
        task=asyncio.create_task(location.set(30,120))
        await closing.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert writer.aborted
    run(scenario())
