"""
答辩口径卡(论文/答辩口径卡.md)与论文初稿的一致性检查。

口径卡的用途是答辩现场"照着自己组织句子"的备忘,它的风险与初稿、大纲都不同:
初稿的风险是"从大纲抄错",大纲的风险是"从实验文件抄错",而口径卡的风险是
**"答辩时说的数字和论文里写的不一样"** —— 这是唯一一种会被评委当场发现的错误,
因为评委手里就有论文。

所以这里查两件事:
    ① 口径卡里的每个数字,论文正文里必须有 —— 不许出现论文没写过的数字;
    ② 口径卡里的每个纪律,论文里也必须守 —— 卡片教学生"不能说"的话,
       卡片自己先不能违反。

另外守一条形式纪律:口径卡是"要点卡",不是讲稿。学校教务通知字〔2026〕57 号
规定答辩陈述须由作者本人完成,所以卡片必须自己声明这一点,且不能写成
可以直接朗读的成段文字。

不联网、不加载模型、不跑训练:只读 Markdown / CSV / JSON。
"""

import csv
import json
import os
import re

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_PAPER_DIR = os.path.join(_REPO_ROOT, '论文')
_CARD = os.path.join(_PAPER_DIR, '答辩口径卡.md')
_DRAFT = os.path.join(_PAPER_DIR, '毕业论文初稿.md')
_OUTLINE = os.path.join(_PAPER_DIR, '论文写作大纲.md')
_EXP = os.path.join(_REPO_ROOT, 'data', 'experiments')
_RAW = os.path.join(_REPO_ROOT, 'data', 'raw')

_REF_HEADER = '## 参考文献'

# 口径卡里由两个论文数字相减/相除得到的派生值,论文正文没直接写过。
# 每项给出算式,测试里回算一遍 —— 允许派生,但不允许算错。
_DERIVED = {
    '34.5': ('accuracy_gap', 0.7540, 0.4089),   # 主结果相对多数类基线,百分点
    '0.0056': ('stacking_gap', 0.7596, 0.7540),  # 堆叠相对基线
}


# ---------------------------------------------------------------- 读取工具

def _card_text():
    if not os.path.isfile(_CARD):
        pytest.skip('尚无 论文/答辩口径卡.md')
    with open(_CARD, encoding='utf-8') as fh:
        return fh.read()


def _draft_text():
    if not os.path.isfile(_DRAFT):
        pytest.skip('缺少 论文/毕业论文初稿.md')
    with open(_DRAFT, encoding='utf-8') as fh:
        return fh.read()


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


def _strip_urls(text):
    """URL 里的数字(端口、路径)不是论文数据,抽数字前先去掉。"""
    return re.sub(r'https?://\S+', ' ', text)


def _decimals(text):
    """抽所有小数写法,返回集合。"""
    return set(re.findall(r'\d+\.\d+', _strip_urls(text)))


def _section(text, start_marker, end_marker=None):
    start = text.find(start_marker)
    assert start >= 0, '找不到章节标记「%s」' % start_marker
    if end_marker is None:
        return text[start:]
    end = text.find(end_marker, start)
    assert end > start, '找不到章节结束标记「%s」' % end_marker
    return text[start:end]


def _table_rows(block):
    """把一段 Markdown 里的表格拆成二维单元格列表(跳过表头分隔行)。"""
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


def _chapter_block(card, n):
    """取「### 第 N 章 ...」到下一个三级标题之间的内容。"""
    marker = '### 第 %d 章' % n
    start = card.find(marker)
    assert start >= 0, '口径卡缺少「%s」小节' % marker
    nxt = card.find('\n### ', start + 1)
    return card[start:nxt] if nxt > 0 else card[start:]


# ---------------------------------------------------------------- 形式:是卡不是讲稿

def test_card_declares_itself_not_a_script():
    """口径卡必须自己声明「不是讲稿」。

    学校教务通知字〔2026〕57 号:答辩陈述须由作者本人完成,AI 代写取消资格。
    这张卡如果写成可以直接朗读的成段文字,就成了讲稿。所以它必须在开头
    把用途说清楚:给要点、给数字出处、给预判问题,句子由作者自己组织。
    """
    card = _card_text()
    head = card[:card.find('## 〇')] if '## 〇' in card else card[:1500]
    assert '不是讲稿' in head, '口径卡开头未声明「这不是讲稿」'
    assert '自己' in head, '口径卡开头未说明句子须由作者自己组织'


