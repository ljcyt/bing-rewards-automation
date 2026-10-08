# Bing Rewards 云手机每日积分自动化

纯 adb + Python 的 Bing (Microsoft Rewards) 每日积分任务自动化，无必装第三方依赖。覆盖五类每日任务：签到（签入）、搜索赚分、每日活动、阅读赚分、每日 Quiz / 资讯活动卡。

## 文件清单

| 文件 | 说明 |
|---|---|
| `bing_rewards.py` | 主脚本（Python 3.8+ 标准库，transformers/torch 为可选） |
| `config.example.json` | 配置模板（复制为 `config.json` 后按需修改，key 填入 `jev.api_keys`） |
| `words.txt` | 200+ ASCII 搜索词库，每日随机取词 |
| `run_daily.bat` | Windows 计划任务入口（电脑侧执行，经 adb 隧道） |
| `phone/` | 手机端执行方案：脚本跑在云手机 Termux 里，adb 仅做部署与验收（见 `phone/README.md`） |
| `SKILL.md` | Agent skill 规范说明 |
| `tools/` | 辅助脚本：连通自检、单测、进度读取、诊断（见 `tools/README.md`） |
| `logs/`、`results/` | 运行日志与结果汇总（自动生成） |

## 两种执行方式

| 方式 | 执行位置 | 适用场景 | 入口 |
|---|---|---|---|
| 电脑侧 | Windows，经 adb 隧道控制设备 | 隧道稳定、希望电脑统一管理日志 | `run_daily.bat` |
| 手机侧 | 云手机 Termux 内，adb 连本机 5555 | 隧道抖动频繁、或电脑关机时也要跑 | `phone/run_daily.sh` |

两套方式共用同一份 `bing_rewards.py`，仅 `config.json` 的 `device.serial` 不同（电脑侧 `127.0.0.1:55556`，手机侧 `127.0.0.1:5555`）。

## 快速开始

```bat
adb connect 127.0.0.1:55556
adb devices
python bing_rewards.py --dry-run
python bing_rewards.py --single search
python bing_rewards.py
```

1. `--dry-run`：连接设备、启动 Bing、dump 界面、输出页面分类与首步决策，并模拟正式跑前置链路（读积分→验搜索框可见性）；不执行任务动作（搜索/开卡），但含导航类点击（进头像/积分卡）。
2. `--single <checkin|search|daily_activities|read|quiz>`：单任务调试（建议人工验证 2-3 天）。
3. 正式跑：顺序执行全部任务，结束时打印各任务完成情况汇总，写 `results/YYYY-MM-DD.json` 与 `results/summary.csv`。退出码 `0`=全部成功，`1`=部分失败，`2`=设备/App 失败。
4. 跑完自动审核：读今日积分，**未满 120 就在积分页抓取未完成任务清单并截图留证**，写入结果 JSON 的 `audit` 字段并打印到日志。
5. `--audit`：只审核不跑任务（读今日积分，未满则列出未完成任务）。

### 审核的三层判定

审核（`audit_tasks()`）不只看一个来源，避免单点误判：

| 层 | 做什么 | 依据 |
|---|---|---|
| 1. 规则解析 | 给出确定的完成/未完成清单 | 页面文案：已完成 `已赚取的 N 积分`；未完成 `已赚取 X 积分(需要 Y 积分)` 且 X<Y |
| 2. Jev 语义核对 | 把任务文案交给 Jev 判别未完成项，提供置信度 | `choice` 原语 + `probabilities` 分布 |
| 3. 分歧标注 | 两者不一致时以规则为准，差异记入 `disagreement` | 不静默吞掉差异，供人工确认 |

两个实现细节值得注意：

- **Jev 取全部显著项，不只 top1**：实测多项未完成时概率接近（read 0.51 vs search 0.47），只看 `choice` 会漏项，因此取 `probabilities` 中所有 ≥0.15 的项。
- **Jev 失败不影响审核**：手机网络抖动时 Jev 会返回 `Network is unreachable`，此时自动降级为纯规则结果，审核照常完成（已实测）。

Jev 后端关闭（`jev.backend=off`）或调用失败时，`audit.jev` 为 `null`，审核仍给出规则结果。

## 配置说明（config.json）

- `device.serial`：adb 串号，默认 `127.0.0.1:55556`；`device.adb_path`：adb 可执行文件路径。
- `tasks.max_searches`：搜索次数上限（默认 30）；`tasks.watchdog_minutes`：整体看门狗（默认 45 分钟，超时跳收尾）。
- `delays.*`：全部为随机区间（秒），脚本内所有 sleep 均 `random.uniform`，无固定值。
- `human.start_jitter_minutes`：每日开始时间 ±25 分钟随机偏移；`zoneout_prob`：5-10% 概率的 20-40s"走神"长停顿；`tap_jitter_px`：点击坐标 ±30px 抖动。
- `jev`：Jev 单步决策配置，`backend` 取 `api` / `local` / `off`。

### TypeSafe AI API key 的用途与轮换

