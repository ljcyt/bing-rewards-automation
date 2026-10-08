# tools/ 辅助脚本

这些脚本都从仓库根目录定位 `config.json` 与 `bing_rewards.py`，在任意目录下执行都可以（例：`python tools/test_jev_api.py`）。

| 脚本 | 用途 | 是否需真机 |
|---|---|---|
| `test_jev_api.py` | Jev 官方端点连通性自检：按序用 `jev.api_keys` 每个 key 发一次最小请求，打印 HTTP 状态与响应摘要；至少一个 key 返回 200 即退出码 0 | 否 |
| `test_fixes.py` | 修复项回归单测（规则引擎候选覆盖、OK 词边界、坐标等比换算、ensure_home 恢复、task_search 自锁、quiz 待做卡路径等 8 项） | 否 |
| `read_progress.py` | 读取"阅读以赚取"卡片进度，输出 `READ_PROGRESS=X/Y` | 是 |
| `supervisor_read.py` | read 任务监督循环：反复跑 `--single read` 并测进度，满 30/30 或连续 2 轮不涨即停 | 是 |
| `diag_feed.py` | 诊断：进新闻流后 dump，统计文章候选命中数并打印卡片节点 | 是 |
| `diag_read.py` | 诊断：复现阅读任务的导航与收割逻辑，定位点击落空/误收割 | 是 |
| `probe_read_rule.py` | 实验：逐篇阅读并逐篇核对进度，确定阅读计分规则 | 是 |

运行前提与主脚本相同：`adb` 可用、设备已连接（`config.json` 的 `device.serial`）、Bing 已登录。
