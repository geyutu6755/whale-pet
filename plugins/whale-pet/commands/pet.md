---
description: 查看鲸鱼娘状态并汇报 Token 用量统计
---

查看鲸鱼娘桌宠：调用 `pet_state` 工具获取她的当前状态，调用 `pet_metrics` 工具获取
Token 用量统计（累计输入/输出、缓存命中率、最近输出速率），然后用一句轻松的中文向
用户汇报。如果桌宠未运行，可以调用 `pet_control(working)` 唤起她（无钩子的 Agent
会自动拉起），或手动运行插件目录下的 `manage.py start`。

要安装到别的 Agent 或卸载，用同一个入口：`python "<插件目录>/manage.py" status`
（总览）/ `install codex`（装到 Codex）/ `uninstall all --purge`（卸干净）。
