"""
pip 包装器 —— 在 DSH 沙箱下让 pip 能正常工作。

用法(替换 `python -m pip`):
    .python\\python.exe .pysandbox\\pipp.py install <包名...>

它做四件事:
  1. 显式把 .pysandbox 加进 sys.path 并导入 sitecustomize,
     修复 mkdtemp 建出的目录不可写的问题;
  2. 把 TEMP/TMP/TMPDIR 与 pip 缓存目录全部指进工作区(沙箱只允许写工作区);
  3. 把 PYTHONUSERBASE 指向工作区内的 .pylibs ——
     解释器自带的 site-packages 在工作区外、沙箱不允许写入,
     因此新包一律装进工作区,再由 python312._pth 挂进 sys.path;
  4. 原样把命令行参数交给真正的 pip。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)

# 1) 先打沙箱兼容补丁(必须在 pip 调用 mkdtemp 之前)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import sitecustomize  # noqa: F401  (导入即生效)

# 2) 临时目录与缓存目录全部收敛到工作区内
_TMP = os.path.join(_WS, '.tmp')
_CACHE = os.path.join(_WS, '.pip-cache')
os.makedirs(_TMP, exist_ok=True)
os.makedirs(_CACHE, exist_ok=True)
for _var in ('TEMP', 'TMP', 'TMPDIR'):
    os.environ[_var] = _TMP
os.environ.setdefault('PIP_CACHE_DIR', _CACHE)
os.environ['PYTHONUTF8'] = '1'

# 3) 安装目标指向工作区内的 .pylibs(与 python312._pth 中的条目一致)
os.environ['PYTHONUSERBASE'] = os.path.join(_WS, '.pylibs')
if '--user' not in sys.argv[1:]:
    sys.argv.append('--user')

# 4) 交给真正的 pip
from pip._internal.cli.main import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
