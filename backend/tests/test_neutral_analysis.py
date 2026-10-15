"""
中性类瓶颈分析工具的测试(tools/analyze_neutral.py)。

这个脚本的产物要写进论文,所以每个数字的定义都必须锁死:
  - is_question 的判据若变了,报告里所有问句占比都会跟着变
  - error_flow 的两种口径若算错,论文的"核心对比"就是错的
    (曾经算错过一次:只统计"流向中性"的 227 个,漏掉了
     中性被误判成负面/正面的 158 个,把 73% 说成了 43%)
  - render 的分节编号若写错,报告会出现裸的"四"这样的残句
    (Python 的 % 比条件表达式优先级高,踩过一次)

不加载模型、不跑训练:只测纯逻辑。
"""

import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import analyze_neutral as an  # noqa: E402


# ---------------------------------------------------------------- 问句判据

@pytest.mark.parametrize('text,expected', [
    ('明天会涨吗?', True),
    ('明天会涨吗？', True),          # 全角问号
    ('这也能叫利好?  ', True),       # 尾部空白不影响
    ('明天会涨吗', False),           # 没有问号就不算(窄口径)
    ('今天涨停了', False),
    ('', False),
    (None, False),
])
def test_is_question(text, expected):
    assert an.is_question(text) is expected


@pytest.mark.parametrize('text,expected', [
    ('明天会涨吗', True),            # 句末语气词
    ('这是为什么呢', True),
    ('怎么回事', True),              # 疑问词
    ('是否应该买入', True),
    ('明天会涨吗?', True),
    ('今天涨停了', False),
    ('大盘暴跌', False),
])
def test_is_question_loose(text, expected):
    assert an.is_question_loose(text) is expected


def test_loose_is_superset_of_narrow():
    """宽口径必须覆盖窄口径,否则"两个口径都报"就没意义。"""
    samples = ['明天涨吗?', '为什么呢', '怎么回事', '涨停了', '割肉走人']
    for s in samples:
        if an.is_question(s):
            assert an.is_question_loose(s), s


# ---------------------------------------------------------------- 问句统计

def test_question_stats_counts_per_class():
    texts = ['涨吗?', '跌吗?', '涨停', '利好吗?']
    labels = [2, 2, 1, 0]           # 0=负 1=正 2=中性
    st = an.question_stats(texts, labels)

    assert st['n'] == 4
    assert st['question'] == 3
    assert st['question_ratio'] == 0.75

    assert st['per_class']['neutral']['n'] == 2
    assert st['per_class']['neutral']['question'] == 2
    assert st['per_class']['neutral']['question_ratio'] == 1.0
    assert st['per_class']['positive']['question'] == 0
    assert st['per_class']['positive']['question_ratio'] == 0.0
    assert st['per_class']['negative']['question'] == 1


def test_question_stats_label_dist():
    """问句落在哪些类别 —— 这是"复合标签"的核心证据。"""
    texts = ['a?', 'b?', 'c?', 'd']
    labels = [2, 2, 0, 1]
    st = an.question_stats(texts, labels)
    assert st['question_label_dist'] == {
        'negative': 1, 'positive': 0, 'neutral': 2}


def test_question_stats_skips_absent_class():
    """某个类别一条都没有时不能除零。"""
    st = an.question_stats(['涨吗?'], [2])
    assert 'positive' not in st['per_class']
    assert st['per_class']['neutral']['question_ratio'] == 1.0


# ---------------------------------------------------------------- 错误流向

def test_error_flow_boundary_vs_polarity():
    """两种口径都要算对,且必须互斥、求和等于总错误数。"""
    # 行=真实 0/1/2,列=预测 0/1/2
    cm = [
        [10, 1, 2],   # 真负面:1 条错判正面(极性),2 条错判中性(边界)
        [3, 10, 4],   # 真正面:3 条错判负面(极性),4 条错判中性(边界)
        [5, 6, 10],   # 真中性:5 条错判负面(边界),6 条错判正面(边界)
    ]
    f = an.error_flow(cm, ['negative', 'positive', 'neutral'])

    assert f['total_errors'] == 1 + 2 + 3 + 4 + 5 + 6
    assert f['polarity_errors'] == 1 + 3          # 只算 负<->正
    assert f['boundary_errors'] == 2 + 4 + 5 + 6  # 任一边是中性
    assert f['boundary_errors'] + f['polarity_errors'] == f['total_errors']
    assert f['boundary_share'] + f['polarity_share'] == pytest.approx(1.0)


def test_error_flow_sink_counts_incoming_only():
    """口径一按预测类别归并,只数"别人错判成我",不含我错判成别人。"""
    cm = [
        [0, 1, 2],
        [3, 0, 4],
        [5, 6, 0],
    ]
    f = an.error_flow(cm, ['negative', 'positive', 'neutral'])
    by = {s['label']: s['absorbed'] for s in f['sinks']}
    # 按列取:negative 列 = 3 + 5;不含 negative 自己错判出去的 1 + 2
    assert by['negative'] == 3 + 5
    assert by['positive'] == 1 + 6
    assert by['neutral'] == 2 + 4
    # 三个 sink 之和 = 全部错误(所有非对角元素)
    assert sum(by.values()) == 1 + 2 + 3 + 4 + 5 + 6 == f['total_errors']


