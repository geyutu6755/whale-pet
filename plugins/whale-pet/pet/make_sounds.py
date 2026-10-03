# -*- coding: utf-8 -*-
"""鲸鱼娘音效生成器 —— 全部原创合成，不依赖任何外部素材（可安全开源分发）。

模型：声门源（Rosenberg 脉冲串 + 抖动/气声）→ 四级共振峰谐振腔（元音轨迹）
      → 包络 → 软限幅 → 亮度提升 → 归一化。

合成内容（22050Hz / 16bit / 单声道 WAV，输出到 assets/sounds/）：
  嗷呜 ×3（点击/互动）、哎呀 ×2（受惊/抱怨）、呜呼（庆祝）、呜…（失落）、
  咕噜咕噜（投喂泡泡）

用法:
  python make_sounds.py            # 生成全部音效
  python make_sounds.py --play     # 生成后依次试听
"""
import math
import os
import sys
import wave

import numpy as np

SR = 22050
BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, 'assets', 'sounds')

# ---- 元音共振峰 (F1,F2,F3,F4)，Hz；童声化：整体偏高 10% 左右 ----
VOWELS = {
    'a': (900, 1300, 3000, 3650),
    'o': (480,  850, 2900, 3500),
    'u': (350,  740, 2600, 3400),
    'i': (340, 2800, 3400, 4250),
    'e': (640, 2050, 2800, 3600),
    'y': (320, 2300, 3200, 4050),     # /j/ 半元音（呀）
    'w': (340,  800, 2500, 3400),     # /w/ 半元音（呜）
}
FBW = (85.0, 105.0, 155.0, 230.0)     # 各共振峰带宽
FGAIN = (1.0, 0.75, 0.50, 0.28)       # 各共振峰增益（保持 F2/F3 亮度→咬字清楚）


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def _track(points, n):
    """分段余弦缓动插值（比线性更接近人声的自然过渡）。"""
    t = np.arange(n) / SR
    pts_t = np.asarray([p[0] for p in points], dtype=float)
    pts_v = np.asarray([p[1] for p in points], dtype=float)
    if len(pts_t) == 1:
        return np.full(n, pts_v[0])
    idx = np.clip(np.searchsorted(pts_t, t, side='right') - 1, 0, len(pts_t) - 2)
    t0, t1 = pts_t[idx], pts_t[idx + 1]
    u = np.clip((t - t0) / np.maximum(t1 - t0, 1e-9), 0.0, 1.0)
    u = 0.5 - 0.5 * np.cos(np.pi * u)          # smoothstep
    return pts_v[idx] + (pts_v[idx + 1] - pts_v[idx]) * u


def _lopass(x, fc, stages=1):
    a = math.exp(-2 * math.pi * fc / SR)
    y = np.asarray(x, dtype=float)
    for _ in range(stages):
        out = np.empty_like(y)
        prev = 0.0
        for i in range(len(y)):
            prev = (1 - a) * y[i] + a * prev
            out[i] = prev
        y = out
    return y


def _hipass(x, fc):
    return x - _lopass(x, fc, 1)


def _rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, dtype=float) ** 2)))


def _glottal(f0):
    """声门脉冲串（Rosenberg 近似）+ 唇辐射高通 + 抗混叠低通。

    脉冲宽度用**绝对时间**（ms）而非周期比例：高音区（500Hz+）也能保有
    2-4kHz 泛音——这是咬字清晰、音色明亮（可爱）的关键。
    """
    phase = np.cumsum(f0) / SR
    frac = phase - np.floor(phase)
    T_ms = 1000.0 / np.maximum(f0, 1e-6)
    t = frac * T_ms                              # 周期内绝对时间(ms)
    rise = np.minimum(0.13, 0.05 * T_ms)         # 高音区压缩开相，避免糊成一团
    fall = np.minimum(0.55, 0.22 * T_ms)
    p = np.exp(-t / fall) - np.exp(-t / rise)
    p /= np.max(np.abs(p))
    p = np.diff(p, prepend=p[0])                 # 唇辐射（+6dB/oct）
    return _lopass(p, 9500, 2)


