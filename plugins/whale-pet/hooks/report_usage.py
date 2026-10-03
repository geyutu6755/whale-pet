#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop / PostToolUse 钩子：把本次响应的 Token 用量上报给鲸鱼娘桌宠 HUD。

输入（stdin）: 宿主钩子 JSON（兼容 Claude Code 风格）。
提取顺序:
  1. 载荷内直接的 usage 字段
  2. transcript_path JSONL 尾部的最后一条 assistant 消息 usage
输出速率: 用转写记录相邻时间戳估算本次回复的生成耗时。
任何异常都静默退出（exit 0），绝不影响宿主。
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PET_DIR = os.path.abspath(os.path.join(HERE, '..', 'pet'))
TAIL_BYTES = 200_000


def _epoch(s):
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(str(s).strip().replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _delta_ms(a, b):
    """ISO 时间戳差（毫秒），失败返回 None。"""
    try:
        return int(abs(_epoch(b) - _epoch(a)) * 1000)
    except Exception:
        return None


def _usage_from_transcript(path):
    """读转写尾部，取最后一条带 usage 的 assistant 记录及其耗时估算。"""
    usage = None
    dur_ms = None
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode('utf-8', 'ignore')
        lines = tail.splitlines()
        if size > TAIL_BYTES and lines:
            lines = lines[1:]          # 丢弃可能截断的首行
        later_ts = None                # 逆序遍历时，上一个（更晚的）时间戳
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not isinstance(e, dict):
                continue
            ts = e.get('timestamp')
            msg = e.get('message')
            u = msg.get('usage') if isinstance(msg, dict) else None
            if usage is None and isinstance(u, dict) and \
                    (u.get('output_tokens') or u.get('input_tokens')):
                usage = u
                if later_ts:
                    dur_ms = _delta_ms(ts, later_ts)
            if ts:
                later_ts = ts
            if usage:
                break
    except Exception:
        return None, None
    return usage, dur_ms


def _post_metrics(payload):
    try:
        with open(os.path.join(PET_DIR, 'assets', 'bridge_token')) as f:
            token = f.read().strip()
        port = 37821
        cfg = os.path.join(PET_DIR, 'pet_config.json')
        if os.path.exists(cfg):
            port = int(json.load(open(cfg, encoding='utf-8')).get('bridge_port', 37821))
        req = urllib.request.Request(
            'http://127.0.0.1:%d/metrics' % port,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'X-Token': token},
            method='POST')
        urllib.request.urlopen(req, timeout=1.5).read()
    except Exception:
        pass


def _pet_uses_rollout():
    """桌宠当前按模型 I/O 记录采集（ZCode）时，钩子上报是多余的 → 直接退出。"""
    try:
        with open(os.path.join(PET_DIR, 'pet_config.json'), encoding='utf-8') as f:
            src = json.load(f).get('usage_source', 'auto')
    except Exception:
        src = 'auto'
    if src == 'auto':
        return os.path.isdir(os.path.join(os.path.expanduser('~'),
                                          '.zcode', 'cli', 'rollout'))
    return src == 'rollout'


def main():
    if _pet_uses_rollout():
        return
    try:
        raw = sys.stdin.read()
    except Exception:
        return
    try:
        data = json.loads(raw)
    except Exception:
        return
    if not isinstance(data, dict):
        return

    usage = data.get('usage')
    dur_ms = data.get('duration_ms')
    if not isinstance(usage, dict) or not usage:
        tp = data.get('transcript_path')
        if tp and os.path.exists(tp):
            usage, dur_ms = _usage_from_transcript(tp)
    if not isinstance(usage, dict) or not usage:
        return

    def _i(v):
        try:
            return max(0, int(v))
        except Exception:
            return 0

    payload = {
        'type': 'usage',
        'source': 'hooks',         # 与 pet_config.json 的 usage_source 取值保持一致
        'input_tokens': _i(usage.get('input_tokens')),
        'output_tokens': _i(usage.get('output_tokens')),
        'cache_read_tokens': _i(usage.get('cache_read_input_tokens')),
        'cache_creation_tokens': _i(usage.get('cache_creation_input_tokens')),
        'duration_ms': _i(dur_ms) if dur_ms else _i(data.get('duration_ms')),
    }
    if payload['input_tokens'] + payload['output_tokens'] <= 0:
        return
    _post_metrics(payload)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