def test_card_covers_all_eight_chapters():
    card = _card_text()
    for n in range(1, 9):
        assert re.search(r'^### 第 %d 章 ' % n, card, re.M), \
            '口径卡缺少第 %d 章的口径' % n


def test_each_chapter_has_talking_points_and_questions():
    """每章都要有「要点」与「预判问题」两块,缺一块就不是口径卡。"""
    card = _card_text()
    for n in range(1, 9):
        block = _chapter_block(card, n)
        assert '这章存在的理由' in block, '第 %d 章缺「这章存在的理由」' % n
        assert 'Q：' in block, '第 %d 章没有预判问题' % n


def test_card_has_three_minute_summary():
    """答辩可能被压缩到三分钟,卡片要给一个能背下来的短版本。"""
    card = _card_text()
    sec = _section(card, '## 〇、三分钟版', '## 一、')
    assert '一句话' in sec, '三分钟版缺「一句话」总括'
    # 三条核心判断都要在
    for token in ('0.7540', '73.47', '26.53'):
        assert token in sec, '三分钟版缺关键数字 %s' % token


def test_card_has_number_cheatsheet():
    """被追问时要能立刻报数字,所以要有速查表。"""
    card = _card_text()
    sec = _section(card, '## 六、数字速查表', '## 七、')
    for group in ('### 数据', '### 主结果', '### 中性瓶颈', '### 改进实验',
                  '### 系统', '### 论文规模'):
        assert group in sec, '速查表缺少「%s」分组' % group


def test_card_length_is_reasonable():
    """口径卡是卡片,不是论文。

    下限防止写成空壳;上限防止把初稿搬进来 —— 搬进来就等于给了讲稿,
    也违背了"作者本人撰写"的要求。
    """
    card = _card_text()
    n = len(re.findall(r'[\u4e00-\u9fff]', card))
    assert 5000 <= n <= 12000, '口径卡汉字 %d,不在 5000-12000 区间' % n


def test_no_unfinished_placeholders_in_card():
    card = _card_text()
    for token in ('待补', '待核', 'TODO', 'XXX', '待写'):
        assert token not in card, '口径卡残留占位符「%s」' % token


# ---------------------------------------------------------------- 数字:不许出现论文没写过的

def test_every_decimal_in_card_appears_in_draft():
    """口径卡里的每个小数,论文正文里必须有。

    这是本文件最重要的一条。答辩时评委手里有论文,卡片上多一个数字就是
    "你说的和写的对不上"。派生值(两项相减)单独回算,不允许既没出处又算错。
    """
    card = _card_text()
    draft = _draft_text()
    draft_nums = _decimals(draft)

    missing = sorted(n for n in _decimals(card)
                     if n not in draft_nums and n not in _DERIVED)
    assert not missing, \
        '口径卡出现论文正文没有的数字: %s' % missing


def test_derived_numbers_are_arithmetically_correct():
    """派生值允许存在,但必须算对,且两个来源数都在论文里。"""
    card = _card_text()
    draft = _draft_text()
    draft_nums = _decimals(draft)

    # 34.5 = (0.7540 - 0.4089) * 100,保留一位小数
    gap_pp = (0.7540 - 0.4089) * 100
    assert abs(round(gap_pp, 1) - 34.5) < 0.05, \
        '34.5 个百分点回算为 %.2f,与卡片不符' % gap_pp
    assert '0.7540' in draft_nums and '0.4089' in draft_nums, \
        '派生值 34.5 的两个来源数须在论文中出现'

    # 0.0056 = 0.7596 - 0.7540
    diff = 0.7596 - 0.7540
    assert abs(diff - 0.0056) < 0.00005, \
        '0.0056 回算为 %.5f,与卡片不符' % diff
    assert '0.7596' in draft_nums, '派生值 0.0056 的来源数 0.7596 不在论文中'

    assert '34.5' in card, '口径卡未用 34.5 个百分点说明相对基线的优势'
    assert '0.0056' in card, '口径卡未用 0.0056 说明堆叠增益'


def test_no_unreproducible_intermediate_result_in_card():
    """纪律:0.0526 来自已被覆盖的中间轮次,卡片里也不许出现。"""
    card = _card_text()
    assert '0.0526' not in card, \
        '口径卡出现 0.0526 —— 该值来自已被覆盖的中间轮次,不可复现'


