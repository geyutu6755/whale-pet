#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鲸鱼娘桌宠 · 统一管理器 —— 安装 / 卸载 / 状态 / 启停（一个入口管所有 Agent）

    python manage.py                      查看状态与用法
    python manage.py status               总览：桌宠进程 + 各 Agent 安装情况
    python manage.py install zcode        装到 ZCode（原生插件）
    python manage.py install claude       装到 Claude Code（原生插件）
    python manage.py install codex        装到 Codex（注册 MCP 服务器）
    python manage.py install mcp          生成通用 MCP 配置（Cursor/Windsurf/Cline…）
    python manage.py install all          一次装到所有可用 Agent
    python manage.py uninstall zcode      从 ZCode 卸载（默认连市场一起清掉）
    python manage.py uninstall all --purge
                                          全部卸载 + 清掉本地产物（配置/token/缓存）
    python manage.py start | stop | restart | sound
                                          启停桌宠 / 试听音效

设计约定：
  - 卸载即除净：先停桌宠 → 再摘注册 → 再（可选）清本地产物，不留孤儿条目
  - 修改任何 Agent 配置文件前先备份为 *.whale-bak
  - 只操作名字带 whale-pet 的条目，绝不触碰别人的配置
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(PLUGIN_DIR))
PET_DIR = os.path.join(PLUGIN_DIR, 'pet')
PET_SCRIPT = os.path.join(PET_DIR, 'whale_pet.py')
MCP_SCRIPT = os.path.join(PLUGIN_DIR, 'mcp', 'whale_pet_mcp.py')
CONFIG_PATH = os.path.join(PET_DIR, 'pet_config.json')
TOKEN_PATH = os.path.join(PET_DIR, 'assets', 'bridge_token')

NAME = 'whale-pet'
MARKET = 'whale-pet-market'
GITHUB_REPO = 'geyutu6755/whale-pet'
HOME = os.path.expanduser('~')

