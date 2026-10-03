---
name: whale-pet
description: 鲸鱼娘桌宠控制与 Token 用量查询。当用户提到鲸鱼娘/桌宠、要求庆祝/安慰/汇报进度，或需要查询 Token 用量、缓存命中率、输出速率时使用。
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

## 礼仪

- 台词交给桌宠自己说（不传 text 也有随机台词）；只在用户指定内容时传 `text`
- 状态类动作（think/working/wait）建议带 `ms` 持续时长，结束后她自动回待机
- 不要连续频繁调用庆祝/惊吓——她会累的
- 用户没提桌宠时，不要主动打扰
