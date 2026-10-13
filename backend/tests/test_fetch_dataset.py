"""
数据集工具测试。

覆盖 CSV 解析与校验逻辑 —— 这两处关系到"论文实验数据是否可信",
必须测到位。不发网络请求,用临时文件构造样本。
"""

import os
import sys

import pytest

# tools/ 不是包,把仓库根的 tools 目录加进 sys.path 再导入。
# 本文件在 <repo>/backend/tests/ 下,故上溯三级到仓库根。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import fetch_dataset  # noqa: E402


@pytest.fixture()
def tmpdir():
    """沙箱安全的临时目录(不用 pytest 的 tmp_path,见交接文档)。"""
    import shutil
    import tempfile
    path = tempfile.mkdtemp(prefix='ds-test-')
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _write(directory, name, content):
    p = os.path.join(directory, name)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(content)
    return p


# ---------------------------------------------------------------- 解析

def test_read_rows_basic(tmpdir):
    p = _write(tmpdir, 'a.csv', 'title,label\nhello,1\nworld,0\n')
    assert fetch_dataset.read_rows(p) == [('hello', '1'), ('world', '0')]


def test_read_rows_skips_blank_lines(tmpdir):
    p = _write(tmpdir, 'a.csv', 'title,label\nhello,1\n\n\nworld,0\n')
    assert len(fetch_dataset.read_rows(p)) == 2


def test_read_rows_handles_comma_in_title(tmpdir):
    """标题含逗号时,只能按最后一个逗号切分,否则标签会被切坏。"""
    p = _write(tmpdir, 'a.csv', 'title,label\n贵州茅台,重回股王,1\n')
    rows = fetch_dataset.read_rows(p)
    assert rows == [('贵州茅台,重回股王', '1')]


def test_read_rows_handles_multiple_commas(tmpdir):
    p = _write(tmpdir, 'a.csv', 'title,label\na,b,c,d,2\n')
    assert fetch_dataset.read_rows(p) == [('a,b,c,d', '2')]


def test_read_rows_strips_quotes(tmpdir):
    p = _write(tmpdir, 'a.csv', 'title,label\n"quoted",1\n')
    assert fetch_dataset.read_rows(p)[0][0] == 'quoted'


def test_read_rows_header_only(tmpdir):
    p = _write(tmpdir, 'a.csv', 'title,label\n')
    assert fetch_dataset.read_rows(p) == []


def test_read_rows_skips_lines_without_comma(tmpdir):
    p = _write(tmpdir, 'a.csv', 'title,label\nnocommahere\nok,1\n')
    assert fetch_dataset.read_rows(p) == [('ok', '1')]


# ---------------------------------------------------------------- 标签

def test_label_names_complete():
    assert set(fetch_dataset.LABEL_NAMES) == {'0', '1', '2'}
    assert fetch_dataset.LABEL_NAMES['0'] == '负面'
    assert fetch_dataset.LABEL_NAMES['1'] == '正面'
    assert fetch_dataset.LABEL_NAMES['2'] == '中性'


def test_files_are_the_expected_two():
    assert fetch_dataset.FILES == ['train.csv', 'test.csv']


# ---------------------------------------------------------------- 校验

def _point_outputs_at(monkeypatch, directory):
    """把脚本的输出目录指向临时目录。"""
    monkeypatch.setattr(fetch_dataset, 'OUT_DIR', directory)
    monkeypatch.setattr(fetch_dataset, 'EXPECTED_MIN', {})


def test_check_missing_files_fails(monkeypatch, tmpdir):
    _point_outputs_at(monkeypatch, tmpdir)
    assert fetch_dataset.check() == 1


def test_check_valid_dataset_passes(monkeypatch, tmpdir):
    _point_outputs_at(monkeypatch, tmpdir)
    _write(tmpdir, 'eastmoney_train.csv',
           'title,label\n' + '\n'.join('title%d,1' % i for i in range(10)))
    _write(tmpdir, 'eastmoney_test.csv',
           'title,label\n' + '\n'.join('other%d,0' % i for i in range(10)))
    assert fetch_dataset.check() == 0


def test_check_detects_overlap(monkeypatch, tmpdir):
    """训练/测试重叠 = 数据泄漏,必须报错。"""
    _point_outputs_at(monkeypatch, tmpdir)
    shared = '\n'.join('same%d,1' % i for i in range(5))
    _write(tmpdir, 'eastmoney_train.csv', 'title,label\n' + shared)
    _write(tmpdir, 'eastmoney_test.csv', 'title,label\n' + shared)
    assert fetch_dataset.check() == 1


def test_check_detects_illegal_label(monkeypatch, tmpdir):
    _point_outputs_at(monkeypatch, tmpdir)
    _write(tmpdir, 'eastmoney_train.csv', 'title,label\na,9\n')
    _write(tmpdir, 'eastmoney_test.csv', 'title,label\nb,0\n')
    assert fetch_dataset.check() == 1


def test_check_detects_empty_title(monkeypatch, tmpdir):
    _point_outputs_at(monkeypatch, tmpdir)
    _write(tmpdir, 'eastmoney_train.csv', 'title,label\n,1\nok,0\n')
    _write(tmpdir, 'eastmoney_test.csv', 'title,label\nb,0\n')
    assert fetch_dataset.check() == 1


def test_check_enforces_min_size(monkeypatch, tmpdir):
    monkeypatch.setattr(fetch_dataset, 'OUT_DIR', tmpdir)
    monkeypatch.setattr(fetch_dataset, 'EXPECTED_MIN',
                        {'train.csv': 100, 'test.csv': 100})
    _write(tmpdir, 'eastmoney_train.csv', 'title,label\na,1\n')
    _write(tmpdir, 'eastmoney_test.csv', 'title,label\nb,0\n')
    assert fetch_dataset.check() == 1


def test_local_path_uses_expected_prefix(monkeypatch, tmpdir):
    monkeypatch.setattr(fetch_dataset, 'OUT_DIR', tmpdir)
    p = fetch_dataset.local_path('train.csv')
    assert p.endswith('eastmoney_train.csv')
    assert os.path.dirname(p) == tmpdir
