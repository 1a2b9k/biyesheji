"""
启动脚本的测试。

这些脚本是"学生双击就能跑"的入口,一旦坏掉,现象是"网页打不开",
很难从报错反推到脚本本身,所以必须有测试盯着。

两个已经踩过的坑,各自对应下面一组断言:
  1. `.cmd` 文件必须纯 ASCII。cmd.exe 按 OEM 代码页(本机 GBK)解析,
     中文注释会让脚本在第一条命令前就解析失败。
  2. `start-backend.cmd` 不能默认开 `--reload`。uvicorn 的 reloader 会
     spawn 子进程并用**命名管道**通信,而 DSH 沙箱禁止受限进程开命名管道,
     结果是 reloader 在 `PermissionError: [WinError 5]` 上死循环,
     端口永远不绑定 —— 表现为"后端打不开",但直接跑 uvicorn 却是好的。
"""

import os
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_REPO_ROOT, 'scripts')
_PY = os.path.join(_REPO_ROOT, '.python', 'python.exe')

_ALL_CMDS = ['start-backend.cmd', 'start-frontend.cmd', 'test-all.cmd']


# ------------------------------------------------------------ 文件编码

@pytest.mark.parametrize('name', _ALL_CMDS)
def test_cmd_is_ascii_only(name):
    """cmd.exe 用 GBK 解析 .cmd,非 ASCII 字符会破坏解析。"""
    path = os.path.join(_SCRIPTS, name)
    raw = open(path, 'rb').read()
    bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    assert not bad, '%s 含非 ASCII 字节,首个位于偏移 %d' % (name, bad[0][0])


@pytest.mark.parametrize('name', _ALL_CMDS)
def test_cmd_has_no_bom(name):
    """带 BOM 会让 cmd.exe 把首行当成未知命令。"""
    raw = open(os.path.join(_SCRIPTS, name), 'rb').read(3)
    assert raw != b'\xef\xbb\xbf', '%s 不应带 UTF-8 BOM' % name


# ------------------------------------------------------------ 后端脚本

def _read_cmd(name):
    return open(os.path.join(_SCRIPTS, name), encoding='ascii').read()


def test_backend_does_not_enable_reload_by_default():
    """--reload 走命名管道,沙箱下会死循环,默认绝不能开。"""
    text = _read_cmd('start-backend.cmd')
    assert 'RELOAD_FLAG' in text, '应通过 RELOAD_FLAG 变量有条件地加 --reload'
    # 直接写死的 --reload(不带变量)是不允许的
    assert '--reload --app-dir' not in text
    assert '%RELOAD_FLAG%' in text, '命令行必须用变量,不能写死'


def test_backend_reload_is_opt_in():
    """允许显式 opt-in(沙箱外想用热重载时)。"""
    text = _read_cmd('start-backend.cmd')
    assert '"%RELOAD%"=="1"' in text


def test_backend_points_at_local_interpreter():
    """必须用工作区内本地化的解释器,否则沙箱下装不了包。"""
    text = _read_cmd('start-backend.cmd')
    assert '.python\\python.exe' in text


def test_backend_binds_loopback_only():
    text = _read_cmd('start-backend.cmd')
    assert '--host 127.0.0.1' in text
    assert '--port 8000' in text


# ------------------------------------------------------------ 前端脚本

def test_frontend_uses_sandbox_shim():
    """不加垫片的话 Vite 的 `net use` 探测会 EPERM,连配置都加载不了。"""
    text = _read_cmd('start-frontend.cmd')
    assert 'vite-sandbox-shim.mjs' in text


def test_frontend_points_cache_into_workspace():
    """npm 缓存默认在 %TEMP%,沙箱下不可写。"""
    text = _read_cmd('start-frontend.cmd')
    assert 'npm_config_cache' in text
    assert '.npm-cache' in text


def test_frontend_port_matches_backend_proxy():
    """前端 dev server 端口要和 vite 配置里的代理目标对得上。"""
    text = _read_cmd('start-frontend.cmd')
    assert '--port 5173' in text


# ------------------------------------------------------------ 实时冒烟

@pytest.mark.skipif(not os.path.exists(_PY), reason='workspace interpreter missing')
def test_backend_actually_serves():
    """真起一次后端,确认端口能绑上、接口有响应。

    这条是回归防线:上面几条只检查文本,--reload 那类问题只有真跑才暴露。
    """
    import json
    import socket
    import tempfile
    import time
    import urllib.request

    # 先确认端口空闲,避免和已在跑的实例混淆
    probe = socket.socket()
    try:
        probe.connect(('127.0.0.1', 8000))
    except OSError:
        pass
    else:
        pytest.skip('8000 已被占用,跳过(假定已有实例在跑)')
    finally:
        probe.close()

    log = tempfile.mkstemp(prefix='start-backend-', suffix='.log')[1]
    with open(log, 'wb') as out:
        proc = subprocess.Popen(
            [_PY, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
             '--port', '8000', '--app-dir', 'backend'],
            cwd=_REPO_ROOT, stdout=out, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL)
    try:
        ok = False
        for _ in range(40):
            time.sleep(0.5)
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                        'http://127.0.0.1:8000/api/health', timeout=2) as r:
                    ok = json.loads(r.read().decode('utf-8'))['status'] == 'ok'
                if ok:
                    break
            except Exception:
                continue
        if not ok:
            body = open(log, 'rb').read().decode('utf-8', 'replace')
            pytest.fail('后端未能起来,退出码 %s\n%s' % (proc.poll(), body[-3000:]))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            os.remove(log)
        except OSError:
            pass
