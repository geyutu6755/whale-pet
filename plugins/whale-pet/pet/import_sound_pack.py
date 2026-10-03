# -*- coding: utf-8 -*-
"""从「鲸鱼娘音效包」导入音效到 pet/assets/sounds/（可重复执行、结果确定）。

处理：读清单 → 裁掉首尾静音（原素材每条尾部有 1s+ 空白）→ 44.1kHz 降采样到
22.05kHz（63 抽头窗函数 sinc 抗混叠 + 2 倍抽取）→ 峰值归一 0.72 → 5ms 淡入淡出
→ 写 22.05kHz/16bit/单声道 WAV。

输出结构（voice/ 为社区素材，许可另见 LICENSE-community-*.txt，删掉即可退化）：
  assets/sounds/short/<id>.wav    28 条新制作短音效（Edge TTS）
  assets/sounds/voice/<id>.wav    49 条社区现成语音（dsh-whale-pet）
  assets/sounds/lines.json        id → 台词/场景/来源（桌宠用它同步气泡文案）
  assets/sounds/CREDITS.md        来源与许可说明

用法:
  python import_sound_pack.py "<音效包目录或 zip 路径>"
"""
import io
import json
import os
import sys
import wave
import zipfile

import numpy as np

SR_OUT = 22050
PEAK = 0.72
HERE = os.path.dirname(os.path.abspath(__file__))
SOUNDS = os.path.join(HERE, 'assets', 'sounds')

SRC_NAMES = {'01_新制作短音效': 'short', '02_社区现成语音': 'voice'}


def read_wav(path):
    with wave.open(path, 'rb') as w:
        assert w.getsampwidth() == 2, f'{path}: 只支持 16bit PCM'
        nch, sr = w.getnchannels(), w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float32)
    if nch > 1:
        x = x.reshape(-1, nch).mean(axis=1)
    return x / 32768.0, sr


def decimate2(x, fc=0.225, taps=63):
    """44.1k → 22.05k：窗函数 sinc 低通（截至 ~9.9kHz）后 2 倍抽取。"""
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2.0 * fc * n) * np.hamming(taps)
    h /= h.sum()
    return np.convolve(x, h, 'same')[::2]


def trim(x, head=0.05, tail=0.14):
    """按 -42dB 阈值裁掉首尾静音，保留自然的头尾留白。"""
    if len(x) == 0:
        return x
    thr = max(0.002, float(np.max(np.abs(x))) * 0.008)
    idx = np.where(np.abs(x) > thr)[0]
    if len(idx) == 0:
        return x
    a = max(0, int(idx[0] - head * SR_OUT))
    b = min(len(x), int(idx[-1] + tail * SR_OUT))
    return x[a:b]


def finish(x):
    """去直流 + 5ms 淡入淡出 + 峰值归一。"""
    if len(x) == 0:
        return x
    x = x - x.mean()
    k = int(0.005 * SR_OUT)
    if len(x) > 2 * k:
        x[:k] *= np.linspace(0, 1, k)
        x[-k:] *= np.linspace(1, 0, k)
    peak = float(np.max(np.abs(x))) or 1.0
    return x / peak * PEAK


def write_wav(path, x):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR_OUT)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes())


def load_pack(src):
    """返回 (根目录, 打开子路径的函数, 清单)。src 可以是目录或 zip。"""
    if os.path.isdir(src):
        return src, (lambda p: os.path.join(src, p)), None
    z = zipfile.ZipFile(src)
    root = z.namelist()[0].split('/')[0]
    inner = lambda p: f'{root}/{p}'
    return None, None, (z, inner)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    src = argv[0]
    tmp = None
    if os.path.isdir(src):
        base = src
        if not os.path.exists(os.path.join(base, '音效清单.json')):
            base = os.path.join(src, '鲸鱼娘音效包')
        opener = lambda p: os.path.join(base, p)
        closer = lambda: None
    else:
        z = zipfile.ZipFile(src)
        root = z.namelist()[0].split('/')[0]
        opener = lambda p: z.open(f'{root}/{p}')
        closer = z.close

    manifest = json.loads(opener('音效清单.json').read().decode('utf-8'))
    total = 0
    lines = {}
    for item in manifest:
        sub = SRC_NAMES.get(item['source'])
        if not sub:
            continue
        x, sr = read_wav(opener(item['wav']))
        if sr != 44100:                      # 防止错误比例重采样：非 44.1k 原样保留
            print(f'  注意 {item["id"]}: 采样率 {sr}Hz，跳过降采样')
        else:
            x = decimate2(x)
        x = finish(trim(x))
        out = os.path.join(SOUNDS, sub, item['id'] + '.wav')
        write_wav(out, x)
        lines[item['id']] = {'text': item['text'], 'scene': item['scene'],
                             'source': item['source'], 'dir': sub}
        total += 1
        print(f'  {sub:5s} {item["id"]:12s} {item["text"]:14s} '
              f'{len(x) / SR_OUT:.2f}s  {os.path.getsize(out) // 1024}KB')
    closer()

    with io.open(os.path.join(SOUNDS, 'lines.json'), 'w', encoding='utf-8') as f:
        json.dump(lines, f, ensure_ascii=False, indent=1)
    print(f'\n导入 {total} 条 → {SOUNDS}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
