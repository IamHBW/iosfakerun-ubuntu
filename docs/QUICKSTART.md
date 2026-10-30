# Quick start

安装、设备准备与恢复统一见 [README](../README.md)。完成首次 `doctor`、`prepare` 后，常用入口为：

```bash
uv run --locked iosfakerun jog yuquan --distance 3000 --pace 6:00
```

距离只填米数，配速为每公里 `M:SS`。离线预览追加 `--dry-run`；真实回放通过 `p`/`r`/`q` 加回车控制。
已验证范围与限制见 [STATUS](STATUS.md)，验收复跑见 [TESTING](TESTING.md)。
