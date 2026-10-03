# 多 Agent 接入指南

鲸鱼娘桌宠的核心与 Agent **完全解耦**：桌宠本体是独立进程，暴露三种通用接口
（HTTP 桥 / CLI / MCP 服务器），任何 Agent 只要能跑 Shell、调 HTTP 或连 MCP，
就能驱动她并回传 Token 用量。

```
┌─────────────────────────────────────────────────┐
│  Agent（ZCode / Claude Code / Codex / 其他）      │
│    │ MCP 工具  pet_control / pet_metrics         │
│    │ Shell     whale_cli.py celebrate            │
│    │ HTTP      POST /event  POST /metrics        │
│    ▼                                             │
│  本地桥 127.0.0.1:37821（token 鉴权）             │
│    ▼                                             │
│  鲸鱼娘桌宠进程（Tk 透明窗口，独立运行）            │
└─────────────────────────────────────────────────┘
```

## 兼容性总览

| Agent | 安装方式 | 桌宠控制 | 用量 HUD |
|-------|---------|---------|---------|
| **ZCode** | 原生插件（添加本仓库为市场） | MCP 工具 + hooks 自启 | ✅ Stop/PostToolUse 钩子 |
| **Claude Code** | 原生插件（本仓库含 `.claude-plugin` 双清单） | MCP 工具 + SessionStart 自启 | ✅ 同名钩子格式 |
| **Codex** | MCP 服务器（无钩子，工具调用时自动拉起桌宠） | MCP 工具 | ⚠️ 需用 CLI/HTTP 上报用量 |
| **任何支持 MCP 的 Agent**（Cursor、Windsurf、Cline…） | 添加 MCP 服务器配置 | MCP 工具（自动拉起桌宠） | ⚠️ 同上 |
| **仅能跑 Shell 的 Agent** | 无 | `whale_cli.py` | 可用 CLI 上报 |
| **完全封闭的 Agent** | 无 | 手动启动桌宠即可陪伴 | ❌ |

## 统一管理（一个入口管所有 Agent）

```bash
python plugins/whale-pet/manage.py                    # 状态总览
python plugins/whale-pet/manage.py install <agent>    # zcode | claude | codex | mcp | all
python plugins/whale-pet/manage.py uninstall <agent> [--purge]
python plugins/whale-pet/manage.py start | stop | restart | sound
```

- **安装**幂等：市场/插件/MCP 已存在就跳过；`--from-github` 可用 GitHub 仓库作市场源
- **卸载**除净：先优雅停掉桌宠（跨安装副本都能停——按进程命令行找到实际副本，
  用该副本自己的 token 走桥退出），再移除插件/市场/MCP 注册；`--purge` 清本地产物
- 改动任何 Agent 配置文件前备份为 `*.whale-bak`，只动 `whale-pet` 相关条目

## ZCode（原生）

```bash
python plugins/whale-pet/manage.py install zcode       # 命令行一条装好
```

或图形界面：`Plugin Marketplace → Add → Add Plugin Marketplace → 粘贴 geyutu6755/whale-pet
（或本地仓库根）→ Personal → whale-pet-market → 鲸鱼娘桌宠 → Install`

随 Agent 自启（SessionStart 钩子）；用量由 Stop/PostToolUse 钩子自动上报。

## Claude Code（原生）

本仓库同时包含 Claude Code 格式清单（`.claude-plugin/`），可直接作为插件市场：

```bash
python plugins/whale-pet/manage.py install claude      # 检测到 claude 命令时自动执行
# 等价手动命令：
claude plugin marketplace add geyutu6755/whale-pet
claude plugin install whale-pet@whale-pet-market
```

钩子事件名（SessionStart / Stop / PostToolUse）与转写格式（transcript JSONL 的
`message.usage`）与 Claude Code 一致，用量 HUD 开箱可用。

## Codex（MCP 接入，调用即自动拉起桌宠）

```bash
python plugins/whale-pet/manage.py install codex       # 内部执行 codex mcp add
```

等价手动命令：

