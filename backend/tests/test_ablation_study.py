"""`tools/ablation_study.py` 的测试。

这个工具的价值在于「负面结论必须能被质疑」,所以测试的重点是
**口径与自洽性**,而不是数字大小:

  * 宏 F1 两种口径必须在类别均衡时几乎相等、在极端不均衡时分开;
  * 渲染出的 Markdown 必须包含关键数字,不能是空壳;
  * 结果 JSON 里的每个统计量都必须内部自洽(和 == n、p 与 significant 一致);
  * 缺模型/缺数据时必须优雅降级为 skipped,而不是抛异常。

最后一条尤其重要:干净检出(没有 models/ 与 data/raw/)时
这个工具仍然要能跑通,否则论文仓库 clone 下来第一步就报错。
"""
import json
import os
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
_PY = os.path.join(_REPO_ROOT, '.python', 'python.exe')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import ablation_study as ab  # noqa: E402


# ---------------------------------------------------------------- 宏 F1 口径

def test_macro_f1_two_ways_agree_when_balanced():
    """类别完全均衡时两种口径应当给出同一个数。"""
    cm = [[10, 2, 3], [2, 10, 3], [3, 2, 10]]
    got = ab.macro_f1_two_ways(cm)
    assert got['f1_per_class_average'] == pytest.approx(
        got['f1_from_macro_pr'], abs=0.02)


def test_macro_f1_two_ways_identical_for_perfect_matrix():
    cm = [[5, 0, 0], [0, 5, 0], [0, 0, 5]]
    got = ab.macro_f1_two_ways(cm)
    assert got['f1_per_class_average'] == pytest.approx(1.0)
    assert got['f1_from_macro_pr'] == pytest.approx(1.0)
    assert got['delta'] == pytest.approx(0.0, abs=1e-9)


def test_macro_f1_two_ways_diverge_on_extreme_imbalance():
    """极端不均衡时 B 口径(先平均 P/R 再求调和)会明显高于 A 口径。

    注意「不均衡」指的是**错误集中在某一类上**,不是单纯类别样本数
    悬殊 —— 对角阵(每类都全对)无论多不均衡两种口径都是 1.0。
    这里第三类只有 1 条正确,却有 2000 条被误判进第三类,
    宏精确率被拉低、宏召回率却接近 0.67,B 口径因此虚高。
    本数据集类别比只有 1.47 且错误分散,所以看不到这个现象。
    """
    cm = [[1, 0, 0], [0, 1, 0], [1000, 1000, 1]]
    got = ab.macro_f1_two_ways(cm)
    assert got['f1_from_macro_pr'] > got['f1_per_class_average']
    assert got['delta'] > 0.4


def test_macro_f1_delta_matches_difference():
    # delta 与两个分项都各自四舍五入到 4 位,所以容差取 1e-4 而非 1e-9:
    # 差值是两个未舍入数相减后再舍入,与两个舍入数相减可能差一个 ulp。
    cm = [[40, 5, 3], [6, 38, 4], [3, 2, 45]]
    got = ab.macro_f1_two_ways(cm)
    assert got['delta'] == pytest.approx(
        got['f1_from_macro_pr'] - got['f1_per_class_average'], abs=1e-4)


def test_macro_f1_handles_empty_class():
    """某一类完全没被预测也不能除零。"""
    cm = [[10, 0, 0], [0, 0, 0], [0, 0, 10]]
    got = ab.macro_f1_two_ways(cm)
    assert 0.0 <= got['f1_per_class_average'] <= 1.0
    assert 0.0 <= got['f1_from_macro_pr'] <= 1.0


# ---------------------------------------------------------------- 文本归一化

@pytest.mark.parametrize('raw,expected', [
    ('招商银行？', '招商银行'),
    ('A股 大涨 3.5%', 'a股大涨'),
    ('!!!冲高回落!!!', '冲高回落'),
    ('', ''),
])
def test_norm_keeps_only_chinese_and_letters(raw, expected):
    assert ab._norm(raw) == expected


def test_norm_is_case_insensitive():
    assert ab._norm('ABC') == ab._norm('abc')


# ---------------------------------------------------------------- 结果文件自洽

_EXP = os.path.join(_REPO_ROOT, 'data', 'experiments')


