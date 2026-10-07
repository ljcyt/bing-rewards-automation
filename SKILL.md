---
name: bing-rewards
description: 云手机/安卓真机上的 Bing (Microsoft Rewards) 每日积分任务自动化。纯 adb + Python，无需 root。覆盖签到、搜索赚分、每日活动、阅读赚分、Quiz 活动卡五类任务，内置 Jev 范式单步决策（TypeSafe AI API → 本地 logits → 规则引擎三级降级）、拟人化随机延迟、硬禁区保护与积分前后对照。适用于每天 9 点定时自动跑或手动单任务调试。
---

# Bing Rewards 每日任务自动化

## 何时用
- 需要在云手机（adb 通道，如 127.0.0.1:55556）或安卓真机上自动完成 Bing App 的每日积分任务（签到 / 搜索 / 每日活动 / 阅读 / Quiz 卡）。
- 需要 Windows 计划任务每天定时无人值守执行并留日志。
- 不适用：iOS、无 adb 通道的环境、需要多账号并行的场景（脚本按单设备串号运行，可多份目录配不同 serial 实现轮跑）。

## 前置条件
1. Windows 已装 Python 3.8+ 与 adb（platform-tools），`adb` 在 PATH 或 config.json 的 `device.adb_path` 指向完整路径。
2. 云手机/真机已连接：`adb devices` 显示目标串号且状态为 device。
3. Bing App 已安装并登录 Microsoft 账号（脚本不负责登录）。基线版本 32.6.2110003561；升级后 resource-id 可能变化，脚本启动时会把版本号写进日志。
4. 可选依赖：`pip install transformers torch` 启用本地 logits 决策后端（缺省自动禁用）；API 后端用标准库 urllib，无需安装。
5. config.json 存在（从 config.example.json 复制；该文件含 key，已在 .gitignore 中排除，不要提交到仓库）。按需设置 `jev.backend`：`api` 需在 `jev.api_keys` 填入有效的 TypeSafe key，`off` 完全离线走规则引擎。

## 操作步骤

### 1. 连接与确认
```
adb connect 127.0.0.1:55556
adb devices
python bing_rewards.py --dry-run
```
--dry-run 启动 Bing、dump 界面、输出页面分类与首步建议动作，并模拟正式跑前置链路（读积分→验搜索框可见性）；不执行任务动作（搜索/开卡），但含导航类点击。确认日志 `logs/run_日期.log` 中页面分类合理。

### 2. 单任务调试（建议先人工验证 2-3 天再挂定时）
```
python bing_rewards.py --single search
python bing_rewards.py --single checkin
```
可单跑：checkin / search / daily_activities / read / quiz。

### 3. 正式跑
```
python bing_rewards.py
```
按顺序执行全部任务，结束后输出汇总（各任务状态、积分前后对照），写 `results/YYYY-MM-DD.json` 与 `results/summary.csv`。退出码：0 全部成功 / 1 部分失败 / 2 设备或 App 失败。

### 4. 挂 Windows 定时（每天 09:00，管理员 cmd）
```
schtasks /Create /TN "BingRewardsDaily" /TR "C:\path\to\bing-rewards-automation\run_daily.bat" /SC DAILY /ST 09:00 /F
```
可选开机补跑：`schtasks /Create /TN "BingRewardsOnLogon" /TR "...同上..." /SC ONLOGON /F`（脚本内置当日已完成检测，重复触发无副作用）。查询/删除：`schtasks /Query|/Delete /TN "BingRewardsDaily"`。

## 参数
| 参数 | 说明 |
|---|---|
| `--config <path>` | 配置文件，默认同目录 config.json |
| `--dry-run` | dump+决策+打印，不执行任务动作（搜索/开卡），仅允许导航类点击 |
| `--max-searches N` | 搜索次数上限（默认读 config，30） |
| `--single <task>` | 只跑单个任务 |