def _resonators(x, F):
    """四级 2 极点谐振腔级联；F: (4, n) 随时间变化的共振峰轨迹。

    只在末尾做一次整体归一（不逐级归一）：保留共振峰之间的自然强弱关系。
    """
    y = np.asarray(x, dtype=float)
    n = len(y)
    idx = np.arange(n)
    for k in range(F.shape[0]):
        f, bw = F[k], FBW[k]
        step = 24                          # 每 24 采样更新一次系数（线性插值）
        cs = np.arange(0, n, step)
        r = np.exp(-math.pi * bw / SR)
        th = 2 * math.pi * f[cs] / SR
        a1 = np.interp(idx, cs, 2 * r * np.cos(th))
        a2 = np.full(n, -(r * r))
        out = np.empty(n)
        y1 = y2 = 0.0
        for i in range(n):
            v = y[i] + a1[i] * y1 + a2[i] * y2
            out[i] = v
            y2, y1 = y1, v
        y = out * FGAIN[k]
    p99 = np.percentile(np.abs(y), 99.9) or 1.0
    return y / p99


def _vowel_track(track, n):
    """把 [(t, 元音)] 控制点变成 (4, n) 共振峰轨迹。"""
    times = [p[0] for p in track]
    keys = [p[1] for p in track]
    F = np.empty((4, n))
    for k in range(4):
        F[k] = _track(list(zip(times, [VOWELS[key][k] for key in keys])), n)
    return F


def _post(y, pres=0.12, drive=1.25, peak=0.72):
    """软限幅 + 亮度提升 + 淡入淡出 + 峰值归一。"""
    y = np.tanh(y * drive) / drive
    y = y + pres * _hipass(y, 3000)
    fade = int(0.006 * SR)
    if len(y) > 2 * fade:
        y[:fade] *= np.linspace(0, 1, fade)
        y[-fade:] *= np.linspace(1, 0, fade)
    y -= y.mean()
    y /= (np.max(np.abs(y)) or 1.0)
    return y * peak


# --------------------------------------------------------------------------
# 人声合成
# --------------------------------------------------------------------------
def voice(dur, f0_pts, vowel_pts, gain_pts, vib=(5.6, 0.035, 0.0),
          breath_db=((0.0, -30.0),), jitter=0.004, seed=0):
    """合成一段拟声台词。

    breath_db: 气声电平（dB，相对人声 RMS），负数越小越轻；
               尾巴拉到 -12 左右 = 叹息/撒娇的气声收尾。
    """
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)

    f0 = _track(f0_pts, n)
    hz, depth, start = vib
    f0 = f0 * (1 + depth * np.sin(2 * np.pi * hz * np.maximum(t - start, 0.0))
               * (t >= start))
    if jitter:                                  # 周期抖动：自然、不做作
        jn = np.convolve(rng.normal(0, 1, n), np.hanning(24) / 12, 'same')
        f0 = f0 * (1 + jitter * jn)

    F = _vowel_track(vowel_pts, n)
    y = _resonators(_glottal(f0), F)
    y /= (_rms(y) or 1.0)                       # 人声归一到单位 RMS

    amp = 10 ** (_track(list(breath_db), n) / 20.0)
    noise = _lopass(rng.normal(0, 1, n), 4500, 1)
    nf = _resonators(noise, F)                  # 气声同样经过声道（共振峰塑形）
    nf /= (_rms(nf) or 1.0)
    y = y + nf * amp

    return y * _track(gain_pts, n)


def snd_aowu1():
    """嗷呜①：明亮好奇的招牌叫（升—降滑音，鲸歌式咬字 a→o→u）。"""
    return voice(
        dur=0.72,
        f0_pts=[(0, 340), (0.08, 380), (0.26, 640), (0.42, 520),
                (0.60, 310), (0.72, 262)],
        vowel_pts=[(0, 'a'), (0.20, 'a'), (0.34, 'o'), (0.48, 'u'), (0.72, 'u')],
        gain_pts=[(0, 0.0), (0.035, 1.0), (0.55, 0.92), (0.72, 0.12)],
        vib=(5.8, 0.04, 0.22),
        breath_db=[(0, -20), (0.06, -30), (0.55, -27), (0.72, -16)],
        seed=11)


