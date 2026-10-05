"""
环境自检 —— 一条命令验证本机开发环境是否可用。

用法:
    <python.exe> tools\\check_env.py

退出码 0 = 全部通过;非 0 = 有检查项失败。
凡在本机做环境相关改动后,都应先跑通本脚本再交付。

检查内容:
  1. Python 解释器可用且版本受支持
  2. DSH 沙箱兼容补丁已生效(临时目录可写 —— 这是 pip 能否工作的前提)
  3. pip 可导入
  4. 能连通 PyPI(装包前提)
  5. torch 是否已安装 / 是否识别到 CUDA(未安装时仅提示,不算失败)
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
_SANDBOX = os.path.join(_WS, '.pysandbox')

# 先加载沙箱兼容补丁(与 .pysandbox/pipp.py 采用同一前置步骤)
if _SANDBOX not in sys.path:
    sys.path.insert(0, _SANDBOX)

failures = []


def report(ok, label, detail=''):
    mark = 'PASS' if ok else 'FAIL'
    print('  [%s] %-46s %s' % (mark, label, detail))
    if not ok:
        failures.append(label)


print('=== Environment self-check ===')

# 1) 解释器
v = sys.version_info
report(v >= (3, 10), 'Python version >= 3.10',
       '%d.%d.%d (%s)' % (v.major, v.minor, v.micro, sys.executable))

# 2) 沙箱兼容补丁:临时目录必须可写
try:
    import sitecustomize  # noqa: F401
    import tempfile
    patched = tempfile.mkdtemp.__module__ == 'sitecustomize'
    d = tempfile.mkdtemp(prefix='check-env-')
    try:
        with open(os.path.join(d, 'probe.txt'), 'wb') as f:
            f.write(b'ok')
        writable = True
    except OSError:
        writable = False
    report(patched and writable, 'sandbox temp-dir patch active & writable',
           d.replace(_WS, '.') if patched else 'patch NOT applied')
except Exception as exc:  # pragma: no cover
    report(False, 'sandbox temp-dir patch active & writable', repr(exc))

# 3) pip 可导入
try:
    import pip
    report(True, 'pip importable', pip.__version__)
except Exception as exc:
    report(False, 'pip importable', repr(exc))

# 4) 网络:PyPI 可达
try:
    import urllib.request
    with urllib.request.urlopen('https://pypi.org/simple/', timeout=15) as r:
        report(r.status == 200, 'PyPI reachable', 'HTTP %d' % r.status)
except Exception as exc:
    report(False, 'PyPI reachable', type(exc).__name__)

# 5) torch(可选)
try:
    import torch
    report(torch.cuda.is_available(), 'torch installed / CUDA available',
           'torch %s, cuda=%s' % (torch.__version__, torch.cuda.is_available()))
except ImportError:
    print('  [SKIP] %-46s %s' % ('torch installed / CUDA available', 'not installed yet'))

print()
if failures:
    print('RESULT: %d check(s) FAILED -> %s' % (len(failures), ', '.join(failures)))
    sys.exit(1)
print('RESULT: all checks passed')
sys.exit(0)
