#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鲸鱼娘桌宠 CLI —— 供 Agent（DeepSeek Harness / Codex / ZCode）与脚本调用。

用法:
  python whale_cli.py say "任务完成，已部署！"
  python whale_cli.py celebrate            # 任务完成庆祝
  python whale_cli.py error                # 出错惊吓
  python whale_cli.py disappointed         # 失落
  python whale_cli.py think [毫秒]         # 沉思陪伴（Agent 思考中）
  python whale_cli.py wait   [毫秒]        # 等待审批
  python whale_cli.py working [毫秒]       # 工作姿态
  python whale_cli.py welcome              # 欢迎挥手
  python whale_cli.py feed | play | pat    # 互动
  python whale_cli.py spin | headshake | sway | hop | nod | trick  # 小动作（trick=随机）
  python whale_cli.py idle                 # 回到待机
  python whale_cli.py state                # 查询当前状态 (JSON)
  python whale_cli.py hide | show          # 隐藏/显示
  python whale_cli.py sound_on | sound_off # 开启/静音音效
  python whale_cli.py quit                 # 退出桌宠

集成示例:
  ZCode/Codex 任务结束后:  python whale_cli.py celebrate
  开始思考时:              python whale_cli.py think
  需要用户批准时:          python whale_cli.py wait
"""
import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, 'pet_config.json')
TOKEN_PATH = os.path.join(BASE, 'assets', 'bridge_token')


def _load():
    port = 37821
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            port = int(json.load(f).get('bridge_port', 37821))
    except Exception:
        pass
    try:
        with open(TOKEN_PATH) as f:
            token = f.read().strip()
    except Exception:
        token = ''
    return port, token


def _post(event):
    port, token = _load()
    req = urllib.request.Request(
        f'http://127.0.0.1:{port}/event',
        data=json.dumps(event, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'X-Token': token},
        method='POST')
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read().decode('utf-8'))


def _get_state():
    port, token = _load()
    req = urllib.request.Request(
        f'http://127.0.0.1:{port}/state', headers={'X-Token': token})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read().decode('utf-8'))


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0].lower()
    arg = argv[1] if len(argv) > 1 else None
    try:
        if cmd == 'state':
            print(json.dumps(_get_state(), ensure_ascii=False))
            return 0
        event = {'type': cmd}
        if cmd == 'say':
            if not arg:
                print('用法: whale_cli.py say "文本"', file=sys.stderr)
                return 2
            event['text'] = arg
        elif cmd in ('think', 'wait', 'working'):
            if arg:
                try:
                    event['ms'] = max(500, int(arg))
                except ValueError:
                    pass
        elif cmd not in ('welcome', 'celebrate', 'error', 'disappointed',
                         'feed', 'play', 'pat', 'idle', 'hide', 'show', 'quit',
                         'spin', 'headshake', 'sway', 'hop', 'nod', 'trick',
                         'sound_on', 'sound_off'):
            print(f'未知命令: {cmd}', file=sys.stderr)
            return 2
        print(json.dumps(_post(event), ensure_ascii=False))
        return 0
    except Exception as e:
        print(f'桌宠未运行或桥接失败: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
