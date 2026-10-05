# -*- coding: utf-8 -*-
"""鲸鱼娘"肉嘟嘟"皮肤生成器：把平面贴纸帧处理成偏 3D 的充气质感。

原理（对每一帧）：
  1. 高度场 = alpha 遮罩的充气膨胀（模拟往贴纸里吹气，四肢/身体鼓起来）
             + 少量"内亮度"分量（画稿里的深色凹陷、浅色凸起，保留原有体积感）
  2. 由高度场求法线 → 左上主光做兰伯特漫反射（伪 3D 的核心）
  3. 底部环境光遮蔽（贴地感）、右下冷色边缘反光（轮廓从背景里"鼓"出来）
  4. 头顶一处柔和高光（果冻质感）
  5. 2x 超采样处理再缩回，渐变平滑无色带

输出 assets/sheets-puffy/（sheet 文件名与 manifest.json 与原版完全一致），
桌宠通过 pet_config.json 的 `skin`（puffy/flat）选择加载哪一套，可随时切回。

用法:
  python make_skin_puffy.py            # 生成/刷新 sheets-puffy/
  python make_skin_puffy.py --preview  # 额外输出 原版 vs 立体 对比图到 %TEMP%
"""
import io
import json
import os
import sys

import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE, 'assets', 'sheets')
DST_DIR = os.path.join(BASE, 'assets', 'sheets-puffy')
SS = 2          # 处理时 2x 超采样

# 可调参数（整体"胖嘟嘟"程度）
INFLATE_SIGMA = 8.0     # 充气模糊半径（越大越圆润）
INFLATE_MIX = 0.68      # 充气分量占比（其余给画稿明暗，保留原有体积感）
BUMP = 2.6              # 法线凹凸强度
AMBIENT = 0.75          # 环境光
DIFFUSE = 0.66          # 漫反射强度
AO_BOTTOM = 0.15        # 底部遮蔽
RIM = 0.38              # 边缘反光强度
SPEC_WIDE = 0.15        # 大面积柔光（果冻光泽底层）
SPEC_TIGHT = 0.15       # 小而亮的果冻高光点
LIGHT = (-0.42, -0.58, 0.70)   # 主光方向（左上、朝向观察者）


# --------------------------------------------------------------------------
# numpy 基础工具（无 scipy 依赖）
# --------------------------------------------------------------------------
def _box1d(x, r, axis):
    """一维盒式模糊（累计和实现，r=0 时原样返回）。"""
    r = int(round(r))
    if r <= 0:
        return x
    pad = [(0, 0)] * x.ndim
    pad[axis] = (r + 1, r)
    xp = np.pad(x, pad, mode='edge')
    c = np.cumsum(xp, axis=axis)
    hi = np.take(c, np.arange(2 * r + 1, x.shape[axis] + 2 * r + 1), axis=axis)
    lo = np.take(c, np.arange(0, x.shape[axis]), axis=axis)
    return (hi - lo) / (2 * r + 1)


def blur(x, r, passes=3):
    """三次盒式模糊 ≈ 高斯模糊。x: 2D float。"""
    for _ in range(passes):
        x = _box1d(x, r, 0)
        x = _box1d(x, r, 1)
    return x


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


