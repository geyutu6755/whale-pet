# 🐋 鲸鱼娘桌宠 — ZCode / Agent 插件

经典的 **DeepSeek 鲸鱼娘**桌面宠物插件：B站画师 **ZipZipPipe** 的「鲸鱼娘」表情包形象，
15 状态正版精灵图 + 5 个程序化动作，60fps 丝滑渲染。
内置 **Token 用量 HUD**（累计用量 / 缓存命中率 / 输出速率）与 **MCP 工具**，
适配 ZCode / DeepSeek Harness / Codex 等 Agent。

![鲸鱼娘](plugins/whale-pet/pet/assets/sheets/idle.png)

## ✨ 特性

- **桌宠**：正版鲸鱼娘形象，待机眨眼、走路散步、转圈圈、摇头晃脑、摇摆、蹦跳、点头、
  睡觉 Zzz、开心飘爱心、被拖拽摇摆——全部帧预渲染，60fps 无卡顿
- **118 条台词**：打招呼/戳戳/抚摸/拖拽/散步/小动作/睡前醒后 + 独家 token 梗
  （「我要吃 token！」「我可不是吃白饭的——我吃 token。」「缓存命中！省下来的算力请你吃糖🍬」）
  ——点击查看用量时她会即兴吐槽
- **Token 用量 HUD**（均匀渐变毛玻璃卡片，默认点击宠物时短暂显示 8 秒后自动隐藏）：
  - 总 Token 消耗量（含输入/输出明细）
  - 缓存命中率（cache_read ÷ (cache_read + cache_creation + input)，带进度条）
  - 响应次数 + 最近输出速率（tok/s，按回复耗时估算）
  - 显示模式三档：点击时显示 / 始终显示 / 关闭（托盘菜单或 MCP `hud_on/hud_off/hud_auto`）
- **Agent 联动**：MCP 工具让 Agent 在任务完成时庆祝、出错时惊吓、思考时陪伴、
  等待批准时提醒
- **真配音**：事件全部优先使用 **49 条社区原声**（鲸鱼娘真配音）——点她说
  「嗯哼～人家在呢！」、连戳她会说「哼！不理你了……才怪～」、摸头「主人摸摸头，
  烦恼全飞走～」、投喂「好想吃小鱼干…啊不是，是投喂～」；Agent 任务完成她会说
  「任务完成啦！主人真棒！」，出错「别急别急，人家再想想办法～」，
  等待批准「需要主人批准啦～」；同类随机不重复，**整句语音与她头顶气泡的台词同步**
  （28 条 TTS 合成短音效已默认退出事件池，仅作备用素材）
- **音效可控且不吵**：默认开启，**开关 + 音量三档**（托盘菜单 / 右键菜单 / 配置）；
  只有你动手（点击/连戳/抚摸/拖拽/投喂/玩耍/哄睡）或任务完成·出错·等待批准时才出声，
  待机、入睡、散步一律安静；她说话时上一条没播完不会插队，也在 1.2 秒内不连开第二条
- **「肉嘟嘟」伪 3D 皮肤**（默认）：给平面贴纸做程序化充气增色——把角色当充气气球
  建高度场，左上主光 + 底部环境光遮蔽 + 边缘反光 + 双层果冻高光，圆润立体、脸不糊；
  托盘「皮肤」一键切回原版平面（`pet_config.json` 的 `skin`），
  由 `pet/make_skin_puffy.py` 从原版素材生成（`assets/sheets-puffy/`）
- **Q弹果冻动画**：点她、戳她、放下她、庆祝、投喂、摸摸时，会有衰减的
  挤压↔拉伸形变（以脚底为锚，先压扁再回弹）——果冻手感的关键
- **扔得出去也接得住**：拖拽甩出去她会沿抛物线飞出去（还会朝飞行方向转头），
  落地弹两下再站稳
- **视线跟随**：待机时把鼠标停在哪边超过 2 秒，她就转过去看（纯轮询，无全局钩子）
- **久坐提醒**（可关）：连续工作/思考 50 分钟，她会温柔催你起来伸个懒腰
- **陪伴成长**（借鉴上游 whale-girl 成长系统）：完成任务 +10 XP、会话 +5、
  陪伴时长累积；等级与称号（初次协作 → 勤劳伙伴 → 百炼成钢…）解锁即庆祝；
  `pet_state` 可查；账本存 `~/.whale-pet/companion.json`
