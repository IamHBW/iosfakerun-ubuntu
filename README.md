# iOSFakeRun Ubuntu

通过 USB 在自己的 iOS 15 设备上回放模拟定位。常用操作只需**英文场地标识、距离（米）、配速**：

```bash
uv run --locked iosfakerun jog yuquan --distance 3000 --pace 6:00
```

表示在 `yuquan` 路线回放 3000 米，配速每公里 6 分钟，预计 18 分钟；到达目标后自动清除模拟定位。当前仅内置 Zhejiang University Yuquan Track，支持自定义 JSON 路线。

## 安装

需要 Ubuntu、Python 3.10+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。真实设备需要系统已有可用的 `usbmuxd`；离线预览无需手机。工具不以 root 运行，不修改系统 Python、服务或 USB 权限。

```bash
git clone https://github.com/IamHBW/iosfakerun-ubuntu.git
cd iosfakerun-ubuntu
export UV_CACHE_DIR="$PWD/.uv-cache"
uv sync --locked
uv run --locked iosfakerun --help
```

依赖固定在 `uv.lock`，锁定源为清华 TUNA 镜像，在 `pyproject.toml` 显式声明。无需手动激活虚拟环境，不混用 pip。

## 先离线预览

```bash
mkdir -p outputs/evidence
uv run --locked iosfakerun jog yuquan --distance 3000 --pace 6:00 --dry-run --output outputs/evidence/yuquan.csv
```

`--dry-run` 不枚举、连接或修改设备，不下载镜像，不联网。CSV 字段为 `time_s,latitude,longitude,distance_m,loop`。

## 连接手机并回放

解锁自己的手机，通过 USB 连接。第一次使用先执行：

```bash
uv run --locked iosfakerun doctor
uv run --locked iosfakerun prepare
uv run --locked iosfakerun jog yuquan --distance 3000 --pace 6:00
```

- `doctor` 只读诊断，检查版本、USB 和现有配对，使用 `autopair=False`。
- `prepare` 指引解锁、信任电脑，确认或挂载 DeveloperDiskImage，可能联网下载镜像；不发送定位命令。只有此命令允许自动配对。
- `jog` 从起点直接按配速移动，没有十秒定点等待。距离只填数字，单位固定为米；配速为每公里 `M:SS`。
- 终端输入 `p`、`r`、`q` 加回车，分别暂停、继续、停止。非 TTY 不监听 stdin；Ctrl+C/SIGTERM 同样触发清理。
- 一台 USB 设备可自动选择，多台必须通过 `--udid ID` 指定；全过程锁定该设备。

`jog` 将采样均匀排到各段精确拐点，保留原始几何与目标配速；多圈自动连续回放，最后一圈可在目标距离处截断。

如果设备未确认恢复，重新连接、解锁后独立执行：

```bash
uv run --locked iosfakerun reset
```

`set`、`jog` 和 `run` 一旦尝试发送定位，就在正常结束、停止、异常或取消时尝试 clear，再关闭资源。发送及每项清理分别有 5 秒超时。清理失败会非零退出，并提示“未能确认已解除模拟定位”。库返回仍需和手机地图观察分开判断。拔线、SIGKILL、主机断电后无法保证清理，必要时用户自行重启手机。

## 自定义路线与固定位置

路线 JSON 使用 `lat`、`lng` 字段，也兼容省略最外层方括号的逗号分隔对象：

```json
[{"lat":31.2304,"lng":121.4737},{"lat":31.2306,"lng":121.4739}]
```

`--crs` 必填：`wgs84` 保留原值；`bd09` 按上游近似公式转换，精度不作测绘承诺。拒绝布尔值、非有限数、越界经纬度；相邻重复点去重后至少两点。支持局部路线：纬度绝对值 ≤75°，任意点距起点 ≤100 km，不跨日期变更线；距离采用 Haversine（R=6378137m）。

```bash
uv run --locked iosfakerun run examples/route_wgs84.json --crs wgs84 --speed 3 --dry-run
uv run --locked iosfakerun run examples/route_bd09.json --crs bd09 --speed 3 --loops 2 --close-route --max-seconds 10
uv run --locked iosfakerun set --lat 30.2654986 --lon 120.1190416 --seconds 10
```

真实命令中的示例坐标/路线须在自己的测试设备上确认后使用。原始 `run` 默认 3m/s、1Hz、1圈；多圈要求已闭合或显式 `--close-route`。它使用全局采样与额外拐点事件，真实发送来不及时会停止，不突发补发、不删拐点。`--max-seconds` 只计算有效运动时间，不含暂停。固定时刻调度使用单调时钟，通信耗时不会逐点累加。

独立 `set --seconds 10` 在十秒结束时自动清除；接着再执行 `jog` 会重新设起点。这两条命令属于两次会话，不是连续的定点后移动流程。

`set`/`jog`/`run` 缺少镜像会提示先执行 `prepare`，不会隐式下载。手动镜像需同时给出文件和签名：

```bash
uv run --locked iosfakerun prepare --image /path/DeveloperDiskImage.dmg --signature /path/DeveloperDiskImage.dmg.signature
```

也可在有兼容依据时使用 `prepare --ddi-version 15.5`，与手动文件模式互斥。已有镜像直接复用；自动选择失败保留原始错误，不盲试多个版本。

## 验证与范围

```bash
uv run --locked python -m pytest -q -ra
```

当前实现、真机已验证范围和已知限制统一见 [docs/STATUS.md](docs/STATUS.md)；完整离线复跑步骤见 [docs/TESTING.md](docs/TESTING.md)，路线来源见 [docs/YUQUAN_ROUTE.md](docs/YUQUAN_ROUTE.md)。

仅支持 iOS 15 USB；不包含 GUI、无线、iOS 17+、DVT 或第三方平台集成。第三方跑步/打卡系统是否接受轨迹未验证。内置 `yuquan` 是公开场地外围轮廓，未校准为 400 米标准内圈。

## 授权与本地数据

项目代码按 LGPL-2.1 提供，完整授权及上游归属见 [LICENSE](LICENSE)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。路线数据来自 © OpenStreetMap contributors，按 ODbL-1.0 使用。

配对资料与开发者镜像保存在当前工作目录的 `.reference/`，配对目录权限为 0700；不要分享此目录。镜像、本地环境、原始设备日志、任务书和执行流水被 Git 忽略，并排除在源码包之外。公开仓库保留可复现代码、冻结预期值和经整理的验证结论。