def test_card_dataset_numbers_match_csv():
    """数据规模与类别分布须与原始 CSV 一致。"""
    card = _card_text()
    train = _read_csv('eastmoney_train.csv')
    test = _read_csv('eastmoney_test.csv')

    assert str(len(train) + len(test)) in card, '口径卡未写总样本数'
    assert str(len(train)) in card, '口径卡未写训练集条数'
    assert str(len(test)) in card, '口径卡未写测试集条数'

    counts = {0: 0, 1: 0, 2: 0}
    for r in train:
        counts[int(r['label'])] += 1
    for label in (0, 1, 2):
        assert str(counts[label]) in card, \
            '口径卡未写训练集 label=%d 的条数 %d' % (label, counts[label])

    ratio = counts[2] / counts[1]
    assert abs(ratio - 1.49) < 0.005, '类别比回算 %.4f 与 1.49 不符' % ratio
    assert '1.49' in card, '口径卡未写类别比 1.49'


def test_card_main_results_match_json():
    """三个任务的主结果须与实验文件一致。"""
    card = _card_text()
    for name in ('bert-3class', 'bert-polarity', 'bert-neutral',
                 'tfidf-3class', 'tfidf-polarity', 'tfidf-neutral'):
        data = _load_json('%s.json' % name)
        assert '%.4f' % data['accuracy'] in card, \
            '口径卡未写 %s 的准确率 %.4f' % (name, data['accuracy'])
        assert '%.4f' % data['macro_f1'] in card, \
            '口径卡未写 %s 的宏 F1 %.4f' % (name, data['macro_f1'])


def test_card_neutral_bottleneck_numbers_match_json():
    """中性瓶颈的四条证据数字须回算。"""
    card = _card_text()
    data = _load_json('neutral-split.json')

    # 证据一:问句占比
    per_class = data['train_questions']['per_class']
    assert '%.2f' % (per_class['neutral']['question_ratio'] * 100) in card, \
        '口径卡未写中性类问句占比 48.28%'
    assert '%.2f' % (per_class['negative']['question_ratio'] * 100) in card, \
        '口径卡未写负面类问句占比'
    assert '%.2f' % (per_class['positive']['question_ratio'] * 100) in card, \
        '口径卡未写正面类问句占比'

    # 全部问句中被标中性的比例
    qdist = data['train_questions']['question_label_dist']
    total_q = sum(qdist.values())
    share = qdist['neutral'] / total_q * 100
    assert abs(share - 68.39) < 0.01, '问句中中性占比回算 %.2f' % share
    assert '68.39' in card, '口径卡未写 68.39%'

    # 证据三:句式切分
    split = data['split_eval']
    for part in ('question', 'statement'):
        assert '%.4f' % split[part]['accuracy'] in card, \
            '口径卡未写 %s 组准确率' % part
        assert '%.4f' % split[part]['macro_f1'] in card, \
            '口径卡未写 %s 组宏 F1' % part
    pos_recall = split['question']['per_class']['positive']['recall']
    assert abs(pos_recall - 0.2885) < 0.0005, '问句组正面召回回算 %.4f' % pos_recall
    assert '0.2885' in card, '口径卡未写问句组正面类召回率 0.2885'

    # 证据四:剔除重训
    base = _load_json('bert-3class.json')
    noq = _load_json('bert-3class-noq.json')
    assert noq['accuracy'] < base['accuracy'], '前提不成立:剔除问句应下降'
    assert '0.0103' in card, '口径卡未写准确率降幅 0.0103'
    assert '0.0086' in card, '口径卡未写宏 F1 降幅 0.0086'


def test_card_reports_both_error_flow_calibers():
    """纪律:错误流向的两个口径都要报,只报口径一会被质疑挑了有利算法。"""
    card = _card_text()
    flow = _load_json('neutral-split.json')['error_flow']

    assert flow['boundary_errors'] == 385
    assert abs(flow['boundary_share'] - 0.7347) < 1e-4
    assert abs(flow['polarity_share'] - 0.2653) < 1e-4

    assert '73.47' in card, '口径卡未写口径二 73.47%'
    assert '26.53' in card, '口径卡未写极性互错 26.53%'

    sink = {s['label']: s for s in flow['sinks']}
    assert abs(sink['neutral']['share'] - 0.4332) < 1e-4
    assert '43.32' in card, '口径卡未写口径一 43.32%'

    # 必须解释口径一为什么低估
    sec = _section(card, '第 5 章', '### 第 6 章')
    assert '低估' in sec, '口径卡未说明口径一为什么低估'
    assert '2.8' in sec, '口径卡未写 2.8 倍'