- **开机自启**（托盘开关）：写 HKCU Run 键并指向自定位最新副本的自启脚本，
  插件升级不会失效
- **自动出现**：Agent 会话启动（SessionStart 钩子）时自动拉起桌宠；没有钩子的
  Agent（Codex/Cursor…）由 MCP 工具调用时自动拉起
- **可开关**：托盘菜单 / Agent MCP 工具 / 配置文件三处开关
- **装得干净卸得干净**：`manage.py` 一个入口管理所有 Agent 的安装/卸载，
  卸载先停进程再摘注册，不留孤儿条目
- **漫游视口**：角色在窗口内 60fps 移动，越界才平移窗口，拖拽 1:1 跟随不卡顿

## 📦 安装 / 卸载

### 一个入口管所有 Agent（推荐）

```bash
python plugins/whale-pet/manage.py              # 状态总览（桌宠进程 + 各 Agent 装没装）
python plugins/whale-pet/manage.py install zcode    # 装到 ZCode（原生插件）
python plugins/whale-pet/manage.py install codex     # 装到 Codex（注册 MCP，调用时自动拉起桌宠）
python plugins/whale-pet/manage.py install all       # 所有检测到的 Agent 一次装好
python plugins/whale-pet/manage.py uninstall zcode   # 卸载（先停桌宠 → 再摘注册 → 不留残渣）
python plugins/whale-pet/manage.py uninstall all --purge   # 全卸 + 清理本地产物
python plugins/whale-pet/manage.py start | stop | restart  # 启停桌宠
python plugins/whale-pet/manage.py sound             # 依次试听 8 条音效
```

卸载是「除净」语义：先摘掉插件/市场/MCP 注册，**只有当没有别的 Agent 还在用时才停掉
桌宠**（`uninstall all` 或 `--purge` 一定停）；`--purge` 额外清掉 `pet_config.json`、
`bridge_token`、`usage_state.json`、`__pycache__`、ZCode 插件缓存与 MCP 启动器；
改任何 Agent 配置文件前都会备份成 `*.whale-bak`。

**升级不会失效**：注册到别的 Agent 的 MCP 用的是 `~/.whale-pet/mcp_launcher.py`
（每次启动自动定位最新安装副本），所以插件升级换版本目录后依然能跑；
ZCode 的钩子也带路径存在性守卫，升级后不重启只会静默跳过、不再报错。

**升级流程是自动的**：`manage.py install zcode` 会先停桌宠（Windows 下运行中的副本会
锁住插件缓存目录，导致 CLI 替换版本时 `EPERM` 失败）→ 更新 → **清掉缓存里的旧版本副本**
（CLI 不会自己清，每个好几 MB）→ 从新副本自动重新拉起桌宠。
`manage.py start` 也总是优先拉起"已安装的那份"，保证 token 与 ZCode 钩子/MCP 一致。

### ZCode 图形界面安装

1. ZCode → 左下 **Plugin Marketplace → Add → Add Plugin Marketplace**
2. 粘贴本仓库地址：`geyutu6755/whale-pet`（或完整 `https://github.com/geyutu6755/whale-pet`）
3. **Personal → whale-pet-market → 鲸鱼娘桌宠 → Install**
4. 新建任务（或重启 ZCode）→ 鲸鱼娘自动出现 🎉

**方式二（本地目录）**
1. `git clone https://github.com/geyutu6755/whale-pet` 到本地
2. 添加市场时粘贴仓库根目录路径（含 `marketplace.json` 的那层）
3. 同样在 Personal 里 Install

## 🤝 适配哪些 Agent？

| Agent | 支持方式 | 一条命令安装 |
|-------|---------|-------------|
| **ZCode** | 原生插件（本仓库即插件市场） | `manage.py install zcode` |
| **Claude Code** | 原生插件（仓库含 `.claude-plugin` 双格式） | `manage.py install claude` |
| **Codex** | MCP 服务器（注册稳定启动器，无钩子、工具调用时自动拉起桌宠） | `manage.py install codex` |
| **其他支持 MCP 的 Agent**（Cursor/Windsurf/Cline…） | MCP JSON 片段 | `manage.py install mcp [--config 配置文件]` |
| **任何能跑命令的 Agent** | `whale_cli.py` CLI / HTTP 桥 | 无需安装 |

桌宠核心与 Agent 完全解耦：独立进程 + 本地 HTTP 桥（`127.0.0.1:37821`）
+ CLI + MCP 服务器，换 Agent 不用换桌宠。完整接入说明见
**[docs/integrations.md](docs/integrations.md)**。

