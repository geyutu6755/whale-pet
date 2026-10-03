#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鲸鱼娘桌宠 MCP 服务器（stdio，无第三方依赖）。

工具:
  pet_control  控制桌宠：说话/庆祝/惊吓/思考陪伴/工作/等待/投喂/玩耍/摸摸/
               小动作/隐藏/显示/HUD 开关
  pet_metrics  查询 Token 用量统计（累计/缓存命中率/输出速率）
  pet_state    查询桌宠当前状态

桌宠未运行时工具调用返回可读文本（不报错），Agent 可据此提示用户。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
PET_DIR = os.path.join(PLUGIN_ROOT, 'pet')
PET_SCRIPT = os.path.join(PET_DIR, 'whale_pet.py')
TOKEN_PATH = os.path.join(PET_DIR, 'assets', 'bridge_token')
CONFIG_PATH = os.path.join(PET_DIR, 'pet_config.json')

SERVER_INFO = {'name': 'whale-pet', 'version': '0.2.0'}

TOOLS = [
    {
        'name': 'pet_control',
        'description': ('控制鲸鱼娘桌宠。动作: '
                        'say=说话(配text), celebrate=任务完成庆祝, error=出错惊吓, '
                        'disappointed=失落, think=思考陪伴(Agent思考中用), '
                        'working=工作姿态, wait=等待用户批准(Agent等待批准用), '
                        'welcome=欢迎, feed=投喂, play=玩耍, pat=摸摸, '
                        'trick=随机小动作(转圈圈/摇头晃脑等), idle=回待机, '
                        'hide=隐藏, show=显示, hud_on/hud_off=用量面板开关, '
                        'sound_on/sound_off=音效开关'),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'action': {
                    'type': 'string',
                    'enum': ['say', 'celebrate', 'error', 'disappointed', 'think',
                             'working', 'wait', 'welcome', 'feed', 'play', 'pat',
                             'trick', 'idle', 'hide', 'show', 'hud_on', 'hud_off',
                             'sound_on', 'sound_off'],
                    'description': '要执行的动作',
                },
                'text': {'type': 'string', 'description': 'say 动作的台词（可选）'},
                'ms': {'type': 'integer', 'description': 'think/working/wait 的持续毫秒（可选）'},
            },
            'required': ['action'],
        },
    },
    {
        'name': 'pet_metrics',
        'description': '查询鲸鱼娘 HUD 的 Token 用量统计：累计输入/输出、缓存命中率、最近输出速率',
        'inputSchema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'pet_state',
        'description': '查询鲸鱼娘桌宠当前状态（姿态/位置/可见性）',
        'inputSchema': {'type': 'object', 'properties': {}},
    },
]


def _bridge_cfg():
    port = 37821
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            port = int(json.load(f).get('bridge_port', 37821))
    except Exception:
        pass
    token = ''
    try:
        with open(TOKEN_PATH) as f:
            token = f.read().strip()
    except Exception:
        pass
    return port, token


def _bridge_request(method, path, obj=None):
    port, token = _bridge_cfg()
    url = 'http://127.0.0.1:%d%s' % (port, path)
    headers = {'X-Token': token}
    data = None
    if obj is not None:
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=2) as resp:
        return json.loads(resp.read().decode('utf-8'))


def ensure_pet(wait=8.0):
    """桌宠没在跑就拉起来 —— 没有插件钩子的 Agent（Codex/Cursor…）即装即用。

    由 pet_config.json 的 "mcp_autostart" 控制（默认开）。
    """
    try:
        _bridge_request('GET', '/state')
        return True
    except Exception:
        pass
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            if not json.load(f).get('mcp_autostart', True):
                return False
    except Exception:
        pass
    if not os.path.exists(PET_SCRIPT):
        return False
    python = sys.executable
    if python.lower().endswith('pythonw.exe') and os.path.exists(
            python[:-len('pythonw.exe')] + 'python.exe'):
        python = python[:-len('pythonw.exe')] + 'python.exe'
    flags = 0x00000008 | 0x00000200 if os.name == 'nt' else 0
    try:
        subprocess.Popen([python, PET_SCRIPT], cwd=PET_DIR, creationflags=flags,
                         close_fds=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except Exception:
        return False
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(0.25)
        try:
            _bridge_request('GET', '/state')
            return True
        except Exception:
            pass
    return False


def call_tool(name, args):
    args = args or {}
    try:
        if name == 'pet_control' and args.get('action') != 'quit':
            ensure_pet()
        if name == 'pet_control':
            action = args.get('action', 'idle')
            payload = {'type': action}
            if args.get('text'):
                payload['text'] = str(args['text'])[:120]
            if args.get('ms'):
                payload['ms'] = int(args['ms'])
            _bridge_request('POST', '/event', payload)
            return {'content': [{'type': 'text', 'text': f'鲸鱼娘执行了: {action}'}]}
        if name == 'pet_metrics':
            m = _bridge_request('GET', '/metrics')
            hit = m.get('cache_hit_rate', 0)
            rate = m.get('output_rate', 0)
            text = (f'累计输入 {m.get("input_tokens", 0)} tok，'
                    f'累计输出 {m.get("output_tokens", 0)} tok，'
                    f'缓存命中率 {hit * 100:.0f}%，'
                    f'最近输出速率 {rate:.0f} tok/s，'
                    f'响应次数 {m.get("responses", 0)}')
            return {'content': [{'type': 'text', 'text': text}]}
        if name == 'pet_state':
            st = _bridge_request('GET', '/state')
            return {'content': [{'type': 'text',
                                 'text': json.dumps(st, ensure_ascii=False)}]}
        return {'content': [{'type': 'text', 'text': f'未知工具: {name}'}]}
    except Exception as e:
            return {'content': [{'type': 'text',
                                 'text': f'鲸鱼娘桌宠未运行或桥接失败（{e}）。'
                                         f'调用 pet_control（如 working）可唤起她，'
                                         f'或在插件目录运行 manage.py start。'}]}


def handle(msg):
    method = msg.get('method')
    mid = msg.get('id')
    if mid is None:
        return None                      # 通知，无需应答
    if method == 'initialize':
        result = {'protocolVersion': msg.get('params', {}).get('protocolVersion', '2024-11-05'),
                  'capabilities': {'tools': {}},
                  'serverInfo': SERVER_INFO}
    elif method == 'tools/list':
        result = {'tools': TOOLS}
    elif method == 'tools/call':
        params = msg.get('params') or {}
        # MCP 标准字段是 arguments；兼容部分客户端的 args 写法
        args = params.get('arguments')
        if args is None:
            args = params.get('args')
        result = call_tool(params.get('name', ''), args)
    elif method == 'ping':
        result = {}
    else:
        return {'jsonrpc': '2.0', 'id': mid,
                'error': {'code': -32601, 'message': 'Method not found'}}
    return {'jsonrpc': '2.0', 'id': mid, 'result': result}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        try:
            resp = handle(msg)
        except Exception as e:      # 任何工具异常都不中断服务器
            mid = msg.get('id')
            resp = None
            if mid is not None:
                resp = {'jsonrpc': '2.0', 'id': mid,
                        'error': {'code': -32603, 'message': str(e)}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + '\n')
            sys.stdout.flush()


if __name__ == '__main__':
    main()
