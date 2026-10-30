import asyncio
import csv
import io
import signal
import socket
from pathlib import Path

import pytest

from iosfakerun.cli import controls, main, parser
from iosfakerun.runner import Control


def bomb(*args,**kwargs):
    raise AssertionError('禁止设备/网络调用')


def test_offline_dry_run_device_and_network_boundaries(monkeypatch,tmp_path,acceptance):
    from pymobiledevice3 import usbmux,lockdown
    from pymobiledevice3.services.mobile_image_mounter import DeveloperDiskImageMounter
    from pymobiledevice3.services.simulate_location import DtSimulateLocation
    import requests
    monkeypatch.setattr(usbmux,'list_devices',bomb)
    monkeypatch.setattr(lockdown,'create_using_usbmux',bomb)
    monkeypatch.setattr(DeveloperDiskImageMounter,'mount',bomb)
    monkeypatch.setattr(DtSimulateLocation,'set',bomb)
    monkeypatch.setattr(DtSimulateLocation,'clear',bomb)
    monkeypatch.setattr(requests.Session,'request',bomb)
    monkeypatch.setattr(socket.socket,'connect',bomb)
    output=tmp_path/'preview.csv'
    assert main(['run','examples/route_wgs84.json','--crs','wgs84','--speed','3','--dry-run','--output',str(output)])==0
    rows=list(csv.DictReader(output.open()))
    assert len(rows)==101
    assert list(rows[0])==acceptance['csv_fields']
    assert float(rows[-1]['distance_m'])==pytest.approx(300,abs=1e-6,rel=0)
    assert float(rows[-1]['time_s'])==pytest.approx(100,abs=1e-7,rel=0)


@pytest.mark.parametrize('argv',[
    ['set','--lat','nan','--lon','0'],
    ['set','--lat','0','--lon','181'],
    ['set','--lat','0','--lon','0','--seconds','0'],
    ['run','examples/route_wgs84.json','--crs','wgs84','--speed','-1'],
    ['run','examples/route_wgs84.json','--crs','wgs84','--hz','nan'],
    ['run','examples/route_wgs84.json','--crs','wgs84','--max-seconds','0'],
    ['run','examples/route_wgs84.json','--crs','wgs84','--loops','0'],
    ['run','examples/route_wgs84.json','--crs','wgs84','--loops','3'],
    ['run','examples/route_wgs84.json','--crs','wgs84','--max-lateness','inf'],
    ['prepare','--image','missing'],
    ['prepare','--signature','missing'],
    ['prepare','--ddi-version','17.0'],
    ['run','examples/route_wgs84.json','--crs','wgs84','--output','preview.csv'],
    ['run','examples/route_wgs84.json','--crs','wgs84','--dry-run','--output','examples/route_wgs84.json'],
])
def test_invalid_inputs_never_touch_device(monkeypatch,argv):
    from iosfakerun import device
    monkeypatch.setattr(device,'RealBackend',bomb)
    monkeypatch.setattr(socket.socket,'connect',bomb)
    assert main(argv)!=0


@pytest.mark.parametrize('text',[
    '[{"lat":true,"lng":0},{"lat":0,"lng":1}]',
    '[{"lat":NaN,"lng":0},{"lat":0,"lng":1}]',
    '[]', '[{"lat":91,"lng":0}]',
])
def test_bad_route_never_touches_device_or_network(monkeypatch,tmp_path,text):
    from iosfakerun import device
    route=tmp_path/'bad.json'
    route.write_text(text)
    monkeypatch.setattr(device,'RealBackend',bomb)
    monkeypatch.setattr(socket.socket,'connect',bomb)
    assert main(['run',str(route),'--crs','wgs84'])!=0


def test_crs_is_required_and_chinese_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(['run','examples/route_wgs84.json','--dry-run'])
    assert exc.value.code==2
    for args in [[],['run'],['set'],['prepare'],['reset'],['doctor']]:
        with pytest.raises(SystemExit) as exc:
            main(args+['--help'])
        assert exc.value.code==0
    assert '离线' in capsys.readouterr().out


def test_six_forms_and_defaults():
    p=parser()
    forms=[['doctor'],['prepare'],['set','--lat','0','--lon','0'],['reset'],
           ['run','examples/route_bd09.json','--crs','bd09','--speed','3','--loops','2','--close-route'],
           ['run','examples/route_wgs84.json','--crs','wgs84','--dry-run','--output','preview.csv']]
    for form in forms:
        assert p.parse_args(form).command==form[0]
    default=p.parse_args(['run','r','--crs','wgs84'])
    assert (default.speed,default.hz,default.loops)==('3','1',1)


def test_non_tty_does_not_read_or_watch_stdin():
    class NonTTY:
        def isatty(self): return False
        readline=bomb
        fileno=bomb
    async def scenario():
        control=Control()
        with controls(control,NonTTY()):
            await asyncio.sleep(0)
        assert not control.stopped
    asyncio.run(scenario())


def test_tty_line_commands_p_r_q_restore_handlers():
    import os
    async def scenario():
        readfd,writefd=os.pipe()
        stream=os.fdopen(readfd,'r')
        class TTY:
            def isatty(self): return True
            def fileno(self): return stream.fileno()
            def readline(self): return stream.readline()
        control=Control()
        previous=signal.getsignal(signal.SIGTERM)
        try:
            with controls(control,TTY()):
                for cmd in ['p','r','q']:
                    os.write(writefd,(cmd+'\n').encode())
                    for _ in range(3): await asyncio.sleep(0)
                    if cmd=='p': assert control.paused_at is not None
                    if cmd=='r': assert control.paused_at is None
                assert control.stopped
            assert signal.getsignal(signal.SIGTERM)==previous
        finally:
            stream.close()
            os.close(writefd)
    asyncio.run(scenario())


def test_clear_error_cli_nonzero(monkeypatch,capsys):
    from iosfakerun import device
    from iosfakerun.device import FakeBackend
    class Broken(FakeBackend):
        def __init__(self,*args): super().__init__(clear_error=ConnectionError('断线'))
    monkeypatch.setattr(device,'RealBackend',Broken)
    assert main(['set','--lat','0','--lon','0','--seconds','.001'])==1
    assert '未能确认已解除模拟定位' in capsys.readouterr().err


def test_prepare_manual_validation_before_device(tmp_path,monkeypatch):
    from iosfakerun import device
    image=tmp_path/'image.dmg'
    signature=tmp_path/'image.signature'
    image.write_bytes(b'test')
    signature.write_bytes(b'test')
    monkeypatch.setattr(device,'RealBackend',bomb)
    assert main(['prepare','--image',str(image),'--signature',str(signature),'--ddi-version','15.5'])==1
