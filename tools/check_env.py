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

# 3b) mode=0o700 的目录在本沙箱下不可写(实测),补丁须把它降级。
#     这条单列,因为它影响 pytest 的 tmp_path 与 pip 的临时目录,
#     出问题时症状是 PermissionError 而不是"补丁没生效",很难联想。
try:
    import shutil
    probe_root = tempfile.mkdtemp(prefix='check-mode-')
    bad = os.path.join(probe_root, 'd700')
    os.makedirs(bad, mode=0o700)
    try:
        with open(os.path.join(bad, 'probe.txt'), 'wb') as f:
            f.write(b'ok')
        mode_ok = True
    except OSError:
        mode_ok = False
    shutil.rmtree(probe_root, ignore_errors=True)
    report(mode_ok, 'mkdir(mode=0o700) dirs are writable', 'downgraded to 0o755')
except Exception as exc:  # pragma: no cover
    report(False, 'mkdir(mode=0o700) dirs are writable', repr(exc))

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

# 6) 网络:装包镜像可达
#    注意:pypi.org 官方源本机实测只有 ~0.01 MB/s(延迟极高),虽然返回 200
#    但实际装不了包,所以这里检查真正在用的国内镜像。
_MIRROR = os.environ.get('PIP_MIRROR', 'https://pypi.tuna.tsinghua.edu.cn/simple/')
try:
    import urllib.request
    with urllib.request.urlopen(_MIRROR, timeout=15) as r:
        report(r.status == 200, 'PyPI mirror reachable', 'HTTP %d %s' % (r.status, _MIRROR.split('/')[2]))
except Exception as exc:
    report(False, 'PyPI mirror reachable', type(exc).__name__)

# 7) 关键第三方库
for mod in ('numpy', 'requests', 'docx', 'fitz'):
    try:
        m = __import__(mod)
        report(True, 'lib %s' % mod, getattr(m, '__version__', 'ok'))
    except Exception as exc:
        report(False, 'lib %s' % mod, type(exc).__name__)

# 8) torch(可选):不只是看 is_available,真跑一次 GPU 矩阵乘法
#    只有这样才能发现「驱动能认卡、但 wheel 里没有本卡算力的 kernel」这类问题
#    (RTX 5060 是 sm_120,需要 cu128+ 的构建才带对应 kernel)。
try:
    import torch
    if not torch.cuda.is_available():
        report(False, 'torch GPU compute', 'torch %s installed but CUDA unavailable' % torch.__version__)
    else:
        cap = torch.cuda.get_device_capability(0)
        arch = 'sm_%d%d' % cap
        built = torch.cuda.get_arch_list()
        # 该卡算力是否在本次构建的 kernel 列表里
        report(arch in built, 'torch GPU compute',
               'torch %s, %s, %s' % (torch.__version__, torch.cuda.get_device_name(0), arch))
        if arch in built:
            a = torch.randn(512, 512, device='cuda')
            b = torch.randn(512, 512, device='cuda')
            c = a @ b
            torch.cuda.synchronize()
            ok = bool(torch.allclose(c.cpu(), a.cpu() @ b.cpu(), rtol=1e-2, atol=1e-1))
            report(ok, 'torch GPU matmul matches CPU',
                   'max diff %.2e' % float((c.cpu() - a.cpu() @ b.cpu()).abs().max()))
except ImportError:
    print('  [SKIP] %-46s %s' % ('torch GPU compute', 'torch not installed yet'))

# 9) 情感分析的机器学习栈(可选)
#    这些是 v0.2 要用的,没装不算环境故障,但装了就要确认能 import。
for mod in ('transformers', 'sklearn', 'pandas'):
    try:
        m = __import__(mod)
        report(True, 'ml lib %s' % mod, getattr(m, '__version__', 'ok'))
    except ImportError:
        print('  [SKIP] %-46s %s' % ('ml lib %s' % mod, 'not installed yet'))
    except Exception as exc:
        report(False, 'ml lib %s' % mod, type(exc).__name__)

# 10) 预训练 / 已训练模型(可选):只查文件在不在,不加载(加载要几秒)
# 三类模型目录并存:
#   bert-base-chinese          HuggingFace 格式(config.json + 权重)
#   sentiment-tfidf-3class     joblib 格式(model.joblib,sklearn 流水线)
#   multitask-4class           自定义格式(config.json + model.pt,state_dict)
# 之前只认 HF 格式,TF-IDF 模型一训练出来自检就红,这里按格式分别判断。
# 多任务模型是「共享编码器 + 3 个头」,不是 HF 的 AutoModelForSequenceClassification,
# 所以存的是 model.pt 而不是 safetensors —— 必须单独认,否则自检会误报不完整。
_MODELS = os.path.join(_WS, 'models')
if os.path.isdir(_MODELS):
    for name in sorted(os.listdir(_MODELS)):
        d = os.path.join(_MODELS, name)
        if not os.path.isdir(d):
            continue
        size = sum(os.path.getsize(os.path.join(dp, f))
                   for dp, _, fs in os.walk(d) for f in fs)

        if os.path.exists(os.path.join(d, 'model.joblib')):
            report(True, 'model %s' % name,
                   '%.1f MB (joblib)' % (size / 1048576))
            continue

        has_cfg = os.path.exists(os.path.join(d, 'config.json'))

        # 自定义多任务格式:config.json 里带 n_main,权重是 model.pt
        has_pt = os.path.exists(os.path.join(d, 'model.pt'))
        if has_cfg and has_pt:
            report(True, 'model %s' % name,
                   '%.1f MB (multitask)' % (size / 1048576))
            continue

        has_w = any(os.path.exists(os.path.join(d, w))
                    for w in ('model.safetensors', 'pytorch_model.bin'))
        report(has_cfg and has_w, 'model %s' % name,
               '%.1f MB' % (size / 1048576) if has_cfg and has_w
               else 'incomplete (config=%s weights=%s)' % (has_cfg, has_w))
else:
    print('  [SKIP] %-46s %s' % ('pretrained models', 'models/ not found'))

print()
if failures:
    print('RESULT: %d check(s) FAILED -> %s' % (len(failures), ', '.join(failures)))
    sys.exit(1)
print('RESULT: all checks passed')
sys.exit(0)
