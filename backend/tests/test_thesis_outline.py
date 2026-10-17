"""
论文写作大纲(论文/论文写作大纲.md)与实验数据的一致性检查。

这份大纲的作用是给正文写作提供"可直接引用的数字",它最大的风险不是写得
不好,而是**写错一个数字**——正文照抄过去,答辩时对不上实验文件,整章结论
都会被怀疑。所以这里把大纲里出现的关键数字全部回算一遍:

    · 表 3-1 / 3-2 的分布与长度  ← 直接读 data/raw/*.csv 重算
    · 表 3-3 的近重复与冲突     ← ablation-probes.json 的 label_noise
    · 表 3-4 / 3-5 的问句统计   ← neutral-split.json 的 train/test_questions
    · 表 4-x 的三任务结果       ← REPORT.md 与 bert-*/tfidf-*.json
    · 表 5-x 的错误流向与切分   ← neutral-split.json 的 error_flow/split_eval
    · 表 6-x 的消融与显著性     ← ablation-probes.json / ensemble-3class.json
    · 表 7-x 的接口与测试数     ← backend/app/main.py 与 pytest 收集

另外守护三条"不许写"的纪律:
    ① 不许引用已被覆盖、无法复现的中间轮次结果(+0.0526);
    ② 集成不许写成"显著提升"(McNemar p=0.0583);
    ③ 不许把训练集泄漏结果 0.9864 当成成绩。

不联网、不加载模型:只读 CSV / JSON / 源码。
"""

import json
import os
import re

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_OUTLINE = os.path.join(_REPO_ROOT, '论文', '论文写作大纲.md')
_EXP = os.path.join(_REPO_ROOT, 'data', 'experiments')
_RAW = os.path.join(_REPO_ROOT, 'data', 'raw')


# ---------------------------------------------------------------- 读取工具

def _outline_text():
    if not os.path.isfile(_OUTLINE):
        pytest.skip('尚无 论文/论文写作大纲.md')
    with open(_OUTLINE, encoding='utf-8') as fh:
        return fh.read()


def _load_json(name):
    path = os.path.join(_EXP, name)
    if not os.path.isfile(path):
        pytest.skip('缺少实验结果 %s' % name)
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _read_csv_labels():
    """读原始数据集,返回 [(训练标签列表), (测试标签列表)]。"""
    train = os.path.join(_RAW, 'eastmoney_train.csv')
    test = os.path.join(_RAW, 'eastmoney_test.csv')
    if not (os.path.isfile(train) and os.path.isfile(test)):
        pytest.skip('缺少 data/raw 数据集')

    import csv
    out = []
    for path in (train, test):
        with open(path, encoding='utf-8', newline='') as fh:
            rows = list(csv.DictReader(fh))
        out.append(rows)
    return out


def _label_counts(rows):
    counts = {0: 0, 1: 0, 2: 0}
    for r in rows:
        counts[int(r['label'])] += 1
    return counts


# ---------------------------------------------------------------- 解析大纲表格

