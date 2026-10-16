"""
多任务/标签重构与多种子集成工具的测试。

这两处逻辑都涉及"改标签"或"合预测",错了不会报错、只会悄悄
让准确率变化,所以必须用纯逻辑测试钉住:

  1. train_multitask.build_labels 的 4 分类拆分 —— 若把陈述句
     误判成问句,中性类会被对半劈错,而训练照样跑得下去。
     这里必须与 analyze_neutral.is_question 的口径完全一致。
  2. train_multitask.combine 的类号约定 —— 它依赖
     "0/1 = 极性、>= 2 = 中性" 这个不变量。若哪天有人调整了
     类别顺序,combine 会把中性样本当成极性 0 用,静默出错。
  3. ensemble_sentiment 的概率平均 —— 类别顺序必须一致,
     否则平均出来的是无意义的数。

不加载 BERT、不跑训练:真实数字由 data/experiments/*.json 保证。
"""

import json
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import ensemble_sentiment  # noqa: E402
import train_multitask  # noqa: E402
import train_sentiment  # noqa: E402


# ---------------------------------------------------------------- 标签重构

def test_mtl_mode_keeps_three_labels():
    labs, names = train_multitask.build_labels(
        ['涨了', '跌了', '怎么样'], [1, 0, 2], 'mtl')
    assert labs == [1, 0, 2]
    assert names == list(train_sentiment.LABELS)


def test_4class_splits_neutral_by_question_mark():
    labs, names = train_multitask.build_labels(
        ['还会涨吗？', '今天天气不错', '跌了', '涨了'], [2, 2, 0, 1], '4class')
    # 中性问句 -> 2,中性陈述 -> 3,极性类原样保留
    assert labs == [2, 3, 0, 1]
    assert names == train_multitask.FOUR_LABELS


def test_4class_question_particle_without_mark_is_statement():
    """「吗/呢/吧」结尾但无问号 -> 算陈述。

    这是**故意**的窄口径:analyze_neutral.is_question 只看句末问号。
    宽口径(is_question_loose)才把语气词算进来,但 4 分类用的是窄口径,
    否则中性问句占比会从 48.28% 涨到 50.21%,和报告里的数字对不上。
    """
    labs, _ = train_multitask.build_labels(['明天会涨吗'], [2], '4class')
    assert labs == [3]
    # 加个问号就变成问句
    labs2, _ = train_multitask.build_labels(['明天会涨吗？'], [2], '4class')
    assert labs2 == [2]


def test_4class_statement_with_inner_question_word_is_not_question():
    """窄口径:只有问号结尾才算问句。

    「什么」出现在句中是疑问词,但句子本身是陈述,
    宽口径会把它误判成问句 —— 这里钉住用的是窄口径。
    """
    labs, _ = train_multitask.build_labels(['我不知道为什么跌'], [2], '4class')
    assert labs == [3]


def test_4class_never_changes_polarity_labels():
    """4 分类只动中性类,极性类的标签必须一个都不变。"""
    texts = ['涨', '跌', '吗？', '吧', '呢', '好']
    labs = [1, 0, 2, 2, 2, 1]
    out, _ = train_multitask.build_labels(texts, labs, '4class')
    for i, lb in enumerate(labs):
        if lb != 2:
            assert out[i] == lb, '极性类 %d 被改成了 %d' % (lb, out[i])


def test_4class_preserves_total_count():
    texts = ['a', 'b?', 'c', 'd?']
    labs = [2, 2, 0, 1]
    out, _ = train_multitask.build_labels(texts, labs, '4class')
    assert len(out) == len(labs)


def test_4class_neutral_stays_inside_neutral_range():
    """不变量:>= NEUTRAL_FROM 一定是中性。

    combine 与辅助头的掩码都依赖这一点。
    """
    texts = ['吗？', '吧', '呢', '陈述句', '？']
    labs = [2] * 5
    out, _ = train_multitask.build_labels(texts, labs, '4class')
    assert all(v >= train_multitask.NEUTRAL_FROM for v in out)


