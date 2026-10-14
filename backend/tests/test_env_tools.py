"""
环境与下载工具的测试。

覆盖两处:
  1. tools/fetch_wheel.py 的纯逻辑 —— 版本解析、CDN 主机改写、wheel 挑选。
     这里最要紧的是「默认挑最新版」必须按数字比较,而不是按字符串比较,
     否则 2.10.0 会被判成比 2.9.0 小。
  2. tools/check_env.py 作为脚本的退出码 —— 它是交付前的环境闸门,
     必须真的能跑通并返回 0。

不发网络请求:需要 HTTP 的地方用假的 _open 替换。
"""

import os
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import fetch_wheel  # noqa: E402

_PY = os.path.join(_REPO_ROOT, '.python', 'python.exe')


# ------------------------------------------------------------ 版本解析

@pytest.mark.parametrize('filename,expected', [
    ('torch-2.10.0+cu130-cp312-cp312-win_amd64.whl', '2.10.0'),
    ('torch-2.9.0+cu130-cp312-cp312-win_amd64.whl', '2.9.0'),
    ('torch-2.14.1+cu130-cp312-cp312-win_amd64.whl', '2.14.1'),
    ('numpy-2.4.6-cp312-cp312-win_amd64.whl', '2.4.6'),
    ('torchvision-0.24.0+cu130-cp312-cp312-win_amd64.whl', '0.24.0'),
])
def test_parse_version(filename, expected):
    assert fetch_wheel.parse_version(filename) == expected


def test_parse_version_ignores_local_tag():
    """+cu130 这类本地版本标签不能混进版本号里。"""
    assert '+' not in fetch_wheel.parse_version(
        'torch-2.14.1+cu130-cp312-cp312-win_amd64.whl')


# ------------------------------------------------------------ CDN 改写

def test_rewrite_swaps_slow_host():
    url = ('https://download-r2.pytorch.org/whl/cu130/'
           'torch-2.10.0%2Bcu130-cp312-cp312-win_amd64.whl')
    out = fetch_wheel.rewrite(url)
    assert out.startswith('https://download.pytorch.org/')
    assert 'download-r2' not in out


def test_rewrite_leaves_other_hosts_untouched():
    url = 'https://pypi.tuna.tsinghua.edu.cn/simple/torch/'
    assert fetch_wheel.rewrite(url) == url


def test_rewrite_is_idempotent():
    url = ('https://download-r2.pytorch.org/whl/cu130/torch-2.10.0%2Bcu130'
           '-cp312-cp312-win_amd64.whl')
    assert fetch_wheel.rewrite(fetch_wheel.rewrite(url)) == fetch_wheel.rewrite(url)


# ------------------------------------------------------------ wheel 挑选

_WHEELS = [
    ('torch-2.9.0+cu130-cp312-cp312-win_amd64.whl', 'u/2.9.0'),
    ('torch-2.9.1+cu130-cp312-cp312-win_amd64.whl', 'u/2.9.1'),
    ('torch-2.10.0+cu130-cp312-cp312-win_amd64.whl', 'u/2.10.0'),
    ('torch-2.14.1+cu130-cp312-cp312-win_amd64.whl', 'u/2.14.1'),
]


def test_pick_explicit_version():
    name, url = fetch_wheel.pick(_WHEELS, '2.10.0')
    assert name == 'torch-2.10.0+cu130-cp312-cp312-win_amd64.whl'
    assert url == 'u/2.10.0'


def test_pick_default_is_numerically_newest():
    """2.10.0 必须被认成比 2.9.1 新 —— 字符串比较会判反。"""
    name, _ = fetch_wheel.pick(_WHEELS, None)
    assert name == 'torch-2.14.1+cu130-cp312-cp312-win_amd64.whl'


def test_pick_default_beats_lexicographic_order():
    wheels = [
        ('torch-2.9.0+cu130-cp312-cp312-win_amd64.whl', 'u/a'),
        ('torch-2.10.0+cu130-cp312-cp312-win_amd64.whl', 'u/b'),
    ]
    assert fetch_wheel.pick(wheels, None)[1] == 'u/b'


def test_pick_unknown_version_raises():
    with pytest.raises(SystemExit) as exc:
        fetch_wheel.pick(_WHEELS, '9.9.9')
    assert '9.9.9' in str(exc.value)


def test_pick_empty_raises():
    with pytest.raises(SystemExit):
        fetch_wheel.pick([], None)


# ------------------------------------------------------------ 索引解析

_FAKE_INDEX = """
<!DOCTYPE html><html><body>
<a href="torch-2.10.0%2Bcu130-cp312-cp312-win_amd64.whl#sha256=abc">a</a>
<a href="torch-2.10.0%2Bcu130-cp312-cp312-win_amd64.whl#sha256=abc">dup</a>
<a href="torch-2.10.0%2Bcu130-cp313-cp313-win_amd64.whl#sha256=d">newer py</a>
<a href="torch-2.10.0%2Bcu130-cp312-cp312-manylinux_2_28_x86_64.whl#sha256=e">linux</a>
<a href="torch-2.10.0%2Bcu130-cp312-cp312-macosx_11_0_arm64.whl#sha256=f">mac</a>
<a href="../../">parent</a>
</body></html>
"""


class _FakeResponse:
    def __init__(self, body):
        self._body = body.encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_list_wheels_filters_platform_and_python(monkeypatch):
    """只保留 cp312 + win_amd64,并且能剥掉 #sha256= 片段。"""
    monkeypatch.setattr(fetch_wheel, '_open',
                        lambda url, headers=None, timeout=60: _FakeResponse(_FAKE_INDEX))
    got = fetch_wheel.list_wheels('torch')
    assert len(got) == 1
    name, url = got[0]
    assert name == 'torch-2.10.0+cu130-cp312-cp312-win_amd64.whl'
    assert name.endswith('.whl') and '#' not in name
    assert url.endswith('.whl')


def test_list_wheels_drops_linux_and_macos(monkeypatch):
    monkeypatch.setattr(fetch_wheel, '_open',
                        lambda url, headers=None, timeout=60: _FakeResponse(_FAKE_INDEX))
    names = [n for n, _ in fetch_wheel.list_wheels('torch')]
    assert not any('linux' in n or 'macosx' in n for n in names)


# ------------------------------------------------------------ 环境闸门

@pytest.mark.skipif(not os.path.exists(_PY), reason='workspace interpreter missing')
def test_check_env_exits_zero():
    """check_env.py 是交付前必须跑通的环境自检。"""
    r = subprocess.run([_PY, os.path.join(_TOOLS, 'check_env.py')],
                       cwd=_REPO_ROOT, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'RESULT: all checks passed' in r.stdout


@pytest.mark.skipif(not os.path.exists(_PY), reason='workspace interpreter missing')
def test_check_env_reports_gpu_compute():
    """torch 装好后,自检必须真的验证 GPU 能算,而不只是报告 is_available。"""
    r = subprocess.run([_PY, os.path.join(_TOOLS, 'check_env.py')],
                       cwd=_REPO_ROOT, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=300)
    assert 'torch GPU compute' in r.stdout