**平台要求**：桌宠本体（透明窗口 / 音效 / 托盘）目前仅支持 **Windows**
（非 Windows 会给出提示后安静退出）；HTTP 桥、CLI、MCP 三个接口本身不挑平台，
所以「控制 + 用量上报」在其他系统上依然可用。需要 Python 3.8+，依赖
`pillow`、`numpy`、`pystray`。

## 🔄 数据实时性（按天统计）

面板显示**今天**的用量，**跨天自动归零**，实时记录当天数据：

- 桌宠常驻采集：每 **1 秒**读一次 ZCode 的模型 I/O 记录（`~/.zcode/cli/rollout/*.jsonl`），
  每次模型调用完成即入账 → 面板数字当场变化
- **右键 / 托盘 → 用量统计**：今日 / 近 7 天 / 近 30 天（带逐日迷你柱状图，今天高亮）
- **绝不重复计**：按 requestId 逐条记账（持久化），重启、重装、升级都不会把同一次调用算两遍
- 账本存在 `~/.whale-pet/usage_state.json`（**插件目录之外**，重装/升级不会覆盖或回退），
  保留 40 天明细；首次运行自动回填 rollout 里已有的历史
- 数据源可切：`pet_config.json` 的 `usage_source`（`auto` / `rollout` / `hooks`）；
  其他宿主没有这份记录时自动回落宿主钩子

## 🎮 交互

| 操作 | 反应 | 语音 |
|------|------|------|
| 快速点击 | 开心 + 飘爱心 | 「嗷呜～」等短反应音 |
| 双击 | 玩耍抛球 | 「好耶！」「嘿嘿～」 |
| 按住不动 0.5s | 抚摸（眯眼笑 + 爱心上浮） | 「摸摸头～」或整句撒娇 |
| 按住拖动 | 被拎起来摇摆 | 「哎呀呀～」「哇！」 |
| 连续戳 3 下以上 | 逐渐不耐烦 | 「哎呀！」「别、别戳啦！」 |
| 连续戳 5 下 | 吓到 → 失落 | 「哼！」→「呜呜～」 |
| 空闲 60 秒 | 自己睡着，点她唤醒 | 醒来「我在呢～」（入睡不发声） |
| 右键「哄她睡觉」 | 立刻睡觉 | 「困困啦～」「晚安呀～」 |
| 右键 / 托盘 | 菜单（打招呼/投喂/玩耍/哄她睡觉/转圈圈/摇头晃脑/隐藏/**用量统计**/用量面板/**音效+音量+皮肤**/退出） | 投喂「小鱼干！」 |

## 🎵 音效

77 条语音素材，**一条都不浪费**：28 条短反应音 + 49 条整句语音，按「事件 → 候选池」
随机播放、避开刚播过的，反复触发类事件还带冷却（待机闲聊 ≥150s、思考 ≥20s）。

| 触发 | 用到的语音（随机） |
|------|------------------|
| 点击 | 嗷呜～ / 嗷呜，嗷呜～ / 好哒！ / 我在呢～ |
| 连戳 | 哎呀！ / 别、别戳啦！ / 哼！ |
| 抚摸 · Agent 夸奖 | 摸摸头～ / 好痒呀～ / 贴贴～ / 抱抱嘛～ / 谢谢你呀～ / 主人～摸摸我的头嘛～ … |
| 拖拽 | 哎呀呀～ / 哇！ |
| 玩耍 · 双击 | 好耶！ / 嘿嘿～ / 呜呼！ / 搞定啦！ / 嗯哼～ |
| 投喂 | 小鱼干！ |
| 睡醒 / 入睡 / 恢复显示 | 我在呢～ / 好哒！ / 来啦！ / 困困啦～ / 晚安呀～ |
| 打招呼 · 出现 | 主人好～人家是鲸鱼娘！ / 来啦！ |
| Agent 任务完成 | 任务完成啦！主人真棒！ / 搞定！夸夸人家嘛～ / 完美收工！撒花～ …（10 条） |
| Agent 出错 · 失落 | 呜哇…这里出了点问题… / 别急别急，人家再想想办法～ / 呜呜…（9 条） |
| Agent 思考 · 工作 ※ | 正在努力思考中… / 工具在手，天下我有～ / 冲鸭！ / 加油呀！（12 条） |
| 等待批准 | 需要主人批准啦～ |
| 哄她睡觉（菜单） | 困困啦～ / 晚安呀～ |