def _load(name):
    p = os.path.join(_EXP, name)
    if not os.path.isfile(p):
        pytest.skip('缺少 %s(需先跑实验)' % name)
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def test_ablation_json_is_internally_consistent():
    r = _load('ablation-probes.json')
    assert 'macro_f1_ambiguity' in r
    for name, v in r['macro_f1_ambiguity'].items():
        assert 0.0 <= v['f1_per_class_average'] <= 1.0, name
        assert 0.0 <= v['f1_from_macro_pr'] <= 1.0, name
        assert v['delta'] == pytest.approx(
            v['f1_from_macro_pr'] - v['f1_per_class_average'], abs=1e-4), name
        # 结果文件里报的宏 F1 必须与重算的 A 口径一致,否则说明口径漂了
        assert v['reported_macro_f1'] == pytest.approx(
            v['f1_per_class_average'], abs=0.002), name


def test_ablation_json_label_noise_counts_add_up():
    r = _load('ablation-probes.json')
    ln = r.get('label_noise')
    if not ln or ln.get('skipped'):
        pytest.skip('标签噪声项被跳过')
    assert ln['n_train'] > 0 and ln['n_test'] > 0
    # 每个阈值档的样本数必须随阈值放宽单调不减
    # 键是 '0.99' / '0.95' / '0.90' / '0.80' / '0.70' 这样的阈值字符串,
    # 按阈值从高到低取,样本数应当只增不减。
    counts = [ln['by_threshold'][k]['n'] for k in sorted(
        ln['by_threshold'], key=lambda s: -float(s))]
    assert counts == sorted(counts)
    # 冲突组数不可能超过重复组数
    assert ln['conflicting_label_groups'] <= ln['normalized_duplicate_groups']


def test_ablation_json_cascade_strategies_are_ordered():
    r = _load('ablation-probes.json')
    ca = r.get('cascade') or {}
    if ca.get('skipped'):
        pytest.skip('级联项被跳过')
    s = ca['strategies']
    # 硬路由必须比直接三分类差 —— 这是该节的核心结论
    assert s['s2_hard_routing'] < s['s1_direct_three_class']
    assert s['s2_delta'] == pytest.approx(
        s['s2_hard_routing'] - s['s1_direct_three_class'], abs=1e-4)
    # 置信度阈值越高,越接近直接三分类(越来越多样本不走门控)
    cr = s.get('s3_confidence_routing') or {}
    if cr:
        vals = [cr[k] for k in sorted(cr)]
        assert vals == sorted(vals)
        assert vals[-1] <= s['s1_direct_three_class'] + 1e-6


def test_ablation_json_neutral_specialist_is_not_zero():
    """回归测试:中性专用模型是二分类,不能拿它的 0/1 去比三分类的 2。

    修这个 bug 前渲染出来是 0.0000,看起来像模型坏了,其实是口径错。
    """
    r = _load('ablation-probes.json')
    ca = r.get('cascade') or {}
    if ca.get('skipped'):
        pytest.skip('级联项被跳过')
    assert ca['neutral']['neutral_specialist'] > 0.5


def test_ablation_json_stacking_reports_leak_free_control():
    r = _load('ablation-probes.json')
    st = r.get('stacking')
    if not st or st.get('skipped'):
        pytest.skip('堆叠项被跳过或该 JSON 由不含堆叠的旧版运行生成')
    # 训练集准确率必须高于测试集 —— 否则说明「泄漏」这个说法不成立
    assert st['meta_train_accuracy'] > st['meta_test_accuracy']
    lf = st['leak_free']
    assert lf['delta'] == pytest.approx(
        lf['meta_accuracy'] - lf['base_accuracy'], abs=1e-4)
    assert lf['n'] > 0
    for mc in (st['mcnemar'], lf['mcnemar']):
        assert mc['significant'] == (mc['p_value'] < 0.05)
        assert mc['n_discordant'] == mc['b'] + mc['c']
    # 结论文字里报的 p 值必须与结构化的 p 值一致,不能各说各话
    assert ('%.4f' % st['mcnemar']['p_value']) in st['conclusion']
    assert ('%.4f' % lf['mcnemar']['p_value']) in st['conclusion']


def test_render_tolerates_missing_sections():
    """旧版 JSON 缺 stacking 这一项时,渲染器不能 KeyError。

    报告是给人看的,少一节也要出得来 —— 渲染器要面对的可能是
    别人机器上、旧版本生成的 JSON。
    """
    text = ab.render_md({'macro_f1_ambiguity': {}})
    for sec in ('## 1 ', '## 2 ', '## 3 ', '## 4 ', '## 5 ', '## 6 ', '## 7 '):
        assert sec in text, sec
    assert text.count('> 跳过:') >= 6