def test_card_ensemble_significance_matches_json():
    """纪律:集成不许写成"显著提升",两个检验结论都要报。"""
    card = _card_text()
    data = _load_json('ensemble-3class.json')
    sig = data['significance']

    assert sig['mcnemar']['p_value'] == pytest.approx(0.0583, abs=1e-4)
    assert '0.0583' in card, '口径卡未写 McNemar p=0.0583'

    for m in re.finditer(r'0\.0583', card):
        window = card[max(0, m.start() - 200):m.start() + 200]
        assert '不显著' in window or '未达' in window, \
            'p=0.0583 出现处未写不显著'

    # 两个 bootstrap 区间都要报
    acc_ci = sig['bootstrap']['accuracy']['ci95']
    f1_ci = sig['bootstrap']['macro_f1']['ci95']
    for v in acc_ci + f1_ci:
        s = '%.4f' % v
        assert s in card or s.replace('-', '−') in card, \
            '口径卡未写置信区间端点 %s' % s

    # 宏 F1 区间不含 0 才叫显著,卡片必须点明这个对比
    assert f1_ci[0] > 0, '前提不成立:宏 F1 区间下界应大于 0'
    assert '不含 0' in card or '不含0' in card, \
        '口径卡未说明宏 F1 区间不含 0'

    # 种子间极差也要报,否则"提升 1.13 点"没有参照
    spread = data['seed_spread']
    assert '%.4f' % spread['accuracy_range'] in card, '口径卡未写种子间准确率极差'
    assert '%.4f' % spread['macro_f1_range'] in card, '口径卡未写种子间宏 F1 极差'


def test_card_improvement_results_match_json():
    """六类改进的数字须与实验文件一致。"""
    card = _card_text()
    probes = _load_json('ablation-probes.json')

    cascade = probes['cascade']
    strategies = cascade['strategies']
    assert '%.4f' % strategies['s2_hard_routing'] in card, \
        '口径卡未写硬路由 S2 准确率'
    assert '%.4f' % strategies['s3_confidence_routing']['0.9'] in card, \
        '口径卡未写置信度路由 t=0.9 的准确率'
    # 硬路由的下降幅度也要在卡片里,否则只报终点看不出代价
    assert '%.4f' % abs(strategies['s2_delta']) in card, \
        '口径卡未写硬路由相对基线的降幅 0.0258'

    calib = probes['calibration']
    assert '0.3634' in card, '口径卡未写校准 McNemar p=0.3634'
    assert '0.0012' in card, '口径卡未写 CV 平均增益 0.0012'

    for name, key in (('4class.json', 'accuracy'), ('mtl.json', 'accuracy')):
        data = _load_json(name)
        assert '%.4f' % data[key] in card, '口径卡未写 %s 的 %s' % (name, key)
        assert '%.4f' % data['macro_f1'] in card, \
            '口径卡未写 %s 的宏 F1' % name


def test_card_system_scale_matches_draft():
    """系统规模、情感分布、测试数须与论文第 7 章一致。"""
    card = _card_text()
    draft = _draft_text()

    for token in ('72235', '6420', '723', '605', '118'):
        assert token in card, '口径卡未写系统数据 %s' % token
        assert token in draft, '论文正文未写 %s,口径卡不该先出现' % token

    # 723 是后端 605 + 前端 118,三个数都要能对上,
    # 免得改了一边忘了另一边
    assert '605 + 前端 118' in card, \
        '口径卡未说明 723 由后端 605 + 前端 118 组成'
    assert '后端 605' in draft, '论文正文未说明后端测试数 605'

    for share in ('32.12', '6.64', '61.25'):
        assert share in card, '口径卡未写系统情感分布 %s' % share
        assert share in draft, '论文正文未写 %s' % share

    # 训练集中性占比 42.05,与系统 61.25 是两个数,必须都能区分
    assert '42.05' in card and '61.25' in card, \
        '口径卡未同时给出训练集与系统的中性占比'


