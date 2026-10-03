# -*- coding: utf-8 -*-
"""鲸鱼娘桌宠素材工具。

角色精灵图（15 状态，256x256 帧横排）与 manifest.json 取自开源项目
vlln/whale-girl（MIT License，画师 ZipZipPipe），位于 assets/sheets/。
本脚本从 idle.png 第 0 帧生成托盘/窗口图标。

重新生成:  python make_assets.py
"""
import os
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
SHEETS = os.path.join(BASE, 'assets', 'sheets')
OUT = os.path.join(BASE, 'assets')


def make_icon():
    im = Image.open(os.path.join(SHEETS_DIR if False else SHEETS, 'idle.png')).convert('RGBA')
    fw = im.width // 3
    frame = im.crop((0, 0, fw, im.height))
    # 角色内容裁边（去透明边距）
    bbox = frame.getbbox()
    frame = frame.crop(bbox)
    # 居中放到正方形画布
    side = max(frame.size)
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    canvas.paste(frame, ((side - frame.width) // 2, (side - frame.height) // 2), frame)
    for size in (16, 24, 32, 48, 64):
        canvas.resize((size, size), Image.LANCZOS).save(
            os.path.join(OUT, f'icon{size}.png'))
    canvas.resize((48, 48), Image.LANCZOS).save(
        os.path.join(OUT, 'tray.ico'),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48)])
    print('icon + tray.ico regenerated from whale-girl idle frame')


if __name__ == '__main__':
    make_icon()