def test_error_flow_sinks_sorted_desc():
    cm = [[0, 1, 9], [1, 0, 1], [2, 2, 0]]
    f = an.error_flow(cm, ['negative', 'positive', 'neutral'])
    got = [s['absorbed'] for s in f['sinks']]
    assert got == sorted(got, reverse=True)


def test_error_flow_pairs_exclude_diagonal():
    cm = [[5, 2], [3, 7]]
    f = an.error_flow(cm, ['negative', 'positive'])
    assert all(p['true'] != p['pred'] for p in f['pairs'])
    assert {p['n'] for p in f['pairs']} == {2, 3}


def test_error_flow_perfect_matrix_has_no_errors():
    cm = [[5, 0], [0, 7]]
    f = an.error_flow(cm, ['negative', 'positive'])
    assert f['total_errors'] == 0
    assert f['boundary_share'] == 0.0
    assert f['polarity_share'] == 0.0
    assert f['pairs'] == []


def test_error_flow_without_neutral_class():
    """二分类(无中性)时,全部错误都算极性互错。"""
    cm = [[5, 2], [3, 7]]
    f = an.error_flow(cm, ['negative', 'positive'])
    assert f['boundary_errors'] == 0
    assert f['polarity_errors'] == 5
    assert f['polarity_share'] == 1.0


# ---------------------------------------------------------------- 子集指标

def test_subset_metrics_accuracy_and_macro_f1():
    y_true = [0, 0, 1, 1]
    y_pred = [0, 0, 1, 0]
    m = an.subset_metrics(y_true, y_pred, ['negative', 'positive'])
    assert m['n'] == 4
    assert m['accuracy'] == 0.75
    assert m['per_class']['negative']['recall'] == 1.0
    assert m['per_class']['positive']['recall'] == 0.5


def test_subset_metrics_empty_is_none():
    assert an.subset_metrics([], [], ['negative']) is None


def test_subset_metrics_handles_absent_class():
    """子集里没有某一类时,该类的 recall 为 None 而不是 0。

    0 会被读成"全错",而实际上只是没有样本 —— 报告里会误导读者。
    """
    m = an.subset_metrics([0, 0], [0, 0], ['negative', 'positive'])
    assert m['per_class']['positive']['support'] == 0
    assert m['per_class']['positive']['recall'] is None


# ---------------------------------------------------------------- 渲染

def _flow():
    return an.error_flow(
        [[10, 1, 2], [3, 10, 4], [5, 6, 10]],
        ['negative', 'positive', 'neutral'])


def _qstats():
    return an.question_stats(['a?', 'b?', 'c', 'd?'], [2, 2, 0, 1])


def test_render_has_no_bare_section_number():
    """分节编号必须拼进标题里。

    曾经写成 `'## %s、...' % '五' if sec == 5 else '四'`,
    由于 % 优先级高于条件表达式,else 分支只输出裸的"四"。
    """
    text = an.render(_qstats(), _qstats(), _flow())
    for line in text.splitlines():
        assert line.strip() not in ('四', '五'), '出现了裸的分节编号'


def test_render_conclusion_number_follows_sections():
    """没有第四节时结论是"四",有第四节时是"五"。"""
    no_sec4 = an.render(_qstats(), _qstats(), _flow())
    assert '## 四、结论与改进方向' in no_sec4
    assert '## 五、结论与改进方向' not in no_sec4

    with_sec4 = an.render(
        _qstats(), _qstats(), _flow(),
        noq={'n_train': 100, 'accuracy': 0.75, 'macro_f1': 0.74},
        base={'n_train': 200, 'accuracy': 0.74, 'macro_f1': 0.73})
    assert '## 五、结论与改进方向' in with_sec4
    assert '## 四、结论与改进方向' not in with_sec4


def test_render_reports_both_error_flow_calibres():
    """两种口径都必须出现在报告里 —— 只报一种会被质疑挑了有利算法。"""
    text = an.render(_qstats(), _qstats(), _flow())
    assert '口径一' in text
    assert '口径二' in text
    assert '牵涉中性边界' in text
    assert '负面与正面直接互错' in text


def test_render_works_without_optional_sections():
    """缺模型/缺指标时不能崩 —— 干净检出跑不出切分实验。"""
    text = an.render(_qstats(), _qstats(), None)
    assert '# 中性类瓶颈分析' in text
    assert '结论与改进方向' in text


def test_render_flags_accuracy_f1_divergence():
    """问句组 acc 更高但宏 F1 更低时,报告必须点出这个反直觉现象。

    这是本实验最容易误读的地方:只看准确率会得出
    "模型处理问句更好"的错误结论。
    """
    split = {
        'overall': {'n': 100, 'accuracy': 0.75, 'macro_f1': 0.74},
        'statement': {'n': 70, 'accuracy': 0.74, 'macro_f1': 0.74,
                      'per_class': {}, 'label_dist': {}},
        'question': {'n': 30, 'accuracy': 0.79, 'macro_f1': 0.65,
                     'per_class': {}, 'label_dist': {'neutral': 20}},
    }
    text = an.render(_qstats(), _qstats(), _flow(), split=split)
    assert '反直觉' in text
    assert '宏 F1' in text