def test_unknown_mode_raises():
    with pytest.raises(SystemExit):
        train_multitask.build_labels(['x'], [2], 'nosuch')


# ---------------------------------------------------------------- 组合策略

def test_combine_uses_polarity_head_only_for_polarity():
    """主头判为极性(< NEUTRAL_FROM)时,改用极性头的值。"""
    p_main = [0, 1, 2, 3]
    p_pol = [1, 0, 1, 0]
    # 前两个主头判为极性 -> 取 p_pol;后两个主头判为中性 -> 保留主头
    assert train_multitask.combine(p_main, p_pol) == [1, 0, 2, 3]


def test_combine_keeps_main_when_neutral():
    """主头判为中性时,原样保留主头的类号(不被极性头覆盖)。"""
    out = train_multitask.combine([2, 3], [0, 1])
    assert out == [2, 3]


def test_combine_output_is_valid_label_set():
    p_main = [0, 1, 2, 3, 0, 2]
    p_pol = [1, 0, 0, 1, 1, 1]
    out = train_multitask.combine(p_main, p_pol)
    assert set(out) <= {0, 1, 2, 3}
    assert len(out) == len(p_main)


# ---------------------------------------------------------------- 集成

def test_average_probs_is_elementwise_mean():
    import numpy as np
    a = np.array([[1.0, 0.0], [0.0, 1.0]])
    b = np.array([[0.0, 1.0], [0.0, 1.0]])
    got = ensemble_sentiment.average_probs([a, b])
    assert np.allclose(got, [[0.5, 0.5], [0.0, 1.0]])


def test_average_probs_requires_same_shape():
    import numpy as np
    with pytest.raises(ValueError):
        ensemble_sentiment.average_probs(
            [np.zeros((2, 3)), np.zeros((3, 3))])


def test_average_probs_single_model_is_identity():
    import numpy as np
    a = np.array([[0.2, 0.8], [0.6, 0.4]])
    assert np.allclose(ensemble_sentiment.average_probs([a]), a)


def test_seed_dir_seed42_reuses_baseline_directory():
    """种子 42 就是基线,必须指向同目录,否则会白训一份。"""
    d = ensemble_sentiment.seed_dir(train_sentiment.SEED)
    assert os.path.basename(d) == 'sentiment-bert-3class'
    assert 'seed' not in os.path.basename(d)


def test_seed_dir_others_are_distinct():
    a = ensemble_sentiment.seed_dir(1)
    b = ensemble_sentiment.seed_dir(2)
    assert a != b
    assert a.endswith('sentiment-bert-3class-seed1')
    assert b.endswith('sentiment-bert-3class-seed2')


def test_default_seeds_include_baseline_seed():
    """默认种子集合必须含基线种子,否则 delta_vs_seed42 无从计算。"""
    assert train_sentiment.SEED in ensemble_sentiment.DEFAULT_SEEDS
    assert len(ensemble_sentiment.DEFAULT_SEEDS) >= 2


# ------------------------------------------------------- 显著性检验

def test_mcnemar_identical_predictions_is_not_significant():
    """两个模型预测完全一样时,没有任何可判别的差异。

    此时 b=c=0,必须报不显著 —— 若这里报显著,说明公式把
    "没有不一致样本" 当成了 "差异极大"。
    """
    y = [0, 1, 2, 0, 1, 2]
    r = ensemble_sentiment.mcnemar_exact(y, y, y)
    assert r['b'] == 0 and r['c'] == 0
    assert r['n_discordant'] == 0
    assert r['significant'] is False


def test_mcnemar_counts_only_discordant_cells():
    """b/c 只统计两者预测不一致的样本,两边都错的样本不计入。"""
    y = [0, 0, 0, 0]
    a = [0, 0, 1, 1]   # a 对 2 个、错 2 个
    b = [1, 1, 1, 1]   # b 全错
    # 样本 0: a 对 b 错 -> b 格;样本 1: 同 -> b 格
    # 样本 2: 两边都错 -> 不计;样本 3: 同 -> 不计
    r = ensemble_sentiment.mcnemar_exact(y, a, b)
    assert r['b'] == 2
    assert r['c'] == 0
    assert r['n_discordant'] == 2


