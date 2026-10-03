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
- **音效**：点她会「嗷呜」，连戳会「哎呀」；庆祝「呜呼」、出错「哎呀！」、失落「呜…」、
  投喂「咕噜咕噜」——8 条**原创合成**音效（后台线程播放，不卡 60fps 动画），
  托盘一键静音
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

卸载是「除净」语义：先优雅退出桌宠进程（跨安装副本都能停），再移除插件/市场/MCP
注册，`--purge` 额外清掉 `pet_config.json`、`bridge_token`、`__pycache__`；
改任何 Agent 配置文件前都会备份成 `*.whale-bak`。

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
| **Codex** | MCP 服务器（无钩子，工具调用时自动拉起桌宠） | `manage.py install codex` |
| **其他支持 MCP 的 Agent**（Cursor/Windsurf/Cline…） | MCP JSON 片段 | `manage.py install mcp [--config 配置文件]` |
| **任何能跑命令的 Agent** | `whale_cli.py` CLI / HTTP 桥 | 无需安装 |

桌宠核心与 Agent 完全解耦：独立进程 + 本地 HTTP 桥（`127.0.0.1:37821`）
+ CLI + MCP 服务器，换 Agent 不用换桌宠。完整接入说明见
**[docs/integrations.md](docs/integrations.md)**。

## 🔄 数据实时性

面板数据**全自动实时更新**，无需任何手动刷新：
- 每次回复/工具调用结束 → Agent 钩子自动上报用量 → 面板数字立即变化
- 面板隐藏期间数据照常累计，点开即是最新值
- 面板显示中若有新数据到达，当场刷新

## 🎮 交互

| 操作 | 反应 | 音效 |
|------|------|------|
| 快速点击 | 开心 + 飘爱心 | 「嗷呜」随机变体 |
| 双击 | 玩耍抛球 | 「呜呼」 |
| 按住不动 0.5s | 抚摸（眯眼笑 + 爱心上浮） | 软糯「嗷呜」 |
| 按住拖动 | 被拎起来摇摆 | 短促「嗷呜」 |
| 连续戳 3 下以上 | 逐渐不耐烦 | 「哎呀」（抱怨） |
| 连续戳 5 下 | 吓到 → 失落 | 「哎呀！」→「呜…」 |
| 空闲 60 秒 | 自己睡着，点她唤醒 | 醒来轻哼 |
| 右键 / 托盘 | 菜单（打招呼/投喂/玩耍/转圈圈/摇头晃脑/隐藏/用量面板/**音效开关**/退出） | 投喂「咕噜咕噜」 |

## 🎵 音效

8 条音效全部**原创程序化合成**（`pet/make_sounds.py`，声门源 + 共振峰滤波），
不含任何外部素材，可安全开源分发：

| 文件 | 内容 | 触发 |
|------|------|------|
| `aowu1/2/3.wav` | 嗷呜（招牌叫 / 撒娇 / 短促惊喜） | 点击、抚摸、拖拽、唤醒 |
| `aiya1/2.wav` | 哎呀（受惊 / 抱怨） | 连戳、Agent 报错 |
| `yay.wav` | 呜呼（庆祝 whoop） | 双击玩耍、任务完成庆祝 |
| `sad.wav` | 呜…（失落下垂） | 任务失败失落 |
| `bubble.wav` | 咕噜咕噜（泡泡+吞咽） | 投喂 |

- 播放走后台线程 + 内存 WAV（winsound 不支持「内存+异步」，故用线程），
  主循环零阻塞，动画不受影响
- 托盘菜单「音效」一键静音；配置 `pet_config.json` 的 `sound` / `sound_volume`
- Agent 侧可用 `pet_control(sound_on/sound_off)` 或 `whale_cli.py sound_off` 控制
- 想改音色：编辑 `pet/make_sounds.py` 里的音高/共振峰轨迹后
  `python pet/make_sounds.py` 重新生成，`--play` 可试听

## 🤖 Agent 集成

### MCP 工具（ZCode 装插件后自动可用）

| 工具 | 说明 |
|------|------|
| `pet_control` | action 枚举：say/celebrate/error/disappointed/think/working/wait/welcome/feed/play/pat/trick/idle/hide/show/hud_on/hud_off/sound_on/sound_off |
| `pet_metrics` | 查询 Token 用量统计 |
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

`Stop` / `PostToolUse` 钩子读取会话转写尾部（transcript JSONL）中最后一条 assistant
消息的 `usage`（input/output/cache_read/cache_creation），上报给桌宠 HUD；
输出速率按转写相邻时间戳估算。不同 Agent 的钩子载荷格式如有差异，
可自行适配 `hooks/report_usage.py`，或由 Agent 直接调用 `pet_metrics` 上报。

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
├── hooks/hooks.json            # SessionStart 自启 + Stop/PostToolUse 用量上报
├── hooks/launch_pet.py         # 分离进程启动桌宠
├── hooks/report_usage.py       # 转写用量提取上报
├── mcp/.mcp.json               # MCP 服务器声明
├── mcp/whale_pet_mcp.py        # MCP 实现（stdio，零依赖，调用时自动拉起桌宠）
├── skills/whale-pet/SKILL.md   # Agent 使用指南
├── commands/pet.md             # /pet 命令
└── pet/                        # 桌宠本体
    ├── whale_pet.py            # 主程序（含音效引擎）
    ├── whale_cli.py            # CLI
    ├── make_sounds.py          # 音效合成器（原创，可重新生成）
    ├── make_assets.py          # 图标生成
    └── assets/                 # 精灵图/图标/音效/bridge_token
        └── sounds/*.wav        # 8 条音效
```

## 📜 素材来源与许可

- 角色立绘：B站画师 ZipZipPipe 的「鲸鱼娘」表情包形象
- 精灵图/状态机规格：[vlln/whale-girl](https://github.com/vlln/whale-girl)（MIT License）
- 详见 `plugins/whale-pet/pet/assets/sheets/CREDITS.md`