- 用途：`jev.backend=api` 时，脚本把当前屏幕摘要（页面类型、锚点、可点文本）POST 到 TypeSafe AI 官方 System One 接口，由 Jev 模型（`jev-latest`）做单步判别，返回离散动作 choice + 置信度。
- Endpoint / 模型名：TypeSafe AI 官方文档（truefoundry.com/docs/ai-gateway/jev）——`POST https://api.typesafe.ai/v1/systemone`，`Authorization: Bearer <key>`，body 为 TypeSafe 自有 schema `{"model", "state", "questions"}`，响应 `{"model", "answers", "usage"}`，模型别名 `jev-latest`。
- **⚠️ 只认官方域名**：TypeSafe 官方域名只有 `api.typesafe.ai` 与 `console.typesafe.ai`，其他任何域名（包括第三方中转/代理站）都不是官方端点，配置为 `jev.endpoint` 会导致 key 被拒（401）。连通性自检：`python tools/test_jev_api.py`。
- **主备轮换机制**：`jev.api_keys` 数组存全部 key（主 key 在前，备用 key 依次排后）。请求遇到 HTTP 401/402/403/429 或响应含 quota/credit/insufficient 等额度类错误时，自动换下一个 key 重试；同一轮决策最多轮完全部 key，全部失效则本步降级规则引擎并记 `DECISION_BACKEND_FALLBACK`。key 只存配置文件，绝不硬编码进 py 脚本。
- 替换：到 console.typesafe.ai 生成新 key，改 `config.json` 与 `config.example.json` 的 `jev.api_keys` 数组即可（不需要改脚本）。key 需为官方完整格式 `apikey_<hex_hex>`；脚本（`TypeSafeApiBackend.__init__`）会对裸 `hex_hex` 自动补 `apikey_` 前缀，裸 key 直发会 401。
- 降级：API 超时（8s）/解析失败 → 本地 logits 后端（需 `pip install transformers torch`，未装自动禁用）→ 确定性规则引擎（永远可用）。`jev.backend` 设 `off` 直接走规则引擎，完全不联网。
- 若你的账号所在区域/套餐 endpoint 不同，以 console 内文档为准修改 `jev.endpoint`。

## 每日定时（每天早上 9 点）

管理员 cmd 执行（把路径换成实际安装路径）：

```bat
schtasks /Create /TN "BingRewardsDaily" /TR "C:\path\to\bing-rewards-automation\run_daily.bat" /SC DAILY /ST 09:00 /F
```

可选开机补跑（脚本内置当日已完成检测，重复触发无副作用）：

```bat
schtasks /Create /TN "BingRewardsOnLogon" /TR "C:\path\to\bing-rewards-automation\run_daily.bat" /SC ONLOGON /F
```

查询 / 删除：

```bat
schtasks /Query /TN "BingRewardsDaily"
schtasks /Delete /TN "BingRewardsDaily" /F
```

日志：每次运行追加到 `logs\run_YYYY-MM-DD.log` 与 `logs\sched_YYYYMMDD.log`（bat 层）；任务失败追加 `logs\alerts.log`。

## 内置安全机制

- **硬禁区**：Rewards 页顶部礼品卡兑换轮播（"兑换"按钮）与底部"兑换积分/订单历史记录/打开Rewards网站"入口永不点击；任何候选动作文本命中黑名单即一票否决（日志记 `REFUSED_FORBIDDEN_ZONE`），安全线不信任模型输出。
- **弹窗处置**：每步 dump 后扫描"同意/知道了/Not now"等按钮词与"发生错误。请联系客户支持"错误弹窗（BACK 重进即恢复）。
- **计分校验**：每 5 次搜索回 Rewards 卡读 `sa_profile_daily_points` 增量，连续 2 轮无增量自动停止搜索任务；任务前后读总积分/今日积分/连续天数做对照。
- **看门狗**：整体 45 分钟超时跳收尾汇总；单任务失败重试 2 次（间隔 30-90s）后继续下一任务。
- **收尾**：`force-stop com.microsoft.bing`，退出码供 bat 写 alerts。

## 限制与风险

- **封号风险**：自动化 Rewards 违反微软服务条款，主流开源项目 README 均明示风险（3kh0/bing-rewards 曾于 2023-01 被 GitHub 下架）。脚本以随机延迟、随机词序、限次、固定设备指纹、每日总时长 25-50 分钟来降低风险，**不能消除风险**；建议用小号/低价值账号。
- **App 版本耦合**：resource-id 锚点基于 Bing 32.6.2110003561 实测；App 升级后如定位失效，按日志中版本号更新脚本顶部 `ID_*` 常量。兜底次数（summary.csv 末列）突然飙升是改版的最灵敏指标。
- **输入限制**：`input text` 不支持中文；words.txt 仅 ASCII 词，空格自动转 `%s`。
- **Quiz**：不做自动作答，仅点开停留计曝光（题库无维护保证，避免答错与风控）。
- **真机依赖**：锚点与坐标基于真机分析（Bing 32.6.2110003561，127.0.0.1:55556 云手机）；挂定时前建议先 `--dry-run` + 单任务各跑一天。
- **本地 logits 后端**：Qwen2.5-0.5B 需自行 `pip install transformers torch` 并联网拉模型；未安装时自动禁用，不影响运行。
- **坐标自适应**：滑动与 HARD_FALLBACK 兜底坐标按 `wm size` 实际分辨率相对 1080x2346 基线等比换算，非 1080p 云手机也可用。