def snd_aowu2():
    """嗷呜②：软糯撒娇（低一点、慢一点、气声更多）。"""
    return voice(
        dur=0.90,
        f0_pts=[(0, 300), (0.14, 352), (0.40, 470), (0.62, 380), (0.90, 286)],
        vowel_pts=[(0, 'w'), (0.10, 'a'), (0.34, 'o'), (0.58, 'u'), (0.90, 'u')],
        gain_pts=[(0, 0.0), (0.06, 0.95), (0.5, 0.85), (0.9, 0.06)],
        vib=(5.0, 0.045, 0.3),
        breath_db=[(0, -18), (0.12, -26), (0.6, -22), (0.9, -10)],
        jitter=0.006, seed=22)


def snd_aowu3():
    """嗷呜③：短促惊喜欢叫（快速上扬、干脆收尾）。"""
    return voice(
        dur=0.42,
        f0_pts=[(0, 400), (0.10, 690), (0.22, 610), (0.42, 430)],
        vowel_pts=[(0, 'a'), (0.14, 'o'), (0.28, 'u'), (0.42, 'u')],
        gain_pts=[(0, 0.0), (0.025, 1.0), (0.30, 0.9), (0.42, 0.1)],
        vib=(6.2, 0.03, 0.12),
        breath_db=[(0, -18), (0.05, -30), (0.42, -20)],
        seed=33)


def snd_aiya1():
    """哎呀①：吓一跳（ai + ya 两声，前高后低，中间声门顿挫）。"""
    y1 = voice(
        dur=0.30,
        f0_pts=[(0, 660), (0.10, 700), (0.30, 540)],
        vowel_pts=[(0, 'a'), (0.14, 'i'), (0.30, 'i')],
        gain_pts=[(0, 0.0), (0.02, 1.0), (0.24, 0.85), (0.30, 0.15)],
        vib=(6.5, 0.02, 0.1),
        breath_db=[(0, -22), (0.06, -32)],
        seed=44)
    gap = np.zeros(int(0.035 * SR))
    y2 = voice(
        dur=0.34,
        f0_pts=[(0, 520), (0.10, 470), (0.22, 380), (0.34, 330)],
        vowel_pts=[(0, 'y'), (0.06, 'a'), (0.34, 'a')],
        gain_pts=[(0, 0.0), (0.02, 1.0), (0.26, 0.8), (0.34, 0.12)],
        vib=(6.0, 0.03, 0.12),
        breath_db=[(0, -22), (0.12, -26), (0.34, -16)],
        jitter=0.006, seed=45)
    return np.concatenate([y1, gap, y2])


def snd_aiya2():
    """哎呀②：被戳烦的抱怨（拖长、下滑、叹息收尾）。"""
    y1 = voice(
        dur=0.42,
        f0_pts=[(0, 520), (0.16, 460), (0.42, 400)],
        vowel_pts=[(0, 'a'), (0.20, 'i'), (0.42, 'i')],
        gain_pts=[(0, 0.0), (0.04, 0.95), (0.34, 0.85), (0.42, 0.3)],
        vib=(5.2, 0.035, 0.15),
        breath_db=[(0, -20), (0.10, -28)],
        jitter=0.005, seed=55)
    gap = np.zeros(int(0.03 * SR))
    y2 = voice(
        dur=0.46,
        f0_pts=[(0, 430), (0.16, 390), (0.46, 296)],
        vowel_pts=[(0, 'y'), (0.08, 'a'), (0.46, 'a')],
        gain_pts=[(0, 0.0), (0.03, 0.9), (0.30, 0.7), (0.46, 0.05)],
        vib=(5.0, 0.04, 0.2),
        breath_db=[(0, -22), (0.15, -20), (0.46, -8)],
        jitter=0.008, seed=56)
    return np.concatenate([y1, gap, y2])