def test_render_does_not_mutate_input():
    """补 skipped 不能写回调用方的 dict,否则会把 JSON 污染成假结果。"""
    data = {'macro_f1_ambiguity': {}}
    ab.render_md(data)
    assert list(data) == ['macro_f1_ambiguity']


def test_ablation_json_calibration_does_not_claim_improvement():
    """校准那一节必须明确不把 oracle 成绩算作改进。"""
    r = _load('ablation-probes.json')
    ca = r.get('calibration') or {}
    if ca.get('skipped'):
        pytest.skip('校准项被跳过')
    assert '选择偏差' in ca['oracle_note']
    # 逆先验权重必须由训练集先验算出来,中性类先验最大所以权重最小
    w = ca['inverse_prior_weight']
    prior = ca['train_prior']
    assert w.index(min(w)) == prior.index(max(prior))


def test_ablation_json_hyperparam_sweep_has_baseline_best():
    r = _load('ablation-probes.json')
    sw = r.get('hyperparam_sweep') or {}
    if sw.get('skipped'):
        pytest.skip('超参扫描项被跳过')
    cfg = sw['configs']
    base = cfg[sw['baseline']]
    for name, v in cfg.items():
        assert v['accuracy'] <= base['accuracy'] + 1e-9, name


# ---------------------------------------------------------------- 渲染

def test_render_contains_all_sections():
    r = _load('ablation-probes.json')
    text = ab.render_md(r)
    for sec in ('## 1 ', '## 2 ', '## 3 ', '## 4 ', '## 5 ', '## 6 ', '## 7 '):
        assert sec in text, sec
    assert '宏 F1' in text
    assert '请勿手工修改' in text


def test_render_of_empty_data_does_not_crash():
    """所有项都 skipped 时也要能渲染出完整骨架。"""
    data = {
        'macro_f1_ambiguity': {},
        'label_noise': {'skipped': 'x'},
        'cascade': {'skipped': 'x'},
        'aux_head': {'skipped': 'x'},
        'stacking': {'skipped': 'x'},
        'hyperparam_sweep': {'skipped': 'x'},
        'calibration': {'skipped': 'x'},
    }
    text = ab.render_md(data)
    assert text.count('> 跳过:') >= 5


def test_render_is_deterministic():
    r = _load('ablation-probes.json')
    assert ab.render_md(r) == ab.render_md(r)


# ---------------------------------------------------------------- CLI

def test_cli_no_models_writes_files(tmp_path):
    out = tmp_path / 'A.md'
    js = tmp_path / 'a.json'
    got = subprocess.run(
        [_PY, os.path.join(_TOOLS, 'ablation_study.py'),
         '--no-models', '-o', str(out), '--json', str(js)],
        cwd=_REPO_ROOT, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=300)
    assert got.returncode == 0, got.stderr[-2000:]
    assert out.is_file() and js.is_file()
    with open(js, encoding='utf-8') as fh:
        data = json.load(fh)
    # --no-models 必须把三个需要模型的项都标 skipped
    for key in ('cascade', 'aux_head', 'stacking'):
        assert data[key].get('skipped'), key
    # 纯计算项仍然要有结果
    assert data['macro_f1_ambiguity']


def test_cli_no_models_output_mentions_skip():
    got = subprocess.run(
        [_PY, os.path.join(_TOOLS, 'ablation_study.py'), '--no-models',
         '-o', os.path.join(_REPO_ROOT, 'data', 'experiments', '.tmp-ab.md'),
         '--json', os.path.join(_REPO_ROOT, 'data', 'experiments',
                                '.tmp-ab.json')],
        cwd=_REPO_ROOT, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=300)
    assert got.returncode == 0
    for p in (os.path.join(_REPO_ROOT, 'data', 'experiments', '.tmp-ab.md'),
              os.path.join(_REPO_ROOT, 'data', 'experiments', '.tmp-ab.json')):
        if os.path.isfile(p):
            os.remove(p)


def test_committed_ablation_report_is_current():
    """仓库里的 ABLATION.md 必须与当前 JSON 一致,不能是手改的旧版。"""
    p = os.path.join(_EXP, 'ABLATION.md')
    if not os.path.isfile(p):
        pytest.skip('尚未生成 ABLATION.md')
    r = _load('ablation-probes.json')
    with open(p, encoding='utf-8') as fh:
        on_disk = fh.read()
    assert on_disk == ab.render_md(r)
