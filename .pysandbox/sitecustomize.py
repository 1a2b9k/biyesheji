"""
DSH 沙箱兼容补丁 —— 修复本沙箱下"新建目录不可写"的问题。

背景(实测,非推测):
    在本机 DSH 沙箱下,用 mode=0o700 建出的目录**无法被写入**
    (PermissionError [Errno 13] / WinError 5,且 chmod 也失败),
    而默认 mode 或 0o755 建出的目录完全正常:

        os.mkdir(p)             -> 可写
        os.mkdir(p, 0o755)      -> 可写
        os.mkdir(p, 0o700)      -> PermissionError
        os.makedirs(p, mode=0o700) -> PermissionError

    注意 os.stat 对两者都报 0o777 —— 差别在安全描述符而非 POSIX 位,
    所以靠改权限位修不了,只能在创建时就不传 0o700。

影响面(两处都走 0o700,都因此失败):
    - tempfile.mkdtemp()          → pip 的全部临时目录,导致装不了任何包
    - pytest 的 basetemp/编号目录  → 任何用 tmp_path fixture 的用例

本补丁做两件事:
    1. 把 tempfile.mkdtemp 换成「os.makedirs + 随机后缀」的实现,
       语义一致(创建唯一目录并返回路径),只是不用 0o700。
    2. 包装 os.mkdir / os.makedirs,把传入的 0o700 降级为 0o755。
       其余 mode 原样透传,避免影响正常代码的意图。

生效方式:
    PYTHONPATH 指向本文件所在目录即可(Python 启动时自动导入
    sitecustomize);本仓库的 .python\\python312._pth 已包含该目录。
    临时根目录可用环境变量 DSH_PY_TMP 覆盖,默认 <工作区>/.tmp。
"""

import os
import random
import string
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_BASE = os.path.join(os.path.dirname(_HERE), '.tmp')
_BASE = os.environ.get('DSH_PY_TMP') or _DEFAULT_BASE

_original_mkdtemp = tempfile.mkdtemp
_ALPHABET = string.ascii_lowercase + string.digits

# 本沙箱里唯一会出问题的 mode。0o700 = 仅所有者可访问,
# 沙箱的完整性标签恰好让"仅所有者"的目录对子进程不可写。
_BAD_MODE = 0o700
_SAFE_MODE = 0o755

_original_mkdir = os.mkdir
_original_makedirs = os.makedirs


def _fix_mode(mode):
    """把 0o700 换成 0o755,其余原样返回。"""
    if mode is None:
        return None
    try:
        return _SAFE_MODE if (mode & 0o777) == _BAD_MODE else mode
    except TypeError:
        return mode


def _mkdir(path, mode=None, *args, **kwargs):
    if mode is None:
        return _original_mkdir(path, *args, **kwargs)
    return _original_mkdir(path, _fix_mode(mode), *args, **kwargs)


def _makedirs(name, mode=None, exist_ok=False):
    if mode is None:
        return _original_makedirs(name, exist_ok=exist_ok)
    return _original_makedirs(name, _fix_mode(mode), exist_ok=exist_ok)


def _mkdtemp(suffix=None, prefix=None, dir=None):
    """与 tempfile.mkdtemp 语义一致的替代实现,但用默认 mode 建目录。"""
    base = dir if dir is not None else _BASE
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        # 连临时根都建不出来时,退回原实现,保持行为可预期
        return _original_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)

    prefix = prefix or 'tmp'
    suffix = suffix or ''
    for _ in range(1000):
        name = prefix + ''.join(random.choices(_ALPHABET, k=8)) + suffix
        path = os.path.join(base, name)
        try:
            _original_makedirs(path)   # 关键:不传 mode
            return os.path.realpath(path)
        except FileExistsError:
            continue
    return _original_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)


os.mkdir = _mkdir
os.makedirs = _makedirs
tempfile.mkdtemp = _mkdtemp
