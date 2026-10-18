"""
采集与出图辅助工具的测试(tools/collect_corpus.py、tools/check_datasource.py、
tools/make_figures.py 的取数函数)。

这三处都不是"论文数字"的直接来源,但它们决定数据能不能采对、图和表会不会
对不上,所以按同一套标准测:纯逻辑单测,不发网络请求。

要点:
  1. **股票池外不猜市场。** 原来 `_select_stocks` 对不认识的代码默认 'SH',
     深市 000/300 开头的会被当成沪市,行情接口静默返回空数据。
  2. **import 不发网络。** check_datasource 原来在模块级执行全部请求,
     任何 import 它的脚本都会顺手打外网。
  3. **图里的数字从实验文件算。** 写死一份、JSON 里一份,改了实验必有
     一边忘改,而 Word 打开之前看不出来。
"""

import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import check_datasource  # noqa: E402
import collect_corpus  # noqa: E402
import make_figures  # noqa: E402


# ------------------------------------------------------------ 股票选择

def test_default_pool_is_returned_when_no_codes():
    pool = collect_corpus._select_stocks('')
    assert len(pool) >= 13
    assert all(len(x) == 3 for x in pool)


def test_codes_in_pool_keep_their_name_and_market():
    got = collect_corpus._select_stocks('600519,000001')
    assert got == [('600519', '贵州茅台', 'SH'), ('000001', '平安银行', 'SZ')]


def test_unknown_code_is_rejected_instead_of_guessed():
    """池子外的代码必须显式带市场 —— 猜成 SH 会让深市股票采不到行情。"""
    with pytest.raises(SystemExit) as exc:
        collect_corpus._select_stocks('688981')
    msg = str(exc.value)
    assert '688981' in msg
    assert '代码:市场' in msg


def test_explicit_market_is_accepted():
    assert collect_corpus._select_stocks('688981:SH') == [
        ('688981', '688981', 'SH')]
    assert collect_corpus._select_stocks('688981:sz') == [
        ('688981', '688981', 'SZ')]


def test_invalid_market_is_rejected():
    with pytest.raises(SystemExit) as exc:
        collect_corpus._select_stocks('688981:XX')
    assert 'SH / SZ / BJ' in str(exc.value)


# ------------------------------------------------------------ JSON 切片

def test_json_slice_parses_jsonp():
    assert check_datasource._json_slice('cb({"a": 1});') == {'a': 1}


def test_json_slice_returns_none_without_braces():
    """响应体里没有大括号时要返回 None,不能切出空串再抛解析错误。"""
    assert check_datasource._json_slice('no json here') is None


def test_json_slice_returns_none_on_broken_json():
    assert check_datasource._json_slice('{broken') is None


def test_importing_check_datasource_does_not_touch_network():
    """模块导入不得发请求 —— 上面已经 import 过,能跑到这里就说明没发。"""
    assert callable(check_datasource.main)
    assert hasattr(check_datasource, 'check_eastmoney_kline')
    # 每条探测都是一个函数,由 main 串起来,而不是模块级代码
    src = open(check_datasource.__file__, encoding='utf-8').read()
    body_after_import = src.split('if __name__ ==')[0]
    assert 'urllib.request.urlopen' in body_after_import  # 在 get() 里
    assert 'kline_ok = True' not in body_after_import


# ------------------------------------------------------------ 出图取数

def test_label_dist_matches_csv_order():
    """标签分布按 negative/positive/neutral 的顺序返回,与 LABELS 对齐。"""
    tr = make_figures._label_dist('eastmoney_train.csv')
    assert tr == [2529, 2406, 3581]


def test_label_dist_sums_to_row_count():
    tr = make_figures._label_dist('eastmoney_train.csv')
    te = make_figures._label_dist('eastmoney_test.csv')
    assert sum(tr) == 8516
    assert sum(te) == 2130


def test_task_metrics_matches_json():
    """图 4-1 的六个数组必须与表 4-1 的 JSON 完全一致。"""
    m = make_figures._task_metrics()
    assert m['tasks'] == ['A 三分类', 'B 二分类极性', 'C 中性 vs 有情感']
    assert m['bert_acc'] == pytest.approx([0.7540, 0.8435, 0.8099])
    assert m['tfidf_acc'] == pytest.approx([0.6296, 0.7546, 0.7352])
    assert m['bert_f1'] == pytest.approx([0.7491, 0.8435, 0.7962])
    assert m['tfidf_f1'] == pytest.approx([0.6204, 0.7540, 0.7093])
    assert m['major'] == pytest.approx([0.4089, 0.5091, 0.5911])


def test_task_metrics_reads_from_experiment_files():
    """改一个 JSON 里的数,图的数据源要跟着变 —— 证明不是写死的。"""
    real = make_figures._load_json

    def fake(name):
        data = real(name)
        if name == 'bert-3class.json':
            data = dict(data)
            data['accuracy'] = 0.1234
        return data

    make_figures._load_json = fake
    try:
        got = make_figures._task_metrics()
    finally:
        make_figures._load_json = real
    assert got['bert_acc'][0] == pytest.approx(0.1234)


def test_cjk_font_candidates_are_not_pinned_to_windows():
    """字体候选必须包含跨平台目录,不能只有 C:/Windows/Fonts。"""
    cands = list(make_figures._cjk_font_candidates())
    assert cands
    joined = '|'.join(cands)
    assert '/usr/share/fonts' in joined or 'fonts' in joined
    assert os.path.join(_REPO_ROOT, 'fonts') in joined


def test_cjk_font_candidates_honour_env(tmp_path, monkeypatch):
    """设了 BIYESHEJI_FONTS 就直接用它的路径。"""
    f = tmp_path / 'myfont.ttc'
    f.write_bytes(b'fake')
    monkeypatch.setenv('BIYESHEJI_FONTS', str(f))
    assert list(make_figures._cjk_font_candidates())[0] == str(f)