def _table_rows(text, title):
    """取 '### 表 x-y 标题' 之后的 Markdown 表格,返回二维单元格列表。"""
    idx = text.find(title)
    if idx < 0:
        pytest.skip('大纲中未找到「%s」' % title)
    block = text[idx:]
    # 截到下一个标题
    nxt = block.find('\n### ', 1)
    if nxt > 0:
        block = block[:nxt]

    rows = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if all(re.fullmatch(r'-{2,}', c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def _find_row(rows, keyword):
    for r in rows:
        if r and keyword in r[0]:
            return r
    pytest.skip('表格中未找到含「%s」的行' % keyword)


def _num(cell):
    """从单元格里抠出第一个数字(去掉 ** 与千分位)。"""
    s = cell.replace('*', '').replace(',', '').strip()
    m = re.search(r'-?\d+(?:\.\d+)?', s)
    assert m, '单元格无数字: %r' % cell
    return float(m.group(0))


# ---------------------------------------------------------------- 表 3-1 分布

def test_table_3_1_label_counts_match_csv():
    text = _outline_text()
    rows = _table_rows(text, '### 表 3-1')
    train_rows, test_rows = _read_csv_labels()
    tr, te = _label_counts(train_rows), _label_counts(test_rows)

    expect = {
        '训练集': (tr[0], tr[1], tr[2], len(train_rows)),
        '测试集': (te[0], te[1], te[2], len(test_rows)),
        '合计': (tr[0] + te[0], tr[1] + te[1], tr[2] + te[2],
                 len(train_rows) + len(test_rows)),
    }
    for key, want in expect.items():
        row = _find_row(rows, key)
        got = tuple(int(_num(c)) for c in row[1:5])
        assert got == want, '%s 分布不符: 大纲 %s != 数据 %s' % (key, got, want)


def test_table_3_1_totals_are_10646():
    rows = _table_rows(_outline_text(), '### 表 3-1')
    total = _find_row(rows, '合计')
    assert int(_num(total[4])) == 10646


# ---------------------------------------------------------------- 类别比 1.49

def test_class_ratio_stated_as_1_49():
    """大纲与第 3 章正文都写 1.49,这里回算 3581/2406 确认。"""
    text = _outline_text()
    ratio = 3581 / 2406
    assert round(ratio, 2) == 1.49, '实际类别比 %.4f,与文中 1.49 不符' % ratio
    assert '1.49' in text, '大纲未写明类别比 1.49'


# ---------------------------------------------------------------- 表 3-3 质量

def test_table_3_3_matches_label_noise_probe():
    text = _outline_text()
    rows = _table_rows(text, '### 表 3-3')
    probe = _load_json('ablation-probes.json')['label_noise']

    # 表 3-3 是两列(核查项 | 结果),"34 组，涉及 117 条" 这种双数写在
    # 同一个单元格里,所以按「组」和「条」分别抠数字。
    def _group_and_items(keyword):
        cell = _find_row(rows, keyword)[1]
        groups = re.search(r'(\d+)\s*组', cell)
        items = re.search(r'(\d+)\s*条', cell)
        assert groups and items, '单元格格式无法解析: %r' % cell
        return int(groups.group(1)), int(items.group(1))

    got = _group_and_items('归一化后重复组')
    want = (probe['normalized_duplicate_groups'],
            probe['normalized_duplicate_items'])
    assert got == want, '归一化重复组不符: 大纲 %s != 数据 %s' % (got, want)

    got = _group_and_items('标签不一致')
    want = (probe['conflicting_label_groups'],
            probe['conflicting_label_items'])
    assert got == want, '标签冲突组不符: 大纲 %s != 数据 %s' % (got, want)


def test_table_3_3_duplicate_and_overlap_are_zero():
    """训练集内重复 0 条、训练/测试交集 0 条,是大纲的核心结论,回算确认。"""
    text = _outline_text()
    train_rows, test_rows = _read_csv_labels()
    titles_tr = [r['title'] for r in train_rows]
    titles_te = [r['title'] for r in test_rows]
    assert len(titles_tr) == len(set(titles_tr)), '训练集存在重复标题'
    assert not (set(titles_tr) & set(titles_te)), '训练/测试存在重叠'

    rows = _table_rows(text, '### 表 3-3')
    for keyword in ('训练集内完全重复标题', '训练集与测试集交集'):
        row = _find_row(rows, keyword)
        assert int(_num(row[1])) == 0, '%s 应写 0' % keyword


# ---------------------------------------------------------------- 表 3-4/3-5 问句

def test_table_3_4_train_question_stats_match():
    text = _outline_text()
    rows = _table_rows(text, '### 表 3-4')
    data = _load_json('neutral-split.json')['train_questions']

    for label, name in (('负面', 'negative'), ('正面', 'positive'),
                        ('中性', 'neutral')):
        want = data['per_class'][name]
        row = _find_row(rows, label)
        assert int(_num(row[1])) == want['n'], '%s 样本数不符' % name
        assert int(_num(row[2])) == want['question'], '%s 问句数不符' % name
        assert int(_num(row[4])) == want['question_loose'], \
            '%s 宽口径问句数不符' % name

    total = _find_row(rows, '合计')
    assert int(_num(total[2])) == data['question']
    assert int(_num(total[4])) == data['question_loose']


def test_key_question_ratios_are_correct():
    """48.28% 与 68.39% 是全文最核心的两个数字,单独回算。"""
    data = _load_json('neutral-split.json')['train_questions']
    neu = data['per_class']['neutral']

    ratio_in_neutral = neu['question'] / neu['n']
    assert round(ratio_in_neutral * 100, 2) == 48.28

    # 全部问句中被标为中性的比例
    ratio_of_questions = neu['question'] / data['question']
    assert round(ratio_of_questions * 100, 2) == 68.39

    text = _outline_text()
    assert '48.28%' in text and '68.39%' in text


def test_table_3_5_test_question_stats_match():
    text = _outline_text()
    rows = _table_rows(text, '### 表 3-5')
    data = _load_json('neutral-split.json')['test_questions']

    for label, name in (('负面', 'negative'), ('正面', 'positive'),
                        ('中性', 'neutral')):
        want = data['per_class'][name]
        row = _find_row(rows, label)
        assert int(_num(row[1])) == want['n']
        assert int(_num(row[2])) == want['question']


# ---------------------------------------------------------------- 表 4-1 三任务

def test_table_4_1_matches_report():
    text = _outline_text()
    rows = _table_rows(text, '### 表 4-1')

    cases = [
        ('A 三分类', 'bert-3class.json', 'tfidf-3class.json'),
        ('B 二分类极性', 'bert-polarity.json', 'tfidf-polarity.json'),
        ('C 中性', 'bert-neutral.json', 'tfidf-neutral.json'),
    ]
    for keyword, bert_file, tfidf_file in cases:
        bert = _load_json(bert_file)
        tfidf = _load_json(tfidf_file)
        row = _find_row(rows, keyword)
        assert abs(_num(row[3]) - tfidf['accuracy']) < 1e-9, \
            '%s TF-IDF acc 不符' % keyword
        assert abs(_num(row[4]) - tfidf['macro_f1']) < 1e-9, \
            '%s TF-IDF 宏F1 不符' % keyword
        assert abs(_num(row[5]) - bert['accuracy']) < 1e-9, \
            '%s BERT acc 不符' % keyword
        assert abs(_num(row[6]) - bert['macro_f1']) < 1e-9, \
            '%s BERT 宏F1 不符' % keyword


def test_headline_numbers_0754_and_0629_present():
    text = _outline_text()
    bert = _load_json('bert-3class.json')
    tfidf = _load_json('tfidf-3class.json')
    assert abs(bert['accuracy'] - 0.754) < 1e-9
    assert abs(tfidf['accuracy'] - 0.6296) < 1e-9
    assert '0.7540' in text
    assert '0.6296' in text


# ---------------------------------------------------------------- 表 4-4/4-5 混淆

def test_table_4_4_bert_confusion_matrix_matches():
    text = _outline_text()
    rows = _table_rows(text, '### 表 4-4')
    cm = _load_json('bert-3class.json')['confusion_matrix']

    for i, name in enumerate(('负面', '正面', '中性')):
        row = _find_row(rows, name)
        got = [int(_num(c)) for c in row[1:4]]
        assert got == cm[i], '%s 行不符: %s != %s' % (name, got, cm[i])


def test_table_4_5_tfidf_confusion_matrix_matches():
    text = _outline_text()
    rows = _table_rows(text, '### 表 4-5')
    cm = _load_json('tfidf-3class.json')['confusion_matrix']

    for i, name in enumerate(('负面', '正面', '中性')):
        row = _find_row(rows, name)
        got = [int(_num(c)) for c in row[1:4]]
        assert got == cm[i]


# ---------------------------------------------------------------- 表 5-1/5-2 错误流向

def test_table_5_1_error_sinks_match():
    text = _outline_text()
    rows = _table_rows(text, '### 表 5-1')
    sinks = {s['label']: s for s in
             _load_json('neutral-split.json')['error_flow']['sinks']}

    for label, name in (('中性', 'neutral'), ('负面', 'negative'),
                        ('正面', 'positive')):
        row = _find_row(rows, label)
        assert int(_num(row[1])) == sinks[name]['absorbed'], \
            '%s 吸收错误数不符' % name


def test_table_5_2_boundary_vs_polarity_split():
    """385 / 73.47% 与 139 / 26.53%,以及 2.8 倍,是核心章的骨架。"""
    text = _outline_text()
    rows = _table_rows(text, '### 表 5-2')

    cm = _load_json('bert-3class.json')['confusion_matrix']
    # 牵涉中性边界 = 真实或预测有一边是中性
    boundary = 0
    polarity = 0
    for i in range(3):
        for j in range(3):
            if i == j:
                continue
            if i == 2 or j == 2:
                boundary += cm[i][j]
            else:
                polarity += cm[i][j]
    total = boundary + polarity

    assert total == 524, '总错误数应为 524,实为 %d' % total
    assert boundary == 385, '牵涉中性边界应为 385,实为 %d' % boundary
    assert polarity == 139, '极性互错应为 139,实为 %d' % polarity
    assert round(boundary / total * 100, 2) == 73.47
    assert round(polarity / total * 100, 2) == 26.53
    assert round(boundary / polarity, 1) == 2.8

    row_b = _find_row(rows, '牵涉中性边界')
    assert int(_num(row_b[1])) == 385
    row_p = _find_row(rows, '负面与正面直接互错')
    assert int(_num(row_p[1])) == 139


# ---------------------------------------------------------------- 表 5-4 句式切分

def test_table_5_4_split_eval_matches():
    text = _outline_text()
    rows = _table_rows(text, '### 表 5-4')
    data = _load_json('neutral-split.json')['split_eval']

    cases = [('全部', 'overall'), ('陈述句', 'statement'), ('问句', 'question')]
    for keyword, key in cases:
        want = data[key]
        row = _find_row(rows, keyword)
        assert int(_num(row[1])) == want['n'], '%s 样本数不符' % keyword
        assert abs(_num(row[2]) - want['accuracy']) < 1e-9, \
            '%s 准确率不符' % keyword
        assert abs(_num(row[3]) - want['macro_f1']) < 1e-9, \
            '%s 宏F1 不符' % keyword


def test_question_group_has_higher_acc_but_lower_macro_f1():
    """反直觉结论:问句组 acc 更高、宏 F1 更低。这个方向性必须成立。"""
    data = _load_json('neutral-split.json')['split_eval']
    q, s = data['question'], data['statement']
    assert q['accuracy'] > s['accuracy'], '问句组准确率应更高'
    assert q['macro_f1'] < s['macro_f1'], '问句组宏 F1 应更低'
    assert q['per_class']['positive']['recall'] < 0.30, \
        '问句组正面类召回率应低于 0.30'


# ---------------------------------------------------------------- 表 5-6 剔除重训

def test_table_5_6_retrain_without_questions():
    text = _outline_text()
    rows = _table_rows(text, '### 表 5-6')
    noq = _load_json('bert-3class-noq.json')
    base = _load_json('bert-3class.json')

    row = _find_row(rows, '剔除问句')
    assert abs(_num(row[2]) - noq['accuracy']) < 1e-9
    assert abs(_num(row[3]) - noq['macro_f1']) < 1e-9
    assert int(_num(row[1])) == noq['n_train']

    # 差值方向:剔除问句后两项指标都下降
    assert noq['accuracy'] < base['accuracy']
    assert noq['macro_f1'] < base['macro_f1']
    assert round(noq['accuracy'] - base['accuracy'], 4) == -0.0103
    assert round(noq['macro_f1'] - base['macro_f1'], 4) == -0.0086


# ---------------------------------------------------------------- 表 6-1 宏 F1 口径

def test_table_6_1_macro_f1_ambiguity():
    text = _outline_text()
    rows = _table_rows(text, '### 表 6-1')
    data = _load_json('ablation-probes.json')['macro_f1_ambiguity']

    for name, want in data.items():
        row = _find_row(rows, name)
        assert abs(_num(row[1]) - want['f1_per_class_average']) < 1e-9, \
            '%s A 口径不符' % name
        assert abs(_num(row[2]) - want['f1_from_macro_pr']) < 1e-9, \
            '%s B 口径不符' % name

    max_delta = max(v['delta'] for v in data.values())
    assert round(max_delta, 4) == 0.0073, '最大差异应为 0.0073'
    assert '0.0073' in text


def test_macro_f1_citation_carries_data_condition():
    """引用文献说"差异可达 0.5"时必须同时给出本文的数据条件。"""
    text = _outline_text()
    idx = text.find('0.5')
    assert idx > 0, '大纲应提到文献中的 0.5'
    window = text[max(0, idx - 400):idx + 400]
    assert '1.49' in window or '极端不均衡' in window, \
        '提到 0.5 时必须说明数据条件,否则属于照搬文献结论'


# ---------------------------------------------------------------- 表 6-3 级联

def test_table_6_3_cascade_strategies():
    text = _outline_text()
    rows = _table_rows(text, '### 表 6-3')
    data = _load_json('ablation-probes.json')['cascade']

    assert abs(_num(_find_row(rows, 'S1 直接三分类')[1])
               - data['strategies']['s1_direct_three_class']) < 1e-9
    assert abs(_num(_find_row(rows, 'S2 硬路由级联')[1])
               - data['strategies']['s2_hard_routing']) < 1e-9

    routing = data['strategies']['s3_confidence_routing']
    for thr, want in routing.items():
        row = _find_row(rows, 't=%s' % thr)
        assert abs(_num(row[1]) - want) < 1e-9, 't=%s 不符' % thr


# ---------------------------------------------------------------- 表 6-4 多任务

def test_table_6_4_multitask_results():
    text = _outline_text()
    rows = _table_rows(text, '### 表 6-4')
    four = _load_json('4class.json')
    mtl = _load_json('mtl.json')

    row4 = _find_row(rows, '4class')
    assert abs(_num(row4[1]) - four['accuracy']) < 1e-9
    assert abs(_num(row4[2]) - four['macro_f1']) < 1e-9

    rowm = _find_row(rows, 'mtl')
    assert abs(_num(rowm[1]) - mtl['accuracy']) < 1e-9
    assert abs(_num(rowm[2]) - mtl['macro_f1']) < 1e-9


def test_multitask_did_not_beat_baseline():
    """4class 与 mtl 的准确率都必须低于三分类基线,这是"改进无效"的证据。"""
    base = _load_json('bert-3class.json')['accuracy']
    assert _load_json('4class.json')['accuracy'] < base
    assert _load_json('mtl.json')['accuracy'] < base


# ---------------------------------------------------------------- 表 6-6 超参

def test_table_6_6_sweep_matches():
    text = _outline_text()
    rows = _table_rows(text, '### 表 6-6')
    sweep = _load_json('sweep.json')

    # 大纲里的数值按 4 位小数展示,源 JSON 是全精度浮点,比较时按 4 位四舍五入。
    for key, want in sweep.items():
        row = _find_row(rows, key)
        assert round(_num(row[3]), 4) == round(want['accuracy'], 4), \
            '%s acc 不符' % key
        assert round(_num(row[4]), 4) == round(want['macro_f1'], 4), \
            '%s 宏F1 不符' % key


def test_baseline_is_best_in_sweep():
    sweep = _load_json('sweep.json')
    best = max(sweep.items(), key=lambda kv: kv[1]['accuracy'])
    assert best[0] == 'ep3_lr2e-05', '基线应已是扫描最优,实为 %s' % best[0]


# ---------------------------------------------------------------- 表 6-8/6-9 集成

def test_table_6_8_ensemble_seeds():
    text = _outline_text()
    rows = _table_rows(text, '### 表 6-8')
    ens = _load_json('ensemble-3class.json')

    # 种子号必须精确匹配第一列 —— 用子串匹配会让 '2' 命中 '42（基线）'。
    def _row_by_first_cell(value):
        for r in rows:
            if r and r[0].replace('*', '').strip() == value:
                return r
        pytest.skip('表 6-8 未找到种子 %s' % value)

    for seed, want in ens['individual_seeds'].items():
        label = '%s（基线）' % seed if seed == '42' else seed
        row = _row_by_first_cell(label)
        assert abs(_num(row[1]) - want['accuracy']) < 1e-9, \
            'seed %s acc 不符' % seed
        assert abs(_num(row[2]) - want['macro_f1']) < 1e-9

    row_ens = _find_row(rows, '5 种子概率平均')
    assert abs(_num(row_ens[1]) - ens['accuracy']) < 1e-9
    assert abs(_num(row_ens[2]) - ens['macro_f1']) < 1e-9


def test_ensemble_is_not_reported_as_significant():
    """McNemar p=0.0583 > 0.05,大纲不得把集成写成显著提升。"""
    ens = _load_json('ensemble-3class.json')
    p = ens['significance']['mcnemar']['p_value']
    assert p > 0.05, 'McNemar p 应大于 0.05,实为 %s' % p
    assert round(p, 4) == 0.0583

    text = _outline_text()
    # 大纲里出现 0.0583 的地方必须带"不显著"
    for m in re.finditer(r'0\.0583', text):
        window = text[max(0, m.start() - 120):m.start() + 120]
        assert '不显著' in window, '提到 0.0583 处未标注"不显著"'


def test_ensemble_macro_f1_bootstrap_ci_excludes_zero():
    """宏 F1 的 bootstrap 区间不含 0,这是唯一部分显著的证据,不能漏报。"""
    boot = _load_json('ensemble-3class.json')['significance']['bootstrap']
    lo, hi = boot['macro_f1']['ci95']
    assert lo > 0, '宏 F1 的 95%CI 下界应大于 0'
    acc_lo, acc_hi = boot['accuracy']['ci95']
    assert acc_lo < 0 < acc_hi, '准确率的 95%CI 应跨 0'


def test_seed_spread_is_reported():
    """种子间极差 0.0192 / 0.0236 说明单次结果带 ±1 点不确定性。"""
    spread = _load_json('ensemble-3class.json')['seed_spread']
    assert round(spread['accuracy_range'], 4) == 0.0192
    assert round(spread['macro_f1_range'], 4) == 0.0236
    text = _outline_text()
    assert '0.0192' in text and '0.0236' in text


# ---------------------------------------------------------------- 纪律:禁止引用

def test_no_unreproducible_intermediate_result():
    """+0.0526 是已被覆盖的中间轮次结果,不得作为论据引用。

    大纲里只允许它出现在"不要引用"的警告中。
    """
    text = _outline_text()
    for m in re.finditer(r'\+?0\.0526', text):
        window = text[max(0, m.start() - 200):m.start() + 100]
        assert '不要引用' in window or '已被覆盖' in window, \
            '0.0526 只能出现在"不要引用"的警告里'


def test_no_leaked_training_accuracy_as_result():
    """0.9864 是训练集泄漏结果,只能作为反面例子出现。"""
    text = _outline_text()
    for m in re.finditer(r'0\.9864', text):
        window = text[max(0, m.start() - 250):m.start() + 250]
        assert ('泄漏' in window) or ('不可引用' in window), \
            '0.9864 出现处必须标明有泄漏、不可引用'


def test_no_question_is_noise_claim():
    """不得写"问句是噪声"——剔除重训指标反而下降,否证了这一点。"""
    text = _outline_text()
    for m in re.finditer(r'问句.{0,6}(是|为)?.{0,4}噪声', text):
        window = text[max(0, m.start() - 200):m.start() + 200]
        assert ('并非' in window) or ('不是' in window) or \
               ('否证' in window) or ('不能写' in window), \
            '出现"问句是噪声"的说法但未否证'


def test_sentiment_return_conclusion_is_bounded():
    """744 样本 Pearson −0.0019 不显著,不得写成"情感分析能预测股价"。"""
    text = _outline_text()
    assert '−0.0019' in text or '-0.0019' in text

    # 只看 7.6 这一节,避免窗口跨到相邻章节
    start = text.find('#### 7.6')
    assert start >= 0, '大纲缺少 7.6 节'
    end = text.find('#### 7.7', start)
    section = text[start:end if end > 0 else len(text)]

    assert '0.0019' in section, '7.6 节应给出 Pearson −0.0019'
    assert ('未检出' in section or '不能检出' in section
            or '没有可检出' in section), \
        '7.6 节必须把结论限定为"未检出线性关系"'


# ---------------------------------------------------------------- 结构与完整性

def test_outline_has_all_eight_chapters():
    text = _outline_text()
    for i in range(1, 9):
        assert '第 %d 章' % i in text, '大纲缺少第 %d 章' % i


def test_table_numbering_has_no_gaps():
    """每个章节内的表号必须从 1 开始连续,不许跳号。"""
    text = _outline_text()
    defined = re.findall(r'^### 表 (\d+)-(\d+)', text, re.M)
    assert defined, '未解析到任何表定义'

    by_chapter = {}
    for ch, num in defined:
        by_chapter.setdefault(int(ch), []).append(int(num))

    for ch, nums in by_chapter.items():
        nums.sort()
        assert nums == list(range(1, len(nums) + 1)), \
            '第 %d 章表号不连续: %s' % (ch, nums)


def test_every_table_reference_has_a_definition():
    """正文里引用的表号必须有对应的表定义,防"引了不存在的表"。"""
    text = _outline_text()
    defined = {'%s-%s' % m for m in re.findall(r'^### 表 (\d+)-(\d+)', text, re.M)}
    referenced = {'%s-%s' % m for m in re.findall(r'表 (\d+)-(\d+)', text)}
    missing = referenced - defined
    assert not missing, '引用了不存在的表: %s' % sorted(missing)


def test_every_figure_reference_has_a_plan():
    """正文引用的图号必须在图表清单里有规划。"""
    text = _outline_text()
    planned = set(re.findall(r'^\| 图 (\d+-\d+) \|', text, re.M))
    referenced = set(re.findall(r'图 (\d+-\d+)', text))
    missing = referenced - planned
    assert not missing, '引用了未规划的图: %s' % sorted(missing)


def test_no_placeholder_left():
    text = _outline_text()
    for bad in ('待补', '待核', 'TODO', 'XXX', '???', 'FIXME'):
        assert bad not in text, '大纲残留占位符: %s' % bad


# ---------------------------------------------------------------- 系统侧数字

def test_backend_test_count_matches_outline():
    """表 7-5 写的后端测试数必须与 pytest 实际收集数一致。

    注意:本文件自身也在 tests/ 下,收集时会算进去,所以两边同源、能自洽。
    """
    import subprocess
    import sys

    text = _outline_text()
    rows = _table_rows(text, '### 表 7-5')
    row = _find_row(rows, '后端')
    stated = int(_num(row[1]))

    proc = subprocess.run(
        [sys.executable, '-m', 'pytest', 'backend/tests',
         '--collect-only', '-q', '--tb=no', '-p', 'no:cacheprovider'],
        cwd=_REPO_ROOT, capture_output=True, text=True, timeout=600)

    # -q 模式下输出形如 "368 tests collected in 0.16s",也可能被 ini 的
    # addopts 抑制掉汇总行,所以再兜一层:统计每行 "path: N" 的和。
    m = re.search(r'(\d+) tests? collected', proc.stdout)
    if m:
        actual = int(m.group(1))
    else:
        actual = sum(int(n) for n in re.findall(r':\s*(\d+)\s*$',
                                                proc.stdout, re.M))
        assert actual > 0, '无法解析 pytest 收集结果:\n%s' % proc.stdout[-2000:]

    assert stated == actual, \
        '表 7-5 写 %d 项,实际收集 %d 项' % (stated, actual)


def test_api_paths_in_outline_exist_in_source():
    """表 7-1 的每个接口路径都必须在 main.py 里真实存在。"""
    text = _outline_text()
    rows = _table_rows(text, '### 表 7-1')

    src = os.path.join(_REPO_ROOT, 'backend', 'app', 'main.py')
    if not os.path.isfile(src):
        pytest.skip('缺少 backend/app/main.py')
    with open(src, encoding='utf-8') as fh:
        code = fh.read()

    for row in rows[1:]:
        path = row[1].strip()
        if not path.startswith('/api/'):
            continue
        # /api/stocks/{code}/klines -> 源码里是 "/stocks/{code}/klines"
        bare = path[len('/api'):]
        assert bare in code, '接口 %s 在 main.py 中不存在' % path


def test_db_tables_in_outline_exist_in_models():
    """表 7-2 的三张表必须真实存在于 models.py。"""
    text = _outline_text()
    rows = _table_rows(text, '### 表 7-2')

    src = os.path.join(_REPO_ROOT, 'backend', 'app', 'models.py')
    if not os.path.isfile(src):
        pytest.skip('缺少 backend/app/models.py')
    with open(src, encoding='utf-8') as fh:
        code = fh.read()

    for row in rows[1:]:
        name = row[0].strip().strip('`')
        if not name or name.startswith('表'):
            continue
        assert 'class %s(' % name in code, '模型 %s 不存在' % name


def test_system_news_distribution_sums_to_total():
    """表 7-4 的三类之和必须等于 6420(系统实际新闻数)。"""
    text = _outline_text()
    rows = _table_rows(text, '### 表 7-4')
    total = 0
    for label in ('正面', '负面', '中性'):
        total += int(_num(_find_row(rows, label)[1]))
    assert total == 6420, '表 7-4 合计 %d,应为 6420' % total


def test_docs_agree_on_test_counts():
    """README / 交接文档 / 大纲三处的测试数必须彼此一致。

    加测试会同时让这三处过期,所以单独锁一条:三处一起改,不许只改一处。
    与 test_backend_test_count_matches_outline 的区别在于,这条只查**互相一致**,
    不查是否等于实时收集数 —— 后者由上面那条负责。
    """
    outline = _outline_text()
    rows = _table_rows(outline, '### 表 7-5')
    backend = int(_num(_find_row(rows, '后端')[1]))
    frontend = int(_num(_find_row(rows, '前端')[1]))
    total = int(_num(_find_row(rows, '合计')[1]))
    assert backend + frontend == total, '表 7-5 合计与分项不符'

    # README: "当前:**624 个测试全部通过**(后端 409 + 前端 82 + 技能安装 133)"
    readme_path = os.path.join(_REPO_ROOT, 'README.md')
    if not os.path.isfile(readme_path):
        pytest.skip('缺少 README.md')
    with open(readme_path, encoding='utf-8') as fh:
        readme = fh.read()

    m = re.search(r'后端\s*(\d+)\s*\+\s*前端\s*(\d+)', readme)
    assert m, 'README 未按「后端 N + 前端 M」写测试数'
    assert int(m.group(1)) == backend, \
        'README 后端测试数 %s 与大纲 %d 不一致' % (m.group(1), backend)
    assert int(m.group(2)) == frontend, \
        'README 前端测试数 %s 与大纲 %d 不一致' % (m.group(2), frontend)

    total_m = re.search(r'当前:\*\*(\d+) 个测试全部通过', readme)
    assert total_m, 'README 未写「当前:**N 个测试全部通过」'
    readme_total = int(total_m.group(1))
    assert readme_total == total + 133, \
        'README 总数 %d 应等于 %d(后端+前端) + 133(技能安装)' % (
            readme_total, total)

    # 交接文档: "后端 **409 passed**，前端 82 passed ... （共 **624 项**）"
    ho_path = os.path.join(_REPO_ROOT, '交接文档.md')
    if not os.path.isfile(ho_path):
        pytest.skip('缺少 交接文档.md')
    with open(ho_path, encoding='utf-8') as fh:
        ho = fh.read()

    ho_m = re.search(r'后端 \*\*(\d+) passed\*\*，前端 (\d+) passed', ho)
    assert ho_m, '交接文档未按「后端 **N passed**，前端 M passed」写测试数'
    assert int(ho_m.group(1)) == backend, \
        '交接文档后端测试数 %s 与大纲 %d 不一致' % (ho_m.group(1), backend)
    assert int(ho_m.group(2)) == frontend

    ho_total = re.search(r'共 \*\*(\d+) 项\*\*', ho)
    assert ho_total, '交接文档未写「共 **N 项**」'
    assert int(ho_total.group(1)) == readme_total, \
        '交接文档总数 %s 与 README %d 不一致' % (ho_total.group(1), readme_total)


def test_outline_is_not_part_of_final_thesis():
    """大纲是脚手架,不得被当成正文交上去 —— 它自己必须写明这一点。"""
    text = _outline_text()
    head = text[:1200]
    assert ('不是论文正文' in head) or ('不进定稿' in head), \
        '大纲开头必须声明"不是论文正文、不进定稿"'
    assert ('正文请你自己写' in text) or ('正文由学生本人写' in text) or \
           ('正文必须学生本人撰写' in text), \
        '大纲必须写明正文由本人撰写(学术诚信边界)'


def test_handoff_table_and_figure_counts_match_outline():
    """交接文档说大纲有 N 张表 / M 张图,必须与实际数量一致。

    这类"文档描述另一个文档的规模"的数字最容易悄悄过期:加一张表、
    删一张图,大纲本身没错,但交接文档就开始说谎,而且没人会发现。
    """
    text = _outline_text()
    n_tables = len(re.findall(r'^### 表 ', text, re.M))
    n_figures = len(re.findall(r'^\| 图 ', text, re.M))
    assert n_tables > 0 and n_figures > 0, '大纲里没找到表/图'

    ho_path = os.path.join(_REPO_ROOT, '交接文档.md')
    if not os.path.isfile(ho_path):
        pytest.skip('缺少 交接文档.md')
    with open(ho_path, encoding='utf-8') as fh:
        ho = fh.read()

    for m in re.finditer(r'(\d+) 张数据表', ho):
        assert int(m.group(1)) == n_tables, \
            '交接文档写 %s 张数据表,大纲实际 %d 张' % (m.group(1), n_tables)
    for m in re.finditer(r'(\d+) 张图', ho):
        assert int(m.group(1)) == n_figures, \
            '交接文档写 %s 张图,大纲实际 %d 张' % (m.group(1), n_figures)
