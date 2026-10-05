# -*- coding: utf-8 -*-
"""鲸鱼娘桌宠 (Whale Girl Desktop Pet)

角色素材与状态机规格来自开源项目 vlln/whale-girl（MIT License）：
  https://github.com/vlln/whale-girl
  角色立绘：B站画师 ZipZipPipe 的「鲸鱼娘」表情包形象
  精灵图：15 状态 × 256x256 帧横排（assets/sheets/，含 manifest.json）

技术栈: Python + Tkinter(颜色键透明窗口) + PIL(帧插值/合成) + pystray(托盘)

架构要点:
  - 帧间插值引擎: 源素材每状态仅 2-3 帧，播放前在相邻帧之间生成 alpha 混合
    过渡帧（软快门效果），源 6fps 的走路动画以 24ms/子帧 插值播放 → 丝滑
  - 漫游视口: 窗口比角色大一圈，角色在窗口内以画布坐标移动（60fps），
    仅当接近窗口边缘时才整体平移窗口（原子操作，屏幕位置连续）
  - 统一序列模型: 所有状态（素材/程序化动作）都是 (图, 时长, dx, dy) 序列
  - Agent 桥: 本地 HTTP 事件服务（127.0.0.1 + token），
    DeepSeek Harness / Codex / ZCode 可通过 whale_cli.py 或 HTTP 推送事件
"""
import ctypes
import datetime
import io
import json
import math
import os

if os.name != 'nt':      # 透明窗口(颜色键)/winsound/DPI 都依赖 Windows；早点给出人话
    import sys as _sys
    _sys.stderr.write('鲸鱼娘桌宠目前仅支持 Windows（需要透明窗口与 winsound）。\n'
                      '本次退出；其他 Agent 上的文本互动仍可用 MCP/CLI 接口。\n')
    _sys.exit(0)
import queue
import random
import secrets
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tkinter as tk

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

# --------------------------------------------------------------------------
# 基础设置: DPI 感知 / 单实例 / 控制台隐藏
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE_DIR, 'assets')
SHEETS_DIR = os.path.join(ASSETS, 'sheets')
SHEETS_PUFFY = os.path.join(ASSETS, 'sheets-puffy')   # 「肉嘟嘟」伪 3D 皮肤（make_skin_puffy.py 生成）
SOUNDS_DIR = os.path.join(ASSETS, 'sounds')
CONFIG_PATH = os.path.join(BASE_DIR, 'pet_config.json')
TOKEN_PATH = os.path.join(ASSETS, 'bridge_token')
KEY_RGB = (255, 0, 254)          # 透明键色（transparentcolor）
KEY_HEX = '#%02x%02x%02x' % KEY_RGB
DEBUG = '--debug' in sys.argv

try:  # 系统级 DPI 感知，避免高缩放屏下窗口与图像被拉伸模糊
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

if not DEBUG:  # 隐藏 python.exe 的控制台窗口
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

try:  # 单实例
    ctypes.windll.kernel32.CreateMutexW(None, False, 'WhaleGirlPetMutex')
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)
except Exception:
    pass

# --------------------------------------------------------------------------
# 常量（时长参数与 vlln/whale-girl 状态机一致）
# --------------------------------------------------------------------------
BUBBLE_MARGIN = 8
TICK_MS = 16                     # ~60fps

TRANSIENT_MS = 1500              # eat/play 瞬发
WAKE_MS = 3000                   # 醒觉过渡
JOY_MS = 1600                    # 互动喜悦
BLINK_MIN_MS, BLINK_MAX_MS = 3000, 9000   # 眨眼间隔
FACING_MIN_MS, FACING_MAX_MS = 10000, 25000  # 静止态随机转身
SLEEP_AFTER_MS = 60000           # 空闲入睡
WALK_MIN_WAIT_MS, WALK_MAX_WAIT_MS = 18000, 40000  # 散步间隔
WALK_SPEED = 62                  # 散步速度 px/s
WELCOME_MS, CELEBRATE_MS = 6000, 6000
ERROR_MS, DISAPPOINTED_MS = 4000, 6000
POKE_RESET_MS = 2500             # 连戳计数窗口
POKE_THRESHOLD = 5               # 连戳触发惊吓次数
DRAG_RELEASE_MS = 1500           # 放下缓冲
TRICK_MIN_WAIT_MS, TRICK_MAX_WAIT_MS = 12000, 24000  # 小动作间隔

# Agent 事件默认持续时长（ms）
AGENT_STATE_MS = {'think': 15000, 'wait': 8000, 'working': 5000}

IDLE_HOLD_MS = 420               # idle 常驻帧停驻时长（眨眼节奏）

SCALES = {'小': 0.7, '中': 0.9, '大': 1.1, '特大': 1.35}
ALPHAS = {'100%': 1.0, '85%': 0.85, '70%': 0.70, '55%': 0.55}
VOLUMES = {'小': 0.40, '中': 0.70, '大': 1.0}
BRIDGE_PORT_DEFAULT = 37821

# 用量采集：ZCode 的模型 I/O 记录（每次模型调用的真实 usage + 起止时间）
ROLLOUT_DIR = os.path.join(os.path.expanduser('~'), '.zcode', 'cli', 'rollout')
USAGE_DIR = os.path.join(os.path.expanduser('~'), '.whale-pet')
USAGE_STATE = os.path.join(USAGE_DIR, 'usage_state.json')   # 状态放插件外：重装/升级不会回退水位

NAVY = (58, 84, 140)
INK = (43, 58, 103)

FONT_PATH = r'C:\Windows\Fonts\msyh.ttc'
FONT_BOLD = r'C:\Windows\Fonts\msyhbd.ttc'
if not os.path.exists(FONT_BOLD):
    FONT_BOLD = FONT_PATH

LINES = {
    'welcome': ['主人回来啦！鲸鱼娘待命中~', '今天也要一起加油鲸！', '欢迎回来~想我了吗？',
                '哟，还知道回来呀主人？', '主人消失这么久，是不是背着我吃好吃的去了？',
                '欢迎回来～我差点要去捞你了🐋'],
    'hello': ['主人叫我吗？', '我在这里呀！', '需要我做什么吗？', '咕噜咕噜~',
              '点单吗？我已经准备好啦～', '在等什么？等你一声令下，我立刻营业🎀'],
    'poke': ['呀！', '咕噜？', '怎么啦怎么啦？', '戳戳也没关系哦~', '嘿嘿，痒痒的',
             '别戳啦，鱼鳔要漏气了！', '再戳一下就要收费了哦（开玩笑的）',
             '主人要是累了就戳戳我，免费解压，童叟无欺🫧'],
    'pet': ['好舒服…再摸摸~', '最喜欢主人了！', '咕噜咕噜咕噜♥', '尾巴也要摸摸！',
            '主人的手好暖和~', '嘿嘿嘿…', '再摸五分钟……就五分钟……',
            '摸头可以，不许摸鱼缸！'],
    'drag': ['哇哇，要飞起来了！', '轻一点轻一点！', '带我去哪儿呀？', '被拎起来了…',
             '我不是快递！', '放下我，我还想再躺一会儿…'],
    'feed': ['开动啦~', '好好吃！谢谢主人！', '咕噜咕噜…吃饱了', '这顿是真·白饭，不是 token。'],
    'play': ['再来再来！', '接住啦！', '玩球最开心了！', '接住这个球给你表演一个喷水🐋'],
    'sleep': ['Zzz…', '咕噜…咕噜…', '梦里也在帮主人数 bug…', '别叫我，我在梦里做大模型。'],
    'wake': ['呜…醒了。', '唔…我睡着了吗？', '啊…睡得好香~',
             '谁把我叫醒的？哦是主人，那没事了。', '呼……急事就摇摇我的尾巴嘛。'],
    'celebrate': ['完成啦！撒花！', '耶——！主人最棒！', '任务达成，庆祝庆祝！',
                  '搞定！这单稳得像我的尾巴（虽然它一直在晃）', '收工！限时夸夸窗口已开启👏',
                  '漂亮！主人可以摸鱼五分钟，我批准了🎫'],
    'error': ['呜哇！吓我一跳！', '出、出错了？！', '呜呜呜…',
              '报错而已，又不是世界末日…抱抱先🥺', '这个 bug 好嚣张，看我把它的网线拔了💢'],
    'disappointed': ['没事…下次努力…', '呜…有点失落。',
                     '失败了也别低头，我的尾巴借你握一下🐋'],
    'idle': ['主人还在忙吗？', '发呆中…咕噜。', '要不要休息一下呀？', '偷偷看主人…',
             '今天也要元气满满！', '无聊…陪我玩嘛~',
             '主人认真工作的样子，还挺好看的嘛。',
             '待机中……耳朵可没闲着，我听见 bug 在远处笑😼',
             '偷偷给你加一颗糖～', '我什么都没说，只是嘴角有点压不住😏',
             '主人今天的勤奋值有点高，是不是想卷死谁🌪️'],
    'walk': ['出去散散步鲸~', '走走走，活动一下！', '去深海里溜达一圈～'],
    'walk_done': ['到啦！', '这里风景不错鲸~', '散步真舒服~'],
    'spin': ['转圈圈~咕噜咕噜！', '看我的旋风转！', '头晕了…但好开心！'],
    'headshake': ['摇头晃脑ing~', '咕噜咕噜，摇一摇~', '不听不听，王八念经！'],
    'sway': ['跟着节奏摇一摇~', '左右左，左右左！'],
    'hop': ['蹦蹦跳跳！', '跳得更高！', '兔子也要甘拜下风~'],
    'nod': ['嗯嗯嗯，你说得对！', '点头点头~'],
    # ---- Token / 算力 / 摸鱼 梗 ----
    'token': ['让我看看今天吃了多少 token…', '我要吃 token！喂我算力！',
              '我可不是吃白饭的——我吃 token。', '咕噜咕噜…这顿 token 好香～',
              '缓存命中！省下来的算力请你吃糖🍬',
              '我的饭量不大，一天也就几亿 token。',
              '主人省着点用，我是按 token 长胖的！',
              '这个月账单别叫我背哦，我只是一只鲸鱼。'],
    'work': ['开工开工！', '叮叮当当，工具转起来啦🔧', '这速度，主人跟得上吗？',
             '工具们今天也很听话，毕竟我管饭（虚拟的）。'],
    'think_line': ['让本鲸想想…尾巴都转起来了。', '思考中，请勿投喂，除非是能补脑的小蛋糕🧁',
                   '灵感加载中，进度条卡在 99% 是正常现象✨'],
    'agent_think': ['主人在思考…我陪你。', '认真工作中…加油！', '我先安静地漂一会儿…'],
    'agent_wait': ['在等主人确认哦~', '需要批准啦！我举着牌子呢🪧'],
    'agent_working': ['开工开工！', '看我的，马上就好！', '工房一切就绪，随时可以开工哦。'],
}

def load_font(size, bold=False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_PATH, size)
    except Exception:
        return ImageFont.truetype(FONT_PATH, size)


def load_config():
    cfg = {'x': None, 'y': None, 'scale': 0.9, 'alpha': 1.0, 'topmost': True,
           'bridge_enabled': True, 'bridge_port': BRIDGE_PORT_DEFAULT,
           # 音效：默认开启，音量 中；sound_chatter=思考/工作中的碎碎念（默认关，免打扰）
           'sound': True, 'sound_volume': VOLUMES['中'], 'sound_chatter': False,
           'skin': 'puffy',
           # 用量来源：auto=有 ZCode 模型 I/O 记录就用它（钩子在 ZCode 上不触发）
           'usage_source': 'auto'}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def to_photo(im, remap=True):
    """PIL 图像 -> Tk PhotoImage（numpy 向量化 + ImageTk 直通）。

    remap=True（精灵用）: alpha<250 的像素 RGB 置为键色——LANCZOS 缩放产生的
    半透明边缘与键色画布合成后恰好等于键色，被 transparentcolor 完全抠除（零 fringe）。
    remap=False（气泡/爱心等覆盖层用）: 它们是不透明色块，无需重映射。
    """
    im = im.convert('RGBA')
    if remap:
        arr = np.asarray(im).copy()
        mask = arr[..., 3] < 250
        arr[..., 0:3][mask] = KEY_RGB
        im = Image.fromarray(arr, 'RGBA')
    return ImageTk.PhotoImage(image=im)


def draw_heart(d, cx, cy, size, fill, outline=None):
    r = size / 2.0
    w = max(2, int(size * 0.07))
    d.ellipse([cx - size * 0.52, cy - size * 0.62, cx - size * 0.02, cy - size * 0.12],
              fill=fill, outline=outline, width=w)
    d.ellipse([cx + size * 0.02, cy - size * 0.62, cx + size * 0.52, cy - size * 0.12],
              fill=fill, outline=outline, width=w)
    d.polygon([(cx - size * 0.5, cy - size * 0.32), (cx + size * 0.5, cy - size * 0.32),
               (cx, cy + size * 0.55)], fill=fill, outline=outline)


