# phone/ 手机端执行方案

把任务执行放在**云手机内部的 Termux** 里跑，adb 只用于部署和验收。适合隧道不稳定、或希望电脑关机也能跑的场景。

## 为什么这样做

原先电脑侧执行时，每一步都要经 frp 隧道往返。隧道抖动（`i/o deadline reached`）会让 `uiautomator dump` 超时、脚本中断。

手机端执行时，脚本用 Termux 里的 adb 连**本机 adbd（127.0.0.1:5555）**，全程不出设备，隧道断多久都不影响任务；电脑只在需要时连上去看日志、做验收。

## 前置

- 云手机已装 Termux（F-Droid 或 GitHub 版本）
- 云手机设置里已开启「ADB 调试」（本机 127.0.0.1:5555 在监听）
- Bing App 已登录 Microsoft 账号

## 部署步骤

### 1. 电脑侧推送文件

```bat
cd bing-rewards-automation\phone
push-to-phone.bat 127.0.0.1:55556
```

这一步会把 `bing_rewards.py`、`words.txt`、手机版 `config.json`（serial 自动改为 `127.0.0.1:5555`）和三个手机端脚本推到 `/sdcard/br/`。

> 手机版 config 由 `make_phone_config.py` 从仓库根的 `config.json` 生成，key 自动带过去。

### 2. 云手机侧初始化（只需一次）

在 Termux 里执行：

```bash
bash /sdcard/br/setup-termux.sh
```

它装 Python 和 adb 客户端。注意：Termux 的 adb 可能报 `cannot locate symbol "_ZNSt6__ndk1..."`，脚本会自动升级 `libc++` 修复。

### 3. 部署并自检

```bash
bash /sdcard/br/deploy.sh
```

把文件复制到 `~/bing-rewards/`，做语法检查并跑一次 dry-run。

### 4. 正式执行

```bash
bash /sdcard/br/run_daily.sh
```

日志写到 `~/bing-rewards/logs/run_YYYY-MM-DD.log`，保留 14 天。

跑完会自动审核：读今日积分，**未满 120 就在积分页抓取未完成任务清单并截图留证**，结果写入 `results/YYYY-MM-DD.json` 的 `audit` 字段，同时打印到日志。

### 5. 配每日定时（可选，推荐）

```bash
bash /sdcard/br/setup_cron.sh
```

安装 cronie 并写入 crontab：**每天 09:00** 自动执行 `run_daily.sh`。日志在 `~/bing-rewards/logs/cron.log`。

改时间：编辑 crontab（`crontab -e`），第一列是分钟、第二列是小时。例如每天 20:30 就写 `30 20 * * * ...`。

确认 crond 在跑：`pgrep -f crond`。若开机后没自启，手动 `nohup crond > /dev/null 2>&1 &`。

### 6. 随时审核（不跑任务）

```bash
cd ~/bing-rewards && python3 bing_rewards.py --audit
```

只读今日积分：已满则直接退出；未满则列出已完成/未完成任务并截图。适合跑完想快速确认时用。

## 从电脑验收

隧道通的时候：

```bash
adb connect 127.0.0.1:55556
adb -s 127.0.0.1:55556 shell "tail -30 /data/data/com.termux/files/home/bing-rewards/logs/run_$(date +%Y-%m-%d).log"
```

或直接看积分页截图确认（总积分 / 今日积分 / 各任务状态）。

## 常见问题

| 现象 | 处理 |
|---|---|
| `pkg install` 卡住或超时 | Termux 换国内源：`termux-change-repo`，或重跑 `setup-termux.sh`（幂等） |
| `adb: cannot locate symbol` | `pkg install -y libc++`（setup 脚本已自动处理） |
| `adb devices` 里除了 127.0.0.1:5555 还有 emulator-5554 | 正常，脚本按 config 的 serial 指定 5555，不会误连 |
| 手机端 `input text` 输不进命令 | 本方案不依赖它：文件走 /sdcard，命令由 Termux 终端执行 |
| Jev 偶发 `Network is unreachable` | 手机网络瞬时波动，脚本自动降级规则引擎，任务照常完成 |

## 与电脑侧方案的关系

两套入口共用同一份 `bing_rewards.py`，差别只在 `config.json` 的 `device.serial`：

- 电脑侧（`run_daily.bat`）：serial = `127.0.0.1:55556`（经隧道）
- 手机侧（`run_daily.sh`）：serial = `127.0.0.1:5555`（本机）

功能、任务覆盖、Jev 决策、安全边界完全一致。
