"""
预训练模型下载工具的测试。

覆盖 tools/fetch_model.py 里不依赖网络的逻辑:
  - 目录布局与本地路径推导
  - 环境变量前置条件(镜像 / xet / 缓存目录)
  - 文件白名单(只取 PyTorch 权重,不重复下 flax/tf)
  - 模型目录校验的失败分支(缺文件 / 缺权重)
  - CLI 的 --list / --check 退出码

真实的"加载模型跑前向"由 tools/fetch_model.py --check 覆盖(需要模型已下载),
这里不发网络请求。
"""

import importlib
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import fetch_model  # noqa: E402


@pytest.fixture()
def tmpdir():
    """沙箱安全的临时目录(不用 pytest 的 tmp_path,见交接文档)。"""
    import shutil
    import tempfile
    path = tempfile.mkdtemp(prefix='model-test-')
    yield path
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------- 环境前置

def test_mirror_env_is_set_before_hub_import():
    """必须指向 hf-mirror,直连 huggingface.co 在本机不通。"""
    assert fetch_model.os.environ['HF_ENDPOINT'] == 'https://hf-mirror.com'


def test_xet_disabled():
    """xet 协议在镜像上返回 404,必须禁用。"""
    assert fetch_model.os.environ['HF_HUB_DISABLE_XET'] == '1'


def test_hf_home_inside_workspace():
    """默认缓存目录在沙箱下不可写,必须落在工作区内。"""
    home = fetch_model.os.environ['HF_HOME']
    assert os.path.normcase(home).startswith(
        os.path.normcase(fetch_model._WS))


# ---------------------------------------------------------------- 白名单

def test_allowlist_has_pytorch_weights_and_tokenizer():
    for f in ('config.json', 'vocab.txt', 'tokenizer.json'):
        assert f in fetch_model.ALLOW


def test_allowlist_excludes_duplicate_frameworks():
    """flax/tf 权重与 PyTorch 等价,每份 ~400MB,不应下载。"""
    for f in ('flax_model.msgpack', 'tf_model.h5', 'README.md'):
        assert f not in fetch_model.ALLOW


def test_meta_and_weights_are_separate_lists():
    """权重必须与元数据分开 —— 否则没法只挑一种权重格式。"""
    assert 'config.json' in fetch_model.META
    assert 'config.json' not in fetch_model.WEIGHTS
    for w in fetch_model.WEIGHTS:
        assert w not in fetch_model.META
    assert set(fetch_model.ALLOW) == set(fetch_model.META) | set(fetch_model.WEIGHTS)


def test_pick_weight_prefers_safetensors(monkeypatch):
    """两种权重都在时只取 safetensors,不能两个都下。"""
    class _S:
        def __init__(self, n):
            self.rfilename = n

    class _Api:
        def model_info(self, repo):
            return type('I', (), {'siblings': [
                _S('config.json'), _S('pytorch_model.bin'),
                _S('model.safetensors'), _S('flax_model.msgpack')]})()

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, 'HfApi', _Api)
    picked = fetch_model.pick_weight('any/repo')
    assert picked == ['model.safetensors']


def test_pick_weight_falls_back_to_bin(monkeypatch):
    """仓库只有 pytorch_model.bin 时要能退回去(rbt3 就是这种)。"""
    class _S:
        def __init__(self, n):
            self.rfilename = n

    class _Api:
        def model_info(self, repo):
            return type('I', (), {'siblings': [
                _S('config.json'), _S('pytorch_model.bin')]})()

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, 'HfApi', _Api)
    assert fetch_model.pick_weight('hfl/rbt3') == ['pytorch_model.bin']


def test_pick_weight_degrades_when_listing_fails(monkeypatch, capsys):
    """查不到清单时不能直接失败,应退化成"两种都试"。"""
    class _Api:
        def model_info(self, repo):
            raise RuntimeError('network down')

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, 'HfApi', _Api)
    picked = fetch_model.pick_weight('any/repo')
    assert picked == list(fetch_model.WEIGHTS)
    assert 'warn' in capsys.readouterr().out


# ---------------------------------------------------------------- 路径

def test_local_dir_under_models():
    p = fetch_model.local_dir('bert-base-chinese')
    assert p == os.path.join(fetch_model.MODELS_DIR, 'bert-base-chinese')
    assert os.path.normcase(p).startswith(os.path.normcase(fetch_model._WS))


def test_default_model_in_catalog():
    assert fetch_model.DEFAULT in fetch_model.CATALOG


def test_catalog_entries_are_repo_desc_pairs():
    for name, entry in fetch_model.CATALOG.items():
        assert isinstance(entry, tuple) and len(entry) == 2
        repo, desc = entry
        assert repo and desc, '模型 %s 缺仓库名或说明' % name


# ---------------------------------------------------------------- verify 失败分支

def test_verify_missing_dir(tmpdir):
    ok, detail = fetch_model.verify('no-such-model-xyz')
    assert ok is False
    assert '不存在' in detail


def test_verify_missing_files(tmpdir, monkeypatch):
    monkeypatch.setattr(fetch_model, 'MODELS_DIR', tmpdir)
    os.makedirs(fetch_model.local_dir('partial'))
    ok, detail = fetch_model.verify('partial')
    assert ok is False
    assert 'config.json' in detail


def test_verify_missing_weights(tmpdir, monkeypatch):
    """有 config 和分词器但没有权重 —— 必须报出来。"""
    monkeypatch.setattr(fetch_model, 'MODELS_DIR', tmpdir)
    d = fetch_model.local_dir('noweight')
    os.makedirs(d)
    for f in ('config.json', 'tokenizer.json', 'vocab.txt'):
        with open(os.path.join(d, f), 'w', encoding='utf-8') as fh:
            fh.write('{}')
    ok, detail = fetch_model.verify('noweight')
    assert ok is False
    assert '权重' in detail


# ---------------------------------------------------------------- CLI

def test_cli_list_exits_zero(capsys):
    sys.argv = ['fetch_model.py', '--list']
    assert fetch_model.main() == 0
    out = capsys.readouterr().out
    assert 'bert-base-chinese' in out
    assert 'rbt3' in out


def test_cli_unknown_model_exits_nonzero(capsys):
    sys.argv = ['fetch_model.py', '--name', 'nope']
    rc = fetch_model.main()
    assert rc == 2
    assert '未知模型' in capsys.readouterr().out


@pytest.mark.parametrize('arg', ['--list', '--check'])
def test_cli_modes_are_offline(arg, capsys):
    """--list / --check 都不应触发下载:没有已下载模型时 --check 也不报错。"""
    sys.argv = ['fetch_model.py', arg]
    rc = fetch_model.main()
    assert rc in (0, 1)
    assert capsys.readouterr().out