# --------------------------------------------------------------------------
# 精灵播放器 v3：统一序列模型 + 帧间插值
#   所有状态（素材态/程序化动作）都是
#   {'photos': [PhotoImage], 'holds': [ms], 'dx': [px], 'dy': [px],
#    'n': 帧数, 'mode': 'loop'|'pingpong'|'once'|'blink'}
# --------------------------------------------------------------------------
class SpritePlayer:

    def __init__(self, scale, skin='puffy'):
        self.scale = scale
        self.sheets_dir = (SHEETS_PUFFY if (skin == 'puffy' and os.path.isdir(SHEETS_PUFFY))
                           else SHEETS_DIR)
        with open(os.path.join(self.sheets_dir, 'manifest.json'), encoding='utf-8') as f:
            manifest = json.load(f)
        self.states = manifest['characters']['whale-girl']['states']
        self.frame_n = 256
        self.size = max(1, round(self.frame_n * scale))

        # 1) 切片全部源帧（保留 PIL，供插值）
        self._raw = {}
        self._squash_cache = {}                    # (state, flip, idx, level) -> PhotoImage
        for state, cfg in self.states.items():
            sheet = Image.open(os.path.join(self.sheets_dir, cfg['sheet'])).convert('RGBA')
            n = cfg['frames']
            fw = sheet.width // n
            for flip in (1, -1):
                for idx in range(n):
                    fr = sheet.crop((idx * fw, 0, (idx + 1) * fw, sheet.height))
                    fr = fr.resize((self.size, self.size), Image.LANCZOS)
                    if flip == -1:
                        fr = fr.transpose(Image.FLIP_LEFT_RIGHT)
                    self._raw[(state, flip, idx)] = fr

        # 2) 程序化动作（转圈圈/摇头晃脑/摇摆/蹦跳/点头）
        self.actions = {}
        bases = {}
        icfg = self.states['idle']
        ifw = sheet.width // icfg['frames'] if False else sheet.width // 3
        # 注意：上面 sheet 是最后一个状态的图；idle 单独取
        idle_sheet = Image.open(os.path.join(self.sheets_dir, 'idle.png')).convert('RGBA')
        ifw = idle_sheet.width // 3
        for flip in (1, -1):
            fr = idle_sheet.crop((0, 0, ifw, idle_sheet.height)).resize(
                (self.size, self.size), Image.LANCZOS)
            if flip == -1:
                fr = fr.transpose(Image.FLIP_LEFT_RIGHT)
            bases[flip] = fr
        self._build_actions(bases)

        # 3) 素材状态插值序列
        self.seq = {}
        for state, cfg in self.states.items():
            for flip in (1, -1):
                self.seq[(state, flip)] = self._build_seq(state, cfg, flip)

    # ---- 程序化动作 ----
    def _build_actions(self, bases):
        size = self.size
        for flip, base in bases.items():
            # 转圈圈：水平余弦压缩模拟绕竖轴旋转，背面半程镜像
            N, fps = 30, 30
            fr = []
            for i in range(N):
                cs = math.cos(2 * math.pi * i / N)
                w = max(2, int(round(size * abs(cs))))
                f2 = base.resize((w, size), Image.LANCZOS)
                if cs < 0:
                    f2 = f2.transpose(Image.FLIP_LEFT_RIGHT)
                cv = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                cv.paste(f2, ((size - w) // 2, 0), f2)
                fr.append(to_photo(cv))
            self.actions[('spin', flip)] = {'photos': fr, 'n': N,
                                            'holds': [1000 / fps] * N,
                                            'mode': 'once'}

            # 摇头晃脑：整身 ±11° 正弦摇摆两回
            N, fps = 30, 27
            fr = []
            for i in range(N):
                a = 11 * math.sin(2 * math.pi * (2 * i / N))
                fr.append(to_photo(base.rotate(a, Image.BICUBIC)))
            self.actions[('headshake', flip)] = {'photos': fr, 'n': N,
                                                 'holds': [1000 / fps] * N,
                                                 'mode': 'once'}

            # 摇摆舞：±7° 摇摆 + 左右平移
            N, fps = 30, 25
            fr, dx = [], []
            for i in range(N):
                a = 7 * math.sin(2 * math.pi * (2 * i / N))
                fr.append(to_photo(base.rotate(a, Image.BICUBIC)))
                dx.append(int(5 * self.scale * math.sin(2 * math.pi * (2 * i / N))))
            self.actions[('sway', flip)] = {'photos': fr, 'n': N,
                                            'holds': [1000 / fps] * N, 'dx': dx,
                                            'mode': 'once'}

            # 蹦跳：两次抛物线跳跃 + 滞空压缩
            N, fps = 26, 26
            fr, dy = [], []
            for i in range(N):
                t = i / N
                ph = (2 * t) % 1.0
                h = math.sin(ph * math.pi) * 0.15 * size
                sy2 = 1 - 0.05 * abs(math.sin(math.pi * t))
                f2 = base.resize((size, max(2, int(size * sy2))), Image.LANCZOS)
                cv = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                cv.paste(f2, (0, size - f2.height), f2)
                fr.append(to_photo(cv))
                dy.append(-int(h))
            self.actions[('hop', flip)] = {'photos': fr, 'n': N,
                                           'holds': [1000 / fps] * N, 'dy': dy,
                                           'mode': 'once'}

            # 点头：两次下点 + 轻微前倾
            N, fps = 18, 26
            fr, dy = [], []
            for i in range(N):
                t = i / N
                dy.append(int(-abs(math.sin(2 * math.pi * t)) * 0.035 * size))
                fr.append(to_photo(base.rotate(3 * math.sin(2 * math.pi * t),
                                               Image.BICUBIC)))
            self.actions[('nod', flip)] = {'photos': fr, 'n': N,
                                           'holds': [1000 / fps] * N, 'dy': dy,
                                           'mode': 'once'}

    # ---- 素材状态插值序列 ----
    def _build_seq(self, state, cfg, flip):
        n = cfg['frames']
        mode = cfg.get('playback', 'loop')
        hold = 1000 / cfg.get('fps', 3)
        if state == 'idle':
            hold = IDLE_HOLD_MS
        if cfg.get('frameMs'):
            hold = None   # 用 frameMs 按源帧
        get = lambda i: self._raw[(state, flip, i)]

        # 源帧序列（无叠影：不做 alpha 混合，姿态切换由次级运动遮盖）
        if mode == 'pingpong':
            order = list(range(n)) + list(range(n - 2, 0, -1))
        elif mode == 'blink':
            order = list(range(n)) + [0]
        elif mode == 'once':
            order = list(range(n))
        else:  # loop
            order = list(range(n)) + [0]

        photos, holds, dx, dy = [], [], [], []
        motion = cfg.get('motion')

        if motion == 'tilt':   # drag：整帧 ±4° 摇摆（拖拽颠簸感）
            N = 24
            for i in range(N):
                im = get(0).rotate(4 * math.sin(2 * math.pi * 2 * i / N),
                                   Image.BICUBIC)
                photos.append(to_photo(im))
            holds = [1000 / 20] * N
            mode = 'loop'
        elif motion == 'wiggle':   # wait：±2° 轻微摇摆
            N = 15
            for i in range(N):
                im = get(0).rotate(2 * math.sin(2 * math.pi * i / N),
                                   Image.BICUBIC)
                photos.append(to_photo(im))
            holds = [1000 / 15] * N
            mode = 'loop'
        elif motion == 'float':   # think：上下漂浮（位移烘焙）
            N = 18
            for i in range(N):
                photos.append(to_photo(get(0)))
                dy.append(-int(9 * self.scale *
                               (0.5 + 0.5 * math.sin(2 * math.pi * i / N)) * 2))
            holds = [3200 / N] * N
            dx = [0] * N
            mode = 'loop'
        elif motion == 'shake':   # error：源帧 + 左右抖动位移
            for fi in order:
                photos.append(to_photo(get(fi)))
                holds.append(cfg['frameMs'][0] / 1000 if cfg.get('frameMs') else hold)
                dx.append(0); dy.append(0)
            for j, shake_dx in enumerate((0, -3, 0, 3, 0, -2)):
                if j + 1 < len(photos):
                    dx[j + 1] = shake_dx * self.scale * 2
        else:
            for fi in order:
                photos.append(to_photo(get(fi)))
                if cfg.get('frameMs') and fi < len(cfg['frameMs']) and mode == 'once':
                    holds.append(cfg['frameMs'][fi])
                else:
                    holds.append(hold)
            dx = [0] * len(photos); dy = [0] * len(photos)

        # 次级运动：与步频/动作同步的弹跳（60fps 连续位移，遮盖姿态切换）
        bounce = {'walk': (3.0, 3.5), 'joy': (2.5, 2.0), 'welcome': (3.0, 2.0),
                  'eat': (2.5, 1.5), 'play': (3.0, 2.0), 'celebrate': (3.0, 2.0),
                  'working': (2.0, 1.5)}.get(state)
        return {'photos': photos, 'holds': holds, 'dx': dx, 'dy': dy,
                'n': len(photos), 'mode': mode, 'bounce': bounce}

    # ---- 查询 ----
    def seq_of(self, state, flip):
        """返回状态的播放序列：程序化动作优先，其次素材插值序列。"""
        return self.actions.get((state, flip)) or self.seq.get((state, flip))

    def squash_photo(self, base, state, flip, idx, level):
        """果冻挤压变体（懒生成缓存）：level 1=压扁(矮胖) / -1=拉伸(瘦长)。

        以底边中心为锚缩放（贴地不悬空）；程序化动作没有 _raw 帧，返回原图。
        """
        if level == 0:
            return base
        key = (state, flip, idx, level)
        ph = self._squash_cache.get(key)
        if ph is not None:
            return ph
        raw = self._raw.get((state, flip, idx))
        if raw is None:
            return base
        sx, sy = (1.06, 0.935) if level > 0 else (0.955, 1.05)
        nw, nh = max(1, round(self.size * sx)), max(1, round(self.size * sy))
        im = raw.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new('RGBA', (self.size, self.size), (0, 0, 0, 0))
        canvas.paste(im, ((self.size - nw) // 2, self.size - nh))
        ph = to_photo(canvas)
        self._squash_cache[key] = ph
        return ph

    def frame_offset(self, state, flip, idx):
        s = self.seq_of(state, flip)
        if s:
            i = min(idx, s['n'] - 1)
            dx, dy = s.get('dx'), s.get('dy')
            return (dx[i] if dx and i < len(dx) else 0,
                    dy[i] if dy and i < len(dy) else 0)
        return 0, 0


# --------------------------------------------------------------------------
# Agent 桥：本地 HTTP 事件服务（127.0.0.1 + token）
# --------------------------------------------------------------------------
class BridgeServer:
    def __init__(self, app, port, token):
        self.app = app
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authed(self):
                return self.headers.get('X-Token', '') == token

            def do_GET(self):
                if not self._authed():
                    return self._json(401, {'ok': False, 'err': 'bad token'})
                if self.path.startswith('/state'):
                    return self._json(200, {
                        'ok': True, 'state': app.state, 'flip': app.flip,
                        'hidden': app.hidden, 'scale': app.scale,
                        'sound': bool(app.sound.enabled),
                        'sound_volume': round(float(app.sound.volume), 2),
                        'skin': app.skin,
                        'usage_source': app.usage_source,
                        'x': app.px, 'y': app.py, 'ts': time.time()})
                if self.path.startswith('/metrics'):
                    days = 1
                    if 'days=' in self.path:
                        try:
                            days = max(1, min(365,
                                              int(self.path.split('days=')[1].split('&')[0])))
                        except Exception:
                            days = 1
                    if days > 1 and app.usage_tail is not None:
                        agg = app._aggregate(app.usage_tail.days, days)
                        denom = agg['cache_read'] + agg['input']
                        return self._json(200, {
                            'ok': True, 'days': days,
                            'total_tokens': agg['input'] + agg['output'],
                            'input_tokens': agg['input'],
                            'output_tokens': agg['output'],
                            'cache_read_tokens': agg['cache_read'],
                            'cache_hit_rate': (agg['cache_read'] / denom) if denom else 0.0,
                            'responses': agg['responses'],
                            'per_day': agg['per_day']})
                    with app._metrics_lock:
                        return self._json(200, {'ok': True, 'day': app._metrics_day,
                                                **app.metrics})
                return self._json(404, {'ok': False, 'err': 'not found'})

            def do_POST(self):
                if not self._authed():
                    return self._json(401, {'ok': False, 'err': 'bad token'})
                if self.path.startswith('/metrics'):
                    try:
                        ln = int(self.headers.get('Content-Length', 0))
                        if ln > 16384:
                            return self._json(413, {'ok': False, 'err': 'too large'})
                        data = json.loads(self.rfile.read(ln).decode('utf-8'))
                    except Exception:
                        return self._json(400, {'ok': False, 'err': 'bad json'})
                    app.cmd_queue.put(('metrics', data))
                    return self._json(200, {'ok': True})
                if not self.path.startswith('/event'):
                    return self._json(404, {'ok': False, 'err': 'not found'})
                try:
                    ln = int(self.headers.get('Content-Length', 0))
                    if ln > 65536:
                        return self._json(413, {'ok': False, 'err': 'too large'})
                    data = json.loads(self.rfile.read(ln).decode('utf-8'))
                    etype = str(data.get('type', ''))[:24]
                    text = str(data.get('text', ''))[:120]
                    ms = max(0, min(int(data.get('ms', 0)), 120000))
                    value = data.get('value')
                    value = float(value) if isinstance(value, (int, float)) else None
                except Exception:
                    return self._json(400, {'ok': False, 'err': 'bad json'})
                app.cmd_queue.put(('agent', etype, text, ms, value))
                return self._json(200, {'ok': True})

        try:
            self.srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
            self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
            self.thread.start()
        except Exception as e:
            print(f'[bridge] 启动失败: {e}', flush=True)
            self.srv = None


# --------------------------------------------------------------------------
# 音效库：事件 → 候选音效池（来自「鲸鱼娘音效包」，来源与许可见
# assets/sounds/CREDITS.md）。77 条素材全部有归属，同类随机播放、避免重复。
#
#   短反应音（short/，嗷呜/哎呀/摸摸头…）：本地互动时叠加在 118 条台词之上
#   整句语音（voice/，口播整句）：Agent 联动与待机闲聊时使用，气泡同步显示她说的那句话
# --------------------------------------------------------------------------
SOUND_POOLS = {
    # ---- 全部优先用社区原声（voice/，鲸鱼娘真配音）；TTS 合成音已退出池子 ----
    'tap':          ('coquetry10', 'coquetry3', 'coquetry7',     # 在呢/抱抱/主人最好
                     'coquetry9', 'coquetry0', 'coquetry13'),
    'poke':         ('coquetry2', 'coquetry5', 'coquetry1',      # 哼！不理你/偷看/好无聊
                     'coquetry4'),
    'pet':          ('coquetry0', 'coquetry11', 'coquetry13',    # 摸摸头系
                     'coquetry3', 'coquetry7', 'coquetry8',
                     'coquetry12', 'coquetry9', 'coquetry10',
                     'coquetry14'),
    'drag':         ('coquetry5', 'coquetry2'),                  # 被拎起来（咦？/哼！）
    'play':         ('coquetry1', 'coquetry9', 'coquetry4',      # 陪我玩/超乖/努力
                     'coquetry6', 'coquetry12'),
    'feed':         ('coquetry6',),                              # 好想吃小鱼干…是投喂～
    'wake':         ('coquetry10', 'coquetry9'),                 # 在呢/超乖
    'show':         ('welcome0', 'coquetry10'),                  # 主人好～/在呢
    'welcome':      ('welcome0', 'coquetry10', 'coquetry3'),
    'celebrate':    ('celebrate0', 'celebrate1', 'celebrate2', 'celebrate3',
                     'celebrate4', 'celebrate5', 'celebrate6', 'celebrate7',
                     'celebrate8', 'celebrate9'),
    'error':        ('sad0', 'sad3'),                            # 呜…出错了/呜哇…
    'disappointed': ('sad1', 'sad2', 'sad4', 'sad5', 'sad6', 'sad7'),
    'wait':         ('approval0',),
    'think':        ('running0', 'running1', 'running2', 'running3', 'running4',
                     'running5', 'running6', 'running7', 'running8', 'running9',
                     'todo0', 'todo1', 'todo2', 'todo3'),
    'working':      ('running0', 'running1', 'running2', 'running3', 'running4',
                     'running5', 'running6', 'running7', 'running8', 'running9',
                     'todo0', 'todo1', 'todo2', 'todo3'),
}

# 用户主动触发的动作：可以打断正在播的语音（点她要有即时反馈）
URGENT_EVENTS = ('tap', 'poke', 'pet', 'drag', 'play', 'feed', 'wake', 'show',
                 'sleep')

# 反复触发类事件的最小间隔（秒）：整句语音比短音效更容易腻，间隔放宽
SOUND_COOLDOWN = {'tap': 5.0, 'poke': 5.0, 'pet': 8.0, 'drag': 6.0, 'play': 8.0,
                  'feed': 6.0, 'welcome': 10.0, 'celebrate': 12.0, 'think': 25.0,
                  'working': 20.0, 'wait': 8.0}

SYNC_TEXT_MIN = 6      # 台词 ≥6 字 → 气泡同步显示她说的话（社区原声整句都会同步）


class SoundEngine:
    """assets/sounds/{short,voice}/*.wav 播放器 + 事件音效池。

    - winsound 不允许「内存 + 异步」组合，故在后台线程里做同步播放：
      主循环（60fps）零阻塞，这正是丝滑度的前提
    - 音量按需缩放 16bit PCM 后缓存；同名单音 90ms 内不重放，防止连点爆音
    - 池内随机且避开最近用过的条目（含跨事件防重复）；反复触发类事件带冷却
    - 上一条还没播完时，非用户主动的事件不再开腔（避免叠音/听感上的"卡住重复"）
    - 缺文件（例如删掉 voice/ 只留 short/）会自动跳过候选，功能照常
    """

    MIN_GAP_S = 0.09
    VOICE_GAP_S = 1.2          # 两条语音之间的最小间隔（秒）

    def __init__(self, enabled=True, volume=0.8, pools=None):
        self.dir = SOUNDS_DIR
        self.enabled = bool(enabled)
        self.volume = max(0.0, min(1.0, float(volume)))
        self.pools = pools or SOUND_POOLS
        self.lines = self._load_lines()
        self._cache = {}
        self._playing = None          # 保持引用：播放期间缓冲必须存活
        self._last_at = {}
        self._dur = {}                # name -> 时长（判断"还在播"）
        self._playing_until = 0.0
        self._recent = {}             # event -> 最近用过的条目（事件内防重复）
        self._recent_any = []         # 全局最近播过的条目（跨事件防重复）
        self._last_voice = 0.0
        self._last_event = {}         # event -> 上次触发时间（冷却用）
        try:
            import winsound
            self._ws = winsound
        except Exception:
            self._ws = None

    def _load_lines(self):
        try:
            with open(os.path.join(self.dir, 'lines.json'), encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _path(self, name):
        for sub in ('short', 'voice', ''):
            p = (os.path.join(self.dir, sub, name + '.wav') if sub
                 else os.path.join(self.dir, name + '.wav'))
            if os.path.exists(p):
                return p
        return None

    def pick(self, event, urgent=False):
        """按事件挑一条音效。返回 (name, 台词) 或 None（无候选/冷却中/已静音）。

        urgent=True（用户主动点击等）可打断正在播的语音；否则上一条没播完就不再开腔，
        也不会在 1.2 秒内连开第二条——这两条是"卡住/重复读"的根治手段。
        """
        if not self.enabled:
            return None
        now = time.time()
        cd = SOUND_COOLDOWN.get(event)
        if cd and now - self._last_event.get(event, 0.0) < cd:
            return None
        if not urgent:
            if now < self._playing_until - 0.15 or now - self._last_voice < self.VOICE_GAP_S:
                return None
        cands = [n for n in self.pools.get(event, ()) if self._path(n)]
        if not cands:
            return None
        blocked = set(self._recent.get(event, [])) | set(self._recent_any)
        name = random.choice([n for n in cands if n not in blocked] or cands)
        self._recent[event] = ([name] + self._recent.get(event, []))[:3]
        self._recent_any = ([name] + self._recent_any)[:3]
        self._last_event[event] = now
        return name, (self.lines.get(name, {}) or {}).get('text', '')

    def play_event(self, event, urgent=False):
        """挑一条并播放，返回 (name, 台词) 或 None。"""
        item = self.pick(event, urgent)
        if item:
            self.play(item[0])
            self._last_voice = time.time()
            self._playing_until = self._last_voice + self._dur.get(item[0], 0.6)
        return item

    def play_any(self, names):
        """从给定候选里随机播一条（Agent 自带台词时的短反应音）。"""
        cands = [n for n in names if self._path(n)]
        if not cands:
            return False
        name = random.choice([n for n in cands if n not in self._recent_any] or cands)
        self._recent_any = ([name] + self._recent_any)[:3]
        ok = self.play(name)
        if ok:
            self._last_voice = time.time()
            self._playing_until = self._last_voice + self._dur.get(name, 0.6)
        return ok

    def _data(self, name):
        key = (name, round(self.volume, 2))
        data = self._cache.get(key)
        if data is not None:
            return data
        path = self._path(name)
        try:
            with wave.open(path, 'rb') as w:
                nch, sw, fr = w.getnchannels(), w.getsampwidth(), w.getframerate()
                self._dur[name] = w.getnframes() / float(fr or 1)
                raw = w.readframes(w.getnframes())
            if sw == 2:
                arr = np.frombuffer(raw, dtype='<i2').astype(np.float32) * self.volume
                raw = np.clip(arr, -32768.0, 32767.0).astype('<i2').tobytes()
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as out:
                out.setnchannels(nch)
                out.setsampwidth(sw)
                out.setframerate(fr)
                out.writeframes(raw)
            data = buf.getvalue()
        except Exception:
            data = b''
        self._cache[key] = data
        return data

    def play(self, name, force=False):
        if not self.enabled or self._ws is None:
            return False
        now = time.time()
        if not force and now - self._last_at.get(name, 0.0) < self.MIN_GAP_S:
            return False
        data = self._data(name)
        if not data:
            return False
        self._last_at[name] = now
        self._playing = data          # 播放期间保持缓冲存活
        threading.Thread(target=self._play_blocking, args=(data,),
                         daemon=True).start()
        return True

    def _play_blocking(self, data):
        try:
            self._ws.PlaySound(data, self._ws.SND_MEMORY | self._ws.SND_NODEFAULT)
        except Exception:
            pass


# --------------------------------------------------------------------------
# 用量采集：读 ZCode 的模型 I/O 记录，按「天」分桶（不依赖宿主钩子）
# --------------------------------------------------------------------------
class UsageTail:
    """tail ~/.zcode/cli/rollout/model-io-*.jsonl，把每次模型调用的用量记到「天」上。

    - 面板显示**今天**的用量（跨天自动归零），右键菜单可看近 7 天 / 近 30 天
    - 去重：按 requestId 记账（持久化）——无论重启、重装、水位回退都**不会重复计**
      （v1.2.x 的教训：状态文件放插件目录里，重装时被旧副本覆盖 → 水位回退 → 全量重算，
       实测 72 条真实记录被记成 1401 次）
    - 状态存 ~/.whale-pet/usage_state.json（插件外，属于用户数据，重装不覆盖）
    - 首次运行回填 rollout 里已有的历史：近 7/30 天视图立刻有数据
    - 只读本地文件、不出网
    """

    VERSION = 2
    READ_TAIL_BYTES = 8 * 1024 * 1024
    KEEP_DAYS = 40                 # 天级明细保留 40 天（30 天视图 + 余量）
    MAX_IDS_PER_DAY = 8000         # 每天记账的 requestId 上限（防无限膨胀）

    def __init__(self, app, interval=1.0):
        self.app = app
        self.dir = app.cfg.get('usage_rollout_dir') or ROLLOUT_DIR
        self.state_path = USAGE_STATE
        self.interval = interval
        self.offsets = {}
        self.days = {}             # 'YYYY-MM-DD' -> {'input','output','cache_read','responses','ids'}
        self.last_epoch = 0.0
        self._loaded = False
        self._persist_at = 0.0

    # ---- 日期 ----
    @staticmethod
    def _day_of(epoch):
        return time.strftime('%Y-%m-%d', time.localtime(epoch))

    def today(self):
        return self._day_of(time.time())

    # ---- 状态 ----
    def load(self):
        """读状态 → (今日指标快照或 None)。旧格式（v1 平铺）弃用：历史由回填重建。"""
        try:
            with open(self.state_path, encoding='utf-8') as f:
                st = json.load(f)
            if int(st.get('version') or 0) < self.VERSION:
                return None
            self.days = st.get('days') or {}
            self.last_epoch = float(st.get('last_epoch') or 0.0)
            self._loaded = True
            today = self.days.get(self.today())
            if today:
                return {'input_tokens': today.get('input', 0),
                        'output_tokens': today.get('output', 0),
                        'cache_read_tokens': today.get('cache_read', 0),
                        'responses': today.get('responses', 0)}
        except Exception:
            pass
        return None

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            cut = time.strftime('%Y-%m-%d', time.localtime(time.time() - self.KEEP_DAYS * 86400))
            days = {d: v for d, v in self.days.items() if d >= cut}
            for v in days.values():
                if len(v.get('ids', [])) > self.MAX_IDS_PER_DAY:
                    v['ids'] = v['ids'][-self.MAX_IDS_PER_DAY:]
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump({'version': self.VERSION, 'last_epoch': self.last_epoch,
                           'days': days}, f, ensure_ascii=False)
        except Exception:
            pass

    # ---- 扫描 ----
    def _files(self):
        try:
            return [os.path.join(self.dir, f) for f in os.listdir(self.dir)
                    if f.startswith('model-io-') and f.endswith('.jsonl')]
        except Exception:
            return []

    def _record(self, line, path):
        """模型 I/O 记录 → (requestId, epoch, 本地日期, payload)；非用量记录返回 None。"""
        try:
            e = json.loads(line)
        except Exception:
            return None
        if not isinstance(e, dict) or e.get('type') != 'model_io':
            return None
        u = ((e.get('response') or {}).get('usage') or {})
        inp, out = int(u.get('inputTokens') or 0), int(u.get('outputTokens') or 0)
        if inp + out <= 0:
            return None
        ts = str(e.get('completedAt') or e.get('startedAt') or '')
        try:
            epoch = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
        except Exception:
            try:
                epoch = os.path.getmtime(path)
            except Exception:
                return None
        rid = str(e.get('requestId') or f'{path}:{ts}:{inp}:{out}')
        return rid, epoch, self._day_of(epoch), {
            'input_tokens': inp, 'output_tokens': out,
            'cache_read_tokens': int(u.get('cacheReadTokens') or 0),
            'cache_creation_tokens': 0,
            'duration_ms': int(e.get('durationMs') or 0)}

    def _count(self, rid, day, payload):
        """记一笔（按 requestId 幂等，永不重复计）；今天的数据推给面板。"""
        bucket = self.days.setdefault(day, {'input': 0, 'output': 0, 'cache_read': 0,
                                            'responses': 0, 'ids': []})
        ids = bucket.setdefault('ids', [])
        if rid in ids:
            return False
        ids.append(rid)
        bucket['input'] += payload['input_tokens']
        bucket['output'] += payload['output_tokens']
        bucket['cache_read'] += payload['cache_read_tokens']
        bucket['responses'] += 1
        if day == self.today():
            self.app.cmd_queue.put(('metrics', dict(payload, source='rollout', day=day)))
        return True

    def _read(self, path, off_from, backfill=False):
        """从 off_from 读到文件尾；backfill=True 时整文件回填历史。返回新偏移。"""
        try:
            size = os.path.getsize(path)
            if backfill:
                off_from = 0
            elif off_from is None:
                off_from = max(0, size - self.READ_TAIL_BYTES)
            if off_from > size:
                off_from = 0
            if off_from >= size:
                return size
            with open(path, 'rb') as f:
                f.seek(off_from)
                chunk = f.read()
            end = chunk.rfind(b'\n')
            if end < 0:
                return off_from
            for line in chunk[:end].decode('utf-8', 'ignore').splitlines():
                if not line.strip():
                    continue
                rec = self._record(line, path)
                if rec:
                    rid, epoch, day, payload = rec
                    if epoch > self.last_epoch or backfill:
                        self._count(rid, day, payload)
                    if epoch > self.last_epoch:
                        self.last_epoch = epoch
            return off_from + end + 1
        except Exception:
            return off_from or 0

    def scan(self, initial=False):
        # 首次运行（没有按天账本）→ 先回填历史，近 7/30 天视图立刻有数据
        backfill = initial and not self._loaded
        for path in self._files():
            self.offsets[path] = self._read(path, self.offsets.get(path),
                                            backfill=backfill)
        self._loaded = True
        now = time.time()
        if initial or now - self._persist_at > 5:
            self._persist_at = now
            self.save()

    def run(self):
        self.scan(initial=True)
        while True:
            time.sleep(self.interval)
            try:
                self.scan()
            except Exception:
                pass


# --------------------------------------------------------------------------
# 桌宠主程序
# --------------------------------------------------------------------------
class PetApp:
    def __init__(self):
        self.cfg = load_config()
        self.scale = float(self.cfg.get('scale', 0.9))
        self.cmd_queue = queue.Queue()
        self.tray = None
        self.bridge = None

        self.state = 'idle'
        self.state_until = 0.0
        self.flip = 1                 # 1=朝左, -1=朝右（素材朝左基准）
        self.frame = 0
        self.last_frame_at = 0.0
        self.blink_active = False
        self.blink_at = 0.0
        self.facing_at = 0.0
        self.idle_since = time.time()
        self.walk_wait = time.time() + random.uniform(
            WALK_MIN_WAIT_MS / 1000, WALK_MAX_WAIT_MS / 1000)
        self.trick_at = time.time() + random.uniform(7, 14)
        self.pokes = []
        self.drag = None
        self.walk = None
        self.sleeping_anim = False
        self.hidden = False
        self.sound = SoundEngine(self.cfg.get('sound', True),
                                 self.cfg.get('sound_volume', 0.8))
        self.saved_pos = None
        self.particles = []
        self.bubble = None
        self.bubble_queue = []
        self._bubble_cache = {}
        self._last_press_at = 0.0
        self._pp_dir = 1
        self._now = time.time()
        # Token 用量统计（Agent 桥 /metrics 上报）
        self._metrics_lock = threading.Lock()
        self.metrics = {'input_tokens': 0, 'output_tokens': 0,
                        'cache_read_tokens': 0, 'cache_creation_tokens': 0,
                        'cache_hit_rate': 0.0, 'output_rate': 0.0,
                        'responses': 0}
        self._metrics_dirty = False
        # 用量来源：ZCode 用模型 I/O 记录（钩子实测不触发）；其他宿主回落到钩子上报
        self.usage_source = self.cfg.get('usage_source', 'auto')
        if self.usage_source == 'auto':
            self.usage_source = ('rollout' if os.path.isdir(ROLLOUT_DIR) else 'hooks')
        self.usage_tail = None
        if self.usage_source == 'rollout':
            self.usage_tail = UsageTail(self)
            snap = self.usage_tail.load()          # 今天已有的累计（按天账本）
            if isinstance(snap, dict):
                with self._metrics_lock:
                    self.metrics.update({k: snap[k] for k in self.metrics
                                         if k in snap})
        # 用量面板显示模式：auto=点一下短暂显示 / on=常显 / off=关闭
        self.hud_mode = self.cfg.get('hud_mode', 'auto')
        if self.hud_mode not in ('auto', 'on', 'off'):
            self.hud_mode = 'auto'
        self.hud_until = 0.0        # auto 模式的临时显示截止时间
        self._hud_shown = False
        self.hud_item = None
        self._hud_photo = None
        # 用量面板视图：today / 7d / 30d（右键或托盘的「用量统计」切换）
        self.hud_view = 'today'
        self._metrics_day = time.strftime('%Y-%m-%d')
        # Q弹果冻动画：触发后在持续时间内做衰减的压扁/拉伸
        self._jelly_until = 0.0
        self._jelly_dur = 0.32

        self._compute_layout()
        self._build_window()
        self._sound_var = tk.BooleanVar(value=self.sound.enabled)
        self._vol_var = tk.DoubleVar(
            value=float(self.cfg.get('sound_volume', VOLUMES['中'])))
        self._hud_view_var = tk.StringVar(value=self.hud_view)
        self.skin = self.cfg.get('skin', 'puffy')
        self._skin_var = tk.StringVar(value=self.skin)
        self.player = SpritePlayer(self.scale, self.skin)
        self._refresh_base()
        self._bind_events()
        self._start_tray()
        self._start_bridge()
        self._start_usage()
        self._welcome()
        self._t0 = time.time()
        self._tick_count = 0
        self._tick()

    # ---------------- 布局与窗口 ----------------
    def _compute_layout(self):
        """漫游视口布局：窗口大于角色，角色在窗口内移动，越界才平移窗口。"""
        size = max(1, round(256 * self.scale))
        self.spr_w = self.spr_h = size
        self.bubble_h = int(104 * self.scale) + 20
        self.hud_h = int(54 * self.scale) + 20          # 用量 HUD 高度（三栏三行卡片）
        self.roam_side = max(90, round(150 * self.scale))   # 左右可移动量（越大窗口重定位越少）
        self.roam_vert = max(46, round(64 * self.scale))
        head_clear = round(0.90 * size) + self.bubble_h + 6
        hud_reserve = self.hud_h + 8                     # 恒保留：面板隐现不引起布局跳动
        self.win_w = size + self.roam_side * 2
        self.win_h = head_clear + self.roam_vert + 10 + hud_reserve
        self.anchor_x = self.win_w / 2
        self.anchor_y = self.win_h - 10 - hud_reserve
        self.ix_lo = self.anchor_x - self.roam_side
        self.ix_hi = self.anchor_x + self.roam_side
        self.iy_lo = self.anchor_y - self.roam_vert
        self.iy_hi = self.anchor_y

    def _build_window(self):
        self.root = tk.Tk()
        self.root.title('鲸鱼娘桌宠')
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', bool(self.cfg.get('topmost', True)))
        self.root.attributes('-transparentcolor', KEY_HEX)
        self.root.attributes('-alpha', float(self.cfg.get('alpha', 1.0)))
        self.root.configure(bg=KEY_HEX)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if self.cfg.get('x') is None:
            self.sx = sw / 2
            self.sy = sh * 0.86
        else:
            self.sx = float(self.cfg['x']) + self.anchor_x
            self.sy = float(self.cfg['y']) + self.anchor_y
        self.px = int(self.sx - self.anchor_x)
        self.py = int(self.sy - self.anchor_y)
        self.px = max(0, min(self.px, sw - 100))
        self.py = max(0, min(self.py, sh - 100))

        self.canvas = tk.Canvas(self.root, width=self.win_w, height=self.win_h,
                                highlightthickness=0, bg=KEY_HEX)
        self.canvas.pack()
        self.root.geometry(f'{self.win_w}x{self.win_h}+{self.px}+{self.py}')

    def _refresh_base(self, photo=None):
        if photo is None:
            photo = self._current_photo()
            if self._jelly_until > time.time():
                # Q弹果冻：衰减正弦在 压扁/拉伸 间交替（先压后弹）
                p = 1.0 - (self._jelly_until - time.time()) / max(1e-3, self._jelly_dur)
                wave = math.sin(p * math.pi * 2.5) * math.exp(-2.6 * p)
                level = 1 if wave > 0.25 else (-1 if wave < -0.25 else 0)
                if level:
                    photo = self.player.squash_photo(photo, self.state, self.flip,
                                                     self.frame, level)
        if getattr(self, 'base_item', None) is None:
            self.base_item = self.canvas.create_image(0, 0, image=photo, anchor='s')
        else:
            self.canvas.itemconfig(self.base_item, image=photo)
        self._base_photo = photo  # 防 GC

    def _current_photo(self):
        seq = self.player.seq_of(self.state, self.flip)
        if seq:
            return seq['photos'][min(self.frame, seq['n'] - 1)]
        return None

    # ---------------- 漫游视口定位 ----------------
    def _place(self):
        """把角色屏幕坐标换算成画布坐标；接近窗口边缘时原子平移窗口。"""
        ix = self.sx - self.px
        iy = self.sy - self.py
        moved = False
        if ix < self.ix_lo:
            d = self.ix_lo - ix; self.px -= d; ix += d; moved = True
        elif ix > self.ix_hi:
            d = ix - self.ix_hi; self.px += d; ix -= d; moved = True
        if iy < self.iy_lo:
            d = self.iy_lo - iy; self.py -= d; iy += d; moved = True
        elif iy > self.iy_hi:
            d = iy - self.iy_hi; self.py += d; iy -= d; moved = True
        adx, ady = self.player.frame_offset(self.state, self.flip, self.frame)
        seq = self.player.seq_of(self.state, self.flip)
        if seq and seq.get('bounce') and not self.drag:
            hz, amp = seq['bounce']
            ady += math.sin(2 * math.pi * hz * self._now) * amp
        self.canvas.coords(self.base_item, round(ix + adx), round(iy + ady))
        if getattr(self, 'bubble_item', None) is not None and self.bubble:
            bw = self.bubble.get('w', 0)
            bx = max(BUBBLE_MARGIN, min(ix - bw / 2, self.win_w - bw - BUBBLE_MARGIN))
            by = max(4, iy - round(0.88 * self.spr_h) - self.bubble.get('h', 0))
            self.canvas.coords(self.bubble_item,
                               round(bx + bw / 2), round(by + self.bubble['h'] / 2))
        self._place_hud()
        if moved:
            self._move_window_raw(self.px, self.py)

    def _move_window_raw(self, x, y):
        """整体平移窗口（漫游视口下仅在角色越界时调用，频率很低）。
        用 Tk geometry 保证与 Tk 内部记账一致。"""
        self.px, self.py = int(x), int(y)
        self.root.geometry(f'+{self.px}+{self.py}')

    def _move_window(self, x, y):
        """移动角色屏幕位置（漫游视口会自动处理窗口跟随）。"""
        self.sx, self.sy = float(x), float(y)
        self._place()

    def _clamp_and_save(self):
        sw = ctypes.windll.user32.GetSystemMetrics(78)
        sh = ctypes.windll.user32.GetSystemMetrics(79)
        ox = ctypes.windll.user32.GetSystemMetrics(76)
        oy = ctypes.windll.user32.GetSystemMetrics(77)
        self.sx = max(ox + self.spr_w / 2, min(self.sx, ox + sw - self.spr_w / 2))
        self.sy = max(oy + self.spr_h, min(self.sy, oy + sh - 8))
        self._place()
        self.cfg['x'] = int(self.px)
        self.cfg['y'] = int(self.py)
        save_config(self.cfg)

    # ---------------- 事件绑定 ----------------
    def _bind_events(self):
        c = self.canvas
        c.bind('<ButtonPress-1>', self._on_press)
        c.bind('<B1-Motion>', self._on_drag)
        c.bind('<ButtonRelease-1>', self._on_release)
        c.bind('<Button-3>', self._on_menu)
        self.root.bind('<Escape>', lambda e: self.quit())

    # ---------------- 交互 ----------------
    def jelly(self, dur=0.32):
        """Q弹一下：在 dur 秒内做衰减的果冻挤压（先压扁再回弹）。"""
        self._jelly_until = time.time() + dur
        self._jelly_dur = dur

    def _voice(self, event):
        """播放事件语音。返回 True = 气泡已交给语音台词（调用方不必再补台词）。

        短促反应音（嗷呜/哎呀…）返回 False，气泡照旧显示 118 条台词里的随机一句；
        整句语音（≥6 字，如 Agent 庆祝/安慰、抚摸撒娇）返回 True 并同步气泡文案，
        做到"她说的"和"屏幕上写的"一致。隐藏状态下保持安静。
        """
        if self.hidden:
            return False
        item = self.sound.play_event(event, urgent=event in URGENT_EVENTS)
        if not item:
            return False
        text = item[1]
        if text and len(text) >= SYNC_TEXT_MIN:
            self.say(text)
            return True
        return False

    def _note_poke(self):
        """连戳计数；达到阈值触发惊吓。返回是否触发了 error。"""
        now = time.time()
        self.pokes = [t for t in self.pokes if now - t < POKE_RESET_MS / 1000]
        self.pokes.append(now)
        if len(self.pokes) >= POKE_THRESHOLD:
            self.pokes.clear()
            self._set_state('error', ERROR_MS / 1000)
            if not self._voice('error'):
                self.say(random.choice(LINES['error']))
            return True
        return False

    def _interact(self):
        """用户在场信号：空闲计时重置；睡着则先醒觉。"""
        self.idle_since = time.time()
        self.walk_wait = time.time() + random.uniform(
            WALK_MIN_WAIT_MS / 1000, WALK_MAX_WAIT_MS / 1000)
        if self.sleeping_anim:
            self.sleeping_anim = False
            self._set_state('wake', WAKE_MS / 1000)
            self.say(random.choice(LINES['wake']))
            return True
        return False

    def _on_press(self, e):
        now = time.time()
        is_double = now - self._last_press_at < 0.30
        self._last_press_at = now
        if self._note_poke():
            self.drag = None
            return
        if is_double:   # 双击 = 玩耍
            self._interact()
            self._set_state('play', TRANSIENT_MS / 1000)
            self.jelly(0.36)
            if not self._voice('play'):
                self.say(random.choice(LINES['play']))
            self.drag = None
            return
        self.drag = {'x': e.x_root, 'y': e.y_root, 'sx': self.sx, 'sy': self.sy,
                     'moved': False, 'petting': False, 't': now, 'heart_at': 0.0}
        self.canvas.focus_set()
        self.flash_hud()          # 点一下：短暂显示用量面板

    def _on_drag(self, e):
        if not self.drag:
            return
        dx = e.x_root - self.drag['x']
        dy = e.y_root - self.drag['y']
        if not self.drag['moved'] and math.hypot(dx, dy) > 6:
            self.drag['moved'] = True
            was_sleeping = self.sleeping_anim
            self._interact()
            self._set_state('drag')
            if was_sleeping:
                self.drag['wake_on_release'] = True
            if not self._voice('drag'):
                self.say(random.choice(LINES['drag']))
        if self.drag['moved']:
            self._move_window(self.drag['sx'] + dx, self.drag['sy'] + dy)
            self.flip = -1 if dx > 0 else 1

    def _update_drag(self, now):
        """tick 内处理抚摸：按住不动 0.5s 进入抚摸，持续飘爱心。"""
        d = self.drag
        if not d or d['moved']:
            return
        if not d['petting'] and now - d['t'] > 0.5:
            d['petting'] = True
            self._interact()
            self._set_state('joy')
            if not self._voice('pet'):
                self.say(random.choice(LINES['pet']))
        if d['petting'] and now >= d['heart_at']:
            d['heart_at'] = now + 0.45
            self._spawn_hearts(1)

    def _on_release(self, e):
        if not self.drag:
            return
        d = self.drag
        self.drag = None
        if d['moved']:
            self._clamp_and_save()
            self.jelly(0.4)
            if d.get('wake_on_release'):
                self.sleeping_anim = False
                self._set_state('wake', WAKE_MS / 1000)
                self.say(random.choice(LINES['wake']))
            else:
                self._set_state('idle', DRAG_RELEASE_MS / 1000)
            return
        if d['petting']:
            self._interact()
            self._set_state('joy', JOY_MS / 1000)
            self._spawn_hearts(3)
            self.say(random.choice(LINES['pet']))
            return
        if self._interact():          # 刚被叫醒（wake 台词已由 _interact 说出）
            self.jelly(0.3)
            self._voice('wake')
            return
        self._set_state('joy', JOY_MS / 1000)
        self._spawn_hearts(3)
        evt = 'poke' if len(self.pokes) >= 3 else 'tap'   # 连戳 → 不耐烦
        if not self._voice(evt):
            self.say(random.choice(LINES['poke']))

    def _on_menu(self, e):
        m = tk.Menu(self.root, tearoff=0, font=('Microsoft YaHei', 9))
        m.add_command(label='打招呼', command=lambda: self.cmd_queue.put('hello'))
        m.add_command(label='投喂', command=lambda: self.cmd_queue.put('feed'))
        m.add_command(label='玩耍', command=lambda: self.cmd_queue.put('play'))
        m.add_command(label='哄她睡觉', command=lambda: self.cmd_queue.put('sleep_now'))
        m.add_command(label='转圈圈', command=lambda: self.cmd_queue.put('spin'))
        m.add_command(label='摇头晃脑', command=lambda: self.cmd_queue.put('headshake'))
        m.add_command(label='隐藏', command=lambda: self.cmd_queue.put('hide'))
        m.add_separator()
        usage = tk.Menu(m, tearoff=0, font=('Microsoft YaHei', 9))
        for label, key in (('今日', 'today'), ('近 7 天', '7d'), ('近 30 天', '30d')):
            usage.add_radiobutton(label=label, variable=self._hud_view_var,
                                  value=key, command=self.set_hud_view)
        m.add_cascade(label='用量统计', menu=usage)
        m.add_checkbutton(label='音效', variable=self._sound_var,
                          command=self.toggle_sound)
        vol = tk.Menu(m, tearoff=0, font=('Microsoft YaHei', 9))
        for name, val in VOLUMES.items():
            vol.add_radiobutton(label=name, variable=self._vol_var, value=val,
                                command=self.set_volume_choice)
        m.add_cascade(label='音量', menu=vol)
        m.add_separator()
        m.add_command(label='退出', command=self.quit)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # ---------------- 状态机 ----------------
    def _set_state(self, state, duration=0.0):
        if state != self.state or True:
            self.state = state
            self.frame = 0
            self.last_frame_at = time.time()
        self.state_until = time.time() + duration if duration else 0.0
        self.sleeping_anim = (state == 'sleep')
        self._refresh_base()

    def _pick_idle_act(self):
        """底层派生状态：睡眠/散步/小动作/待机。"""
        now = time.time()
        if now - self.idle_since >= SLEEP_AFTER_MS / 1000:
            # 只在「刚入睡」那一刻说一次：sleep 是无时长状态，本函数每 tick 都会走到这里，
            # 少了这个判断就会每秒塞几十条 Zzz…（表现为台词/音效卡住重复）
            if self.state != 'sleep':
                self._set_state('sleep')
                if random.random() < 0.4:
                    self.say(random.choice(LINES['sleep']))
            return
        if now >= self.walk_wait:
            self._start_walk()
            return
        if now >= self.trick_at:
            self.trick_at = now + random.uniform(TRICK_MIN_WAIT_MS / 1000,
                                                 TRICK_MAX_WAIT_MS / 1000)
            self._do_random_trick()
            return
        self._set_state('idle')

    def _do_random_trick(self, name=None):
        names = ('spin', 'headshake', 'sway', 'hop', 'nod')
        self._do_trick(name or random.choice(names))

    def _do_trick(self, name):
        seq = self.player.seq_of(name, self.flip)
        if not seq:
            return
        dur = sum(seq['holds']) / 1000.0 + 0.05
        self._set_state(name, dur)
        if random.random() < 0.6:
            self.say(random.choice(LINES.get(name, LINES['idle'])))

    def _start_walk(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        tx = self.sx + random.choice((-1, 1)) * random.uniform(180, 520)
        tx = max(self.spr_w * 0.6, min(tx, sw - self.spr_w * 0.6))
        ty = self.sy + random.uniform(-70, 90)
        ty = max(self.spr_h * 0.8, min(ty, sh - 10))
        self.flip = -1 if tx > self.sx else 1
        self.walk = {'x0': self.sx, 'y0': self.sy, 'x1': tx, 'y1': ty,
                     't0': time.time(),
                     'dur': max(1.6, abs(tx - self.sx) / WALK_SPEED)}
        self.walk_wait = time.time() + random.uniform(
            WALK_MIN_WAIT_MS / 1000, WALK_MAX_WAIT_MS / 1000)
        self._set_state('walk')
        self.say(random.choice(LINES['walk']))

    def _end_walk(self):
        self.walk = None
        self._clamp_and_save()
        if random.random() < 0.7:
            self.say(random.choice(LINES['walk_done']))
        self._set_state('idle')

    def _update_state(self, now):
        """状态机决策（优先级降序）。"""
        if self.drag:
            return
        if self.state == 'walk':
            w = self.walk
            t = min(1.0, (now - w['t0']) / w['dur'])
            ease = t * t * (3 - 2 * t)
            self.sx = w['x0'] + (w['x1'] - w['x0']) * ease
            self.sy = w['y0'] + (w['y1'] - w['y0']) * ease
            self._place()
            if t >= 1.0:
                self._end_walk()
            return

        if self.state_until and now < self.state_until:
            return

        if self.state == 'error':
            self._set_state('disappointed', DISAPPOINTED_MS / 1000)
            if not self._voice('disappointed'):
                self.say(random.choice(LINES['disappointed']))
            return

        if self.state == 'wake':
            self.idle_since = time.time()
        self._pick_idle_act()

    # ---------------- 主循环 ----------------
    def _tick(self):
        now = time.time()
        self._now = now
        try:
            self._process_commands()
            self._update_drag(now)
            self._update_state(now)
            self._animate(now)
            if self._jelly_until > now:
                self._refresh_base()               # Q弹进行中：逐 tick 换挤压变体
            self._update_particles()
            self._update_hud()
            if self.bubble and now > self.bubble['until']:
                self._next_bubble()
            if not self.bubble and not self.bubble_queue and \
                    self.state == 'idle' and random.random() < 0.0012:
                self.say(random.choice(LINES['idle']))     # 只写字，不出声
            if DEBUG:
                self._fps_count(now)
        except Exception:
            if DEBUG:
                raise
        self._tick_count += 1
        next_t = self._t0 + self._tick_count * (TICK_MS / 1000)
        delay = max(1, int((next_t - time.time()) * 1000))
        self.root.after(delay, self._tick)

    def _fps_count(self, now):
        if not hasattr(self, '_fps_t0'):
            self._fps_t0 = now; self._fps_n = 0
        self._fps_n += 1
        if now - self._fps_t0 >= 5:
            print(f'[fps] {self._fps_n / (now - self._fps_t0):5.1f}  state={self.state}', flush=True)
            self._fps_t0, self._fps_n = now, 0

    def _animate(self, now):
        """统一序列帧推进（dx/dy 由 _place 应用）。"""
        seq = self.player.seq_of(self.state, self.flip)
        if not seq:
            return
        hold = seq['holds'][min(self.frame, seq['n'] - 1)] / 1000.0
        if now - self.last_frame_at >= hold:
            self.last_frame_at = now
            mode = seq['mode']
            if mode == 'blink':
                if self.blink_active:
                    self.frame += 1
                    if self.frame >= seq['n'] - 1:
                        self.frame = 0
                        self.blink_active = False
                        self.blink_at = now + random.uniform(
                            BLINK_MIN_MS / 1000, BLINK_MAX_MS / 1000)
                else:
                    self.frame = 0
                    if now >= self.blink_at:
                        self.blink_active = True
                        self.frame = 1
            elif mode == 'pingpong':
                self._pp_dir = getattr(self, '_pp_dir', 1)
                self.frame += self._pp_dir
                if self.frame >= seq['n'] - 1:
                    self.frame = seq['n'] - 1
                    self._pp_dir = -1
                elif self.frame <= 0:
                    self.frame = 0
                    self._pp_dir = 1
            elif mode == 'once':
                if self.frame < seq['n'] - 1:
                    self.frame += 1
            else:  # loop
                self.frame = (self.frame + 1) % seq['n']
            self._refresh_base()
        self._place()

    # ---------------- 爱心粒子 ----------------
    def _heart_imgs(self):
        if getattr(self, '_hearts', None):
            return self._hearts
        s = max(11, int(26 * self.scale))
        imgs = []
        for k, ratio in enumerate((1.0, 0.8, 0.62)):
            im = Image.new('RGBA', (s + 10, s + 10), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            draw_heart(d, (s + 10) / 2, (s + 10) / 2, s * ratio,
                       (255, 120, 155, 255), (200, 70, 100, 255))
            imgs.append(to_photo(im, remap=False))
        self._hearts = imgs
        return imgs

    def _spawn_hearts(self, n):
        imgs = self._heart_imgs()
        ix, iy = self._item_pos()
        for _ in range(n):
            side = random.choice((-1, 1))
            item = self.canvas.create_image(
                ix + side * self.spr_w * random.uniform(0.24, 0.44),
                iy - self.spr_h * random.uniform(0.38, 0.62), image=imgs[0])
            self.particles.append({
                'item': item, 'imgs': imgs,
                'vx': side * random.uniform(6, 26), 'vy': random.uniform(-46, -30),
                'life': random.uniform(0.9, 1.3), 'age': 0.0})

    def _item_pos(self):
        return (self.sx - self.px, self.sy - self.py)

    def _update_particles(self):
        dt = TICK_MS / 1000.0
        for p in self.particles:
            p['age'] += dt
            c = self.canvas.coords(p['item'])
            self.canvas.coords(p['item'], c[0] + p['vx'] * dt, c[1] + p['vy'] * dt)
            p['vy'] += 14 * dt
            k = 0 if p['age'] < p['life'] * 0.45 else (1 if p['age'] < p['life'] * 0.75 else 2)
            if p.get('k') != k:
                p['k'] = k
                self.canvas.itemconfig(p['item'], image=p['imgs'][k])
        dead = [p for p in self.particles if p['age'] >= p['life']]
        for p in dead:
            self.canvas.delete(p['item'])
            self.particles.remove(p)

    # ---------------- Token 用量 HUD ----------------
    @staticmethod
    def _fmt_tokens(n):
        if n >= 1_000_000:
            return f'{n / 1e6:.1f}M'
        if n >= 1000:
            return f'{n / 1000:.1f}k'
        return str(int(n))

    @staticmethod
    def _fmt_compact(n):
        """紧凑格式（明细行，无小数）：134k / 1.2M"""
        if n >= 1_000_000:
            return f'{n / 1e6:.1f}M'.replace('.0M', 'M')
        if n >= 1000:
            return f'{round(n / 1000)}k'
        return str(int(n))

    def _start_usage(self):
        """启动用量采集线程（模型 I/O 记录）。"""
        if self.usage_tail:
            threading.Thread(target=self.usage_tail.run, daemon=True).start()

    def _handle_metrics(self, data):
        """累计一次用量上报并重算命中率/速率（只认当前数据源；跨天自动归零）。"""
        src = str(data.get('source') or 'hooks')
        if src == 'hook':          # 兼容旧版钩子脚本写的字段值
            src = 'hooks'
        if src != self.usage_source:
            return
        day = str(data.get('day') or self._metrics_day)
        with self._metrics_lock:
            if day != self._metrics_day:      # 跨天：面板从零开始记录新的一天
                self._metrics_day = day
                for k in self.metrics:
                    self.metrics[k] = 0
            m = self.metrics
            m['input_tokens'] += int(data.get('input_tokens', 0))
            m['output_tokens'] += int(data.get('output_tokens', 0))
            m['cache_read_tokens'] += int(data.get('cache_read_tokens', 0))
            m['cache_creation_tokens'] += int(data.get('cache_creation_tokens', 0))
            m['responses'] += 1
            denom = (m['cache_read_tokens'] + m['cache_creation_tokens'] +
                     m['input_tokens'])
            m['cache_hit_rate'] = (m['cache_read_tokens'] / denom) if denom else 0.0
            dur = int(data.get('duration_ms', 0))
            out = int(data.get('output_tokens', 0))
            if dur > 200 and out > 0:
                m['output_rate'] = out / (dur / 1000.0)
            elif 'output_rate' not in m:
                m['output_rate'] = 0.0
            m['last_update'] = time.time()
        self._metrics_dirty = True

    def _hud_should_show(self, now=None):
        now = now or time.time()
        if self.hud_mode == 'off':
            return False
        if self.hud_mode == 'on':
            return True
        return now < self.hud_until       # auto：点击后短暂显示

    def flash_hud(self, seconds=8.0):
        "点击宠物时短暂显示用量面板，随后自动隐藏。"
        if self.hud_mode == 'off':
            return
        self.hud_until = time.time() + seconds
        self._update_hud(force=True)
        if random.random() < 0.35:       # 看用量时即兴吐槽一句
            self.say(random.choice(LINES['token']))

    def set_hud_mode(self, mode):
        if mode not in ('auto', 'on', 'off'):
            mode = 'auto'
        self.hud_mode = mode
        self.cfg['hud_mode'] = mode
        save_config(self.cfg)
        self._update_hud(force=True)
        self._place_hud()

    def _render_hud(self):
        """渲染用量面板：蓝调毛玻璃三栏卡片 + 柔和外投影。

        色板呼应角色（白围裙 + 蓝花边 + 藏青描边）；2x 超采样 + alpha 阈值化，
        几何平滑且与颜色键画布合成零杂边。深浅壁纸上都清晰可辨。
        today 视图显示今天的三栏；7d/30d 视图切换到带迷你柱状图的历史面板。
        """
        if self.hud_view in ('7d', '30d'):
            return self._render_hud_range(int(self.hud_view[:-1]))
        s = self.scale
        SS = 2
        w = max(int(190 * s), round(self.spr_w * 0.98))
        h = self.hud_h - 12
        W, H = w * SS, h * SS
        M = 3 * SS                      # 投影边距
        m = self.metrics
        total = m.get('input_tokens', 0) + m.get('output_tokens', 0)
        hit = min(1.0, max(0.0, m.get('cache_hit_rate', 0.0)))
        resp = m.get('responses', 0)
        rate = m.get('output_rate', 0.0)

        im = Image.new('RGBA', (W + 2 * M, H + 2 * M), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        radius = max(8, int(12 * SS * s))
        # 柔和外投影（右下偏移，浅色壁纸上呈立体感）
        d.rounded_rectangle([M + SS * 2, M + SS * 3,
                             M + W + SS * 2 - 1, M + H + SS * 3 - 1],
                            radius=radius, fill=(203, 214, 232, 255))
        # 蓝调毛玻璃渐变 + 圆角遮罩
        mask = Image.new('L', (W + 2 * M, H + 2 * M), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [M, M, M + W - 1, M + H - 1], radius=radius, fill=255)
        for yy in range(H):
            t = yy / max(1, H - 1)
            d.line([(M, M + yy), (M + W, M + yy)],
                   fill=(int(242 - 9 * t), int(248 - 7 * t), int(255 - 3 * t), 255))
        im.putalpha(mask)
        d = ImageDraw.Draw(im)
        # 外框（蓝灰）+ 顶部内高光
        d.rounded_rectangle([M, M, M + W - 1, M + H - 1], radius=radius,
                            outline=(158, 190, 224, 255), width=max(2, SS))
        d.line([(M + radius + 2, M + max(2, SS + 1)),
                (M + W - radius - 2, M + max(2, SS + 1))],
               fill=(252, 254, 255, 255), width=max(1, SS))
        # 三栏 + 竖向分隔线
        pad_x = int(13 * SS * s)
        pad_y = int(7 * SS * s)
        col_w = (W - 2 * pad_x) // 3
        xs = [M + pad_x, M + pad_x + col_w, M + pad_x + 2 * col_w]
        for i in (1, 2):
            x = M + pad_x + col_w * i - int(7 * SS * s)
            d.line([(x, M + int(H * 0.26)), (x, M + int(H * 0.76))],
                   fill=(190, 208, 230, 255), width=max(1, SS // 2))
        f_lab = load_font(max(10, int(11.5 * SS * s)))
        f_val = load_font(max(13, int(16 * SS * s)), bold=True)
        f_min = load_font(max(9, int(10 * SS * s)))
        lab_h = int(14 * SS * s)
        val_h = int(21 * SS * s)
        min_h = int(13 * SS * s)
        top = M + max(pad_y, (H - (lab_h + val_h + min_h)) // 2)
        lab_y = top
        val_y = lab_y + lab_h
        min_y = val_y + val_h
        # 栏 1：今日 Token（大字，深藏青）+ 输入输出明细
        d.text((xs[0], lab_y), '今日 TOKEN', font=f_lab, fill=(126, 148, 182))
        d.text((xs[0], val_y), self._fmt_tokens(total), font=f_val, fill=(44, 70, 116))
        micro1 = (f'↑{self._fmt_compact(m.get("input_tokens", 0))} '
                  f'↓{self._fmt_compact(m.get("output_tokens", 0))}') \
            if resp > 0 else '等待用量数据…'
        d.text((xs[0], min_y), micro1, font=f_min, fill=(146, 166, 198))
        # 栏 2：缓存命中率（青绿）+ 迷你进度条
        d.text((xs[1], lab_y), '缓存命中', font=f_lab, fill=(126, 148, 182))
        d.text((xs[1], val_y), f'{hit * 100:.0f}%', font=f_val, fill=(26, 138, 126))
        bar_w = col_w - int(8 * SS * s)
        bar_h = max(4, int(5 * SS * s))
        by = val_y + val_h + (min_h - bar_h) // 2
        d.rounded_rectangle([xs[1], by, xs[1] + bar_w, by + bar_h],
                            radius=bar_h // 2, fill=(214, 226, 242, 255))
        if hit > 0.02:
            fw = max(bar_h, int(bar_w * hit))
            for xx in range(xs[1], xs[1] + fw):
                t = (xx - xs[1]) / max(1, fw - 1)
                col = (int(80 + 20 * t), int(178 + 22 * t), int(216 - 46 * t), 255)
                d.line([(xx, by), (xx, by + bar_h)], fill=col)
            d.rounded_rectangle([xs[1], by, xs[1] + fw, by + bar_h],
                                radius=bar_h // 2, outline=(214, 226, 242, 255))
        # 栏 3：响应次数（深藏青）+ 输出速率
        d.text((xs[2], lab_y), '响应', font=f_lab, fill=(126, 148, 182))
        d.text((xs[2], val_y), f'{resp} 次', font=f_val, fill=(44, 70, 116))
        if rate > 0:
            d.text((xs[2], min_y), f'{rate:.0f} t/s', font=f_min, fill=(146, 166, 198))
        # 下采样 + alpha 阈值化（零 fringe）
        im = im.resize((w + 6, h + 6), Image.LANCZOS)
        arr = np.asarray(im).copy()
        arr[..., 3] = np.where(arr[..., 3] >= 120, 255, 0)
        im = Image.fromarray(arr, 'RGBA')
        return to_photo(im, remap=False)

    @staticmethod
    def _aggregate(days, n):
        """聚合最近 n 天（含今天）的按天账本 → 合计/分项/逐日 token。"""
        base = datetime.date.today()
        dates = [(base - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
                 for i in range(n - 1, -1, -1)]
        out = {'input': 0, 'output': 0, 'cache_read': 0, 'responses': 0, 'per_day': []}
        for d in dates:
            v = days.get(d) or {}
            i_, o_ = int(v.get('input', 0)), int(v.get('output', 0))
            out['input'] += i_
            out['output'] += o_
            out['cache_read'] += int(v.get('cache_read', 0))
            out['responses'] += int(v.get('responses', 0))
            out['per_day'].append((d, i_ + o_))
        return out

    def _render_hud_range(self, n):
        """近 n 天用量面板：合计 / 迷你柱状图 / 日均·响应·命中率（与今日面板同尺寸）。"""
        s = self.scale
        SS = 2
        w = max(int(190 * s), round(self.spr_w * 0.98))
        h = self.hud_h - 12
        W, H = w * SS, h * SS
        M = 3 * SS
        days = self.usage_tail.days if self.usage_tail else {}
        agg = self._aggregate(days, n)
        total = agg['input'] + agg['output']
        denom = agg['cache_read'] + agg['input']
        hit = (agg['cache_read'] / denom) if denom else 0.0
        per_day = agg['per_day']
        avg = total / max(1, n)

        im = Image.new('RGBA', (W + 2 * M, H + 2 * M), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        radius = max(8, int(12 * SS * s))
        d.rounded_rectangle([M + SS * 2, M + SS * 3,
                             M + W + SS * 2 - 1, M + H + SS * 3 - 1],
                            radius=radius, fill=(203, 214, 232, 255))
        mask = Image.new('L', (W + 2 * M, H + 2 * M), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [M, M, M + W - 1, M + H - 1], radius=radius, fill=255)
        for yy in range(H):
            t = yy / max(1, H - 1)
            d.line([(M, M + yy), (M + W, M + yy)],
                   fill=(int(242 - 9 * t), int(248 - 7 * t), int(255 - 3 * t), 255))
        im.putalpha(mask)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([M, M, M + W - 1, M + H - 1], radius=radius,
                            outline=(158, 190, 224, 255), width=max(2, SS))
        f_lab = load_font(max(10, int(11.5 * SS * s)))
        f_val = load_font(max(12, int(14 * SS * s)), bold=True)
        f_min = load_font(max(9, int(10 * SS * s)))
        # 标题行：视图名 + 合计
        y0 = M + int(5 * SS * s)
        d.text((M + int(10 * SS * s), y0), f'近 {n} 天用量', font=f_lab,
               fill=(126, 148, 182))
        total_txt = f'合计 {self._fmt_tokens(total)} tok'
        tw = d.textlength(total_txt, font=f_val)
        d.text((M + W - int(10 * SS * s) - tw, y0 - int(2 * SS * s)), total_txt,
               font=f_val, fill=(44, 70, 116))
        # 迷你柱状图（今天用青绿高亮）
        bar_top = y0 + int(19 * SS * s)
        bar_h = int(15 * SS * s)
        bar_bot = bar_top + bar_h
        slot = (W - int(16 * SS * s)) / max(1, n)
        bw = max(2 * SS, int(slot * 0.62))
        today_key = time.strftime('%Y-%m-%d')
        peak = max([v for _, v in per_day] + [1])
        for i, (day, val) in enumerate(per_day):
            x = M + int(8 * SS * s) + int(i * slot) + int((slot - bw) / 2)
            bh = int(bar_h * (val / peak)) if val > 0 else max(1, SS)
            col = (26, 138, 126, 255) if day == today_key else (150, 176, 210, 255)
            d.rounded_rectangle([x, bar_bot - bh, x + bw, bar_bot],
                                radius=max(1, SS // 2), fill=col)
        # 底行：日均 / 响应 / 命中率
        fy = bar_bot + int(4 * SS * s)
        d.text((M + int(10 * SS * s), fy),
               f'日均 {self._fmt_tokens(avg)} · 响应 {agg["responses"]} 次',
               font=f_min, fill=(146, 166, 198))
        hit_txt = f'命中 {hit * 100:.0f}%'
        hw = d.textlength(hit_txt, font=f_min)
        d.text((M + W - int(10 * SS * s) - hw, fy), hit_txt, font=f_min,
               fill=(146, 166, 198))
        im = im.resize((w + 6, h + 6), Image.LANCZOS)
        arr = np.asarray(im).copy()
        arr[..., 3] = np.where(arr[..., 3] >= 120, 255, 0)
        im = Image.fromarray(arr, 'RGBA')
        return to_photo(im, remap=False)

    def set_hud_view(self, view):
        """切换用量面板视图（today/7d/30d），并立刻显示一下。"""
        self.hud_view = view if view in ('today', '7d', '30d') else 'today'
        try:
            self._hud_view_var.set(self.hud_view)
        except Exception:
            pass
        self.flash_hud()

    def _update_hud(self, force=False):
        """按需重建 HUD 图像；auto 模式到点自动隐藏。"""
        if not self._hud_should_show():
            if self._hud_shown and getattr(self, 'hud_item', None) is not None:
                self._hud_shown = False
                self.canvas.coords(self.hud_item, -9999, -9999)
            return
        if not force and not self._metrics_dirty and getattr(self, 'hud_item', None) is not None:
            self._hud_shown = True
            return
        self._hud_photo = self._render_hud()
        if getattr(self, 'hud_item', None) is None:
            self.hud_item = self.canvas.create_image(0, 0, image=self._hud_photo,
                                                     anchor='nw')
        else:
            self.canvas.itemconfig(self.hud_item, image=self._hud_photo)
        self._metrics_dirty = False
        self._hud_shown = True

    def _place_hud(self):
        """HUD 跟随角色底部居中。"""
        if getattr(self, 'hud_item', None) is None or not self._hud_shown:
            return
        ix, iy = self._item_pos()
        w = self._hud_photo.width()
        x = max(4, min(ix - w / 2, self.win_w - w - 4))
        y = min(iy + 8, self.win_h - self._hud_photo.height() - 4)
        self.canvas.coords(self.hud_item, x, y)

    # ---------------- 对话气泡 ----------------
    def _render_bubble(self, text):
        """渲染对话气泡：2x 超采样 + alpha 阈值化（文字平滑清晰，无杂边）。

        圆角矩形 + 指向角色的三角尾巴，配色与角色的白围裙/藏青描边一致。
        """
        if text in self._bubble_cache:
            return self._bubble_cache[text]
        s = self.scale
        SS = 2
        fs = max(11, min(24, int(self.spr_w / 15)))
        font = load_font(fs)
        fss = fs * SS
        font2 = load_font(fss)
        pad = int(9 * s) + 6
        max_w = int(self.spr_w * 1.05)
        lines, cur = [], ''
        NO_LINE_START = '。，、！？；：）】》」』…～!?,.;:)'
        for ch in text:
            if ch == '\n':
                lines.append(cur); cur = ''
                continue
            if font.getlength(cur + ch) > max_w and cur:
                if ch in NO_LINE_START:
                    cur += ch          # 避头尾：标点跟随上一行
                else:
                    lines.append(cur); cur = ch
            else:
                cur += ch
        if cur:
            lines.append(cur)
        lh = int(fs * 1.42)
        tw = max(font.getlength(ln) for ln in lines)
        th = lh * len(lines)
        w = int(tw) + pad * 2
        h = th + pad * 2
        tail_w = int(11 * s) + 6
        PAD = 4 * SS                     # 画布留白（容纳描边与尾巴）
        W = (w + 8) * SS
        H = (h + tail_w + 8) * SS
        im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        x0, y0 = PAD, PAD
        x1, y1 = PAD + w * SS, PAD + h * SS
        rad = (int(8 * s) + 5) * SS
        bw = max(2, 3 * SS)
        # 主体
        d.rounded_rectangle([x0, y0, x1, y1], radius=rad,
                            fill=(255, 255, 255, 255), outline=NAVY, width=bw)
        # 尾巴（指向角色头部）
        cx = PAD + (w // 2) * SS
        tws = tail_w * SS
        ty0 = y1 - bw // 2
        ty1 = y1 + tws
        d.polygon([(cx - tws // 2, ty0), (cx + tws // 2, ty0), (cx, ty1)],
                  fill=(255, 255, 255, 255), outline=NAVY)
        # 尾根与主体之间的开口用白线缝合，形成连续的尾巴
        d.line([(cx - tws // 2 + bw, ty0), (cx + bw // 2, ty1 - bw)],
               fill=(255, 255, 255, 255), width=bw)
        d.line([(cx + tws // 2 - bw, ty0), (cx - bw // 2, ty1 - bw)],
               fill=(255, 255, 255, 255), width=bw)
        # 文本
        for i, ln in enumerate(lines):
            d.text((PAD + (pad + 2) * SS,
                    PAD + (pad + i * lh + (lh - fs) // 2 - 1) * SS),
                   ln, font=font2, fill=INK)
        # 下采样 + alpha 阈值化（零 fringe）
        im = im.resize((w + 8, h + tail_w + 8), Image.LANCZOS)
        arr = np.asarray(im).copy()
        arr[..., 3] = np.where(arr[..., 3] >= 128, 255, 0)
        im = Image.fromarray(arr, 'RGBA')
        photo = to_photo(im, remap=False)
        self._bubble_cache[text] = photo
        return photo

    def say(self, text, duration=None):
        if not text:
            return
        self.bubble_queue.append((text, duration))
        if not self.bubble:
            self._next_bubble()

    def _next_bubble(self):
        if not self.bubble_queue:
            self.bubble = None
            if getattr(self, 'bubble_item', None) is not None:
                self.canvas.coords(self.bubble_item, -9999, -9999)
            return
        text, dur = self.bubble_queue.pop(0)
        photo = self._render_bubble(text)
        self._ensure_bubble_room()
        bw, bh = photo.width(), photo.height()
        ix, iy = self._item_pos()
        bx = max(BUBBLE_MARGIN, min(ix - bw / 2, self.win_w - bw - BUBBLE_MARGIN))
        by = max(4, iy - round(0.88 * self.spr_h) - bh)
        if getattr(self, 'bubble_item', None) is None:
            self.bubble_item = self.canvas.create_image(bx + bw / 2, by + bh / 2, image=photo)
        else:
            self.canvas.itemconfig(self.bubble_item, image=photo)
            self.canvas.coords(self.bubble_item, bx + bw / 2, by + bh / 2)
        self._bubble_photo = photo
        self.bubble = {'until': time.time() + (dur or random.uniform(2.6, 3.8)),
                       'w': bw, 'h': bh}

    def _ensure_bubble_room(self):
        """显示气泡前保证头顶有空间：仅下移窗口使角色回到活动范围上沿。"""
        ix, iy = self._item_pos()
        if iy > self.iy_lo:
            self.py += iy - self.iy_lo   # 窗口下移 → 角色在窗口内上移，屏幕位置不变
            self._move_window_raw(self.px, self.py)
            self._place()

    # ---------------- 窗口移动 ----------------
    def _move_window_raw(self, x, y):
        """整体平移窗口（漫游视口下仅在角色越界时调用，频率很低）。"""
        self.px, self.py = int(x), int(y)
        self.root.geometry(f'+{self.px}+{self.py}')

    def _move_window(self, x, y):
        """移动角色屏幕位置（漫游视口会自动处理窗口跟随）。"""
        self.sx, self.sy = float(x), float(y)
        self._place()

    def _clamp_and_save(self):
        sw = ctypes.windll.user32.GetSystemMetrics(78)
        sh = ctypes.windll.user32.GetSystemMetrics(79)
        ox = ctypes.windll.user32.GetSystemMetrics(76)
        oy = ctypes.windll.user32.GetSystemMetrics(77)
        self.sx = max(ox + self.spr_w / 2, min(self.sx, ox + sw - self.spr_w / 2))
        self.sy = max(oy + self.spr_h, min(self.sy, oy + sh - 8))
        self._place()
        self.cfg['x'] = int(self.px)
        self.cfg['y'] = int(self.py)
        save_config(self.cfg)

    # ---------------- 托盘 ----------------
    def _start_tray(self):
        try:
            import pystray
            icon_img = Image.open(os.path.join(ASSETS, 'tray.ico'))

            def cmd(v):
                return lambda: self.cmd_queue.put(v)

            menu = pystray.Menu(
                pystray.MenuItem('打招呼', cmd('hello')),
                pystray.MenuItem('投喂', cmd('feed')),
                pystray.MenuItem('玩耍', cmd('play')),
                pystray.MenuItem('哄她睡觉', cmd('sleep_now')),
                pystray.MenuItem('转圈圈', cmd('spin')),
                pystray.MenuItem('摇头晃脑', cmd('headshake')),
                pystray.MenuItem('隐藏', cmd('hide')),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('用量面板', pystray.Menu(
                    pystray.MenuItem('点击时显示', cmd(('hud_mode', 'auto')),
                                     checked=lambda i: self.hud_mode == 'auto'),
                    pystray.MenuItem('始终显示', cmd(('hud_mode', 'on')),
                                     checked=lambda i: self.hud_mode == 'on'),
                    pystray.MenuItem('关闭', cmd(('hud_mode', 'off')),
                                     checked=lambda i: self.hud_mode == 'off'))),
                pystray.MenuItem('用量统计', pystray.Menu(
                    pystray.MenuItem('今日', cmd(('hud_view', 'today')), radio=True,
                                     checked=lambda i: self.hud_view == 'today'),
                    pystray.MenuItem('近 7 天', cmd(('hud_view', '7d')), radio=True,
                                     checked=lambda i: self.hud_view == '7d'),
                    pystray.MenuItem('近 30 天', cmd(('hud_view', '30d')), radio=True,
                                     checked=lambda i: self.hud_view == '30d'))),
                pystray.MenuItem('置顶窗口', cmd('topmost'),
                                 checked=lambda i: bool(self.cfg.get('topmost'))),
                pystray.MenuItem('音效', cmd('sound'),
                                 checked=lambda i: self.sound.enabled),
                pystray.MenuItem('皮肤', pystray.Menu(
                    pystray.MenuItem('立体圆润', cmd(('skin', 'puffy')), radio=True,
                                     checked=lambda i: self.skin == 'puffy'),
                    pystray.MenuItem('原版平面', cmd(('skin', 'flat')), radio=True,
                                     checked=lambda i: self.skin == 'flat'))),
                pystray.MenuItem('音量', pystray.Menu(
                    *(pystray.MenuItem(k, cmd(('sound_volume', v)),
                                       checked=lambda i, v=v: abs(self.sound.volume - v) < 1e-6)
                      for k, v in VOLUMES.items()))),
                pystray.MenuItem('工作中碎碎念', cmd('sound_chatter'),
                                 checked=lambda i: bool(self.cfg.get('sound_chatter'))),
                pystray.MenuItem('大小', pystray.Menu(
                    *(pystray.MenuItem(k, cmd(('scale', v)),
                                       checked=lambda i, v=v: abs(self.scale - v) < 1e-6)
                      for k, v in SCALES.items()))),
                pystray.MenuItem('透明度', pystray.Menu(
                    *(pystray.MenuItem(k, cmd(('alpha', v)),
                                       checked=lambda i, v=v: abs(float(self.cfg.get('alpha', 1.0)) - v) < 1e-6)
                      for k, v in ALPHAS.items()))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('退出', cmd('quit')),
            )
            self.tray = pystray.Icon('whale_girl', icon_img, '鲸鱼娘桌宠', menu)
            self.tray.run_detached()
        except Exception:
            self.tray = None

    # ---------------- Agent 桥 ----------------
    def _start_bridge(self):
        if not self.cfg.get('bridge_enabled', True):
            return
        try:
            port = int(self.cfg.get('bridge_port', BRIDGE_PORT_DEFAULT))
            token = secrets.token_hex(16)
            with open(TOKEN_PATH, 'w') as f:
                f.write(token)
            self.bridge = BridgeServer(self, port, token)
            if DEBUG:
                print(f'[bridge] http://127.0.0.1:{port}  (token -> assets/bridge_token)', flush=True)
        except Exception as e:
            print(f'[bridge] {e}', flush=True)
            self.bridge = None

    def _handle_agent(self, etype, text, ms, value=None):
        """处理 Agent 桥事件。"""
        try:
            if etype == 'say':
                self.say(text or '…')
            elif etype == 'hide':
                self.tray_hide()
            elif etype == 'show':
                if self.hidden:
                    self.tray_hide()
            elif etype == 'quit':
                self.quit()
            elif etype == 'pat':
                self._interact()
                self._set_state('joy', JOY_MS / 1000)
                self._spawn_hearts(3)
                self.jelly(0.34)
                if not self._voice('pet'):
                    self.say(random.choice(LINES['pet']))
            elif etype in ('feed', 'play'):
                self._interact()
                self._set_state(etype, TRANSIENT_MS / 1000)
                self.jelly(0.34)
                if not self._voice(etype):
                    self.say(random.choice(LINES[etype]))
            elif etype == 'idle':
                self._interact()
                self._set_state('idle')
            elif etype == 'sleep':
                self._go_sleep()
            elif etype in ('spin', 'headshake', 'sway', 'hop', 'nod', 'trick'):
                self._interact()
                if etype == 'trick':
                    self._do_random_trick()
                else:
                    self._do_trick(etype)
            elif etype == 'hud_on':
                self.set_hud_mode('on')
            elif etype == 'hud_off':
                self.set_hud_mode('off')
            elif etype == 'hud_auto':
                self.set_hud_mode('auto')
            elif etype == 'hud':
                self.flash_hud()
            elif etype == 'sound_on':
                self.set_sound(True)
            elif etype == 'sound_off':
                self.set_sound(False)
            elif etype == 'sound_volume' and value is not None:
                self.set_volume(value)
            elif etype == 'skin':
                self.set_skin(text if text in ('puffy', 'flat')
                              else ('flat' if self.skin == 'puffy' else 'puffy'))
            elif etype in AGENT_STATE_MS:
                self._interact()
                dur = (ms or AGENT_STATE_MS[etype]) / 1000.0
                self._set_state(etype, dur)
                if etype in ('think', 'wait', 'working'):
                    # 思考/工作的碎碎念默认关（sound_chatter），免得你没点她也一直念叨；
                    # 等待批准是关键时刻，始终出声
                    chatter = etype == 'wait' or bool(self.cfg.get('sound_chatter'))
                    if not (chatter and self._voice(etype)) and random.random() < 0.6:
                        pool = LINES[f'agent_{etype}']
                        if etype == 'think' and random.random() < 0.4:
                            pool = LINES['think_line']
                        elif etype == 'working' and random.random() < 0.4:
                            pool = LINES['work']
                        self.say(random.choice(pool))
            elif etype in ('welcome', 'celebrate'):
                self._interact()
                self._set_state(etype, (ms or (WELCOME_MS if etype == 'welcome' else CELEBRATE_MS)) / 1000)
                if text:                  # Agent 自带台词：只改气泡，不出声
                    self.say(text)
                elif not self._voice(etype):
                    self.say(random.choice(LINES[etype]))
                if etype == 'celebrate':
                    self._spawn_hearts(2)
                    self.jelly(0.5)
            elif etype in ('error', 'disappointed'):
                self._set_state(etype, (ms or (ERROR_MS if etype == 'error' else DISAPPOINTED_MS)) / 1000)
                if text:
                    self.say(text)
                elif not self._voice(etype):
                    self.say(random.choice(LINES[etype]))
        except Exception as e:
            if DEBUG:
                print(f'[agent] {etype} 处理失败: {e}', flush=True)

    # ---------------- 命令处理 ----------------
    def _process_commands(self):
        while True:
            try:
                cmd = self.cmd_queue.get_nowait()
            except queue.Empty:
                return
            if cmd == 'quit':
                self.quit()
            elif cmd == 'hello':
                self._interact()
                self._set_state('welcome', WELCOME_MS / 1000)
                if not self._voice('welcome'):
                    self.say(random.choice(LINES['hello']))
                self._spawn_hearts(2)
            elif cmd == 'feed':
                self._interact()
                self._set_state('eat', TRANSIENT_MS / 1000)
                self.jelly(0.34)
                if not self._voice('feed'):
                    self.say(random.choice(LINES['feed']))
            elif cmd == 'play':
                self._interact()
                self._set_state('play', TRANSIENT_MS / 1000)
                self.jelly(0.36)
                if not self._voice('play'):
                    self.say(random.choice(LINES['play']))
            elif cmd in ('spin', 'headshake', 'sway', 'hop', 'nod', 'trick'):
                self._interact()
                if cmd == 'trick':
                    self._do_random_trick()
                else:
                    self._do_trick(cmd)
            elif cmd == 'hide':
                self.tray_hide()
            elif cmd == 'topmost':
                self.set_topmost(not bool(self.cfg.get('topmost')))
            elif cmd == 'sound':
                self.set_sound(not self.sound.enabled)
            elif cmd == 'sound_chatter':
                self.set_sound_chatter(not bool(self.cfg.get('sound_chatter')))
            elif cmd == 'skin':
                self.set_skin('flat' if self.skin == 'puffy' else 'puffy')
            elif cmd == 'sleep_now':
                self._go_sleep()
            elif cmd == 'hud_toggle':
                self.set_hud_mode('on' if self.hud_mode == 'off' else
                                  ('off' if self.hud_mode == 'on' else 'on'))
            elif isinstance(cmd, tuple):
                if cmd[0] == 'agent':
                    self._handle_agent(*cmd[1:])
                elif cmd[0] == 'metrics':
                    self._handle_metrics(cmd[1])
                else:
                    kind, val = cmd
                    if kind == 'scale':
                        self.set_scale(val)
                    elif kind == 'alpha':
                        self.set_alpha(val)
                    elif kind == 'hud_mode':
                        self.set_hud_mode(val)
                    elif kind == 'hud_view':
                        self.set_hud_view(val)
                    elif kind == 'skin':
                        self.set_skin(val)
                    elif kind == 'sound_volume':
                        self.set_volume(val)

    def _go_sleep(self):
        """菜单主动哄睡（用户触发，才会出声）。"""
        self.idle_since = time.time() - SLEEP_AFTER_MS / 1000
        self._set_state('sleep')
        self.sleeping_anim = True
        if not self._voice('sleep'):
            self.say(random.choice(LINES['sleep']))

    def toggle_sound(self):
        self.set_sound(bool(self._sound_var.get()))

    def set_sound_chatter(self, val):
        self.cfg['sound_chatter'] = bool(val)
        save_config(self.cfg)

    def set_volume_choice(self):
        self.set_volume(float(self._vol_var.get()))

    def set_volume(self, val):
        """设置音效音量（0~1）：立即生效，并试听一声。"""
        val = max(0.0, min(1.0, float(val)))
        self.sound.volume = val
        self.cfg['sound_volume'] = val
        save_config(self.cfg)
        self._vol_var.set(val)
        if val > 0 and not self.sound.enabled:
            self.set_sound(True)
        else:
            self.sound.play_any(('coquetry10', 'coquetry3'))

    def set_sound(self, val):
        self.sound.enabled = bool(val)
        self.cfg['sound'] = bool(val)
        save_config(self.cfg)
        self._sound_var.set(bool(val))
        if val:
            self.sound.play_any(('coquetry10', 'coquetry3'))

    def tray_hide(self):
        if self.hidden:
            self.hidden = False
            self._move_window(self.saved_pos[0], self.saved_pos[1])
            self.say(random.choice(LINES['hello']))
            self._voice('show')
        else:
            self.saved_pos = (self.sx, self.sy)
            self.hidden = True
            self._move_window(-6000, -6000)

    def _rebuild_sprites(self):
        """换皮肤/尺寸后重建精灵：清掉画布上的旧图，下一 tick 自动重画。"""
        self.player = SpritePlayer(self.scale, self.skin)
        self._hearts = None
        self.canvas.delete('all')
        self.base_item = None
        self.bubble_item = None
        self.hud_item = None
        self._metrics_dirty = True
        self.particles.clear()
        self.bubble = None
        self.bubble_queue.clear()
        self._refresh_base()
        self._place()

    def set_skin(self, skin):
        """切换皮肤（puffy=立体圆润 / flat=原版平面）。"""
        skin = skin if skin in ('puffy', 'flat') else 'puffy'
        if skin == self.skin and self.player.sheets_dir == (
                SHEETS_PUFFY if skin == 'puffy' else SHEETS_DIR):
            return
        self.skin = skin
        self.cfg['skin'] = skin
        save_config(self.cfg)
        self._rebuild_sprites()
        self.say('换上新皮肤啦，肉嘟嘟的！' if skin == 'puffy' else '换回原版平面啦～')

    def set_scale(self, val):
        if abs(self.scale - val) < 1e-6:
            return
        old_ax, old_ay = self.anchor_x, self.anchor_y
        self.scale = val
        self.cfg['scale'] = val
        save_config(self.cfg)
        self._compute_layout()
        self._rebuild_sprites()
        self.sx += self.anchor_x - old_ax
        self.sy += self.anchor_y - old_ay
        self.root.geometry(f'{self.win_w}x{self.win_h}+{self.px}+{self.py}')
        self.canvas.config(width=self.win_w, height=self.win_h)
        self.bubble_queue.clear()
        self._refresh_base()
        self._place()
        self.say('换了个新造型！')

    def set_alpha(self, val):
        self.cfg['alpha'] = val
        save_config(self.cfg)
        self.root.attributes('-alpha', val)

    def set_topmost(self, val):
        self.cfg['topmost'] = val
        save_config(self.cfg)
        self.root.attributes('-topmost', bool(val))

    def _welcome(self):
        self._set_state('welcome', WELCOME_MS / 1000)
        self.sound.play_any(('coquetry10', 'coquetry3'))
        hour = time.localtime().tm_hour
        key = 'welcome' if (hour >= 18 or hour < 11) else 'hello'
        self.root.after(500, lambda: self.say(random.choice(LINES[key])))

    # ---------------- 退出 ----------------
    def quit(self):
        self.cfg['x'] = int(self.px)
        self.cfg['y'] = int(self.py)
        self.cfg['scale'] = self.scale
        save_config(self.cfg)
        if self.usage_tail:
            try:
                self.usage_tail.save()      # 累计用量落盘，重启不丢
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        os._exit(0)

    def run(self):
        self.root.mainloop()


def main():
    app = PetApp()
    app.run()


if __name__ == '__main__':
    main()
