# 🐋 鲸鱼娘桌宠 — ZCode / Agent 插件

经典的 **DeepSeek 鲸鱼娘**桌面宠物插件：B站画师 **ZipZipPipe** 的「鲸鱼娘」表情包形象，
15 状态正版精灵图 + 5 个程序化动作，60fps 丝滑渲染。
内置 **Token 用量 HUD**（累计用量 / 缓存命中率 / 输出速率）与 **MCP 工具**，
适配 ZCode / DeepSeek Harness / Codex 等 Agent。

![鲸鱼娘](plugins/whale-pet/pet/assets/sheets/idle.png)

## ✨ 特性

- **桌宠**：正版鲸鱼娘形象，待机眨眼、走路散步、转圈圈、摇头晃脑、摇摆、蹦跳、点头、
  睡觉 Zzz、开心飘爱心、被拖拽摇摆——全部帧预渲染，60fps 无卡顿
- **Token 用量 HUD**（DSH 底栏风格）：
  - 累计输入 / 输出 Token
  - 缓存命中率（cache_read ÷ (cache_read + cache_creation + input)）
  - 最近输出速率（tok/s，按回复耗时估算）
- **Agent 联动**：MCP 工具让 Agent 在任务完成时庆祝、出错时惊吓、思考时陪伴、
  等待批准时提醒
- **自动出现**：Agent 会话启动（SessionStart 钩子）时自动拉起桌宠，无需手动操作
- **可开关**：托盘菜单 / Agent MCP 工具 / 配置文件三处开关
- **漫游视口**：角色在窗口内 60fps 移动，越界才平移窗口，拖拽 1:1 跟随不卡顿

## 📦 安装（ZCode）

1. 下载本仓库到本地（或 `git clone`）
2. ZCode → **Plugin Marketplace → Add → Add Plugin Marketplace**，粘贴本仓库的 `plugins` 目录路径
3. **Personal → whale-pet-market → 鲸鱼娘桌宠 → Install**
4. 新建任务（或重启 ZCode）→ 鲸鱼娘自动出现 🎉

## 🎮 交互

| 操作 | 反应 |
|------|------|
| 快速点击 | 开心 + 飘爱心 |
| 双击 | 玩耍抛球 |
| 按住不动 0.5s | 抚摸（眯眼笑 + 爱心上浮） |
| 按住拖动 | 被拎起来摇摆 |
| 连续戳 5 下 | 吓到 → 失落 |
| 空闲 60 秒 | 自己睡着，点她唤醒 |
| 右键 | 菜单（打招呼/投喂/玩耍/转圈圈/摇头晃脑/隐藏/用量面板/退出） |

## 🤖 Agent 集成

### MCP 工具（ZCode 装插件后自动可用）

| 工具 | 说明 |
|------|------|
| `pet_control` | action 枚举：say/celebrate/error/disappointed/think/working/wait/welcome/feed/play/pat/trick/idle/hide/show/hud_on/hud_off |
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
├── .zcode-plugin/plugin.json   # 插件清单
├── hooks/hooks.json            # SessionStart 自启 + Stop/PostToolUse 用量上报
├── hooks/launch_pet.py         # 分离进程启动桌宠
├── hooks/report_usage.py       # 转写用量提取上报
├── mcp/.mcp.json               # MCP 服务器声明
├── mcp/whale_pet_mcp.py        # MCP 实现（stdio，零依赖）
├── skills/whale-pet/SKILL.md   # Agent 使用指南
├── commands/pet.md             # /pet 命令
└── pet/                        # 桌宠本体
    ├── whale_pet.py            # 主程序
    ├── whale_cli.py            # CLI
    ├── make_assets.py          # 图标生成
    └── assets/                 # 精灵图/图标/bridge_token
```

## 📜 素材来源与许可

- 角色立绘：B站画师 ZipZipPipe 的「鲸鱼娘」表情包形象
- 精灵图/状态机规格：[vlln/whale-girl](https://github.com/vlln/whale-girl)（MIT License）
- 详见 `plugins/whale-pet/pet/assets/sheets/CREDITS.md`