def test_mcnemar_symmetric_swap_flips_cells():
    """交换两个模型的顺序,b 与 c 应对调。"""
    y = [0, 0, 0, 0, 0, 0, 0, 0]
    a = [0, 0, 0, 0, 0, 0, 1, 1]
    b = [1, 1, 1, 1, 1, 1, 1, 1]
    r1 = ensemble_sentiment.mcnemar_exact(y, a, b)
    r2 = ensemble_sentiment.mcnemar_exact(y, b, a)
    assert r1['b'] == r2['c']
    assert r1['c'] == r2['b']


def test_mcnemar_large_asymmetry_is_significant():
    """一边压倒性地对、另一边压倒性地错,应当判显著。"""
    n = 40
    y = [0] * n
    good = [0] * n                    # 全对
    bad = [1] * (n - 1) + [0]         # 只对 1 个
    r = ensemble_sentiment.mcnemar_exact(y, good, bad)
    assert r['b'] == n - 1
    assert r['c'] == 0
    assert r['p_value'] < 0.05
    assert r['significant'] is True


def test_bootstrap_delta_of_identical_predictions_is_zero():
    """同一组预测自己减自己,差必须恒为 0,置信区间退化到 0。"""
    y = [0, 1, 2] * 20
    p = list(y)
    r = ensemble_sentiment.bootstrap_delta(y, p, p, rounds=200)
    assert r['accuracy']['mean'] == 0.0
    assert r['macro_f1']['mean'] == 0.0
    assert r['accuracy']['ci95'] == [0.0, 0.0]
    assert r['accuracy']['p_gt_zero'] == 0.0


def test_bootstrap_delta_detects_clear_improvement():
    """新模型明显更好时,区间下界应当为正。"""
    y = [0] * 50 + [1] * 50
    old = [0] * 100            # 只对一半
    new = list(y)              # 全对
    r = ensemble_sentiment.bootstrap_delta(y, new, old, rounds=500)
    assert r['accuracy']['mean'] > 0.4
    assert r['accuracy']['ci95'][0] > 0
    assert r['accuracy']['p_gt_zero'] == 1.0


def test_bootstrap_delta_is_deterministic_for_a_seed():
    """同一个 seed 必须给同一个结果,否则报告里的数字无法复现。"""
    y = [0, 1, 2, 0, 1, 2] * 20
    new = [0, 1, 2, 0, 1, 2] * 20
    old = [1, 1, 2, 0, 2, 2] * 20
    a = ensemble_sentiment.bootstrap_delta(y, new, old, rounds=300, seed=7)
    b = ensemble_sentiment.bootstrap_delta(y, new, old, rounds=300, seed=7)
    assert a == b


def test_main_rejects_single_seed():
    with pytest.raises(SystemExit):
        ensemble_sentiment.main(['--seeds', '42', '--reuse'])


def test_main_rejects_non_integer_seeds():
    with pytest.raises(SystemExit):
        ensemble_sentiment.main(['--seeds', 'a,b'])


# ---------------------------------------------------------------- 真实产物

def test_real_multitask_results_are_consistent():
    """本机跑过的多任务结果必须自洽。"""
    for mode in ('mtl', '4class'):
        path = os.path.join(_REPO_ROOT, 'data', 'experiments', '%s.json' % mode)
        if not os.path.isfile(path):
            pytest.skip('本机尚未跑过多任务实验')
        with open(path, encoding='utf-8') as fh:
            r = json.load(fh)
        assert 0.0 <= r['accuracy'] <= 1.0, mode
        assert 0.0 <= r['macro_f1'] <= 1.0, mode
        assert r['n_test'] > 0
        cm = r['confusion_matrix']
        assert sum(sum(row) for row in cm) == r['n_test'], mode
        assert r['mode'] == mode
        # 辅助头准确率也必须在合法区间
        for k in ('aux_polarity_head_acc', 'aux_neutral_head_acc'):
            assert 0.0 <= r[k] <= 1.0, (mode, k)
        assert 0.0 <= r['combined']['accuracy'] <= 1.0, mode