def snd_yay():
    """呜呼：庆祝欢呼（呜→呼上扬 whoop）。"""
    return voice(
        dur=0.58,
        f0_pts=[(0, 380), (0.16, 520), (0.34, 760), (0.48, 640), (0.58, 560)],
        vowel_pts=[(0, 'w'), (0.12, 'u'), (0.30, 'o'), (0.42, 'a'), (0.58, 'a')],
        gain_pts=[(0, 0.0), (0.05, 1.0), (0.42, 0.95), (0.58, 0.12)],
        vib=(6.4, 0.045, 0.18),
        breath_db=[(0, -20), (0.08, -30), (0.58, -18)],
        seed=66)


def snd_sad():
    """呜…：失落下垂的呜咽（长音下滑 + 大量气声）。"""
    return voice(
        dur=0.82,
        f0_pts=[(0, 380), (0.10, 400), (0.44, 330), (0.82, 250)],
        vowel_pts=[(0, 'u'), (0.44, 'u'), (0.82, 'o')],
        gain_pts=[(0, 0.0), (0.07, 0.9), (0.5, 0.75), (0.82, 0.04)],
        vib=(4.4, 0.05, 0.2),
        breath_db=[(0, -20), (0.2, -22), (0.82, -8)],
        jitter=0.007, seed=77)


# --------------------------------------------------------------------------
# 拟音（水泡 / 咕噜）
# --------------------------------------------------------------------------
def _droplet(t0, f_start, sweep, dur, decay, amp, rng, n):
    """水滴/泡泡：音高快速上滑的正弦 + 指数衰减 + 极短噪声瞬态。"""
    y = np.zeros(n)
    i0 = int(t0 * SR)
    m = min(int(dur * SR), n - i0)
    if m <= 0:
        return y
    t = np.arange(m) / SR
    f = f_start * (1 + (sweep - 1) * (1 - np.exp(-t / 0.02)))
    ph = np.cumsum(f) / SR
    body = np.sin(2 * np.pi * ph) * np.exp(-decay * t)
    click = rng.normal(0, 1, m) * np.exp(-t / 0.004) * 0.25
    y[i0:i0 + m] = (body + click) * amp
    return y


def snd_bubble():
    """咕噜咕噜：三颗泡泡 + 一记低沉的吞咽。"""
    rng = np.random.default_rng(88)
    n = int(0.42 * SR)
    y = np.zeros(n)
    y += _droplet(0.02, 420, 2.6, 0.14, 30, 0.55, rng, n)
    y += _droplet(0.14, 300, 3.2, 0.16, 26, 0.5, rng, n)
    y += _droplet(0.27, 520, 2.2, 0.13, 34, 0.42, rng, n)
    t = np.arange(int(0.30 * SR)) / SR
    gulp = np.sin(2 * np.pi * np.cumsum(190 * np.exp(-t / 0.05) + 70) / SR)
    y[:len(gulp)] += gulp * np.exp(-t / 0.055) * 0.30
    return y


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------
SOUNDS = {
    'aowu1': snd_aowu1,
    'aowu2': snd_aowu2,
    'aowu3': snd_aowu3,
    'aiya1': snd_aiya1,
    'aiya2': snd_aiya2,
    'yay': snd_yay,
    'sad': snd_sad,
    'bubble': snd_bubble,
}


def write_wav(path, y):
    x = np.clip(y, -1.0, 1.0)
    data = (x * 32767).astype('<i2')
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def main(argv):
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, fn in SOUNDS.items():
        y = _post(np.asarray(fn(), dtype=float))
        path = os.path.join(OUT_DIR, f'{name}.wav')
        write_wav(path, y)
        print(f'{name:8s} {len(y) / SR:4.2f}s  {os.path.getsize(path) / 1024:6.1f} KB')
    if '--play' in argv:
        import winsound
        for name in SOUNDS:
            winsound.PlaySound(os.path.join(OUT_DIR, f'{name}.wav'),
                               winsound.SND_FILENAME)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
