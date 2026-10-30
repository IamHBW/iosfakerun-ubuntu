"""3000m/6:00 玉泉CSV的独立验收，不导入iosfakerun。"""
import csv,json,math,sys
from pathlib import Path

route=json.loads(Path('examples/route_yuquan_wgs84.json').read_text())

def segment(a,b):
    def xyz(p):
        lat,lon=math.radians(p['lat']),math.radians(p['lng'])
        return math.cos(lat)*math.cos(lon),math.cos(lat)*math.sin(lon),math.sin(lat)
    u,v=xyz(a),xyz(b)
    cross=(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
    return 6378137*math.atan2(math.sqrt(sum(x*x for x in cross)),sum(x*y for x,y in zip(u,v)))

lengths=[segment(a,b) for a,b in zip(route,route[1:])]
perimeter=sum(lengths)
rows=list(csv.DictReader(Path(sys.argv[1]).open()))
values=[{k:float(v) for k,v in row.items()} for row in rows]
assert all(math.isfinite(v) for row in values for v in row.values())
assert values[0]['time_s']==0 and values[0]['distance_m']==0
assert values[-1]['time_s']==1080 and abs(values[-1]['distance_m']-3000)<1e-6
assert values[-1]['loop']==7
for a,b in zip(values,values[1:]):
    assert b['time_s']>a['time_s']
    assert abs((b['distance_m']-a['distance_m'])/(b['time_s']-a['time_s'])-1000/360)<1e-6
remaining=3000-6*perimeter
for index,length in enumerate(lengths):
    if remaining<=length:
        fraction=remaining/length
        a,b=route[index:index+2]
        assert abs(values[-1]['latitude']-(a['lat']+(b['lat']-a['lat'])*fraction))<1e-9
        assert abs(values[-1]['longitude']-(a['lng']+(b['lng']-a['lng'])*fraction))<1e-9
        break
    remaining-=length
for lap in range(7):
    total=lap*perimeter
    for index,point in enumerate(route):
        if index:total+=lengths[index-1]
        if total<=3000:
            assert any(abs(row['distance_m']-total)<1e-5 and abs(row['latitude']-point['lat'])<1e-9 and abs(row['longitude']-point['lng'])<1e-9 for row in values)
print(f'JOG CSV independent check passed: {len(rows)} events, 3000m, 1080s, 7 laps including partial final lap, all corners and pace retained')