OK, NO, DASH = '[√]', '[×]', '[-]'


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def run(cmd, timeout=180):
    """执行外部命令，返回 (返回码, 合并输出)。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding='utf-8', errors='replace')
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except Exception as e:
        return 1, str(e)


def which(name):
    return shutil.which(name)


def backup(path):
    if os.path.exists(path):
        try:
            shutil.copy2(path, path + '.whale-bak')
            return True
        except Exception:
            return False
    return False


def version():
    for sub in ('.zcode-plugin', '.claude-plugin'):
        try:
            with open(os.path.join(PLUGIN_DIR, sub, 'plugin.json'), encoding='utf-8') as f:
                return json.load(f).get('version', '?')
        except Exception:
            pass
    return '?'


def native_python():
    """stdio/子进程用的 python.exe（避免 pythonw 无控制台带来的边缘问题）。"""
    exe = sys.executable
    if exe.lower().endswith('pythonw.exe'):
        cand = exe[:-len('pythonw.exe')] + 'python.exe'
        if os.path.exists(cand):
            return cand
    return exe


def market_source(from_github=False):
    if not from_github and os.path.exists(os.path.join(REPO_DIR, 'marketplace.json')):
        return REPO_DIR, 'directory'
    return GITHUB_REPO, 'github'


# --------------------------------------------------------------------------
# 桌宠进程（本地桥 127.0.0.1:<port> + X-Token）
# --------------------------------------------------------------------------
def _bridge_of(pet_dir):
    """某份安装副本（本地仓库 / 插件缓存…）的桥端口与 token。"""
    port, token = 37821, ''
    try:
        with open(os.path.join(pet_dir, 'pet_config.json'), encoding='utf-8') as f:
            port = int(json.load(f).get('bridge_port', 37821))
    except Exception:
        pass
    try:
        with open(os.path.join(pet_dir, 'assets', 'bridge_token')) as f:
            token = f.read().strip()
    except Exception:
        pass
    return port, token


def _bridge():
    return _bridge_of(PET_DIR)


def pet_state(timeout=1.0):
    port, token = _bridge()
    req = urllib.request.Request(f'http://127.0.0.1:{port}/state',
                                 headers={'X-Token': token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def pet_running():
    """本安装副本的桥是否可达（桌面宠物全局单实例，可能属于别的副本）。"""
    try:
        pet_state()
        return True
    except Exception:
        return False


def pet_processes():
    """所有正在运行的桌宠进程 [(pid, pet_dir)] —— 跨安装副本都能管。"""
    if os.name != 'nt':
        return []
    # 先强制 PowerShell 用 UTF-8 输出：否则中文路径（如 E:\ai测试\…）会乱码，
    # 拿不到正确目录就读不到该副本的 token，只能退化成强杀
    ps = ('[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; '
          'Get-CimInstance Win32_Process -Filter "Name like \'python%\'" | '
          "Where-Object { $_.CommandLine -like '*whale_pet.py*' } | "
          "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }")
    rc, out = run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                   '-Command', ps], timeout=30)
    procs = []
    for line in out.splitlines():
        if '|' not in line:
            continue
        pid, cmdline = line.split('|', 1)
        # 路径可能带引号（含空格）也可能裸写；取真正以 whale_pet.py 结尾的那一段
        cands = re.findall(r'"([^"]*whale_pet\.py)"', cmdline) + \
            re.findall(r'([A-Za-z]:\\[^\s"]*whale_pet\.py)', cmdline)
        if cands:
            script = cands[0].strip().strip('"')
            procs.append((pid.strip(), os.path.dirname(script)))
    return procs


def _kill_pet_processes():
    """兜底强杀：按命令行匹配 whale_pet.py（只匹配这一个脚本名）。"""
    if os.name != 'nt':
        return
    ps = ('Get-CimInstance Win32_Process | Where-Object '
          "{ $_.CommandLine -like '*whale_pet.py*' } | "
          'ForEach-Object { Stop-Process -Id $_.ProcessId -Force }')
    run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
        timeout=30)


def start_pet(wait=12.0):
    if pet_running():
        return True, '桌宠已在运行'
    others = pet_processes()
    if others:
        return True, f'已有桌宠在运行（另一安装副本：{others[0][1]}）'
    if not os.path.exists(PET_SCRIPT):
        return False, f'缺少 {PET_SCRIPT}'
    flags = 0
    if os.name == 'nt':
        flags = 0x00000008 | 0x00000200        # DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen([native_python(), PET_SCRIPT], cwd=PET_DIR,
                         creationflags=flags, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
    except Exception as e:
        return False, f'启动失败: {e}'
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(0.25)
        if pet_running():
            return True, f'已启动（{time.time() - t0:.1f}s）'
    return False, '启动超时（可手动运行 pet/whale_pet.py 看报错）'


def _quit_via(pet_dir):
    """按指定安装副本自己的端口/token 发送 quit（跨副本也能优雅停止）。"""
    port, token = _bridge_of(pet_dir)
    data = json.dumps({'type': 'quit'}).encode('utf-8')
    req = urllib.request.Request(f'http://127.0.0.1:{port}/event', data=data,
                                 headers={'Content-Type': 'application/json',
                                          'X-Token': token}, method='POST')
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass


def stop_pet():
    procs = pet_processes()
    if not procs:
        return '桌宠本来就没在运行'
    for _, pdir in procs:
        _quit_via(pdir)
    for _ in range(8):                  # 每次探测都要起一次 PowerShell，别太密
        time.sleep(0.3)
        if not pet_processes():
            return '桌宠已优雅退出'
    _kill_pet_processes()
    time.sleep(0.4)
    return ('桌宠已退出（强杀）' if not pet_processes()
            else '桌宠未能退出，请手动结束进程')


def purge_state():
    """清掉本地产物（不含仓库/插件本体）。"""
    removed = []
    for p in (CONFIG_PATH, TOKEN_PATH):
        if os.path.exists(p):
            try:
                os.remove(p)
                removed.append(os.path.relpath(p, PLUGIN_DIR))
            except Exception:
                pass
    for root, dirs, _ in os.walk(PLUGIN_DIR):
        for d in list(dirs):
            if d == '__pycache__':
                try:
                    shutil.rmtree(os.path.join(root, d))
                    removed.append(os.path.relpath(os.path.join(root, d), PLUGIN_DIR))
                except Exception:
                    pass
                dirs.remove(d)
    return removed


# --------------------------------------------------------------------------
# Agent 适配层
# --------------------------------------------------------------------------
def find_zcode_cli():
    """定位 ZCode 内置 CLI（zcode.cjs）与其运行方式。"""
    cands = [os.environ.get('ZCODE_CLI', '')]
    for root in (os.environ.get('ZCode_DIR', ''), r'E:\ZCode',
                 os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'ZCode')):
        if root:
            cands.append(os.path.join(root, 'resources', 'glm', 'zcode.cjs'))
    for c in cands:
        if c and os.path.exists(c):
            node = which('node')
            return ([node, c] if node else None), c
    return None, ''


class ZCode:
    label = 'ZCode'

    def available(self):
        cmd, path = find_zcode_cli()
        return bool(cmd), (path or '未找到 zcode.cjs（可设 ZCODE_CLI 环境变量）')

    def _cli(self):
        cmd, _ = find_zcode_cli()
        return cmd

    def _marketplaces(self):
        try:
            with open(os.path.join(HOME, '.zcode', 'cli', 'plugins',
                                   'known_marketplaces.json'), encoding='utf-8') as f:
                return json.load(f).get('marketplaces', [])
        except Exception:
            return []

    def _enabled(self):
        try:
            with open(os.path.join(HOME, '.zcode', 'cli', 'config.json'),
                      encoding='utf-8') as f:
                return json.load(f).get('plugins', {}).get('enabledPlugins', {})
        except Exception:
            return {}

    def status(self):
        cli, path = find_zcode_cli()
        if not cli:
            return DASH, f'未找到 ZCode CLI（{path}）'
        markets = [m for m in self._marketplaces() if m.get('id') == MARKET]
        installed = f'{NAME}@{MARKET}' in self._enabled()
        if not markets and not installed:
            return DASH, '未安装'
        src = ''
        if markets:
            s = markets[0].get('source', {})
            src = s.get('path') or s.get('repo') or s.get('url') or '?'
        return (OK if installed else NO,
                f'插件{"已装" if installed else "未启用"}，市场源 {src}，'
                f'本地版本 v{version()}')

    def install(self, from_github=False):
        cli, _ = find_zcode_cli()
        if not cli:
            return False, '未找到 ZCode CLI，无法自动安装'
        src, kind = market_source(from_github)
        markets = [m for m in self._marketplaces() if m.get('id') == MARKET]
        if markets:
            cur = markets[0].get('source', {})
            cur = cur.get('path') or cur.get('repo') or ''
            if os.path.normcase(str(cur)) != os.path.normcase(str(src)):
                run(cli + ['plugins', 'marketplace', 'remove', MARKET])
                markets = []
        if not markets:
            rc, out = run(cli + ['plugins', 'marketplace', 'add', src])
            if rc != 0:
                return False, f'添加市场失败：{out.strip()[:200]}'
        if f'{NAME}@{MARKET}' in self._enabled():      # 已装：install 语义升级为 update
            rc, out = run(cli + ['plugins', 'update', NAME])
            return rc == 0, ('已装到 ZCode，且已是最新'
                             if rc == 0 else f'更新失败：{out.strip()[:160]}')
        rc, out = run(cli + ['plugins', 'install', f'{NAME}@{MARKET}'])
        if rc != 0:
            return False, f'安装失败：{out.strip()[:200]}'
        return True, f'已装到 ZCode（源 {src}，v{version()}）——重启 ZCode 生效'

    def uninstall(self, keep_market=False):
        cli, _ = find_zcode_cli()
        if not cli:
            return False, '未找到 ZCode CLI，无法自动卸载'
        msgs = []
        rc, out = run(cli + ['plugins', 'uninstall', NAME])
        msgs.append('插件已卸载' if rc == 0 else f'插件卸载：{out.strip()[:120]}')
        if not keep_market:
            rc, out = run(cli + ['plugins', 'marketplace', 'remove', MARKET])
            msgs.append('市场已移除' if rc == 0 else f'市场移除：{out.strip()[:120]}')
        return True, '；'.join(msgs) + '——重启 ZCode 生效'


class Claude:
    label = 'Claude Code'

    @staticmethod
    def _exe():
        # Windows 上 subprocess 不按 PATHEXT 解析，必须用 which 出来的全路径
        return which('claude')

    def available(self):
        return bool(self._exe()), '未检测到 claude 命令'

    def status(self):
        if not self._exe():
            return DASH, '未检测到 Claude Code CLI（装了会自动识别）'
        rc, out = run([self._exe(), 'plugin', 'list'], timeout=60)
        hit = NAME in out
        return (OK if hit else DASH), ('已安装' if hit else '未安装')

    def install(self, from_github=False):
        exe = self._exe()
        if not exe:
            src, _ = market_source(from_github)
            return False, ('未检测到 claude 命令。可手动执行：\n'
                           f'      claude plugin marketplace add {src}\n'
                           f'      claude plugin install {NAME}@{MARKET}')
        src, _ = market_source(from_github)
        run([exe, 'plugin', 'marketplace', 'add', src])
        rc, out = run([exe, 'plugin', 'install', f'{NAME}@{MARKET}'])
        return rc == 0, (f'已装到 Claude Code（v{version()}）' if rc == 0
                         else f'安装失败：{out.strip()[:200]}')

    def uninstall(self, keep_market=False):
        exe = self._exe()
        if not exe:
            return False, '未检测到 claude 命令，无需卸载'
        rc, out = run([exe, 'plugin', 'uninstall', NAME])
        if not keep_market:
            run([exe, 'plugin', 'marketplace', 'remove', MARKET])
        return rc == 0, ('已从 Claude Code 卸载' if rc == 0
                         else f'卸载：{out.strip()[:150]}')


class Codex:
    label = 'Codex'

    @staticmethod
    def _exe():
        return which('codex')          # 同上：必须全路径，Windows 才找得到

    def available(self):
        return bool(self._exe()), '未检测到 codex 命令'

    def status(self):
        if not self._exe():
            return DASH, '未检测到 codex 命令'
        rc, out = run([self._exe(), 'mcp', 'get', NAME], timeout=60)
        if rc != 0:
            return DASH, 'MCP 未注册'
        return (OK if MCP_SCRIPT.replace('/', os.sep) in out.replace('/', os.sep)
                else NO), 'MCP 已注册' + ('' if MCP_SCRIPT in out else '（路径与当前不同）')

    def install(self, *_):
        exe = self._exe()
        if not exe:
            return False, ('未检测到 codex 命令。可手动在 ~/.codex/config.toml 添加：\n'
                           '      [mcp_servers.whale-pet]\n'
                           f'      command = "{native_python()}"\n'
                           f'      args = ["{MCP_SCRIPT}"]')
        backup(os.path.join(HOME, '.codex', 'config.toml'))
        rc, out = run([exe, 'mcp', 'get', NAME], timeout=60)
        if rc == 0 and MCP_SCRIPT.replace('/', os.sep) in out.replace('/', os.sep):
            return True, 'MCP 已注册（跳过）'
        if rc == 0:
            run([exe, 'mcp', 'remove', NAME], timeout=60)
        rc, out = run([exe, 'mcp', 'add', NAME, '--',
                       native_python(), MCP_SCRIPT], timeout=90)
        if rc != 0:
            return False, f'注册失败：{out.strip()[:200]}'
        return True, f'已注册 MCP（v{version()}）——重启 Codex 生效'

    def uninstall(self, keep_market=False):
        exe = self._exe()
        if not exe:
            return False, '未检测到 codex 命令，无需卸载'
        backup(os.path.join(HOME, '.codex', 'config.toml'))
        rc, out = run([exe, 'mcp', 'remove', NAME], timeout=60)
        return rc == 0, ('已从 Codex 移除 MCP 注册' if rc == 0
                         else f'移除：{out.strip()[:150]}')


class GenericMcp:
    label = '通用 MCP'

    def available(self):
        return True, '始终可用（输出配置片段）'

    def _snippet(self):
        return {'mcpServers': {NAME: {'command': native_python(),
                                      'args': [MCP_SCRIPT]}}}

    def status(self):
        return DASH, '按需输出配置片段（见 install mcp）'

    def install(self, config_path=None):
        snip = json.dumps(self._snippet(), indent=2, ensure_ascii=False)
        if not config_path:
            return True, '把下面这段合并进你的 MCP 配置即可：\n' + snip
        try:
            data = {}
            if os.path.exists(config_path):
                backup(config_path)
                with open(config_path, encoding='utf-8') as f:
                    data = json.load(f)
            data.setdefault('mcpServers', {})[NAME] = \
                self._snippet()['mcpServers'][NAME]
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True, f'已写入 {config_path}（原文件已备份为 .whale-bak）'
        except Exception as e:
            return False, f'写入失败：{e}\n可手动合并：\n{snip}'

    def uninstall(self, config_path=None):
        if not config_path:
            return True, '从你的 MCP 配置里删掉 "whale-pet" 条目即可'
        try:
            if not os.path.exists(config_path):
                return True, f'{config_path} 不存在，无需处理'
            backup(config_path)
            with open(config_path, encoding='utf-8') as f:
                data = json.load(f)
            data.get('mcpServers', {}).pop(NAME, None)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True, f'已从 {config_path} 移除（原文件已备份）'
        except Exception as e:
            return False, f'处理失败：{e}'


# --------------------------------------------------------------------------
# 状态总览
# --------------------------------------------------------------------------
def cmd_status():
    if pet_running():
        run_txt = f'运行中（{pet_state().get("state", "")}，本插件目录）'
    else:
        others = pet_processes()
        run_txt = (f'运行中（另一安装副本：{others[0][1]}）' if others else '未运行')
    print(f'鲸鱼娘桌宠 v{version()}   {PLUGIN_DIR}')
    print(f'  桌宠进程 : {run_txt}')
    short_n, voice_n = len(sound_files('short')), len(sound_files('voice'))
    if short_n or voice_n:
        print(f'  音效素材 : 短音效 {short_n} 条 + 整句语音 {voice_n} 条'
              + ('' if voice_n else '（voice/ 已删，自动降级为纯短音效）'))
    else:
        print('  音效素材 : 缺失（运行 pet/import_sound_pack.py "<音效包>" 导入）')
    print()
    for key, agent in AGENTS.items():
        try:
            mark, text = agent.status()
        except Exception as e:
            mark, text = NO, f'检测异常：{e}'
        print(f'  {agent.label:<12}{mark} {text}')
    print()
    print('  安装: python manage.py install <zcode|claude|codex|mcp|all>')
    print('  卸载: python manage.py uninstall <同上> [--purge]')


AGENTS = {
    'zcode': ZCode(),
    'claude': Claude(),
    'codex': Codex(),
    'mcp': GenericMcp(),
}


def cmd_install(agent, from_github=False, config_path=None):
    targets = list(AGENTS) if agent == 'all' else [agent]
    if agent == 'all':
        targets = [k for k, a in AGENTS.items()
                   if k == 'mcp' or a.available()[0]]
        if 'claude' in targets:
            targets.remove('claude')          # all 默认不打扰未安装的 Claude
    for key in targets:
        obj = AGENTS[key]
        avail, why = obj.available()
        if not avail:
            print(f'  {obj.label:<12}{DASH} {why}')
            continue
        print(f'  {obj.label:<12}安装中…')
        try:
            ok, msg = (obj.install(config_path) if key == 'mcp'
                       else obj.install(from_github))
        except Exception as e:
            ok, msg = False, str(e)
        print(f'  {obj.label:<12}{OK if ok else NO} {msg}')


def cmd_uninstall(agent, purge=False, keep_market=False, config_path=None):
    print(f'  先停桌宠：{stop_pet()}')
    targets = list(AGENTS) if agent == 'all' else [agent]
    if agent == 'all':
        targets = [k for k, a in AGENTS.items() if a.available()[0] or k == 'zcode']
    for key in targets:
        obj = AGENTS[key]
        try:
            ok, msg = (obj.uninstall(config_path) if key == 'mcp'
                       else obj.uninstall(keep_market))
        except Exception as e:
            ok, msg = False, str(e)
        print(f'  {obj.label:<12}{OK if ok else NO} {msg}')
    if purge:
        removed = purge_state()
        print(f'  清本地产物  {OK if removed else DASH} '
              f'{"、".join(removed) if removed else "没有需要清理的"}')


def sound_files(pattern=''):
    """音效文件列表；pattern 为空只列 short/（28 条），否则按相对路径子串过滤。"""
    import glob
    out = []
    for sub in ('short', 'voice'):
        for p in sorted(glob.glob(os.path.join(PET_DIR, 'assets', 'sounds', sub, '*.wav'))):
            rel = f'{sub}/{os.path.basename(p)}'
            if pattern and pattern.lower() not in rel.lower():
                continue
            if not pattern and sub != 'short':
                continue
            out.append(p)
    return out


def cmd_sound(pattern=''):
    """试听音效：默认 28 条短音效；`sound voice` 或 `sound celebrate` 过滤试听。"""
    import winsound
    files = sound_files(pattern)
    if not files:
        print(f'  没有匹配「{pattern}」的音效（先运行 pet/import_sound_pack.py 导入）')
        return 1
    print(f'  试听 {len(files)} 条（Ctrl+C 跳过）')
    for p in files:
        rel = os.path.relpath(p, os.path.join(PET_DIR, 'assets', 'sounds'))
        print(f'  ▶ {rel}')
        winsound.PlaySound(p, winsound.SND_FILENAME)
    return 0


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='manage.py', description='鲸鱼娘桌宠 · 安装/卸载/状态管理',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='示例:\n'
               '  python manage.py install all\n'
               '  python manage.py uninstall zcode\n'
               '  python manage.py uninstall all --purge\n')
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('status', help='查看桌宠与各 Agent 的安装状态')
    for name, helptext in (('install', '安装到指定 Agent（zcode/claude/codex/mcp/all）'),
                           ('uninstall', '从指定 Agent 卸载')):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument('agent', nargs='?', default='all',
                        choices=['zcode', 'claude', 'codex', 'mcp', 'all'])
        sp.add_argument('--from-github', action='store_true',
                        help='市场源用 GitHub 仓库而非本地目录（install）')
        sp.add_argument('--config', help='通用 MCP：目标 JSON 配置文件路径')
        sp.add_argument('--purge', action='store_true', help='卸载后清理本地产物')
        sp.add_argument('--keep-marketplace', action='store_true',
                        help='卸载插件时保留市场注册')
    sub.add_parser('start', help='启动桌宠')
    sub.add_parser('stop', help='退出桌宠')
    sub.add_parser('restart', help='重启桌宠')
    ps = sub.add_parser('sound', help='试听音效（默认 28 条短音效；可加关键词过滤）')
    ps.add_argument('pattern', nargs='?', default='',
                    help='过滤关键词，如 voice / celebrate / coquetry（留空=全部短音效）')
    args = ap.parse_args(argv)

    if args.cmd in (None, 'status'):
        cmd_status()
        return 0
    if args.cmd == 'install':
        cmd_install(args.agent, args.from_github, args.config)
        return 0
    if args.cmd == 'uninstall':
        cmd_uninstall(args.agent, args.purge, args.keep_marketplace, args.config)
        return 0
    if args.cmd == 'start':
        ok, msg = start_pet()
        print(f'  {OK if ok else NO} {msg}')
        return 0 if ok else 1
    if args.cmd == 'stop':
        print(f'  {stop_pet()}')
        return 0
    if args.cmd == 'restart':
        print(f'  {stop_pet()}')
        ok, msg = start_pet()
        print(f'  {OK if ok else NO} {msg}')
        return 0 if ok else 1
    if args.cmd == 'sound':
        return cmd_sound(args.pattern)
    return 2


if __name__ == '__main__':
    sys.exit(main())