config.json 关键段：`device.serial`（设备串号）、`tasks.max_searches` / `watchdog_minutes`（45 分钟看门狗）、`delays.*`（各类随机延迟区间）、`human.*`（开始时间 ±25 分钟抖动、走神概率、坐标抖动）、`jev.*`（决策后端 api/local/off、endpoint、api_keys 主备列表、model）、`local_model.*`。

## 决策模块（Jev 范式）
单步判别：dump 屏幕摘要 → 页面分类 → 离散候选动作集 → choice+置信度 → 门控执行（≥0.90 自动执行；0.60-0.90 复核锚点后保守执行；<0.60 交规则引擎硬兜底）。后端三级降级：(a) TypeSafe AI 官方 API（`POST https://api.typesafe.ai/v1/systemone`，模型 `jev-latest`，Authorization: Bearer，`jev.api_keys` 主备列表遇 401/402/403/429 或额度类错误按序轮换，全部失效本步降级规则引擎）；(b) 本地 Qwen2.5-0.5B logits 投影（可选依赖）；(c) 确定性规则引擎（永远可用）。`jev.backend` 设为 `off` 直接走规则引擎。解析失败/超时自动降级并记 DECISION_BACKEND_FALLBACK，绝不把解析失败当成功。

## 故障排查
| 现象 | 处理 |
|---|---|
| `设备不在线` | `adb connect <serial>`；云手机可能晚开机，run_daily.bat 以 `adb -s <serial> get-state` 轮询最多 5 分钟，超时写 alerts 后退出 |
| uiautomator dump 失败 | 脚本自动重试 3 次；仍失败多为云手机卡顿，重跑即可 |
| 找不到搜索框/积分卡 | Bing 升级导致 resource-id 变更：对比日志中版本号与锚点列表，更新脚本顶部 ID_* 常量 |
| 日志出现 HARD_FALLBACK 增多 | 固定坐标兜底被频繁命中，说明结构化定位失效，优先修 ID 常量 |
| 日志出现 REFUSED_FORBIDDEN_ZONE | 安全线拦截了"兑换/订单历史/Rewards网站"等禁区文本，属正常保护；若误伤正常卡片，检查 FORBIDDEN_KEYWORDS |
| 搜索连续 2 轮积分无增量 | 脚本自动停止搜索任务；确认当日配额口径是否变化 |
| 任务停在资料页/积分页找不到搜索框 | ensure_home 自动恢复（BACK→冷启动）；若日志反复出现"冷启动恢复"说明首页结构变化，核对 ID_SEARCH_BOX 常量 |
| 兜底次数（summary.csv 末列）突然飙升 | App 改版的最灵敏指标，人工核对该日日志 |
| 个人资料页"发生错误。请联系客户支持" | 脚本自动 BACK 重进（最多 3 次），真机实测可恢复 |
| 日志大量 DECISION_BACKEND_FALLBACK | TypeSafe AI key 失效或网络不通；到 console.typesafe.ai 核对并更换 `jev.api_keys`（完整格式 `apikey_<hex_hex>`），或临时把 `jev.backend` 设为 `off`（免轮换等待） |

## 风险与限制
- 自动化 Rewards 有封号风险（各开源项目 README 均明示）；脚本以随机延迟、随机词序、限次、固定设备指纹降低风险，但不能消除。
- `input text` 不支持中文；词库 words.txt 仅 ASCII 词，空格自动转 `%s`。
- Rewards 页 RecyclerView 虚拟化：屏幕外节点 bounds 为 [0,0][0,0]，脚本先滚动再 dump；定位顺序 resource-id → text/desc → bounds 兜底（HARD_FALLBACK）。
- Quiz 不做自动作答，仅点开停留（避免答错与风控）；当日卡全部显示"已赚取"时该任务报 skipped（正常，不算失败）。
- 签到只在确认到达 Rewards 页时报 done；导航失败报 unknown（results JSON 不会记假成功）。