# --------------------------------------------------------------------------
# 核心：单帧"充气"处理
# --------------------------------------------------------------------------
def inflate_frame(im):
    """输入 RGBA 帧（任意尺寸），输出处理后的 RGBA 帧。"""
    w, h = im.size
    im2 = im.resize((w * SS, h * SS), Image.LANCZOS)
    arr = np.asarray(im2).astype(np.float32) / 255.0
    rgb, a = arr[..., :3], arr[..., 3]

    inside = a > 0.02
    if not inside.any():
        return im

    # ---- 1) 高度场：充气（遮罩膨胀）+ 画稿明暗（保留原体积感）----
    solid = np.clip(a * 3.0, 0.0, 1.0)                    # 硬遮罩
    inflated = np.sqrt(np.clip(blur(solid, INFLATE_SIGMA * SS), 0, 1))
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    lum_s = blur(lum * inside, 3 * SS)
    lum_n = lum_s / max(1e-3, float(np.percentile(lum_s[inside], 92)))
    height = (INFLATE_MIX * inflated +
              (1 - INFLATE_MIX) * np.clip(1.15 - 0.9 * lum_n, 0, 1)) * a
    height = blur(height, 1.2 * SS)                        # 再柔一次，消梯度锯齿

    # ---- 2) 法线 + 兰伯特漫反射 ----
    gy, gx = np.gradient(height)
    n = np.dstack([-gx * BUMP * 40, -gy * BUMP * 40, np.ones_like(height)])
    n /= np.linalg.norm(n, axis=2, keepdims=True) + 1e-6
    L = np.array(LIGHT, dtype=np.float32)
    L /= np.linalg.norm(L)
    diff = np.clip(n @ L, 0.0, 1.0) ** 1.25
    light = (AMBIENT + DIFFUSE * diff)

    # ---- 3) 底部环境光遮蔽（贴地感）----
    ys = np.arange(h * SS, dtype=np.float32)[:, None]
    top = np.where(inside.any(axis=1), np.argmax(inside, axis=1), h * SS)[:, None]
    bot = np.where(inside.any(axis=1),
                   h * SS - np.argmax(inside[::-1], axis=1) - 1, 0)[:, None]
    rel = (ys - top) / np.maximum(1.0, bot - top)          # 0=头顶 1=脚底
    ao = 1.0 - AO_BOTTOM * smoothstep((rel - 0.55) / 0.45) * a

    # ---- 4) 右下冷色边缘反光（轮廓鼓出感）----
    edge = np.clip(a - blur(a, 2.2 * SS), 0, 1) ** 1.6
    back = np.array([0.62, 0.78, 1.0], dtype=np.float32)
    rim = edge[..., None] * RIM * back * np.clip(1.0 - diff, 0.35, 1.0)[..., None]

    # ---- 5) 头顶双层高光：大面积柔光 + 小而亮的果冻点 ----
    cols = np.where(inside.any(axis=0), np.argmax(inside, axis=0), w * SS)[None, :]
    head_y = float(np.mean(top[inside.any(axis=1)])) if inside.any() else 0.0
    head_x = float(np.mean(np.nonzero(inside[int(min(head_y + 6, h * SS - 1))])[0])) \
        if inside.any() else w * SS / 2
    gx2, gy2 = np.meshgrid(np.arange(w * SS, dtype=np.float32),
                           np.arange(h * SS, dtype=np.float32))
    sx, sy = head_x + 0.04 * w * SS, head_y + 0.10 * h * SS
    wide = np.exp(-(((gx2 - sx) / (0.22 * w * SS)) ** 2 +
                    ((gy2 - sy) / (0.15 * h * SS)) ** 2)) * SPEC_WIDE * a
    tight = np.exp(-(((gx2 - sx * 1.04) / (0.085 * w * SS)) ** 2 +
                     ((gy2 - sy * 0.92) / (0.055 * h * SS)) ** 2)) * SPEC_TIGHT * a
    spec = wide + tight

    # ---- 合成 ----
    shade = np.clip(light * ao + spec, 0.0, 1.45)[..., None]
    out_rgb = np.clip(rgb * shade, 0.0, 1.0)
    # 轻微提升饱和度与暖度（可爱向）
    luma = out_rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    out_rgb = np.clip(luma[..., None] + (out_rgb - luma[..., None]) * 1.09, 0, 1)
    out_rgb = out_rgb + rim                                # 边缘反光叠加（加色）
    out_rgb = np.clip(out_rgb, 0.0, 1.0)

    out = np.dstack([out_rgb, a[..., None]])
    out_im = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), 'RGBA')
    return out_im.resize((w, h), Image.LANCZOS)


def process_sheet(path, out_path):
    im = Image.open(path).convert('RGBA')
    w, h = im.size
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    n = max(1, w // 256)                                   # 每张 sheet 由若干 256 帧横排
    for i in range(n):
        frame = im.crop((i * 256, 0, (i + 1) * 256, h))
        out.paste(inflate_frame(frame), (i * 256, 0))
    out.save(out_path)


def main(argv):
    preview = '--preview' in argv
    os.makedirs(DST_DIR, exist_ok=True)
    manifest = json.load(io.open(os.path.join(SRC_DIR, 'manifest.json'), encoding='utf-8'))
    states = manifest['characters']['whale-girl']['states']
    for name in sorted(states):
        src = os.path.join(SRC_DIR, f'{name}.png')
        if os.path.exists(src):
            process_sheet(src, os.path.join(DST_DIR, f'{name}.png'))
            print(f'  {name:14s} ✓')
    io.open(os.path.join(DST_DIR, 'manifest.json'), 'w', encoding='utf-8').write(
        json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f'输出 → {DST_DIR}')

    if preview:                                            # 原版 vs 立体 对比图
        tiles = []
        for name in ('idle', 'celebrate', 'walk', 'eat'):
            a = Image.open(os.path.join(SRC_DIR, f'{name}.png')).convert('RGBA')
            b = Image.open(os.path.join(DST_DIR, f'{name}.png')).convert('RGBA')
            for tag, im in (('原版', a), ('立体', b)):
                tile = im.crop((0, 0, 256, 256)).resize((192, 192), Image.LANCZOS)
                tiles.append((f'{name} {tag}', tile))
        W = 4 * 192 + 60
        H = 2 * 192 + 70
        cv = Image.new('RGBA', (W, H), (46, 64, 96, 255))
        from PIL import ImageDraw, ImageFont
        d = ImageDraw.Draw(cv)
        font = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 15)
        for i, (label, tile) in enumerate(tiles):
            x = 10 + (i % 4) * (192 + 12)
            y = 34 + (i // 4) * (192 + 30)
            cv.alpha_composite(tile, (x, y))
            d.text((x, y - 22), label, font=font, fill=(230, 240, 255, 255))
        out = os.path.join(os.environ.get('TEMP', '/tmp'), 'skin_preview.png')
        cv.convert('RGB').save(out)
        print('对比图 →', out)
    return 0



if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
