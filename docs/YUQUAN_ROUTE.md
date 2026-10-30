# Yuquan route

`yuquan` = Zhejiang University Yuquan Track。包内数据 `src/iosfakerun/data/yuquan.json` 与 `examples/route_yuquan_wgs84.json` 一致，保留公开场地外围轮廓的全部 17 个点（含闭合点）。

## 来源与坐标

- [浙大官方玉泉校区平面图](https://www.zju.edu.cn/_upload/tpl/03/6a/874/template874/images/Yuquan.pdf)：37号田径场，在第一教学楼与宿舍区之间，临近游泳池、邵逸夫体育馆。
- [浙大官方场馆介绍](https://www.tyys.zju.edu.cn/redir.php?catalog_id=172636)：玉泉田径场配置400米标准跑道。
- [OpenStreetMap way 554475695](https://www.openstreetmap.org/way/554475695)，version 1，时间2018-01-20T11:25:22Z；同一场地内足球场为way 494814572。
- 数据 © OpenStreetMap contributors，按 [ODbL-1.0](https://www.openstreetmap.org/copyright) 使用。

OSM坐标按WGS84使用，不作BD-09/GCJ转换。起点位于西侧场边：纬度 **30.2654986**，经度 **120.1190416**。
范围为纬度30.2650317–30.2666160，经度120.1190416–120.1203529。方向按原节点顺序，先向南，经南侧弯道沿东侧向北，再回西侧起点。

## 长度口径

该轮廓折线长 **475.712395米**；按3m/s单圈约158.570798秒。长度属于公开场地外轮廓，未作标准400米内圈测绘校准。OSM几何时间较早，设施位置经官方校区图交叉核对。

`jog`按累计折线长度完成目标米数；例如3000米将执行若干完整圈及最后部分圈。具体方向尚未有单独的人工观察确认，验证范围见 [STATUS](STATUS.md)。

## 独立复核

```bash
mkdir -p outputs/evidence
uv run --locked iosfakerun jog yuquan --distance 3000 --pace 6:00 --dry-run --output outputs/evidence/yuquan-jog-3000m.csv
uv run --locked python tests/verify_jog_preview.py outputs/evidence/yuquan-jog-3000m.csv
```

校验器不导入待测模块，使用单位球三维向量cross/dot的atan2弧长独立重算原始段长度，检查目标距离、时长、终点、全部已到达拐点及配速。
