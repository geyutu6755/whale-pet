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
| **Codex** | 手动接入（MCP 配置 + 启动脚本） | MCP 工具 | ⚠️ 需用 CLI/HTTP 上报用量 |
| **任何支持 MCP 的 Agent**（Cursor、Windsurf、Cline…） | 添加 MCP 服务器配置 | MCP 工具 | ⚠️ 同上 |
| **仅能跑 Shell 的 Agent** | 无 | `whale_cli.py` | 可用 CLI 上报 |
| **完全封闭的 Agent** | 无 | 手动启动桌宠即可陪伴 | ❌ |

## ZCode（原生）

```
Plugin Marketplace → Add → Add Plugin Marketplace → 粘贴 geyutu6755/whale-pet（或本地仓库根）
→ Personal → whale-pet-market → 鲸鱼娘桌宠 → Install
```

随 Agent 自启（SessionStart 钩子）；用量由 Stop/PostToolUse 钩子自动上报。

## Claude Code（原生）

本仓库同时包含 Claude Code 格式清单（`.claude-plugin/`），可直接作为插件市场：

```bash
claude  # 或你使用的入口
/plugin marketplace add geyutu6755/whale-pet
/plugin install whale-pet@whale-pet-market
```

钩子事件名（SessionStart / Stop / PostToolUse）与转写格式（transcript JSONL 的
`message.usage`）与 Claude Code 一致，用量 HUD 开箱可用。

## Codex（手动接入）

1. **确保 Python 可用**，先手动启动一次桌宠：

   ```bash
   python "<仓库>/plugins/whale-pet/pet/whale_pet.py"
   ```

2. **添加 MCP 服务器**：编辑 `~/.codex/config.toml`：

   ```toml
   [mcp_servers.whale-pet]
   command = "python"
   args = ["<仓库路径>/plugins/whale-pet/mcp/whale_pet_mcp.py"]
   ```

   重启 Codex 后即可使用 `pet_control` / `pet_metrics` / `pet_state` 三个工具。

3. **用量上报**（可选）：Codex 无兼容钩子时，在任务结束时调用：

   ```bash
   python "<仓库>/plugins/whale-pet/pet/whale_cli.py" celebrate   # 庆祝
   curl -X POST http://127.0.0.1:37821/metrics \
        -H "Content-Type: application/json" \
        -H "X-Token: $(cat "<仓库>/plugins/whale-pet/pet/assets/bridge_token")" \
        -d '{"input_tokens":1200,"output_tokens":350,"cache_read_tokens":8800,"duration_ms":5200}'
   ```

## 通用 MCP 配置（JSON 版，适用于大多数 Agent）

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
