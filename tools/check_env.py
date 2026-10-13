"""
环境自检 —— 一条命令验证本机开发环境是否可用。

用法(注意:用工作区内本地化的解释器):
    .python\\python.exe tools\\check_env.py

退出码 0 = 全部通过;非 0 = 有检查项失败。
凡在本机做环境相关改动后,都应先跑通本脚本再交付。

检查内容:
  1. 解释器是工作区内本地化的那一个(不是工作区外的原始副本)
  2. Python 版本受支持
  3. DSH 沙箱兼容补丁已生效(临时目录可写 —— 这是 pip 能否工作的前提)
  4. pip / setuptools 可导入
  5. 安装目标目录(.pylibs)可写且已在 sys.path 中
  6. 能连通 PyPI(装包前提)
  7. 关键第三方库可导入
  8. torch 是否已安装 / 是否识别到 CUDA(未安装时仅提示,不算失败)
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
_SANDBOX = os.path.join(_WS, '.pysandbox')
_PYLIBS = os.path.join(_WS, '.pylibs', 'Python312', 'site-packages')
_LOCAL_PY = os.path.join(_WS, '.python', 'python.exe')

# 先加载沙箱兼容补丁(与 .pysandbox/pipp.py 采用同一前置步骤)
if _SANDBOX not in sys.path:
    sys.path.insert(0, _SANDBOX)

failures = []


def report(ok, label, detail=''):
    mark = 'PASS' if ok else 'FAIL'
    print('  [%s] %-46s %s' % (mark, label, detail))
    if not ok:
        failures.append(label)


def shorten(path):
    return path.replace(_WS, '.') if path.startswith(_WS) else path


print('=== Environment self-check ===')
print('  解释器: %s' % sys.executable)
print()

# 1) 必须是本地化解释器
exe = os.path.abspath(sys.executable)
report(os.path.normcase(exe) == os.path.normcase(os.path.abspath(_LOCAL_PY)),
       'interpreter is the workspace-localized one',
       shorten(exe) if os.path.normcase(exe) != os.path.normcase(_LOCAL_PY)
       else 'ok')

# 2) 版本
v = sys.version_info
report(v >= (3, 10), 'Python version >= 3.10', '%d.%d.%d' % (v.major, v.minor, v.micro))

# 3) 沙箱兼容补丁:临时目录必须可写
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
           shorten(d) if patched else 'patch NOT applied')
except Exception as exc:  # pragma: no cover
    report(False, 'sandbox temp-dir patch active & writable', repr(exc))

# 4) pip / setuptools
for mod in ('pip', 'setuptools'):
    try:
        m = __import__(mod)
        report(True, '%s importable' % mod, getattr(m, '__version__', 'ok'))
    except Exception as exc:
        report(False, '%s importable' % mod, repr(exc))

# 5) 安装目标可写且已在 sys.path
try:
    os.makedirs(_PYLIBS, exist_ok=True)
    with open(os.path.join(_PYLIBS, '_probe.txt'), 'wb') as f:
        f.write(b'ok')
    os.remove(os.path.join(_PYLIBS, '_probe.txt'))
    on_path = any(os.path.normcase(p) == os.path.normcase(_PYLIBS) for p in sys.path)
    report(on_path, 'install target writable & on sys.path', shorten(_PYLIBS))
except Exception as exc:
    report(False, 'install target writable & on sys.path', repr(exc))

# 6) 网络:PyPI 可达
try:
    import urllib.request
    with urllib.request.urlopen('https://pypi.org/simple/', timeout=15) as r:
        report(r.status == 200, 'PyPI reachable', 'HTTP %d' % r.status)
except Exception as exc:
    report(False, 'PyPI reachable', type(exc).__name__)

# 7) 关键第三方库
for mod in ('numpy', 'requests', 'docx', 'fitz'):
    try:
        m = __import__(mod)
        report(True, 'lib %s' % mod, getattr(m, '__version__', 'ok'))
    except Exception as exc:
        report(False, 'lib %s' % mod, type(exc).__name__)

# 8) torch(可选)
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
