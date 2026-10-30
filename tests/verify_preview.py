"""独立验收 CSV；不导入任何 iosfakerun 模块。"""
import csv
import json
import math
import sys
from pathlib import Path


def verify(path):
    expected=json.loads(Path('tests/fixtures/acceptance.json').read_text())
    with Path(path).open(newline='') as stream:
        reader=csv.DictReader(stream)
        assert reader.fieldnames==expected['csv_fields'], reader.fieldnames
        rows=list(reader)
    assert len(rows)==101, len(rows)
    endpoint=expected['degrees_for_300m_equator']
    for index,row in enumerate(rows):
        values={name:float(value) for name,value in row.items()}
        assert all(math.isfinite(value) for value in values.values())
        assert abs(values['time_s']-index)<=expected['time_tolerance_s']
        assert abs(values['distance_m']-index*3)<=expected['distance_tolerance_m']
        assert values['latitude']==0
        assert abs(values['longitude']-endpoint*index/100)<=expected['coordinate_tolerance_deg']
        assert values['loop']==1
    assert float(rows[0]['longitude'])==0
    assert float(rows[-1]['longitude'])==endpoint
    print('CSV 独立断言通过：101行，字段/首尾/距离300m/时长100s/有限值/逐点位置均通过')


if __name__=='__main__':
    verify(sys.argv[1])
