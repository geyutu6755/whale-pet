#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SessionStart 钩子：确保鲸鱼娘桌宠随 Agent 启动。

- 桌宠未运行 → 以分离进程启动（不阻塞 ZCode）
- 桌宠已运行但隐藏 → 恢复显示
- 任何异常都静默退出（钩子失败不影响宿主）
"""
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PET_DIR = os.path.abspath(os.path.join(HERE, '..', 'pet'))
PET_SCRIPT = os.path.join(PET_DIR, 'whale_pet.py')


def _bridge_ok():
    """桌宠桥是否已就绪（在运行）。"""
    try:
        with open(os.path.join(PET_DIR, 'assets', 'bridge_token')) as f:
            token = f.read().strip()
        port = 37821
        cfg = os.path.join(PET_DIR, 'pet_config.json')
        if os.path.exists(cfg):
            port = int(json.load(open(cfg, encoding='utf-8')).get('bridge_port', 37821))
        r = urllib.request.Request(f'http://127.0.0.1:{port}/state',
                                   headers={'X-Token': token})
        with urllib.request.urlopen(r, timeout=0.8) as resp:
            state = json.loads(resp.read().decode('utf-8'))
            return True, state.get('hidden', False)
    except Exception:
        return False, False


def _show():
    try:
        with open(os.path.join(PET_DIR, 'assets', 'bridge_token')) as f:
            token = f.read().strip()
        port = 37821
        cfg = os.path.join(PET_DIR, 'pet_config.json')
        if os.path.exists(cfg):
            port = int(json.load(open(cfg, encoding='utf-8')).get('bridge_port', 37821))
        data = json.dumps({'type': 'show'}).encode()
        req = urllib.request.Request(f'http://127.0.0.1:{port}/event', data=data,
                                     headers={'Content-Type': 'application/json',
                                              'X-Token': token}, method='POST')
        urllib.request.urlopen(req, timeout=1).read()
    except Exception:
        pass


def main():
    if not os.path.exists(PET_SCRIPT):
        return
    running, hidden = _bridge_ok()
    if running:
        if hidden:
            _show()
        return
    flags = 0
    creationflags = 0
    if os.name == 'nt':
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    python = sys.executable.replace('pythonw.exe', 'python.exe')
    if os.name == 'nt' and os.path.exists(python.replace('python.exe', 'pythonw.exe')):
        python = python.replace('python.exe', 'pythonw.exe')
    subprocess.Popen(
        [python, PET_SCRIPT],
        cwd=PET_DIR,
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        close_fds=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