def test_render_retrain_section_uses_both_metrics():
    text = an.render(
        _qstats(), _qstats(), _flow(),
        noq={'n_train': 100, 'accuracy': 0.76, 'macro_f1': 0.75},
        base={'n_train': 200, 'accuracy': 0.75, 'macro_f1': 0.74})
    assert '剔除问句' in text
    assert '+0.0100' in text      # 准确率差
    assert '+0.0100' in text      # 宏 F1 差(数值相同也要各报一次)


def test_render_has_reproduce_command():
    text = an.render(_qstats(), _qstats(), _flow())
    assert 'tools\\analyze_neutral.py' in text


def test_render_command_mentions_train_flag_only_when_run():
    """生成命令要如实反映本次是否跑了重训。

    否则读者照抄命令会得到一份少了第四节的报告,以为脚本坏了。
    """
    without = an.render(_qstats(), _qstats(), _flow())
    assert 'analyze_neutral.py --train' not in without

    with_train = an.render(
        _qstats(), _qstats(), _flow(),
        noq={'n_train': 100, 'accuracy': 0.76, 'macro_f1': 0.75},
        base={'n_train': 200, 'accuracy': 0.75, 'macro_f1': 0.74})
    assert 'analyze_neutral.py --train' in with_train


def test_render_section4_heading_does_not_prejudge():
    """第四节标题不能预先下结论 —— 实测结果与"问句是噪声"相反。

    标题写死结论、正文给出相反数字,是论文里最容易被抓住的把柄。
    """
    text = an.render(
        _qstats(), _qstats(), _flow(),
        noq={'n_train': 100, 'accuracy': 0.76, 'macro_f1': 0.75},
        base={'n_train': 200, 'accuracy': 0.75, 'macro_f1': 0.74})
    assert '检验问句到底是不是噪声' in text
    assert '## 四、去掉问句重训:训练数据里的问句是噪声' not in text


def test_read_prev_noq_absent_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(an, 'EXP_DIR', str(tmp_path))
    assert an._read_prev_noq() is None


def test_read_prev_noq_reads_retrain_artifact(tmp_path, monkeypatch):
    """必须读 bert-3class-noq.json —— neutral-split.json 每次都会被重写。"""
    import json
    monkeypatch.setattr(an, 'EXP_DIR', str(tmp_path))
    with open(os.path.join(str(tmp_path), 'bert-3class-noq.json'), 'w',
              encoding='utf-8') as fh:
        json.dump({'n_train': 5988, 'accuracy': 0.7437}, fh)
    prev = an._read_prev_noq()
    assert prev['n_train'] == 5988


def test_read_prev_noq_survives_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(an, 'EXP_DIR', str(tmp_path))
    with open(os.path.join(str(tmp_path), 'bert-3class-noq.json'), 'w',
              encoding='utf-8') as fh:
        fh.write('{ not json')
    assert an._read_prev_noq() is None


# ---------------------------------------------------------------- 常量

def test_labels_are_pinned():
    """标签顺序锁死 —— 混淆矩阵的行列顺序依赖它。"""
    assert an.LABELS == ['negative', 'positive', 'neutral']
    assert an.LABELS_4 == ['negative', 'positive', 'neutral_stmt', 'neutral_q']


def test_hyperparams_match_trainer():
    """拆问句重训必须用与 train_sentiment 完全相同的超参数。

    否则"删掉问句后指标变化"里混进了超参数差异,对比就不公平。
    """
    import train_sentiment as ts
    assert an.SEED == ts.SEED
    assert an.MAX_LEN == ts.MAX_LEN
    assert an.BATCH_SIZE == ts.BATCH_SIZE
    assert an.EPOCHS == ts.EPOCHS
    assert an.LR == ts.LR


def test_pct_format():
    assert an.pct(0.5) == '50.00%'
    assert an.pct(0) == '0.00%'
    assert an.pct(1) == '100.00%'


# ---------------------------------------------------------------- 真实产物

def test_real_report_exists_and_is_consistent():
    """跑过分析后,报告与 json 必须自洽。"""
    md = os.path.join(an.EXP_DIR, 'NEUTRAL_ANALYSIS.md')
    js = os.path.join(an.EXP_DIR, 'neutral-split.json')
    if not os.path.isfile(md) or not os.path.isfile(js):
        pytest.skip('尚未跑过 tools/analyze_neutral.py')

    import json
    with open(js, encoding='utf-8') as fh:
        payload = json.load(fh)

    flow = payload['error_flow']
    # 两种口径互斥且求和等于总错误数
    assert flow['boundary_errors'] + flow['polarity_errors'] == flow['total_errors']

    # 训练集问句占比应与数据集实测一致
    tr = payload['train_questions']
    assert tr['n'] == 8516
    assert tr['question'] == 2528

    with open(md, encoding='utf-8') as fh:
        text = fh.read()
    assert '牵涉中性边界' in text
    assert '%d' % flow['boundary_errors'] in text