def test_real_ensemble_result_is_consistent():
    path = os.path.join(_REPO_ROOT, 'data', 'experiments', 'ensemble-3class.json')
    if not os.path.isfile(path):
        pytest.skip('本机尚未跑过集成实验')
    with open(path, encoding='utf-8') as fh:
        r = json.load(fh)
    assert r['model'] == 'ensemble'
    assert r['n_seeds'] == len(r['seeds']) >= 2
    assert 0.0 <= r['accuracy'] <= 1.0
    assert 0.0 <= r['macro_f1'] <= 1.0
    cm = r['confusion_matrix']
    assert sum(sum(row) for row in cm) == r['n_test']
    # 每个种子的单独成绩都要在
    assert len(r['individual_seeds']) == r['n_seeds']
    for s, v in r['individual_seeds'].items():
        assert 0.0 <= v['accuracy'] <= 1.0, s
    # 种子跨度必须与 individual_seeds 自洽
    accs = [v['accuracy'] for v in r['individual_seeds'].values()]
    assert r['seed_spread']['accuracy_min'] == min(accs)
    assert r['seed_spread']['accuracy_max'] == max(accs)
    assert r['seed_spread']['accuracy_range'] == pytest.approx(
        max(accs) - min(accs), abs=1e-4)


def test_real_ensemble_reports_significance():
    """集成结果必须带显著性检验,且内部自洽。

    为什么钉这个:只报一个 +0.0113 的准确率差,读者无从判断
    它是真的还是测试集恰好合适。McNemar 与 bootstrap 是让这个
    数字可被质疑的部分 —— 少了它,报告就退化成自我表扬。
    """
    path = os.path.join(_REPO_ROOT, 'data', 'experiments', 'ensemble-3class.json')
    if not os.path.isfile(path):
        pytest.skip('本机尚未跑过集成实验')
    with open(path, encoding='utf-8') as fh:
        r = json.load(fh)
    sig = r['significance']
    assert sig is not None
    assert sig['baseline'] == 'seed42'

    mc = sig['mcnemar']
    assert mc['b'] + mc['c'] == mc['n_discordant']
    assert 0.0 <= mc['p_value'] <= 1.0
    # significant 必须与 p 值一致,不能手写
    assert mc['significant'] == (mc['p_value'] < 0.05)

    for key in ('accuracy', 'macro_f1'):
        bs = sig['bootstrap'][key]
        assert bs['ci95'][0] <= bs['mean'] <= bs['ci95'][1], key
        assert 0.0 <= bs['p_gt_zero'] <= 1.0, key
    # 准确率与宏F1 的 bootstrap 必须都做了
    assert sig['bootstrap']['rounds'] >= 1000

    # 独立性对照必须存在,且用的是不含基线种子的那批种子
    dj = sig['disjoint_check']
    assert train_sentiment.SEED not in dj['seeds']
    assert dj['delta_vs_seed42'] == pytest.approx(
        dj['accuracy'] - r['individual_seeds'][str(train_sentiment.SEED)]['accuracy'],
        abs=1e-4)
    assert dj['mcnemar']['b'] + dj['mcnemar']['c'] == dj['mcnemar']['n_discordant']


def test_ensemble_result_not_picked_up_by_route_report():
    """集成结果的 model 名是 ensemble,不能被混进两条路线对比表。"""
    import experiment_report
    exp_dir = os.path.join(_REPO_ROOT, 'data', 'experiments')
    results = experiment_report.load_results(exp_dir)
    for (task, model) in results:
        assert model in ('tfidf', 'bert'), (task, model)
        assert task in ('3class', 'polarity', 'neutral'), (task, model)
