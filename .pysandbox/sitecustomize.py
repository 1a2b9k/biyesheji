"""
DSH 沙箱兼容补丁 —— 修复 tempfile.mkdtemp() 建出的目录不可写的问题。

背景(实测,非推测):
    在本机 DSH 沙箱下,`tempfile.mkdtemp()` 创建的目录**无法写入**
    (PermissionError [Errno 13] / WinError 5,且 chmod 也失败),
    而 `os.makedirs()` 创建的目录完全正常。
    pip 的全部临时目录(temp_dir.py:175/291、distlib)都走 mkdtemp,
    因此 pip 在本沙箱内无法安装任何包 —— 所有阶段都会失败。

本补丁:
    把 tempfile.mkdtemp 替换为「os.makedirs + 随机后缀」的实现,
    语义保持一致(创建唯一目录并返回其路径),只是不再受上述限制。

生效方式:
    PYTHONPATH 指向本文件所在目录即可(Python 启动时自动导入 sitecustomize)。
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


def _mkdtemp(suffix=None, prefix=None, dir=None):
    """与 tempfile.mkdtemp 语义一致的替代实现,但用 os.makedirs 建目录。"""
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
            os.makedirs(path)          # 关键:默认 mode,不用 mkdir(0o700)
            return os.path.realpath(path)
        except FileExistsError:
            continue
    return _original_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)


tempfile.mkdtemp = _mkdtemp
