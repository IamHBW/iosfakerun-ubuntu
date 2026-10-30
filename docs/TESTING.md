# Offline verification

从仓库根目录运行。需要现有Python3.10+、uv；依赖安装可联网，已安装后的CLI dry-run保持零设备调用、零网络调用。

```bash
export UV_CACHE_DIR="$PWD/.uv-cache"
uv lock --check
uv sync --locked
mkdir -p outputs/evidence
uv run --locked python -m pytest -q -ra --junitxml=outputs/evidence/pytest.xml
uv run --locked iosfakerun --help
uv run --locked iosfakerun jog --help
uv run --locked iosfakerun run examples/route_wgs84.json --crs wgs84 --speed 3 --dry-run --output outputs/evidence/preview.csv
uv run --locked python tests/verify_preview.py outputs/evidence/preview.csv
uv run --locked iosfakerun jog yuquan --distance 3000 --pace 6:00 --dry-run --output outputs/evidence/yuquan-jog-3000m.csv
uv run --locked python tests/verify_jog_preview.py outputs/evidence/yuquan-jog-3000m.csv
uv build --out-dir outputs/evidence/dist
```

当前结果与实际真机边界见 [STATUS](STATUS.md)。JUnit应为非空测试集，failures/errors/skipped均为0。普通pytest使用FakeBackend和假时钟，不会操作设备。

## 固定预期值

`tests/fixtures/acceptance.json`、`bd09_reference.json`在实现前冻结；不可因实现结果不符而放宽预期值。距离容差1e-6m、调度容差1e-7s、BD-09坐标容差1e-9度。

BD-09参考值来自固定上游C#的独立JavaScript翻译，参考源和授权见 [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md)。可选使用Node重算并人工比较，勿覆盖冻结JSON：

```bash
node tests/fixtures/bd09_reference.js
```

`verify_preview.py`不导入项目模块，按赤道300m/100s的解析预期检查101行CSV；`verify_jog_preview.py`以原始路线三维球面弧长独立重算3000m终点、配速及全部已到达拐点。

## 用例职责

| 文件 | 覆盖范围 |
|---|---|
| test_route.py | JSON/补括号、字段/数值、坐标系、局部边界、短段/重复点/终点、多拐点、闭合及完整3圈 |
| test_runner.py | 绝对时钟、0.15s发送成本无累计漂移、暂停/继续/停止、真实OS信号配合假设备、失败/超时/取消后的清理 |
| test_device.py | USB-only发现、锁定UDID、现有配对、镜像分支、库API参数顺序及有界单次关闭 |
| test_cli.py | CLI输入、dry-run设备/网络边界即失败替身、非TTY、真实PTY命令配合假设备、清理失败非零 |
| test_jog.py | 纯数字米数、M:SS配速、目标距离截断、英文场地、完整3000m/1080s假时钟回放 |

开发期间还执行过一次性副本反向变异：仅去掉clear，原首次set失败测试变红；恢复原源码后全套通过。原始本地设备/调试日志保持私有，公开仓库保留可复跑的测试与冻结数值。