※ 思考/工作的碎碎念默认**关闭**（托盘菜单「工作中碎碎念」可开），免得你没点她也一直念叨。
待机、入睡、散步**不出声**——只在她头顶冒字，不打扰你。

**气泡会跟着她说的话走**：整句语音（≥6 字）播放时，头顶气泡同步显示那句台词，
做到"嘴上说的"和"屏幕写的"一致；短促音（嗷呜/哎呀）仍搭配内置的 118 条台词。

- 播放走**后台线程**（winsound 不支持「内存+异步」，只能这么绕），主循环零阻塞，
  60fps 动画不受影响；同名单音 90ms 内不重放，防止连点爆音
- **开关与音量**：托盘菜单「音效」勾选开关 + 「音量」小/中/大；**右键菜单**同样有；
  配置存 `pet_config.json` 的 `sound`（默认 true）与 `sound_volume`（默认 0.7）；
  Agent 侧可 `pet_control(sound_on|sound_off)` / `whale_cli.py sound_off` /
  `whale_cli.py sound_volume 0.7`
- 防"卡住重复"：同一句不会连着播（同事件避开最近 3 条、跨事件也避开），
  上一条没播完时非点击类事件直接放弃这次出声，两条语音之间至少隔 1.2 秒
- 素材来源与许可见 [`pet/assets/sounds/CREDITS.md`](plugins/whale-pet/pet/assets/sounds/CREDITS.md)：
  `short/` 为 Edge TTS 合成，`voice/` 来自社区项目（**非商业许可**）
- **许可**：本项目为非商业开源项目，`voice/` 按原项目的非商业许可使用并已署名
  （见 `sounds/CREDITS.md`）；**若要商用**先删掉 `pet/assets/sounds/voice/` 目录——
  桌宠会自动退化为只用 28 条短音效（等待这类没有短音效的事件回落台词），功能不受影响
- 重新导入素材包：`python pet/import_sound_pack.py "<音效包目录或 zip>"`
  （自动裁静音、44.1k→22.05k、峰值归一）

## 🤖 Agent 集成

### MCP 工具（ZCode 装插件后自动可用）

| 工具 | 说明 |
|------|------|
| `pet_control` | action 枚举：say/celebrate/error/disappointed/think/working/wait/welcome/feed/play/pat/trick/idle/hide/show/hud_on/hud_off/sound_on/sound_off |
| `pet_metrics` | 查询 Token 用量统计（默认今天；`days=7` 看近 7 天，含逐日明细） |
| `pet_state` | 查询桌宠状态 |

Agent 典型用法：任务完成 → `pet_control(celebrate)`；进入长思考 → `pet_control(think, ms=...)`；
用户问用量 → `pet_metrics()`。

### HTTP API（任何语言/脚本）

桥服务监听 `127.0.0.1:37821`（token 见 `plugins/whale-pet/pet/assets/bridge_token`）：

```bash
TOKEN=$(cat plugins/whale-pet/pet/assets/bridge_token)
curl -X POST http://127.0.0.1:37821/event -H "Content-Type: application/json" \
     -H "X-Token: $TOKEN" -d '{"type":"celebrate"}'
curl -X POST http://127.0.0.1:37821/metrics -H "Content-Type: application/json" \
     -H "X-Token: $TOKEN" \
     -d '{"input_tokens":1200,"output_tokens":350,"cache_read_tokens":8800,"duration_ms":5200}'
curl http://127.0.0.1:37821/state -H "X-Token: $TOKEN"
```

### CLI

```bash
python whale_cli.py say "部署完成！"
python whale_cli.py celebrate | error | think 10000 | wait | metrics | state
python whale_cli.py sound_on | sound_off      # 音效开关
```

### 用量数据来源

桌宠**优先读 ZCode 的模型 I/O 记录**（`~/.zcode/cli/rollout/model-io-*.jsonl`）：
每条记录带真实 `usage`（inputTokens/outputTokens/cacheReadTokens）与耗时，
桌宠每 1 秒 tail 一次，**按 requestId 逐条记账**（同一次调用永远不会算两遍），
按本地日期分桶 → 面板只显示今天，跨天自动归零；`~/.whale-pet/usage_state.json`
保存最近 40 天明细，重装/升级都不会丢或回退；首次运行自动回填已有历史。