```bash
codex mcp add whale-pet -- python "<仓库>/plugins/whale-pet/mcp/whale_pet_mcp.py"
```

Codex 没有插件钩子：由 **MCP 服务器在你调用工具时自动拉起桌宠**（首次调用约 4-6 秒，
之后即时）。不想自动拉起可在 `pet_config.json` 设 `"mcp_autostart": false`。

**用量上报**（可选）：Codex 无兼容钩子时，在任务结束时调用：

```bash
python "<仓库>/plugins/whale-pet/pet/whale_cli.py" celebrate   # 庆祝
curl -X POST http://127.0.0.1:37821/metrics \
     -H "Content-Type: application/json" \
     -H "X-Token: $(cat "<仓库>/plugins/whale-pet/pet/assets/bridge_token")" \
     -d '{"input_tokens":1200,"output_tokens":350,"cache_read_tokens":8800,"duration_ms":5200}'
```

## 通用 MCP 配置（JSON 版，适用于大多数 Agent）

```bash
python plugins/whale-pet/manage.py install mcp                          # 打印 JSON 片段
python plugins/whale-pet/manage.py install mcp --config ~/.cursor/mcp.json  # 直接合并（自动备份）
```

```json
{
  "mcpServers": {
    "whale-pet": {
      "command": "python",
      "args": ["<仓库路径>/plugins/whale-pet/mcp/whale_pet_mcp.py"]
    }
  }
}
```

## 音效

她会说话：点击「嗷呜～」、连戳「别、别戳啦！」、投喂「小鱼干！」；Agent 任务完成她会说
「任务完成啦！主人真棒！」、出错「别急别急，人家再想想办法～」、等待批准
「需要主人批准啦～」。共 77 条语音（28 条短反应音 + 49 条整句语音），同类随机不重复；
整句语音播放时气泡台词同步，说的和写的一致。

- **Agent 想自己说台词**：`pet_control(action="say", text="...")`，或 celebrate/error 时带
  `text` 参数——此时只补一个短反应音，不会抢话
- **声音开关**：`pet_control(sound_on|sound_off)` / `whale_cli.py sound_off` / 托盘菜单
- **素材来源与许可**：见 `pet/assets/sounds/CREDITS.md`（`short/` 为 Edge TTS 合成；
  `voice/` 来自社区项目，非商业许可——删掉该目录即退化为纯短音效，功能不受影响）

## 通用 CLI（任何能执行命令的 Agent/脚本）

```bash
python whale_cli.py say "任务完成！"      # 说话
python whale_cli.py celebrate             # 庆祝
python whale_cli.py error                 # 出错
python whale_cli.py think 10000           # 思考陪伴 10s
python whale_cli.py wait                  # 等待批准
python whale_cli.py spin | headshake | trick
python whale_cli.py metrics               # 查询用量
python whale_cli.py state                 # 查询状态
python whale_cli.py hide | show | quit
python whale_cli.py sound_on | sound_off  # 音效开关
```

## 通用 HTTP（任何语言）

```
POST /event    {"type":"celebrate"}                      # 控制动作
POST /metrics  {"input_tokens":..,"output_tokens":..,
                "cache_read_tokens":..,"duration_ms":..}  # 上报用量
GET  /state    → 当前状态 JSON
GET  /metrics  → 用量统计 JSON
```

鉴权：请求头 `X-Token`（token 见 `pet/assets/bridge_token`，每次启动刷新）。
端口默认 `37821`，可在 `pet/pet_config.json` 的 `bridge_port` 修改。

## 用量 HUD 数据说明

- **总 Token** = 累计输入 + 累计输出
- **缓存命中率** = cache_read ÷ (cache_read + cache_creation + input)
- **响应次数** = 收到多少次用量上报
- **输出速率** = 本次输出 token ÷ 生成耗时（毫秒级精度，来自转写时间戳）

面板默认「点击时显示 8 秒」，可在托盘菜单切换为常显/关闭；
数据是实时的——每次上报到达就自动更新，无需手动刷新。
