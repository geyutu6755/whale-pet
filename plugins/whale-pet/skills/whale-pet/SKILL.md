---
name: whale-pet
description: 鲸鱼娘桌宠控制、Token 用量查询与安装卸载。当用户提到鲸鱼娘/桌宠、要求庆祝/安慰/汇报进度、查询 Token 用量/缓存命中率/输出速率，或要把桌宠装到/卸载自某个 Agent（ZCode/Claude Code/Codex/Cursor 等）时使用。
---

# 鲸鱼娘桌宠

用户桌面上有一只 DeepSeek 鲸鱼娘桌宠（独立进程 + 本地事件桥）。通过 `pet_control`、
`pet_metrics`、`pet_state` 三个 MCP 工具与她互动。

## 何时使用

| 场景 | 动作 |
|------|------|
| 开始处理用户任务前 | `pet_control(action="working")` —— 摆出工作姿态 |
| 长时间思考/执行长任务 | `pet_control(action="think", ms=毫秒)` —— 沉思陪伴 |
| 请求用户批准/等待输入 | `pet_control(action="wait")` |
| 任务成功完成 | `pet_control(action="celebrate")` —— 撒花庆祝 |
| 任务失败/出错 | `pet_control(action="error")` —— 惊吓（随后自动失落） |
| 用户夸奖/心情好 | `pet_control(action="pat")` —— 摸摸头飘爱心 |
| 用户要求她说句话 | `pet_control(action="say", text="...")` |
| 用户想看统计 | `pet_metrics()` —— 汇报 Token 用量/缓存命中率/输出速率 |
| 用户说再见/要专注 | `pet_control(action="hide")`；回来时 `show` |
| 用户嫌音效吵 / 想开声音 | `pet_control(action="sound_off")` / `sound_on` |

## 管理（安装 / 卸载 / 状态）

桌宠可用一个入口装卸到任何 Agent，脚本在本插件根目录：`manage.py`。

| 用户说 | 执行 |
|--------|------|
| 「装到 Codex / Claude Code / 别的 Agent」 | `python "<插件目录>/manage.py" install codex`（`claude` / `mcp` / `all`） |
| 「卸载桌宠 / 不想要了」 | `python "<插件目录>/manage.py" uninstall all --purge` |
| 「桌宠现在什么状态 / 装哪了」 | `python "<插件目录>/manage.py" status` |
| 「重启桌宠 / 她卡住了」 | `python "<插件目录>/manage.py" restart` |
| 「听听音效」 | `python "<插件目录>/manage.py" sound` |

- **卸载是除净语义**：先优雅停掉桌宠（跨安装副本都能停），再摘掉插件/市场/MCP 注册，
  `--purge` 再清 `pet_config.json` / `bridge_token` / `__pycache__`，不留孤儿条目
- 只动名字带 `whale-pet` 的条目，改配置文件前自动备份 `.whale-bak`
- 装卸后需**重启对应 Agent** 才生效
- 桌宠是全局单实例：不同安装副本（本地仓库 / 插件缓存）不会同时出现两只

## 礼仪

- 台词交给桌宠自己说（不传 text 也有随机台词）；只在用户指定内容时传 `text`
- 状态类动作（think/working/wait）建议带 `ms` 持续时长，结束后她自动回待机
- 不要连续频繁调用庆祝/惊吓——她会累的
- 用户没提桌宠时，不要主动打扰
