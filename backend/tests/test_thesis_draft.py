"""
论文初稿(论文/毕业论文初稿.md)与实验数据的一致性检查。

初稿是照着 论文/论文写作大纲.md 写的,所以数字风险和大纲不同:大纲的风险是
"从实验文件抄错",初稿的风险是**从大纲抄错**——中间隔了一层,一旦抄漏一位
小数,正文和实验文件就对不上了。这里不信任大纲,直接把初稿里的每个数字
回算到 data/raw 与 data/experiments 的原始数据。

覆盖:
    · 数据规模与标签分布     ← 直接读 CSV
    · 三任务指标与百分点差   ← bert-*/tfidf-*.json
    · 中性瓶颈四条证据       ← neutral-split.json / bert-3class-noq.json
    · 六类改进的负结论       ← ablation-probes.json / ensemble-3class.json
    · 系统数据规模           ← 与大纲表 7-3/7-4 交叉核对
    · 参考文献完整性         ← 正文引用号 ↔ 文末条目

另外守四条纪律(与大纲测试同源,但这里查的是正文):
    ① 不许出现已被覆盖的中间轮次结果 0.0526;
    ② 集成不许写成"显著提升";
    ③ 不许把泄漏结果 0.9864 当成绩;
    ④ 情感—收益结论必须带限定语。

不联网、不加载模型、不跑训练:只读 CSV / JSON / 源码。
"""

import csv
import json
import os
import re

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_DRAFT = os.path.join(_REPO_ROOT, '论文', '毕业论文初稿.md')
_OUTLINE = os.path.join(_REPO_ROOT, '论文', '论文写作大纲.md')
_EXP = os.path.join(_REPO_ROOT, 'data', 'experiments')
_RAW = os.path.join(_REPO_ROOT, 'data', 'raw')

_REF_HEADER = '## 参考文献'


# ---------------------------------------------------------------- 读取工具

def _draft_text():
    if not os.path.isfile(_DRAFT):
        pytest.skip('尚无 论文/毕业论文初稿.md')
    with open(_DRAFT, encoding='utf-8') as fh:
        return fh.read()


def _body_and_refs():
    """切出正文与参考文献表,返回 (body, {编号: 条目行})。"""
    text = _draft_text()
    idx = text.find(_REF_HEADER)
    assert idx > 0, '初稿缺少「%s」标题' % _REF_HEADER
    body = text[:idx]
    tail = text[idx:]

    refs = {}
    for line in tail.splitlines():
        m = re.match(r'^\[(\d{1,2})\]\s+(\S.*)$', line.strip())
        if m:
            refs[int(m.group(1))] = m.group(2).strip()
    return body, refs


def _load_json(name):
    path = os.path.join(_EXP, name)
    if not os.path.isfile(path):
        pytest.skip('缺少实验结果 %s' % name)
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _read_csv(name):
    path = os.path.join(_RAW, name)
    if not os.path.isfile(path):
        pytest.skip('缺少 data/raw/%s' % name)
    with open(path, encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh))


def _fmt(value, digits=4):
    """把数值格式化成正文里的写法,去掉末尾多余的 0(0.7540 -> 0.754)。"""
    s = ('%.*f' % (digits, value)).rstrip('0')
    if s.endswith('.'):
        s += '0'
    return s


def _has(text, value, digits=4):
    """正文里是否出现过某个数值。

    同时接受全精度写法(0.7540)与去尾写法(0.754),因为正文与实验文件的
    小数位习惯不完全一致。
    """
    full = '%.*f' % (digits, value)
    return full in text or _fmt(value, digits) in text


def _outline_text():
    if not os.path.isfile(_OUTLINE):
        pytest.skip('缺少 论文/论文写作大纲.md')
    with open(_OUTLINE, encoding='utf-8') as fh:
        return fh.read()


# ---------------------------------------------------------------- 篇幅与结构

def test_draft_has_reasonable_length():
    """正文汉字数应落在本科毕设常见区间。

    学校通知未写死字数,按计算机类常见的 12000-20000 规划。下限 12000 是
    多数学院的隐形卡口,低于它容易被要求扩写;上限 20000 是为了防止把大纲
    全量搬进正文导致注水。
    """
    body, _ = _body_and_refs()
    n = len(re.findall(r'[\u4e00-\u9fff]', body))
    assert 12000 <= n <= 20000, '正文汉字 %d,不在 12000-20000 区间' % n


def test_draft_has_all_eight_chapters():
    body, _ = _body_and_refs()
    for i in range(1, 9):
        assert re.search(r'^## 第 %d 章 ' % i, body, re.M), \
            '缺少第 %d 章标题' % i


def test_draft_has_bilingual_abstract():
    body, _ = _body_and_refs()
    assert '## 摘要' in body, '缺少中文摘要'
    assert '## Abstract' in body, '缺少英文摘要'
    assert '关键词' in body and 'Keywords' in body, '摘要缺少关键词'


def test_abstract_contains_four_key_numbers():
    """摘要必须含四个数字:主结果、基线、核心比例、倍数。

    这四个数字是全文的骨架,摘要里缺任何一个,读者都拿不到完整结论。
    """
    body, _ = _body_and_refs()
    idx = body.find('## 摘要')
    end = body.find('## Abstract')
    abstract = body[idx:end]
    for token in ('0.7540', '0.6296', '73.47%', '2.8'):
        assert token in abstract, '摘要缺少关键数字 %s' % token


