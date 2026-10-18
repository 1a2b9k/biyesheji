"""依赖清单的守护测试。

交接文档第十节把它记为 A2:「全仓没有 requirements.txt / pyproject.toml,
干净检出后无法重建环境」—— 这是最硬的交付缺陷,也最容易在改代码时
重新腐化(加了一个 import,忘了写进清单)。

所以这里不只断言文件存在,而是**反推**:扫一遍 backend/ 与 tools/ 里
真实出现的 import,每一个第三方包都必须在清单里有对应条目。
这样新加依赖而忘了登记时,测试会直接失败。

反向也查:清单里不能有已经没人用的包(那种「当初装了但代码删了」
的残留会让人误以为项目很重)。

清单是手写的(不是 pip freeze),原因见 requirements.txt 开头:
本机解释器是共用的,freeze 里混着 edge-tts / Flask / google-genai
等与项目无关的包,直接固化会误导重建者。
"""

import os
import re
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_REQ = os.path.join(_REPO_ROOT, 'requirements.txt')

# 扫哪些目录找 import
_SCAN_DIRS = [
    os.path.join(_REPO_ROOT, 'backend', 'app'),
    os.path.join(_REPO_ROOT, 'backend', 'tests'),
    os.path.join(_REPO_ROOT, 'tools'),
]
_SCAN_EXTRA_FILES = [os.path.join(_REPO_ROOT, 'backend', 'conftest.py')]

# import 名 → 发行包名。只列**项目里真实出现过**的映射,
# 名字不一致的才需要写在这里(fastapi 这种同名的不写也对)。
_IMPORT_TO_DIST = {
    'sklearn': 'scikit-learn',
    'docx': 'python-docx',
    'pymysql': 'PyMySQL',
    'sqlalchemy': 'SQLAlchemy',
    'huggingface_hub': 'huggingface_hub',
    # md_to_docx.image_size_cm 用 PIL 读图片像素定尺寸。
    # 注意 Pillow 的 import 名与发行包名不同,不写映射会被判成未登记。
    'PIL': 'Pillow',
}

# 不靠 import 出现、但运行必需的依赖。
# uvicorn 是被 scripts/start-backend.cmd 用 `-m uvicorn` 起的,
# 代码里没有 `import uvicorn`,所以扫描抓不到。
# httpx 同理:fastapi.testclient.TestClient 内部要它,
# 但测试代码只 `from fastapi.testclient import TestClient`。
_RUNTIME_ONLY = {'uvicorn', 'httpx'}

# 明确不算交付物的脚本 —— 是 agent 自检工具(验证「读图能力」),
# 不是系统的一部分,它需要的 Pillow 不该进项目依赖清单。
_NOT_DELIVERABLE = {'make_vision_test.py'}

# 本仓库自己的模块,不算第三方
_LOCAL_MODULES = {
    'app', 'config', 'db', 'models', 'service', 'collector', 'analysis',
    'sentiment', 'main',
    'ablation_study', 'analyze_neutral', 'ensemble_sentiment',
    'experiment_report', 'fetch_dataset', 'fetch_model', 'fetch_wheel',
    'md_to_docx', 'make_vision_test', 'train_multitask', 'train_sentiment',
    'use_mysql', 'check_env', 'check_datasource', 'setup_python',
    'sitecustomize', 'make_figures', 'make_icon', 'collect_corpus',
}

_IMPORT_RE = re.compile(
    r'^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)', re.MULTILINE)


def _read_requirements():
    assert os.path.isfile(_REQ), (
        'requirements.txt 不见了 —— 这是交付硬缺陷(交接文档 A2)')
    with open(_REQ, encoding='utf-8') as f:
        return f.read()


def _requirement_entries(text):
    """解析成 [(dist_name_lower, specifier)]，跳过注释与空行。"""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r'^([A-Za-z0-9_.\-]+)\s*(\S*)$', line)
        assert m, 'requirements.txt 有一行解析不了: %r' % line
        out.append((m.group(1).lower(), m.group(2)))
    return out