def test_card_sentiment_return_numbers_match_draft():
    """情感—收益的结论数字须与论文一致。

    「744」是合并前的对齐条数,「575」是去重后的收益日数 —— 两个都要出现,
    因为答辩时最容易被追问的就是「你样本到底多少」。
    """
    card = _card_text()
    draft = _draft_text()
    for token in ('744', '575', '0.0452', '0.2795'):
        assert token in card, '口径卡未写情感—收益数字 %s' % token
        assert token in draft, '论文正文未写 %s' % token


def test_card_cited_reference_numbers_exist():
    """口径卡里用 [N] 引的文献,论文参考文献表里必须有。"""
    card = _card_text()
    draft = _draft_text()

    idx = draft.find(_REF_HEADER)
    assert idx > 0, '论文缺少参考文献节'
    refs = set()
    for line in draft[idx:].splitlines():
        m = re.match(r'^\[(\d{1,2})\]\s+(\S.*)$', line.strip())
        if m:
            refs.add(int(m.group(1)))

    cited = {int(n) for n in re.findall(r'\[(\d{1,2})\]', card)}
    orphan = sorted(cited - refs)
    assert not orphan, '口径卡引用了论文没有的文献编号: %s' % orphan


def test_card_paper_scale_numbers_match_draft():
    """论文规模(章/图/表/文献数)须与论文一致。"""
    card = _card_text()
    draft = _draft_text()

    assert '8 章' in card, '口径卡未写论文共 8 章'
    assert '14 张' in card, '口径卡未写论文共 14 张图'
    assert '32 张' in card, '口径卡未写论文共 32 张表'
    assert '37 条' in card, '口径卡未写参考文献 37 条'

    # 与论文正文的计数互相印证
    refs = re.findall(r'^\[(\d{1,2})\]', draft[draft.find(_REF_HEADER):], re.M)
    assert len(refs) == 37, '论文参考文献 %d 条,应为 37' % len(refs)
    tables = set(re.findall(r'^\*\*表 (\d-\d+)', draft, re.M))
    assert len(tables) == 32, '论文表 %d 张,应为 32' % len(tables)


# ---------------------------------------------------------------- 纪律:卡片自己不能违规

def test_card_does_not_claim_questions_are_noise():
    """纪律:不许写"问句是噪声/应当删除",卡片里也只能出现在否定语境。"""
    card = _card_text()
    banned = ['问句是噪声', '问句属于噪声', '应当删除问句样本', '问句样本应当删除']
    for phrase in banned:
        for m in re.finditer(re.escape(phrase), card):
            window = card[max(0, m.start() - 80):m.start()]
            assert ('不能说' in window or '不主张' in window or
                    '否证' in window or '不等于' in window or
                    '不能' in window or '不应' in window), \
                '口径卡出现「%s」且不在否定语境:...%s' % (phrase, window)


def test_card_never_says_significant_improvement():
    """纪律:集成不显著,"显著提升"四个字不能作为论断出现。

    「八句不能说的话」那张表要原样引用错误说法(包括这句),才能对照出
    正确说法,所以先剔除该表再检查 —— 引用的错误话不是论断。
    """
    card = _card_text()
    start = card.find('## 四、八句不能说的话')
    assert start > 0, '口径卡缺少「八句不能说的话」小节'
    end = card.find('## 五、', start)
    assert end > start
    body = card[:start] + card[end:]

    assert '显著提升' not in body, \
        '口径卡出现「显著提升」,集成 McNemar p=0.0583 实际不显著'


def test_card_leaked_accuracy_is_marked_unusable():
    """纪律:0.9864 只能作为"泄漏、不可引用"的反面例子。"""
    card = _card_text()
    if '0.9864' not in card:
        pytest.skip('口径卡未提及泄漏结果')
    for m in re.finditer(r'0\.9864', card):
        window = card[max(0, m.start() - 200):m.start() + 200]
        assert ('泄漏' in window or '不可引用' in window or
                '不能作为' in window or '不能拿' in window), \
            '0.9864 出现处未标注泄漏/不可引用:...%s' % window