def test_draft_declares_itself_a_draft():
    """初稿必须自带"不是定稿"的声明,防止被直接提交。"""
    text = _draft_text()
    head = text[:1500]
    assert '初稿' in head, '开头未声明这是初稿'
    assert ('AIGC' in head or '代写' in head), \
        '开头未提示 AIGC 检测与代写风险'


# ---------------------------------------------------------------- 数据规模

def test_draft_dataset_sizes_match_csv():
    body, _ = _body_and_refs()
    train = _read_csv('eastmoney_train.csv')
    test = _read_csv('eastmoney_test.csv')
    total = len(train) + len(test)

    assert str(len(train)) in body, '正文未出现训练集规模 %d' % len(train)
    assert str(len(test)) in body, '正文未出现测试集规模 %d' % len(test)
    assert str(total) in body, '正文未出现总规模 %d' % total

    counts = {0: 0, 1: 0, 2: 0}
    for r in train:
        counts[int(r['label'])] += 1
    for label, n in counts.items():
        assert str(n) in body, '正文未出现训练集类别 %d 的样本数 %d' % (label, n)


def test_class_ratio_stated_as_1_49():
    """类别比 3581/2406 = 1.4884,正文写 1.49。

    开题报告书里写的是 1.47,与实测不符。初稿必须用实测值,否则第 2 章
    讨论宏 F1 口径时的"不属于极端不均衡"这个前提就站不住。
    """
    body, _ = _body_and_refs()
    train = _read_csv('eastmoney_train.csv')
    counts = {0: 0, 1: 0, 2: 0}
    for r in train:
        counts[int(r['label'])] += 1
    ratio = max(counts.values()) / min(counts.values())
    assert abs(ratio - 1.49) < 0.005, '实测类别比 %.4f 与 1.49 不符' % ratio
    assert '1.49' in body, '正文未写类别比 1.49'
    assert '1.47' not in body, '正文仍残留开题报告书的错误值 1.47'