> 为什么不用钩子：ZCode 侧的钩子确实会执行（启动日志 `hookCount: 3`），但它的钩子
> 载荷里既没有 `usage`、也没有 Claude 式的 `transcript_path`，`report_usage.py`
> 取不到用量 → HUD 长期为 0。模型 I/O 记录是同一份数据的可靠来源，且不需宿主配合。
> 钩子保留着并用 `source` 字段区分，其他宿主（没有该记录）会自动回落到钩子上报，
> 可在 `pet_config.json` 用 `usage_source` 强制指定。

Agent 查询：`pet_metrics()`（今天）/ `pet_metrics(days=7)`（近 7 天，MCP）；
CLI `whale_cli.py metrics`（今天）/ `whale_cli.py metrics 30`（近 30 天）；
HTTP `GET /metrics?days=30`。

## 🛠️ 技术方案

- **Tkinter**：无边框置顶窗口，`-transparentcolor` 颜色键透明（半透明像素统一
  键色化，边缘零杂色）
- **漫游视口**：窗口大于角色，角色以画布坐标 60fps 移动，越界才原子平移窗口
- **PIL**：精灵图切片、姿态帧预渲染（转圈圈/摇摆/蹦跳等程序化动画）、HUD 与气泡绘制
- **numpy**：向量化键色重映射
- **MCP**：无第三方依赖的 stdio JSON-RPC 服务器

## 📁 插件结构

```
plugins/whale-pet/
├── manage.py                   # 统一管理器：安装/卸载/状态/启停/试听
├── .zcode-plugin/plugin.json   # 插件清单
├── .claude-plugin/plugin.json  # Claude Code 清单（双格式）
├── hooks/hooks.json            # Claude Code 钩子（command 写法）
├── hooks/hooks.zcode.json      # ZCode 钩子（process 写法，带路径失效守卫）
├── hooks/launch_pet.py         # 分离进程启动桌宠
├── hooks/report_usage.py       # 转写用量提取上报
├── mcp/.mcp.json               # MCP 服务器声明
├── mcp/whale_pet_mcp.py        # MCP 实现（stdio，零依赖，调用时自动拉起桌宠）
├── skills/whale-pet/SKILL.md   # Agent 使用指南
├── commands/pet.md             # /pet 命令
└── pet/                        # 桌宠本体
    ├── whale_pet.py            # 主程序（含音效池引擎）
    ├── whale_cli.py            # CLI
    ├── import_sound_pack.py    # 音效包导入（裁静音/降采样/归一）
    ├── make_skin_puffy.py      # 伪 3D 皮肤生成（充气高度场 + 法线光照）
    ├── make_assets.py          # 图标生成
    └── assets/                 # 精灵图/图标/音效/bridge_token
        ├── sheets/             # 原版平面精灵图（15 状态）
        ├── sheets-puffy/       # 「肉嘟嘟」伪 3D 皮肤（默认，可切回）
        └── sounds/
            ├── short/*.wav     # 28 条短反应音（Edge TTS）
            ├── voice/*.wav     # 49 条整句语音（社区，非商业许可）
            ├── lines.json      # 素材台词（气泡同步用）
            └── CREDITS.md      # 来源与许可
```

## 📜 素材来源与许可

本项目是**个人非商业性质的同人开源项目**（与 DeepSeek 官方无隶属或背书关系）。
仓库的 MIT License 覆盖**源代码**；下列第三方素材各有其许可，不在 MIT 范围内：

| 素材 | 来源 | 许可 |
|------|------|------|
| 角色立绘「鲸鱼娘」 | B站画师 ZipZipPipe 的表情包形象 | 依上游项目分发条款 |
| 精灵图 / 状态机规格 | [vlln/whale-girl](https://github.com/vlln/whale-girl) | MIT |
| 短反应音效（28 条，`sounds/short/`） | Microsoft Edge TTS（edge-tts）合成 | 受语音服务条款约束 |
| 整句语音（49 条，`sounds/voice/`） | [aceice01/dsh-whale-pet](https://github.com/aceice01/dsh-whale-pet) | **非商业许可**（保留许可与致谢；禁止商业用途） |

- 素材致谢与完整许可文本随仓库一起分发：
  `plugins/whale-pet/pet/assets/sounds/CREDITS.md`、
  `.../sounds/LICENSE-community-dsh-whale-pet.txt`、
  `plugins/whale-pet/pet/assets/sheets/CREDITS.md`
- **要商用**必须先替换或另行取得授权（尤其 `sounds/voice/`）；
  删掉 `sounds/voice/` 目录即可自动降级为纯短音效，去掉这部分依赖