def _scanned_imports():
    """扫描项目源码,返回第三方 import 名集合。"""
    stdlib = getattr(sys, 'stdlib_module_names', set())
    found = set()

    files = list(_SCAN_EXTRA_FILES)
    for d in _SCAN_DIRS:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.endswith('.py'):
                files.append(os.path.join(d, name))

    for path in files:
        if os.path.basename(path) in _NOT_DELIVERABLE:
            continue
        try:
            with open(path, encoding='utf-8') as f:
                src = f.read()
        except OSError:
            continue
        for mod in _IMPORT_RE.findall(src):
            if mod in stdlib or mod in _LOCAL_MODULES or mod.startswith('_'):
                continue
            found.add(mod)
    return found


def test_requirements_file_exists_and_is_not_empty():
    text = _read_requirements()
    entries = _requirement_entries(text)
    assert len(entries) >= 10, '清单条目太少,像是没写完'


def test_every_entry_is_pinned():
    """全部用 == 钉死版本。

    不钉版本的清单在重建时等于没有清单 —— 今天装到 5.x、
    半年后装到 6.x,而 API 已经变了。
    """
    for dist, spec in _requirement_entries(_read_requirements()):
        assert spec.startswith('=='), (
            '%s 没钉版本(得到 %r),重建时结果不可复现' % (dist, spec))


def test_every_third_party_import_is_declared():
    """代码里 import 了,清单里就必须有。"""
    declared = {d for d, _ in _requirement_entries(_read_requirements())}
    missing = []
    for mod in sorted(_scanned_imports()):
        dist = _IMPORT_TO_DIST.get(mod, mod).lower()
        if dist not in declared:
            missing.append('%s(import 名 %s)' % (dist, mod))
    assert not missing, (
        '这些包被 import 但没写进 requirements.txt: %s' % ', '.join(missing))


def test_runtime_only_dependencies_are_declared():
    """不靠 import 出现、但运行必需的依赖也要登记。"""
    declared = {d for d, _ in _requirement_entries(_read_requirements())}
    for name in sorted(_RUNTIME_ONLY):
        assert name.lower() in declared, (
            '%s 是运行必需(scripts 里用 -m 起),但清单里没有' % name)


def test_no_unused_requirements():
    """清单里不能有代码已经不用的包。

    只查「既没被 import、也不在 runtime-only 名单里」的条目。
    pandas 是特例:它只在 tools/check_env.py 里做自检,
    被 import 的方式是字符串 `__import__(mod)`,正则扫不到。
    """
    declared = {d for d, _ in _requirement_entries(_read_requirements())}
    used = {_IMPORT_TO_DIST.get(m, m).lower() for m in _scanned_imports()}
    used |= {n.lower() for n in _RUNTIME_ONLY}
    # check_env.py 用 __import__('pandas') 动态导入,静态扫描抓不到
    used.add('pandas')
    unused = declared - used
    assert not unused, (
        '这些包写在清单里但代码已经不用了: %s' % ', '.join(sorted(unused)))


def test_no_placeholder_markers():
    """清单里不能留 TODO / 待定之类的占位。"""
    text = _read_requirements()
    for marker in ('TODO', '待补', '待定', 'XXX', 'FIXME'):
        assert marker not in text, 'requirements.txt 里还有占位符 %r' % marker


def test_python_version_is_recorded():
    """清单里要写明适配的 Python 版本。

    重建环境的人第一件要知道的就是「用哪个 Python」。
    """
    text = _read_requirements()
    assert re.search(r'Python 3\.\d+', text), (
        'requirements.txt 没写明适配的 Python 版本')


def test_torch_cuda_index_is_documented():
    """torch 的 CUDA 轮子不在 PyPI 主索引,必须写明怎么装。

    这条是踩出来的:直接 `install torch` 会拿到 CPU 版,
    而本机要的是 cu130。不写清楚,重建者会以为 GPU 不可用。
    """
    text = _read_requirements()
    if 'torch==' not in text:
        pytest.skip('清单里没有 torch')
    assert 'download.pytorch.org' in text, (
        'torch 的 CUDA 索引地址没写进清单注释')


def test_install_uses_wrapper():
    """清单里必须提示用包装器装包。

    交接文档第八节:直接 `python -m pip` 会在沙箱下失败,
    必须走 .pysandbox/pipp.py。清单是重建者第一个看的文件,
    提示写在这里最省事。
    """
    text = _read_requirements()
    assert 'pipp.py' in text, '清单没提示用 .pysandbox/pipp.py 装包'