def test_draft_title_length_stats_match_csv():
    body, _ = _body_and_refs()
    train = _read_csv('eastmoney_train.csv')
    lens = sorted(len(r['title']) for r in train)
    mean = sum(lens) / len(lens)
    median = lens[len(lens) // 2]
    p95 = lens[int(len(lens) * 0.95)]
    longest = lens[-1]

    assert _has(body, mean, 1), '正文均值 %.1f 与实测不符' % mean
    assert str(median) in body, '正文中位数 %d 与实测不符' % median
    assert str(p95) in body, '正文 95 分位 %d 与实测不符' % p95
    assert str(longest) in body, '正文最长 %d 与实测不符' % longest


def test_draft_quality_check_numbers_match_probe():
    body, _ = _body_and_refs()
    noise = _load_json('ablation-probes.json')['label_noise']

    groups = noise['normalized_duplicate_groups']
    items = noise['normalized_duplicate_items']
    assert str(groups) in body, '正文近重复组数 %d 未出现' % groups
    assert str(items) in body, '正文近重复条数 %d 未出现' % items

    cg = noise['conflicting_label_groups']
    ci = noise['conflicting_label_items']
    assert str(cg) in body and str(ci) in body, \
        '正文标签冲突 %d 组 %d 条未出现' % (cg, ci)

    median = noise['similarity_median']
    assert _has(body, median, 4), '正文最近邻中位数 %.4f 未出现' % median


def test_draft_truncation_claim_matches_probe():
    """正文说超过 64 token 的只有 2 条(0.02%)。

    这个数字无法从 CSV 直接重算(需要分词),因此只能核对它与大纲、与
    正文自身是否一致,防止三处各说一套。
    """
    body, _ = _body_and_refs()
    assert '0.02%' in body, '正文未写截断样本占比 0.02%'
    assert '2 条' in body, '正文未写截断样本 2 条'
    outline = _outline_text()
    assert '0.02%' in outline, '大纲未写截断占比 0.02%'


# ---------------------------------------------------------------- 主结果

def test_draft_three_task_results_match_json():
    """表 4-1 的三任务六组指标必须与实验 JSON 逐位一致。"""
    body, _ = _body_and_refs()
    cases = [
        ('bert-3class.json', 'accuracy', 'BERT 三分类准确率'),
        ('bert-3class.json', 'macro_f1', 'BERT 三分类宏 F1'),
        ('tfidf-3class.json', 'accuracy', 'TF-IDF 三分类准确率'),
        ('tfidf-3class.json', 'macro_f1', 'TF-IDF 三分类宏 F1'),
        ('bert-polarity.json', 'accuracy', 'BERT 极性准确率'),
        ('bert-polarity.json', 'macro_f1', 'BERT 极性宏 F1'),
        ('bert-neutral.json', 'accuracy', 'BERT 中性准确率'),
        ('bert-neutral.json', 'macro_f1', 'BERT 中性宏 F1'),
        ('tfidf-polarity.json', 'accuracy', 'TF-IDF 极性准确率'),
        ('tfidf-neutral.json', 'accuracy', 'TF-IDF 中性准确率'),
    ]
    for fname, key, label in cases:
        data = _load_json(fname)
        value = data[key]
        assert _has(body, value, 4), '%s %.4f 未出现在正文' % (label, value)


def test_draft_majority_baselines_match_json():
    body, _ = _body_and_refs()
    for fname, label in (('bert-3class.json', '三分类'),
                         ('bert-polarity.json', '极性'),
                         ('bert-neutral.json', '中性')):
        value = _load_json(fname)['majority_baseline']['accuracy']
        assert _has(body, value, 4), '%s多数类基线 %.4f 未出现' % (label, value)


def test_draft_percentage_gap_is_arithmetically_correct():
    """正文说 BERT 比 TF-IDF 高 12.44 与 12.87 个百分点,须能回算。"""
    body, _ = _body_and_refs()
    bert = _load_json('bert-3class.json')
    tfidf = _load_json('tfidf-3class.json')

    gap_acc = (bert['accuracy'] - tfidf['accuracy']) * 100
    gap_f1 = (bert['macro_f1'] - tfidf['macro_f1']) * 100

    assert abs(gap_acc - 12.44) < 0.01, '准确率差 %.2f 与正文 12.44 不符' % gap_acc
    assert abs(gap_f1 - 12.87) < 0.01, '宏 F1 差 %.2f 与正文 12.87 不符' % gap_f1
    assert '12.44' in body and '12.87' in body, '正文未写两个百分点差'


def test_draft_polarity_and_neutral_gaps_are_correct():
    """任务 B、C 的百分点差也须能回算(正文写了 8.89/8.95 与 7.47/8.69)。"""
    body, _ = _body_and_refs()
    bp, tp = _load_json('bert-polarity.json'), _load_json('tfidf-polarity.json')
    bn, tn = _load_json('bert-neutral.json'), _load_json('tfidf-neutral.json')

    gaps = {
        'B 准确率': (bp['accuracy'] - tp['accuracy']) * 100,
        'B 宏 F1': (bp['macro_f1'] - tp['macro_f1']) * 100,
        'C 准确率': (bn['accuracy'] - tn['accuracy']) * 100,
        'C 宏 F1': (bn['macro_f1'] - tn['macro_f1']) * 100,
    }
    for label, gap in gaps.items():
        assert ('%.2f' % gap) in body, '正文未写 %s 差 %.2f' % (label, gap)


def test_draft_per_class_metrics_match_json():
    """表 4-2 / 4-3 的逐类精确率与召回率须与 JSON 一致。"""
    body, _ = _body_and_refs()
    for fname in ('bert-3class.json', 'tfidf-3class.json'):
        per_class = _load_json(fname)['per_class']
        for cls, metrics in per_class.items():
            for key in ('precision', 'recall'):
                assert _has(body, metrics[key], 4), \
                    '%s 的 %s.%s=%.4f 未出现在正文' % (
                        fname, cls, key, metrics[key])


def test_draft_confusion_matrix_matches_json():
    """第 4 章引用的混淆矩阵元素必须与 JSON 一致。"""
    body, _ = _body_and_refs()
    cm = _load_json('bert-3class.json')['confusion_matrix']

    # 行=真实,列=预测;0=负 1=正 2=中
    for i in range(3):
        for j in range(3):
            if i == j:
                continue
            assert str(cm[i][j]) in body, \
                '混淆矩阵元素 cm[%d][%d]=%d 未出现在正文' % (i, j, cm[i][j])

    # 真实为负/正被吸进中性的合计 227
    absorbed = cm[0][2] + cm[1][2]
    assert absorbed == 227, '吸入中性的错误数 %d 应为 227' % absorbed
    assert '227' in body, '正文未写吸入中性的 227 条'


def test_draft_tfidf_confusion_matrix_matches_json():
    body, _ = _body_and_refs()
    cm = _load_json('tfidf-3class.json')['confusion_matrix']
    absorbed = cm[0][2] + cm[1][2]
    assert absorbed == 389, 'TF-IDF 吸入中性的错误数 %d 应为 389' % absorbed
    assert '389' in body, '正文未写 TF-IDF 的 389 条'


def test_draft_training_cost_matches_json():
    body, _ = _body_and_refs()
    for fname in ('bert-3class.json', 'tfidf-3class.json',
                  'bert-polarity.json', 'tfidf-polarity.json',
                  'bert-neutral.json', 'tfidf-neutral.json'):
        elapsed = _load_json(fname)['elapsed_sec']
        assert _has(body, elapsed, 1), \
            '%s 的耗时 %.1f 秒未出现在正文' % (fname, elapsed)


# ---------------------------------------------------------------- 中性瓶颈

def test_draft_error_flow_two_calibers_match_json():
    """两个口径的数字都必须出现,且 385/139 的倍数须回算。"""
    body, _ = _body_and_refs()
    flow = _load_json('neutral-split.json')['error_flow']

    assert flow['total_errors'] == 524, \
        '总错误数 %d 应为 524' % flow['total_errors']
    boundary = flow['boundary_errors']
    polarity = flow['polarity_errors']
    assert boundary == 385, '牵涉中性边界的错误 %d 应为 385' % boundary
    assert polarity == 139, '极性互错 %d 应为 139' % polarity

    ratio = boundary / polarity
    assert abs(ratio - 2.77) < 0.01, '倍数 %.2f 与 2.77 不符' % ratio

    # 正文必须两个口径都报
    assert '385' in body and '139' in body, '正文未同时报告两个口径'
    assert '73.47%' in body and '26.53%' in body, '正文未写两个百分比'
    assert '2.8' in body, '正文未写 2.8 倍'


def test_draft_error_sink_caliber_one_matches_json():
    """口径一:按预测类别归并,中性 227 / 负面 171 / 正面 126。"""
    body, _ = _body_and_refs()
    sinks = _load_json('neutral-split.json')['error_flow']['sinks']

    by_label = {s['label']: s['absorbed'] for s in sinks}
    assert by_label == {'neutral': 227, 'negative': 171, 'positive': 126}, \
        '口径一错误流向 %s 与预期不符' % by_label
    for n in by_label.values():
        assert str(n) in body, '口径一的 %d 未出现在正文' % n


def test_draft_question_stats_match_json():
    """证据一的两个方向都要写:48.28% 与 68.39%。"""
    body, _ = _body_and_refs()
    train_q = _load_json('neutral-split.json')['train_questions']
    per_class = train_q['per_class']

    neutral_n = per_class['neutral']['n']
    neutral_q = per_class['neutral']['question']
    ratio_in_neutral = neutral_q / neutral_n
    assert abs(ratio_in_neutral - 0.4828) < 0.0005, \
        '中性类问句占比 %.4f 与 48.28%% 不符' % ratio_in_neutral

    total_q = train_q['question']
    ratio_of_questions = neutral_q / total_q
    assert abs(ratio_of_questions - 0.6839) < 0.0005, \
        '问句中中性占比 %.4f 与 68.39%% 不符' % ratio_of_questions

    assert '48.28%' in body, '正文未写 48.28%'
    assert '68.39%' in body, '正文未写 68.39%'
    assert str(total_q) in body, '正文未写问句总数 %d' % total_q
    assert str(train_q['n']) in body, '正文未写训练集总数 %d' % train_q['n']


def test_draft_wide_caliber_question_stats():
    """宽口径的数字也要与 JSON 一致,且两个口径都要报。"""
    body, _ = _body_and_refs()
    train_q = _load_json('neutral-split.json')['train_questions']
    per_class = train_q['per_class']

    for cls in ('negative', 'positive', 'neutral'):
        ratio = per_class[cls]['question_loose_ratio']
        pct = '%.2f%%' % (ratio * 100)
        assert pct in body, '%s 宽口径占比 %s 未出现' % (cls, pct)

    loose_total = train_q['question_loose_ratio']
    assert '%.2f%%' % (loose_total * 100) in body, '宽口径总体占比未出现'


def test_draft_question_ratio_is_five_times_positive():
    """正文说中性类问句占比是正面类的 5.2 倍,须回算。"""
    body, _ = _body_and_refs()
    per_class = _load_json('neutral-split.json')['train_questions']['per_class']
    ratio = (per_class['neutral']['question_ratio'] /
             per_class['positive']['question_ratio'])
    assert abs(ratio - 5.2) < 0.05, '倍数 %.2f 与 5.2 不符' % ratio
    assert '5.2' in body, '正文未写 5.2 倍'


def test_draft_test_question_stats_match_json():
    body, _ = _body_and_refs()
    test_q = _load_json('neutral-split.json')['test_questions']
    per_class = test_q['per_class']

    for cls in ('negative', 'positive', 'neutral'):
        pct = '%.2f%%' % (per_class[cls]['question_ratio'] * 100)
        assert pct in body, '%s 测试集问句占比 %s 未出现' % (cls, pct)
    pct_total = '%.2f%%' % (test_q['question_ratio'] * 100)
    assert pct_total in body, '测试集总体问句占比 %s 未出现' % pct_total
    assert str(test_q['question']) in body, '测试集问句数未出现'


def test_draft_split_eval_matches_json():
    """证据三:问句组准确率更高但宏 F1 更低,且正面召回 0.2885。"""
    body, _ = _body_and_refs()
    split = _load_json('neutral-split.json')['split_eval']

    q = split['question']
    s = split['statement']
    assert q['accuracy'] > s['accuracy'], '前提不成立:问句组准确率应更高'
    assert q['macro_f1'] < s['macro_f1'], '前提不成立:问句组宏 F1 应更低'

    for block, label in ((split['overall'], '全集'), (q, '问句'), (s, '陈述句')):
        assert _has(body, block['accuracy'], 4), '%s准确率未出现' % label
        assert _has(body, block['macro_f1'], 4), '%s宏 F1 未出现' % label

    pos_recall = q['per_class']['positive']['recall']
    assert abs(pos_recall - 0.2885) < 0.0005, \
        '问句组正面召回 %.4f 与 0.2885 不符' % pos_recall
    assert '0.2885' in body, '正文未写正面召回 0.2885'

    # 陈述句组的正面召回也要出现,用于对比
    s_pos = s['per_class']['positive']['recall']
    assert _has(body, s_pos, 4), '陈述句组正面召回 %.4f 未出现' % s_pos


def test_draft_subset_label_distribution_matches_json():
    """正文说问句组中性占 66.83%,须回算。"""
    body, _ = _body_and_refs()
    q = _load_json('neutral-split.json')['split_eval']['question']
    dist = q['label_dist']
    ratio = dist['neutral'] / sum(dist.values())
    assert abs(ratio - 0.6683) < 0.0005, '问句组中性占比 %.4f 与 66.83%% 不符' % ratio
    assert '66.83%' in body, '正文未写问句组中性占比 66.83%'


def test_draft_retrain_without_questions_matches_json():
    """证据四:剔除问句后两项指标都下降,且降幅须回算。"""
    body, _ = _body_and_refs()
    base = _load_json('bert-3class.json')
    noq = _load_json('bert-3class-noq.json')

    d_acc = noq['accuracy'] - base['accuracy']
    d_f1 = noq['macro_f1'] - base['macro_f1']
    assert d_acc < 0 and d_f1 < 0, '前提不成立:剔除问句后应下降'
    assert abs(d_acc + 0.0103) < 0.0005, '准确率降幅 %.4f 与 -0.0103 不符' % d_acc
    assert abs(d_f1 + 0.0086) < 0.0005, '宏 F1 降幅 %.4f 与 -0.0086 不符' % d_f1

    assert '0.0103' in body, '正文未写准确率降幅 0.0103'
    assert '0.0086' in body, '正文未写宏 F1 降幅 0.0086'
    assert str(noq['n_train']) in body, '正文未写剔除后的训练样本数'
    removed = base['n_train'] - noq['n_train']
    assert removed == 2528, '删除的问句数 %d 应为 2528' % removed


def test_draft_does_not_claim_questions_are_noise():
    """纪律:不许写"问句是噪声/应当删除"。

    证据四(剔除重训指标反降)明确否证了这一点。正文若出现这类主张,
    与自己的实验结论矛盾。
    """
    body, _ = _body_and_refs()
    banned = ['问句是噪声', '问句属于噪声', '应当删除问句样本', '问句样本应当删除']
    for phrase in banned:
        for m in re.finditer(re.escape(phrase), body):
            window = body[max(0, m.start() - 60):m.start()]
            assert ('不主张' in window or '否证' in window or
                    '不等于' in window or '不能' in window or
                    '不应' in window), \
                '正文出现「%s」且不在否定语境:...%s' % (phrase, window)


# ---------------------------------------------------------------- 负结论

def test_draft_macro_f1_two_calibers_match_json():
    """表 6-1 的最大差值 0.0073 须回算,且引用文献 0.5 时要带数据条件。"""
    body, _ = _body_and_refs()
    probe = _load_json('ablation-probes.json')['macro_f1_ambiguity']

    for name, block in probe.items():
        assert _has(body, block['f1_per_class_average'], 4), \
            '%s 的 A 口径宏 F1 未出现' % name
        assert _has(body, block['f1_from_macro_pr'], 4), \
            '%s 的 B 口径宏 F1 未出现' % name

    worst = max(abs(v['f1_per_class_average'] - v['f1_from_macro_pr'])
                for v in probe.values())
    assert abs(worst - 0.0073) < 0.0005, '最大口径差 %.4f 与 0.0073 不符' % worst
    assert '0.0073' in body, '正文未写最大口径差 0.0073'

    # 引用 0.5 的地方必须说明是极端不均衡条件
    for m in re.finditer(r'0\.5(?![0-9])', body):
        window = body[max(0, m.start() - 150):m.start() + 150]
        if '差异' in window and '宏' in window:
            assert ('极端' in window or '不均衡' in window or
                    '数据条件' in window or '前提' in window), \
                '引用 0.5 处未说明数据条件:...%s' % window


def test_draft_label_noise_thresholds_match_json():
    """表 6-2 的阈值与一致率须与 JSON 一致。"""
    body, _ = _body_and_refs()
    noise = _load_json('ablation-probes.json')['label_noise']
    by_threshold = noise['by_threshold']

    for threshold, block in by_threshold.items():
        agree = block['neighbor_label_agreement']
        assert _has(body, agree, 4), \
            '阈值 %s 的标签一致率 %.4f 未出现' % (threshold, agree)
        assert str(block['n']) in body, \
            '阈值 %s 的样本数 %d 未出现' % (threshold, block['n'])


def test_draft_cascade_numbers_match_json():
    body, _ = _body_and_refs()
    cascade = _load_json('ablation-probes.json')['cascade']
    strategies = cascade['strategies']

    assert _has(body, strategies['s1_direct_three_class'], 4), 'S1 准确率未出现'
    assert _has(body, strategies['s2_hard_routing'], 4), 'S2 准确率未出现'
    for t, acc in strategies['s3_confidence_routing'].items():
        assert _has(body, acc, 4), 'S3 t=%s 的准确率未出现' % t

    # 子集表现
    non_neutral = cascade['non_neutral']
    assert abs(non_neutral['delta'] - 0.1342) < 0.0005, \
        '非中性子集增益 %.4f 与 0.1342 不符' % non_neutral['delta']
    assert '13.42' in body, '正文未写 13.42 个百分点'

    neutral = cascade['neutral']
    assert abs(neutral['delta'] + 0.1447) < 0.0005, \
        '中性子集差 %.4f 与 -0.1447 不符' % neutral['delta']
    assert _has(body, neutral['neutral_specialist'], 4), \
        '中性专用模型准确率未出现'


def test_draft_hyperparameter_sweep_matches_json():
    body, _ = _body_and_refs()
    sweep = _load_json('sweep.json')

    # 最优配置应就是基线
    best = max(sweep.items(), key=lambda kv: kv[1]['accuracy'])
    assert best[0] == 'ep3_lr2e-05', \
        '最优配置不是基线 ep3/lr2e-05,正文结论需改写: %s' % best[0]
    for name, block in sweep.items():
        assert _has(body, block['accuracy'], 4), '%s 准确率未出现' % name
        assert _has(body, block['macro_f1'], 4), '%s 宏 F1 未出现' % name

    # ep8 过拟合:loss 已很低而 acc 下降
    ep8 = sweep['ep8_lr2e-05']
    assert ep8['accuracy'] < sweep['ep3_lr2e-05']['accuracy'], 'ep8 应低于基线'


def test_draft_stacking_numbers_match_json():
    body, _ = _body_and_refs()
    stack = _load_json('ablation-probes.json')['stacking']

    assert _has(body, stack['meta_test_accuracy'], 4), '元分类器测试准确率未出现'
    assert _has(body, stack['meta_train_accuracy'], 4), '元分类器训练准确率未出现'
    assert _has(body, stack['base_accuracy'], 4), '堆叠的基线准确率未出现'

    assert stack['mcnemar']['p_value'] == pytest.approx(0.4097, abs=1e-4)
    assert '0.4097' in body, '正文未写 McNemar p=0.4097'

    leak_free = stack['leak_free']
    assert _has(body, leak_free['meta_accuracy'], 4), '无泄漏对照准确率未出现'
    assert _has(body, leak_free['base_accuracy'], 4), '无泄漏对照基线未出现'
    assert '0.2132' in body, '正文未写无泄漏对照 p=0.2132'


def test_draft_leaked_accuracy_is_marked_unusable():
    """纪律:0.9864 只能作为"不可引用"的反面例子出现。"""
    body, _ = _body_and_refs()
    if '0.9864' not in body:
        pytest.skip('正文未提及泄漏结果')
    for m in re.finditer(r'0\.9864', body):
        window = body[max(0, m.start() - 150):m.start() + 150]
        assert ('泄漏' in window or '不可引用' in window or
                '不能作为' in window or '不能拿' in window), \
            '0.9864 出现处未标注泄漏/不可引用:...%s' % window


def test_draft_calibration_numbers_match_json():
    body, _ = _body_and_refs()
    calib = _load_json('ablation-probes.json')['calibration']
    note = calib['oracle_note']

    assert '0.3634' in body, '正文未写校准的 McNemar p=0.3634'
    assert '+0.0012' in body or '0.0012' in body, '正文未写 CV 平均增益 0.0012'
    assert '0.7700' in body, '正文未写 oracle 准确率 0.7700'
    assert '0.7685' in body, '正文未写 oracle 宏 F1 0.7685'

    # 逆先验权重
    weights = calib['inverse_prior_weight']
    assert _has(body, weights[2], 4), '中性逆先验权重 %.4f 未出现' % weights[2]

    # oracle 结果必须被标注为选择偏差
    for m in re.finditer(r'0\.7700', body):
        window = body[max(0, m.start() - 150):m.start() + 150]
        assert ('选择偏差' in window or '不能算' in window), \
            'oracle 结果未标注选择偏差:...%s' % window

    assert '0.0012' in note, '源文件里的 CV 增益已变,正文需同步'


def test_draft_ensemble_significance_two_sided():
    """纪律:集成不许写成"显著提升";两个检验结论都要报。"""
    body, _ = _body_and_refs()
    sig = _load_json('ensemble-3class.json')['significance']

    assert sig['mcnemar']['p_value'] == pytest.approx(0.0583, abs=1e-4)
    assert '0.0583' in body, '正文未写 McNemar p=0.0583'
    # 0.0583 出现处必须带"不显著"
    for m in re.finditer(r'0\.0583', body):
        window = body[max(0, m.start() - 150):m.start() + 150]
        assert '不显著' in window or '未达' in window, \
            'p=0.0583 处未写不显著:...%s' % window

    # 两个 CI 都要报
    acc_ci = sig['bootstrap']['accuracy']['ci95']
    f1_ci = sig['bootstrap']['macro_f1']['ci95']
    assert ('%.4f' % acc_ci[0]).replace('-', '−') in body or \
           ('%.4f' % acc_ci[0]) in body, '正文未写准确率 CI 下界'
    assert ('%.4f' % f1_ci[1]) in body, '正文未写宏 F1 CI 上界'

    # 不许出现"显著提升"
    assert '显著提升' not in body, '正文出现「显著提升」,集成实际不显著'


def test_draft_seed_variance_is_reported():
    """多种子实验必须报种子间极差,否则"提升 1.13 点"缺少参照。"""
    body, _ = _body_and_refs()
    data = _load_json('ensemble-3class.json')
    seeds = data['individual_seeds']
    spread = data['seed_spread']

    assert abs(spread['accuracy_range'] - 0.0192) < 0.0005, \
        '种子间准确率极差 %.4f 与 0.0192 不符' % spread['accuracy_range']
    assert abs(spread['macro_f1_range'] - 0.0236) < 0.0005, \
        '种子间宏 F1 极差 %.4f 与 0.0236 不符' % spread['macro_f1_range']
    assert '0.0192' in body, '正文未写种子间准确率极差 0.0192'
    assert '0.0236' in body, '正文未写种子间宏 F1 极差 0.0236'

    for name, block in seeds.items():
        assert _has(body, block['accuracy'], 4), \
            '种子 %s 的准确率未出现' % name

    # 集成结果本身
    assert _has(body, data['accuracy'], 4), '集成准确率未出现'
    assert _has(body, data['macro_f1'], 4), '集成宏 F1 未出现'


def test_draft_aux_head_numbers_match_json():
    body, _ = _body_and_refs()
    aux = _load_json('ablation-probes.json')['aux_head']

    assert _has(body, aux['polarity_specialist'], 4), '专用极性模型准确率未出现'
    for head, block in aux['heads'].items():
        assert _has(body, block['accuracy'], 4), '%s 辅助头准确率未出现' % head
        p = block['vs_specialist']['p_value']
        assert ('%.4f' % p) in body, '%s 辅助头的 p=%.4f 未出现' % (head, p)


def test_draft_4class_and_mtl_match_json():
    body, _ = _body_and_refs()
    for fname in ('4class.json', 'mtl.json'):
        data = _load_json(fname)
        assert _has(body, data['accuracy'], 4), '%s 准确率未出现' % fname
        assert _has(body, data['macro_f1'], 4), '%s 宏 F1 未出现' % fname

    # 4class 宏 F1 高于基线但准确率更低 —— 正文必须如实写出这个不一致
    four = _load_json('4class.json')
    base = _load_json('bert-3class.json')
    assert four['macro_f1'] > base['macro_f1'], '前提不成立:4class 宏 F1 应更高'
    assert four['accuracy'] < base['accuracy'], '前提不成立:4class 准确率应更低'

    # 正文必须用一句话同时交代这两个数,并点明方向相反。
    # 注意不能只搜 0.7543 —— 它先出现在表 6-1 里,那里没有解释。
    pattern = r'4class 的准确率为 0\.7493、宏 F1 为 0\.7543'
    assert re.search(pattern, body), '正文未并列写出 4class 的准确率与宏 F1'
    m = re.search(pattern, body)
    window = body[m.end():m.end() + 400]
    assert '准确率' in window and '更低' in window, \
        '4class 宏 F1 上升而准确率下降这一点未如实说明'


# ---------------------------------------------------------------- 系统数据

def test_draft_system_scale_matches_outline():
    """系统数据规模与大纲表 7-3 一致(两边都不联网查库)。"""
    body, _ = _body_and_refs()
    outline = _outline_text()

    for token in ('72235', '6420', '13 只'):
        assert token in body, '正文未写系统规模 %s' % token
        assert token in outline, '大纲未写系统规模 %s' % token


def test_draft_system_sentiment_distribution_sums():
    body, _ = _body_and_refs()
    assert 2062 + 426 + 3932 == 6420, '分布合计应为 6420'
    for token in ('2062', '426', '3932', '32.12%', '6.64%', '61.25%'):
        assert token in body, '正文未写情感分布 %s' % token

    # 必须说明与训练集的语体差异
    idx = body.find('61.25%')
    window = body[max(0, idx - 500):idx + 500]
    assert ('语体' in window or '新闻' in window), \
        '系统情感分布处未说明与训练集的语体差异'


def test_draft_interface_list_matches_source():
    """表 7-1 的接口路径须在 backend/app/main.py 里真实存在。"""
    main_py = os.path.join(_REPO_ROOT, 'backend', 'app', 'main.py')
    if not os.path.isfile(main_py):
        pytest.skip('缺少 backend/app/main.py')
    with open(main_py, encoding='utf-8') as fh:
        source = fh.read()

    body, _ = _body_and_refs()
    routes = re.findall(r"@app\.(?:get|post)\('([^']+)'", source)
    assert routes, '未从 main.py 解析到任何路由'
    for route in routes:
        # 正文里的写法是 /api/stocks/{code}/klines,源码里是同样的花括号
        assert route in body, '接口 %s 未出现在正文表 7-1' % route


def test_draft_sentiment_return_result_is_bounded():
    """纪律:结论必须限定在"本数据、本窗口、线性相关"。"""
    body, _ = _body_and_refs()
    assert '744' in body, '正文未写样本数 744'
    assert '0.0019' in body, '正文未写 Pearson -0.0019'
    assert '0.9579' in body, '正文未写 p=0.9579'
    assert '0.4778' in body, '正文未写方向命中率 0.4778'

    # 限定语在表后那段正文里,而 0.0019 首次出现在表格行中,所以不能只取
    # 首次出现的窗口,要切出 7.6 整节再查。
    start = body.find('### 7.6')
    end = body.find('### 7.7')
    assert start > 0 and end > start, '未找到 7.6 节'
    section = body[start:end]
    assert ('限定' in section or '本数据' in section), \
        '相关系数结论未加限定语'


def test_draft_test_counts_match_outline():
    """系统测试数与大纲表 7-5 一致。"""
    body, _ = _body_and_refs()
    outline = _outline_text()

    m = re.search(r'\| 后端 \| (\d+) \| pytest \|', outline)
    assert m, '大纲表 7-5 未找到后端测试数'
    backend_n = int(m.group(1))

    m2 = re.search(r'\| 前端 \| (\d+) \|', outline)
    assert m2, '大纲表 7-5 未找到前端测试数'
    frontend_n = int(m2.group(1))

    total = backend_n + frontend_n
    assert str(total) in body, '正文未写测试总数 %d' % total
    assert str(backend_n) in body, '正文未写后端测试数 %d' % backend_n


# ---------------------------------------------------------------- 参考文献

def test_every_cited_number_has_a_reference_entry():
    """防引而不注:正文出现的每个 [n] 都必须在文末有条目。"""
    body, refs = _body_and_refs()
    cited = {int(m) for m in re.findall(r'\[(\d{1,2})\]', body)}
    assert cited, '正文未出现任何引用'
    missing = sorted(cited - set(refs))
    assert not missing, '正文引用了不存在的文献编号: %s' % missing


def test_no_orphan_reference_entries():
    """防凑数:文末每条文献都必须被正文引用过。"""
    body, refs = _body_and_refs()
    cited = {int(m) for m in re.findall(r'\[(\d{1,2})\]', body)}
    orphans = sorted(set(refs) - cited)
    assert not orphans, '文末有条目但正文未引用: %s' % orphans


def test_reference_numbers_are_contiguous():
    body, refs = _body_and_refs()
    numbers = sorted(refs)
    assert numbers == list(range(1, len(numbers) + 1)), \
        '参考文献编号不连续: %s' % numbers


def test_reference_entries_look_like_gbt7714():
    body, refs = _body_and_refs()
    for n, entry in refs.items():
        assert len(entry) > 25, '文献 [%d] 条目过短: %r' % (n, entry)
        assert re.search(r'\[(J|C|M|D|EB/OL|R)\]', entry), \
            '文献 [%d] 缺少文献类型标识: %r' % (n, entry)


def test_reference_entries_carry_accessible_id():
    """每条文献都要有 DOI / arXiv / URL 之一,兑现"可访问来源"的自述。"""
    body, refs = _body_and_refs()
    for n, entry in refs.items():
        assert ('DOI' in entry or 'arXiv' in entry or
                'http://' in entry or 'https://' in entry), \
            '文献 [%d] 缺少可访问标识: %r' % (n, entry)


def test_reference_count_matches_lit_review():
    """初稿的文献表须与文献综述的 37 条一致,不许悄悄增删。"""
    body, refs = _body_and_refs()
    review = os.path.join(_REPO_ROOT, '论文', '文献综述.md')
    if not os.path.isfile(review):
        pytest.skip('缺少 论文/文献综述.md')
    with open(review, encoding='utf-8') as fh:
        text = fh.read()
    idx = text.find(_REF_HEADER)
    assert idx > 0, '文献综述缺少参考文献节'
    review_refs = set()
    for line in text[idx:].splitlines():
        m = re.match(r'^\[(\d{1,2})\]\s+(\S.*)$', line.strip())
        if m:
            review_refs.add(int(m.group(1)))

    assert len(refs) == len(review_refs), \
        '初稿 %d 条 vs 文献综述 %d 条,数量不一致' % (len(refs), len(review_refs))
    assert set(refs) == review_refs, '初稿与文献综述的文献编号集合不一致'


# ---------------------------------------------------------------- 占位符与纪律

def test_no_unfinished_placeholders_in_body():
    """正文不许留占位符。

    扫描范围从「## 摘要」开始,不含文件头的说明块——那里写明「封面信息与
    致谢待补」是交代完成度的元信息,不是正文内容。致谢节本身也豁免,它的
    占位说明是有意留下的。
    """
    body, _ = _body_and_refs()
    start = body.find('## 摘要')
    assert start > 0, '缺少摘要节'
    end = body.find('## 致谢')
    target = body[start:end] if end > start else body[start:]
    for token in ('待补', '待核', 'TODO', 'XXX', '待写'):
        assert token not in target, '正文残留占位符「%s」' % token


def test_no_unreproducible_intermediate_result():
    """纪律:不许引用已被覆盖、无法复现的 +0.0526。"""
    body, _ = _body_and_refs()
    assert '0.0526' not in body, \
        '正文出现 0.0526 —— 该值来自已被覆盖的中间轮次,不可复现'


def test_draft_tables_are_all_present():
    """正文引用了 32 张表,必须每张都真的贴出来,不能只在正文里提到编号。

    这是初稿最容易出的漏洞:正文写"如表 4-2 所示"却忘了贴表。
    """
    body, _ = _body_and_refs()
    referenced = set(re.findall(r'表 (\d-\d+)', body))
    defined = set(re.findall(r'^\*\*表 (\d-\d+)', body, re.M))

    missing = sorted(referenced - defined)
    assert not missing, '正文引用了但未贴出的表: %s' % missing

    # 表格定义本身也要有内容行
    for name in sorted(defined):
        pattern = r'^\*\*表 %s [^\n]*\n\n(\|.*?\n)+' % re.escape(name)
        assert re.search(pattern, body, re.M), \
            '表 %s 只有标题没有表格内容' % name
