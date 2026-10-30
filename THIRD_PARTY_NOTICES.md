# Third-party notices

## Coordinate algorithm

`src/iosfakerun/coordinates.py`的BD-09→WGS84近似公式和地球半径常量移植自
[Mythologyli/iOSFakeRun](https://github.com/Mythologyli/iOSFakeRun/tree/3ecb4d31d59a9d811408c64658964587458adaf8)，
固定提交`3ecb4d31d59a9d811408c64658964587458adaf8`的`iOSFakeRun/FakeRun/CoordinateUtils.cs`。
原作者保留版权。2026-10-30翻译为Python，新增验证与具名字段；原回放循环未沿用。
该提交的LICENSE为GNU LGPL2.1；根目录 [LICENSE](LICENSE)保留其完整文本，项目新增代码亦按该授权提供。

服务名称与行为参考同一提交的`Location.cs`、`Image.cs`及`MainWindow.xaml.cs`；未复制其GUI或资源。
[tests/fixtures/bd09_reference.js](tests/fixtures/bd09_reference.js)为独立JavaScript参考翻译，同受上述来源与授权约束；冻结数值位于相邻JSON。
回归结果证明与原近似算法兼容，不证明测绘精度。

## Runtime dependency

[pymobiledevice3 11.48.0](https://pypi.org/project/pymobiledevice3/11.48.0/)通过uv安装，包元数据声明GPL-3.0-or-later，按其自身授权使用；本仓库不复制/修改或随包分发其协议实现。
固定API参考提交为`36193af87b86f18f6b3b0728fb7bc16aecaf8c9d`；实现针对锁定版异步签名核对。

- [异步API文档](https://doronz88.github.io/pymobiledevice3/guides/python-api/)
- [镜像服务源码](https://github.com/doronz88/pymobiledevice3/blob/36193af87b86f18f6b3b0728fb7bc16aecaf8c9d/pymobiledevice3/services/mobile_image_mounter.py)

`uv.lock`保留传递依赖的版本、来源和校验信息；pytest仅为开发依赖，hatchling用于构建。
开发者镜像由用户自行取得或通过上游下载到本地忽略目录；本项目不提交或二次打包镜像，也不分发配对资料。

## Venue data

`src/iosfakerun/data/yuquan.json`与`examples/route_yuquan_wgs84.json`来自 © OpenStreetMap contributors，
[way 554475695](https://www.openstreetmap.org/way/554475695)，version1（2018-01-20）。数据按[ODbL-1.0](https://www.openstreetmap.org/copyright)使用。
保持全部原始轮廓点，未把场地外轮廓声明为400米标准测量线；详见 [YUQUAN_ROUTE](docs/YUQUAN_ROUTE.md)。