def test_card_does_not_claim_price_prediction():
    """纪律:不能说"情感分析能预测股价",也不能说"对股价无效"。"""
    card = _card_text()
    for m in re.finditer(r'预测股价', card):
        window = card[max(0, m.start() - 120):m.start() + 120]
        assert ('不能说' in window or '不能' in window or
                '未检出' in window or '不主张' in window), \
            '口径卡出现「预测股价」且未加否定:...%s' % window

    # 必须带上三重限定
    sec = _section(card, '第 7 章', '### 第 8 章')
    assert '本数据' in sec, '情感—收益结论未限定数据范围'
    assert '线性' in sec, '情感—收益结论未限定线性前提'


def test_card_admits_no_kappa():
    """纪律:没做多人标注一致性检验,卡片必须主动承认,不许编数值。

    这一条对应论文第 8 章第二条不足。卡片如果给出一个 Kappa 数值,
    就等于教学生在答辩时编造数据。
    """
    card = _card_text()
    sec = _section(card, '### 第 3 章', '### 第 4 章')
    assert 'Kappa' in sec, '口径卡第 3 章未提 Kappa'
    assert '没有做' in sec or '没做' in sec, \
        '口径卡未明确承认没有做 Kappa 检验'
    assert '不能声称' in sec or '不能' in sec, \
        '口径卡未说明不能声称标注一致性高'

    # 全文不许出现 Kappa = 某个数
    assert not re.search(r'Kappa\s*[=＝]\s*0?\.\d', card), \
        '口径卡给出了 Kappa 数值,但论文没有做过这项检验'


def test_card_warns_about_system_vs_train_distribution():
    """纪律:系统 61% 中性 vs 训练集 42%,必须主动说明语体差异。"""
    card = _card_text()
    sec = _section(card, '### 第 7 章', '### 第 8 章')
    assert '61.25' in sec and '42.05' in sec, \
        '第 7 章口径未同时给出两个中性占比'
    assert ('语体' in sec or '新闻' in sec), '未说明差异来自语体不同'
    assert ('未做独立评测' in sec or '不知道' in sec), \
        '未承认没有对系统数据做独立评测'


def test_card_eight_forbidden_sentences_table_is_complete():
    """「八句不能说的话」必须是八行,且每行都有"应该说"。"""
    card = _card_text()
    sec = _section(card, '## 四、八句不能说的话', '## 五、')
    rows = _table_rows(sec)
    assert len(rows) == 9, \
        '八句表应为 1 表头 + 8 行,实际 %d 行' % len(rows)

    for row in rows[1:]:
        assert len(row) >= 3, '表格行缺少「应该说」列: %s' % row
        assert row[2].strip(), '第 %s 句缺「应该说」的内容' % row[0]

    body = '\n'.join('|'.join(r) for r in rows[1:])
    for token in ('问句是噪声', '0.5', '43.32', '显著', '0.9864', '预测股价',
                  '61%', '股吧'):
        assert token in body, '八句表未覆盖「%s」这个坑' % token


def test_card_ten_questions_table_is_complete():
    """「十个必答问题」必须是十行,且每行指向具体章节。"""
    card = _card_text()
    sec = _section(card, '## 三、十个必答问题', '## 四、')
    rows = _table_rows(sec)
    assert len(rows) == 11, \
        '十问表应为 1 表头 + 10 行,实际 %d 行' % len(rows)

    for row in rows[1:]:
        assert len(row) >= 4, '表格行缺少列: %s' % row
        assert re.search(r'第 \d+', row[3]) or '〇' in row[3], \
            '第 %s 问未指向具体章节: %s' % (row[0], row[3])


def test_card_demo_section_warns_against_sync():
    """演示流程必须明确警告不要点「同步采集」。

    现场网络不稳时点采集会卡住或报错,这是演示最容易翻车的地方。
    """
    card = _card_text()
    sec = _section(card, '## 五、现场演示流程', '## 六、')
    assert '同步采集' in sec, '演示流程未提到「同步采集」按钮'
    assert '不要点' in sec, '演示流程未警告不要点「同步采集」'
    assert '断网' in sec or '离线' in sec, \
        '演示流程未说明断网也能演示'


def test_card_demo_section_hides_browser_extras():
    """截图/演示前要隐藏书签栏,避免泄露个人信息。"""
    card = _card_text()
    sec = _section(card, '## 五、现场演示流程', '## 六、')
    assert '书签栏' in sec, '演示流程未要求隐藏书签栏'
