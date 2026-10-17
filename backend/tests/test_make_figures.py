"""论文配图生成器的测试(tools/make_figures.py)。

论文里 13 张图全部由实测数据生成,没有一张是手绘或估算的 —— 这条原则
要靠测试守住,否则下次改了实验数值、忘了重画图,正文和图就会对不上,
而 Word 打开之前看不出来。

这里锁四件事:

  1. **图号清单与初稿里的插图一致。** 少一张是多出来一个引用不到的空号,
     多一张是画了没人用的图。
  2. **每张图都是真 PNG 且有内容。** 生成函数静默失败时 matplotlib 仍会
     写一个文件,但可能是空的或全白,所以查文件头和体积下限。
  3. **图 7-3 不由脚本生成。** 它是系统界面截图,必须作者本人截;
     脚本若偷偷画一张占位图,反而会掩盖"还没截"这个待办。
  4. **词元长度缓存与表 3-3 的口径一致。** 论文写的是">64 词元 2 条、
     最长 74",这个数字必须能从缓存重算出来。

不跑全量渲染(13 张要十几秒),只渲染一张验证管线通。
"""

import csv
import json
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import make_figures  # noqa: E402

_FIG_DIR = os.path.join(_REPO_ROOT, '论文', 'figures')
_EXP = os.path.join(_REPO_ROOT, 'data', 'experiments')

# 初稿正文里实际嵌入的图号(与 test_thesis_draft 的插图检查互为印证)
_EXPECTED = {'1-1', '2-1', '3-1', '3-2', '4-1', '4-2',
             '5-1', '5-2', '5-3', '6-1', '7-1', '7-2', '7-4'}

_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


# ---------------------------------------------------------------- 图号清单

def test_figures_registry_covers_expected_numbers():
    assert set(make_figures.FIGURES) == _EXPECTED


def test_screenshot_figure_is_not_generated():
    """图 7-3 是界面截图,脚本不能替它画一张占位图。

    画了占位图就等于把"还没截"这个待办藏起来了,而定稿前必须有人
    真的去截 —— 藏起来比缺着更危险。
    """
    assert '7-3' not in make_figures.FIGURES


def test_every_registered_figure_is_callable():
    for name, fn in make_figures.FIGURES.items():
        assert callable(fn), '图 %s 的生成器不可调用' % name


# ---------------------------------------------------------------- 产物校验

def test_generated_png_files_match_registry():
    """论文/figures 下有的图,必须都在 FIGURES 里登记;反之亦然。"""
    if not os.path.isdir(_FIG_DIR):
        pytest.skip('还没生成过图')
    on_disk = set()
    for fn in os.listdir(_FIG_DIR):
        if fn.startswith('fig-') and fn.endswith('.png'):
            on_disk.add(fn[len('fig-'):-len('.png')])
    missing = _EXPECTED - on_disk
    assert not missing, '这些图登记了但没生成: %s' % sorted(missing)
    extra = on_disk - _EXPECTED
    assert not extra, '这些图生成了但初稿没引用: %s' % sorted(extra)


def test_every_generated_png_is_a_real_image():
    """文件头必须是 PNG 魔数,体积不能小到像空图。"""
    if not os.path.isdir(_FIG_DIR):
        pytest.skip('还没生成过图')
    bad = []
    for name in sorted(_EXPECTED):
        path = os.path.join(_FIG_DIR, 'fig-%s.png' % name)
        if not os.path.isfile(path):
            bad.append('%s(缺文件)' % name)
            continue
        with open(path, 'rb') as fh:
            head = fh.read(8)
        if head != _PNG_MAGIC:
            bad.append('%s(不是 PNG)' % name)
        elif os.path.getsize(path) < 10 * 1024:
            bad.append('%s(只有 %d 字节,像是空图)'
                       % (name, os.path.getsize(path)))
    assert not bad, '这些图有问题: %s' % ', '.join(bad)


# ---------------------------------------------------------------- 渲染管线

def test_one_figure_renders_to_png(tmp_path, monkeypatch):
    """渲染一张验证管线通(全量渲染太慢,单张够用)。"""
    monkeypatch.setattr(make_figures, '_FIG_DIR', str(tmp_path))
    path = make_figures.FIGURES['3-1'](100)
    assert os.path.isfile(path)
    with open(path, 'rb') as fh:
        assert fh.read(8) == _PNG_MAGIC
    assert os.path.getsize(path) > 5 * 1024


def test_unknown_figure_name_exits_with_hint(capsys):
    code = make_figures.main(['--only', '9-9'])
    assert code == 2
    out = capsys.readouterr().out
    assert '9-9' in out and '可用图号' in out


def test_main_always_reminds_about_screenshot(tmp_path, monkeypatch, capsys):
    """即使只画一张,也要提醒图 7-3 需人工截取。"""
    monkeypatch.setattr(make_figures, '_FIG_DIR', str(tmp_path))
    assert make_figures.main(['--only', '3-1', '--dpi', '100']) == 0
    out = capsys.readouterr().out
    assert '7-3' in out and '截' in out


# ---------------------------------------------------------------- 数据口径

def test_token_length_cache_matches_table_3_3():
    """表 3-3 报「>64 词元 2 条、最长 74」,必须能从缓存重算出来。"""
    cache = os.path.join(_EXP, 'token_lengths.json')
    if not os.path.isfile(cache):
        pytest.skip('还没有词元长度缓存')
    with open(cache, encoding='utf-8') as fh:
        data = json.load(fh)

    train = data['train']
    assert len(train) == 8516, '训练集条数与 CSV 不符'
    over = [n for n in train if n > 64]
    assert len(over) == 2, '超过 64 词元的应为 2 条,实得 %d 条' % len(over)
    assert max(train) == 74, '最长应为 74 词元,实得 %d' % max(train)


def test_token_lengths_include_special_tokens():
    """口径说明:长度含 [CLS]/[SEP],所以最短也不少于 2。

    这个口径写进了 make_figures._token_lengths 的 docstring,
    论文表 3-3 也按它报数。口径变了图会跟着变,所以锁住。
    """
    cache = os.path.join(_EXP, 'token_lengths.json')
    if not os.path.isfile(cache):
        pytest.skip('还没有词元长度缓存')
    with open(cache, encoding='utf-8') as fh:
        data = json.load(fh)
    assert min(data['train']) >= 2


def test_read_csv_returns_expected_columns():
    rows = make_figures._read_csv('eastmoney_train.csv')
    assert len(rows) == 8516
    assert set(rows[0]) == {'title', 'label'}


def test_load_json_reads_experiment_file():
    data = make_figures._load_json('bert-3class.json')
    assert abs(data['accuracy'] - 0.7540) < 1e-9


def test_palette_matches_frontend():
    """图和系统界面用同一套配色,读者对照着看不费劲。"""
    assert make_figures.C_POS == '#c8443a'   # 红涨
    assert make_figures.C_NEG == '#2e7d5b'   # 绿跌
    assert make_figures.LABELS == ['负面', '正面', '中性']
