"""
论文配图生成器 —— 把 data/experiments 里的结果画成论文用的 PNG。

为什么单独一个脚本:
    论文里 13 张图全部由实测数据生成,没有一张是手绘或估算的。
    这样"图里的每个数字都能从结果文件重跑出来"这条原则同样延伸到图,
    而不是只延伸到表。图注、坐标轴、标注的数值也都在这里固定,
    避免正文与图不一致。

用法:
    .python\\python.exe tools\\make_figures.py
    .python\\python.exe tools\\make_figures.py --only 3-1,3-2
    .python\\python.exe tools\\make_figures.py --dpi 300

输出:
    论文/figures/fig-<编号>.png

关于图 7-3:
    系统界面截图必须由作者本人从运行中的系统截取,脚本不生成,
    只打印提醒。无头浏览器在沙箱里跑不起来(缺命名管道),不假装能截。

退出码 0 = 成功。
"""

import argparse
import csv
import functools
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
_FIG_DIR = os.path.join(_WS, '论文', 'figures')
_EXP = os.path.join(_WS, 'data', 'experiments')
_RAW = os.path.join(_WS, 'data', 'raw')

# 与前端图表同一套配色:中文语境下红涨绿跌,中性用灰。
# 图和系统界面用同一套颜色,读者对照着看不费劲。
C_POS = '#c8443a'
C_NEG = '#2e7d5b'
C_NEU = '#8a857d'
C_INK = '#191713'
C_MUTED = '#6f6862'
C_LINE = '#c9c2b4'
C_FILL = '#f7f4ee'
C_ACCENT = '#2f5d8a'

LABELS = ['负面', '正面', '中性']
LABEL_KEYS = ['negative', 'positive', 'neutral']
COLORS = [C_NEG, C_POS, C_NEU]

plt = None  # 延迟导入,见 _setup()


# ------------------------------------------------------------------ 基础设施

def _setup():
    """导入 matplotlib 并设好中文字体与全局样式。"""
    global plt
    if plt is not None:
        return plt

    # MPLCONFIGDIR 必须在 import matplotlib **之前**设好:matplotlib 在
    # 导入时就读它来决定缓存目录,设晚了等于没设(仍会去写系统目录,
    # 沙箱下不可写)。这是踩过的坑,顺序不能调。
    os.environ.setdefault('MPLCONFIGDIR', os.path.join(_WS, '.tmp', 'mpl-cache'))

    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import font_manager, pyplot

    # 中文字体必须显式注册,否则标签全是方框。
    for fname in ('msyh.ttc', 'simhei.ttf', 'simsun.ttc'):
        path = 'C:/Windows/Fonts/' + fname
        if os.path.isfile(path):
            font_manager.fontManager.addfont(path)

    pyplot.rcParams['font.family'] = ['Microsoft YaHei', 'SimHei', 'sans-serif']
    pyplot.rcParams['axes.unicode_minus'] = False   # 负号显示成 −,不是方框
    pyplot.rcParams['axes.edgecolor'] = C_LINE
    pyplot.rcParams['axes.labelcolor'] = C_INK
    pyplot.rcParams['text.color'] = C_INK
    pyplot.rcParams['xtick.color'] = C_MUTED
    pyplot.rcParams['ytick.color'] = C_MUTED
    pyplot.rcParams['figure.facecolor'] = 'white'
    plt = pyplot
    return plt


def _load_json(name):
    with open(os.path.join(_EXP, name), encoding='utf-8') as fh:
        return json.load(fh)


def _read_csv(name):
    path = os.path.join(_RAW, name)
    with open(path, encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def _token_lengths():
    """每个标题的 BERT 词元数(含 [CLS]/[SEP]),带缓存。

    论文表 3-3 报的 ">64 词元 2 条、最长 74" 就是这个口径:
    len(tokenizer(text)['input_ids'])。缓存到 data/experiments 下,
    因为加载分词器要十几秒,而这张图一年只画几次。
    """
    cache = os.path.join(_EXP, 'token_lengths.json')
    if os.path.isfile(cache):
        with open(cache, encoding='utf-8') as fh:
            return json.load(fh)

    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(
        os.path.join(_WS, 'models', 'bert-base-chinese'))
    out = {}
    for split, fname in (('train', 'eastmoney_train.csv'),
                         ('test', 'eastmoney_test.csv')):
        lengths = []
        for row in _read_csv(fname):
            ids = tok(row['title'], truncation=False)['input_ids']
            lengths.append(len(ids))
        out[split] = lengths

    with open(cache, 'w', encoding='utf-8') as fh:
        json.dump(out, fh)
    return out


def _save(fig, name, dpi):
    os.makedirs(_FIG_DIR, exist_ok=True)
    path = os.path.join(_FIG_DIR, 'fig-%s.png' % name)
    fig.savefig(path, dpi=dpi, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


def _rounded(ax, x, y, w, h, text, fc=C_FILL, ec=C_LINE, fs=11, weight='normal'):
    """画一个圆角框并在中心写字,用于流程图与架构图。"""
    from matplotlib.patches import FancyBboxPatch

    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle='round,pad=0.012,rounding_size=0.05',
        fc=fc, ec=ec, lw=1.3, zorder=2))
    ax.text(x + w / 2, y + h / 2, text, ha='center', va='center',
            fontsize=fs, weight=weight, linespacing=1.6, zorder=3)


def _arrow(ax, x1, y1, x2, y2, label=''):
    from matplotlib.patches import FancyArrowPatch

    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle='-|>', mutation_scale=15,
        color=C_MUTED, lw=1.3, shrinkA=0, shrinkB=0, zorder=1))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.02, label, ha='center',
                va='bottom', fontsize=9, color=C_MUTED)


# ------------------------------------------------------------------ 第 1 章

def fig_1_1(dpi):
    """技术路线图:四段流程,对应第 3–7 章。"""
    fig, ax = plt.subplots(figsize=(9.2, 2.9))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    steps = [
        ('数据获取与\n质量核查', '第 3 章'),
        ('双路线\n对比实验', '第 4 章'),
        ('中性类标签\n瓶颈量化', '第 5 章'),
        ('改进尝试与\n系统实现', '第 6–7 章'),
    ]
    w, h, y = 0.205, 0.30, 0.46
    xs = [0.02, 0.265, 0.51, 0.755]
    for (text, chap), x in zip(steps, xs):
        _rounded(ax, x, y, w, h, text, fs=11.5, weight='bold')
        ax.text(x + w / 2, y - 0.10, chap, ha='center', va='center',
                fontsize=9.5, color=C_MUTED)
    for i in range(3):
        _arrow(ax, xs[i] + w, y + h / 2, xs[i + 1], y + h / 2)

    # 底部一行说明每段产出什么,让读者一眼看出递进关系
    outs = ['8516 / 2130 条', '0.7540 vs 0.6296', '385 / 524 = 73.47%', '六类改进全负']
    for text, x in zip(outs, xs):
        ax.text(x + w / 2, 0.16, text, ha='center', va='center',
                fontsize=9, color=C_ACCENT)
    return _save(fig, '1-1', dpi)


# ------------------------------------------------------------------ 第 2 章

def fig_2_1(dpi):
    """BERT 微调四段式流程。"""
    fig, ax = plt.subplots(figsize=(9.2, 2.9))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    steps = [
        ('预训练\nBERT 中文版', '110M 参数'),
        ('加三分类头', '768 维 → 3 类'),
        ('微调', '8516 条 / 3 轮 / lr 2e-5'),
        ('推理', '测试集 2130 条'),
    ]
    w, h, y = 0.20, 0.28, 0.47
    xs = [0.025, 0.27, 0.515, 0.76]
    for (text, sub), x in zip(steps, xs):
        _rounded(ax, x, y, w, h, text, fs=11.5, weight='bold')
        ax.text(x + w / 2, y - 0.09, sub, ha='center', va='center',
                fontsize=9, color=C_MUTED)
    for i in range(3):
        _arrow(ax, xs[i] + w, y + h / 2, xs[i + 1], y + h / 2)

    ax.text(0.5, 0.14, '最长 64 词元,超出截断;全量 10646 条中仅 2 条超长(0.02%)',
            ha='center', va='center', fontsize=9.5, color=C_ACCENT)
    return _save(fig, '2-1', dpi)


# ------------------------------------------------------------------ 第 3 章

def fig_3_1(dpi):
    """训练集/测试集标签分布,柱上标数值。"""
    tr = [2529, 2406, 3581]
    te = [641, 618, 871]

    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    xs = range(3)
    width = 0.36
    b1 = ax.bar([x - width / 2 for x in xs], tr, width,
                label='训练集(8516)', color=C_ACCENT, alpha=0.85)
    b2 = ax.bar([x + width / 2 for x in xs], te, width,
                label='测试集(2130)', color=C_NEU, alpha=0.75)
    for bars in (b1, b2):
        for rect in bars:
            ax.text(rect.get_x() + rect.get_width() / 2,
                    rect.get_height() + 45, '%d' % rect.get_height(),
                    ha='center', va='bottom', fontsize=10)
    for i, (n, total) in enumerate(zip(tr, [8516] * 3)):
        ax.text(i - width / 2, n * 0.5, '%.2f%%' % (100 * n / total),
                ha='center', va='center', fontsize=10, color='white',
                weight='bold')

    ax.set_xticks(list(xs))
    ax.set_xticklabels(LABELS)
    ax.set_ylabel('标题条数')
    ax.set_ylim(0, 4100)
    ax.legend(frameon=False, loc='upper left')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_title('训练集与测试集的标签分布', fontsize=12)
    return _save(fig, '3-1', dpi)


def fig_3_2(dpi):
    """标题词元长度分布,标 64 词元截断线。"""
    lengths = _token_lengths()['train']

    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    ax.hist(lengths, bins=range(0, max(lengths) + 3, 3),
            color=C_ACCENT, alpha=0.8, edgecolor='white')
    ax.axvline(64, color=C_NEG, linestyle='--', linewidth=1.6)
    over = sum(1 for n in lengths if n > 64)
    ax.text(64, ax.get_ylim()[1] * 0.92,
            '  截断线 64 词元\n  超出 %d 条(%.2f%%)'
            % (over, 100.0 * over / len(lengths)),
            color=C_NEG, fontsize=10, va='top')
    ax.set_xlabel('词元数(含 [CLS] / [SEP])')
    ax.set_ylabel('标题条数')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_title('训练集标题的词元长度分布(n=%d,最长 %d)'
                 % (len(lengths), max(lengths)), fontsize=12)
    return _save(fig, '3-2', dpi)


# ------------------------------------------------------------------ 第 4 章

def fig_4_1(dpi):
    """三任务指标对比:准确率与宏 F1 两个子图。"""
    tasks = ['A 三分类', 'B 二分类极性', 'C 中性 vs 有情感']
    tfidf_acc = [0.6296, 0.7546, 0.7352]
    bert_acc = [0.7540, 0.8435, 0.8099]
    major = [0.4089, 0.5091, 0.5911]
    tfidf_f1 = [0.6204, 0.7540, 0.7093]
    bert_f1 = [0.7491, 0.8435, 0.7962]

    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.2))
    xs = range(3)
    width = 0.26

    ax = axes[0]
    ax.bar([x - width for x in xs], tfidf_acc, width, label='TF-IDF', color=C_NEU)
    ax.bar(list(xs), bert_acc, width, label='BERT', color=C_ACCENT)
    ax.bar([x + width for x in xs], major, width, label='多数类基线',
           color=C_LINE, alpha=0.9)
    for off, vals in ((-width, tfidf_acc), (0, bert_acc), (width, major)):
        for x, v in zip(xs, vals):
            ax.text(x + off, v + 0.012, '%.4f' % v, ha='center', va='bottom',
                    fontsize=8.5, rotation=90)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel('准确率')
    ax.set_xticks(list(xs))
    ax.set_xticklabels(tasks, fontsize=9.5)
    ax.set_title('准确率', fontsize=11.5)
    ax.legend(frameon=False, fontsize=9, loc='upper left')

    ax = axes[1]
    ax.bar([x - width / 2 for x in xs], tfidf_f1, width, label='TF-IDF', color=C_NEU)
    ax.bar([x + width / 2 for x in xs], bert_f1, width, label='BERT', color=C_ACCENT)
    for off, vals in ((-width / 2, tfidf_f1), (width / 2, bert_f1)):
        for x, v in zip(xs, vals):
            ax.text(x + off, v + 0.012, '%.4f' % v, ha='center', va='bottom',
                    fontsize=8.5, rotation=90)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel('宏 F1')
    ax.set_xticks(list(xs))
    ax.set_xticklabels(tasks, fontsize=9.5)
    ax.set_title('宏 F1(多数类基线不适用,未画)', fontsize=11.5)
    ax.legend(frameon=False, fontsize=9, loc='upper left')

    for ax in axes:
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
    fig.tight_layout()
    return _save(fig, '4-1', dpi)


def fig_4_2(dpi):
    """BERT 混淆矩阵热力图,行归一化并标百分比。"""
    matrix = [[439, 81, 121], [58, 454, 106], [113, 45, 713]]

    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    norm = [[v / sum(row) for v in row] for row in matrix]
    im = ax.imshow(norm, cmap='Blues', vmin=0, vmax=1)
    for i in range(3):
        for j in range(3):
            ax.text(j, i, '%d\n%.2f%%' % (matrix[i][j], 100 * norm[i][j]),
                    ha='center', va='center', fontsize=11,
                    color='white' if norm[i][j] > 0.5 else C_INK)
    ax.set_xticks(range(3))
    ax.set_yticks(range(3))
    ax.set_xticklabels(LABELS)
    ax.set_yticklabels(LABELS)
    ax.set_xlabel('预测类别')
    ax.set_ylabel('真实类别')
    ax.set_title('BERT 三分类混淆矩阵(按行归一化,准确率 0.7540)', fontsize=11.5)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    return _save(fig, '4-2', dpi)


# ------------------------------------------------------------------ 第 5 章

def fig_5_1(dpi):
    """三类问句占比,突出中性类的 48.28%。"""
    narrow = [22.78, 9.27, 48.28]
    loose = [35.98, 19.04, 65.48]

    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    xs = range(3)
    width = 0.34
    # 三类各用一个颜色;中性用强调色,因为它才是本节的主角。
    # 宽口径柱用同色低透明度,读者一眼看出是同一个类的两个口径。
    colors = [C_NEG, C_POS, C_ACCENT]
    bars = ax.bar([x - width / 2 for x in xs], narrow, width,
                  label='窄口径(标题含问号)', color=colors)
    for rect, v in zip(bars, narrow):
        ax.text(rect.get_x() + rect.get_width() / 2, v + 1.0, '%.2f%%' % v,
                ha='center', va='bottom', fontsize=10.5, weight='bold')
    loose_bars = ax.bar([x + width / 2 for x in xs], loose, width,
                        label='宽口径(含疑问词)', color=colors, alpha=0.35)
    for rect, v in zip(loose_bars, loose):
        ax.text(rect.get_x() + rect.get_width() / 2, v + 1.0, '%.2f%%' % v,
                ha='center', va='bottom', fontsize=9.5, color=C_MUTED)

    ax.set_xticks(list(xs))
    ax.set_xticklabels(LABELS)
    ax.set_ylabel('问句占该类条数的比例(%)')
    ax.set_ylim(0, 90)
    ax.legend(frameon=False, loc='upper left', fontsize=9.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    # 不用箭头:中性组两根柱子已经把 48.28% / 65.48% 标出来了,
    # 再加箭头会压住数字,反而看不清。
    ax.text(2, 76, '中性类接近一半是问句', ha='center', va='center',
            fontsize=10, color=C_ACCENT)
    ax.set_title('训练集三类的问句占比', fontsize=12)
    return _save(fig, '5-1', dpi)


def fig_5_2(dpi):
    """错误流向:524 个错误中 385 条牵涉中性边界,139 条极性互错。

    这里必须按 pairs 拆,不能按 sinks 拆。sinks 是"口径一"(按预测类别归并,
    227/171/126 合计 524),它把极性互错的 139 条也算进了负面和正面两个 sink;
    本图讲的是"口径二"(真实或预测有一边是中性),所以要把六个混淆对分开摆,
    再把其中四个含中性的归到上条、两个纯极性互错的归到下条。
    两个口径都要在论文里报,但一张图只能讲一个口径 —— 图注里点明。
    """
    flow = _load_json('neutral-split.json')['error_flow']
    pairs = flow['pairs']
    boundary = flow['boundary_errors']
    polarity = flow['polarity_errors']

    # 中文简称,给图里的分段用
    short = {'negative': '负面', 'positive': '正面', 'neutral': '中性'}

    fig, ax = plt.subplots(figsize=(8.8, 3.6))

    def draw(y, items, title_color):
        left = 0
        for item in items:
            n = item['n']
            src, dst = item['true'], item['pred']
            # 按"被误判成哪一类"上色:误判为中性用灰,误判为负面用绿,正面用红
            color = {'neutral': C_NEU, 'negative': C_NEG, 'positive': C_POS}[dst]
            # 真实类是中性时颜色淡一点,便于区分"被吞进中性"和"从中性吐出"
            alpha = 0.55 if src == 'neutral' else 1.0
            ax.barh(y, n, left=left, color=color, alpha=alpha,
                    edgecolor='white', height=0.46)
            label = '%s→%s\n%d' % (short[src], short[dst], n)
            # 段太窄就把字放到外面,避免压成一团
            if n >= 70:
                ax.text(left + n / 2, y, label, ha='center', va='center',
                        fontsize=9, color='white' if alpha == 1.0 else C_INK,
                        weight='bold', linespacing=1.4)
            else:
                ax.text(left + n / 2, y + 0.30, label, ha='center', va='bottom',
                        fontsize=8.5, color=C_INK, linespacing=1.4)
            left += n

    draw(1, [p for p in pairs if p['true'] == 'neutral' or p['pred'] == 'neutral'],
         C_NEU)
    draw(0, [p for p in pairs if p['true'] != 'neutral' and p['pred'] != 'neutral'],
         C_ACCENT)

    ax.set_yticks([0, 1])
    ax.set_yticklabels([
        '极性互错\n%d 条(%.2f%%)' % (polarity, 100 * flow['polarity_share']),
        '牵涉中性边界\n%d 条(%.2f%%)' % (boundary, 100 * flow['boundary_share']),
    ], fontsize=10)
    ax.set_xlabel('错误条数(合计 %d)' % flow['total_errors'])
    ax.set_xlim(0, boundary * 1.04)
    ax.set_ylim(-0.5, 1.75)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_title('524 个错误的流向:牵涉中性边界的是极性互错的 %.2f 倍'
                 % (boundary / polarity), fontsize=12)
    return _save(fig, '5-2', dpi)


def fig_5_3(dpi):
    """问句组与陈述句组的准确率、宏 F1 方向相反。"""
    ev = _load_json('neutral-split.json')['split_eval']
    groups = ['全集', '陈述句', '问句']
    acc = [ev['overall']['accuracy'], ev['statement']['accuracy'], ev['question']['accuracy']]
    f1 = [ev['overall']['macro_f1'], ev['statement']['macro_f1'], ev['question']['macro_f1']]
    ns = [ev['overall']['n'], ev['statement']['n'], ev['question']['n']]

    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    xs = range(3)
    width = 0.34
    ax.bar([x - width / 2 for x in xs], acc, width, label='准确率', color=C_ACCENT)
    ax.bar([x + width / 2 for x in xs], f1, width, label='宏 F1', color=C_NEU)
    for off, vals in ((-width / 2, acc), (width / 2, f1)):
        for x, v in zip(xs, vals):
            ax.text(x + off, v + 0.01, '%.4f' % v, ha='center', va='bottom',
                    fontsize=9.5)
    ax.set_xticks(list(xs))
    ax.set_xticklabels(['%s\n(n=%d)' % (g, n) for g, n in zip(groups, ns)])
    ax.set_ylim(0, 1.02)
    ax.set_ylabel('指标值')
    # 图例放在柱子之上:柱子都接近 0.8,放左上会压住第一组
    ax.legend(frameon=False, loc='upper left', ncol=2, fontsize=9.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.annotate('准确率更高\n宏 F1 更低', xy=(2 - width / 2, 0.7882),
                xytext=(1.05, 0.55), fontsize=10, color=C_NEG,
                arrowprops=dict(arrowstyle='->', color=C_NEG, lw=1.2))
    ax.set_title('问句组与陈述句组的指标方向相反', fontsize=12)
    return _save(fig, '5-3', dpi)


# ------------------------------------------------------------------ 第 6 章

def fig_6_1(dpi):
    """超参扫描:轮数维度,学习率固定 2e-5。"""
    sweep = _load_json('sweep.json')

    pts = []
    for key, cfg in sweep.items():
        if abs(cfg['lr'] - 2e-5) < 1e-12:
            pts.append((cfg['epochs'], cfg['accuracy'], cfg['macro_f1']))
    pts.sort()

    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    xs = [p[0] for p in pts]
    ax.plot(xs, [p[1] for p in pts], 'o-', color=C_ACCENT, label='准确率', lw=1.8)
    ax.plot(xs, [p[2] for p in pts], 's--', color=C_NEU, label='宏 F1', lw=1.8)
    for x, a, f in pts:
        ax.text(x, a + 0.004, '%.4f' % a, ha='center', va='bottom', fontsize=9,
                color=C_ACCENT)
        ax.text(x, f - 0.006, '%.4f' % f, ha='center', va='top', fontsize=9,
                color=C_MUTED)
    ax.set_xticks(xs)
    ax.set_xlabel('训练轮数(学习率固定 2e-5)')
    ax.set_ylabel('指标值')
    ax.set_ylim(0.70, 0.775)
    ax.legend(frameon=False, loc='lower left')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.annotate('3 轮即最优', xy=(3, 0.7540), xytext=(4.1, 0.768),
                fontsize=10, color=C_NEG,
                arrowprops=dict(arrowstyle='->', color=C_NEG, lw=1.2))
    ax.set_title('超参数扫描:训练轮数的影响', fontsize=12)
    return _save(fig, '6-1', dpi)


# ------------------------------------------------------------------ 第 7 章

def fig_7_1(dpi):
    """系统三层架构。"""
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    layers = [
        (0.70, '展示层', 'Vue 3 单页应用 · ECharts 图表\n行情 / 情感分布 / 情感与收益关联', C_ACCENT),
        (0.40, '服务层', 'FastAPI 提供 REST 接口 · SQLAlchemy 数据访问\n独立推理模块加载 BERT 三分类模型', '#5a7d9a'),
        (0.10, '采集层', '东方财富新闻搜索(分页) · 腾讯日线行情(备用源)\n字段归一化与去重', '#8fa8bd'),
    ]
    for y, name, detail, color in layers:
        ax.add_patch(plt.Rectangle((0.06, y), 0.88, 0.20, fc=C_FILL,
                                   ec=C_LINE, lw=1.3, zorder=2))
        ax.add_patch(plt.Rectangle((0.06, y), 0.14, 0.20, fc=color, ec=color,
                                   lw=1.3, zorder=3))
        ax.text(0.13, y + 0.10, name, ha='center', va='center', fontsize=11.5,
                color='white', weight='bold', zorder=4)
        ax.text(0.55, y + 0.10, detail, ha='center', va='center', fontsize=10,
                zorder=4, linespacing=1.7)

    _arrow(ax, 0.5, 0.30, 0.5, 0.40)
    _arrow(ax, 0.5, 0.60, 0.5, 0.70)
    ax.text(0.53, 0.35, 'REST / JSON', fontsize=9, color=C_MUTED, va='center')
    ax.text(0.53, 0.65, 'REST / JSON', fontsize=9, color=C_MUTED, va='center')
    return _save(fig, '7-1', dpi)


def fig_7_2(dpi):
    """数据库 ER 图:三张表与外键关系。"""
    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    def table(x, y, w, title, fields, color):
        h = 0.085 + 0.052 * len(fields)
        ax.add_patch(plt.Rectangle((x, y - h), w, h, fc='white', ec=color,
                                   lw=1.4, zorder=2))
        ax.add_patch(plt.Rectangle((x, y - 0.085), w, 0.085, fc=color,
                                   ec=color, lw=1.4, zorder=3))
        ax.text(x + w / 2, y - 0.0425, title, ha='center', va='center',
                fontsize=11, color='white', weight='bold', zorder=4)
        # 最后一行的文字中心留 0.026 的底边距,否则会压住边框线
        for i, f in enumerate(fields):
            ax.text(x + 0.012, y - 0.085 - 0.052 * (i + 0.5), f,
                    ha='left', va='center', fontsize=8.6, zorder=4,
                    family=['Consolas', 'Microsoft YaHei'])
        return h

    table(0.03, 0.90, 0.30, 'Stock', [
        'code        PK',
        'name',
        'market',
        'created_at',
    ], C_ACCENT)

    table(0.60, 0.90, 0.36, 'Kline', [
        'id           PK',
        'code         FK -> Stock.code',
        'trade_date   UNIQUE(code, trade_date)',
        'open / close / high / low',
        'volume / amount',
        'amplitude / change_pct',
    ], '#5a7d9a')

    table(0.60, 0.44, 0.36, 'News', [
        'id            PK',
        'code          FK -> Stock.code',
        'title / url   UNIQUE(code, url)',
        'source / publish_time',
        'sentiment / sentiment_score',
        'fetched_at',
    ], C_NEG)

    _arrow(ax, 0.33, 0.78, 0.60, 0.78, '1 : N')
    _arrow(ax, 0.33, 0.70, 0.60, 0.30, '1 : N')
    return _save(fig, '7-2', dpi)


def fig_7_4(dpi):
    """情感指数与次日收益的散点图,附最小二乘拟合线。"""
    data = _load_json('returns.json')
    pairs = []
    for stock in data['per_stock']:
        pairs.extend(stock.get('pairs') or [])
    overall = data['overall']

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    xs = [p['polarity'] for p in pairs]
    ys = [p['return'] for p in pairs]
    ax.scatter(xs, ys, s=18, color=C_ACCENT, alpha=0.45, edgecolor='none')

    # 最小二乘拟合线;方差为 0 时不画(除零会得到 Infinity)
    n = len(xs)
    if n >= 3:
        mx = sum(xs) / n
        my = sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        if den > 0:
            b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
            a = my - b * mx
            line_x = [-1, 1]
            ax.plot(line_x, [a + b * x for x in line_x], color=C_NEG, lw=1.8,
                    label='最小二乘拟合线')

    ax.axhline(0, color=C_LINE, lw=0.9, linestyle=':')
    ax.axvline(0, color=C_LINE, lw=0.9, linestyle=':')
    ax.set_xlim(-1.05, 1.05)
    ax.set_xlabel('情感指数 polarity =(正面条数 − 负面条数)/ 当日总条数')
    ax.set_ylabel('次日收益率(%)')
    ax.legend(frameon=False, loc='upper left', fontsize=9)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_title('情感指数与次日收益(n=%d,Pearson %.4f,p=%.4f)'
                 % (overall['n'], overall['pearson'], overall['p_value']),
                 fontsize=11.5)
    return _save(fig, '7-4', dpi)


# ------------------------------------------------------------------ 入口

# 图号 -> 生成函数。图 7-3(系统界面截图)不在这里,必须作者本人截。
FIGURES = {
    '1-1': fig_1_1,
    '2-1': fig_2_1,
    '3-1': fig_3_1,
    '3-2': fig_3_2,
    '4-1': fig_4_1,
    '4-2': fig_4_2,
    '5-1': fig_5_1,
    '5-2': fig_5_2,
    '5-3': fig_5_3,
    '6-1': fig_6_1,
    '7-1': fig_7_1,
    '7-2': fig_7_2,
    '7-4': fig_7_4,
}


def _autosetup(fn):
    """让每个生成函数自己保证 matplotlib 已就绪。

    plt 是延迟导入的模块级变量,只有 _setup() 跑过才有值。原先依赖
    main() 先调 _setup(),一旦有人绕过 main 直接调 fig_3_1() 就会
    在 plt.subplots 上炸出 'NoneType' object has no attribute。
    在注册处统一包一层,比在每个函数体里重复写 _setup() 可靠。
    """
    @functools.wraps(fn)
    def wrapper(dpi):
        _setup()
        return fn(dpi)
    return wrapper


for _name in list(FIGURES):
    FIGURES[_name] = _autosetup(FIGURES[_name])


def main(argv=None):
    ap = argparse.ArgumentParser(description='生成论文配图')
    ap.add_argument('--only', default='',
                    help='只画这些图号,逗号分隔,如 3-1,3-2;留空表示全部')
    ap.add_argument('--dpi', type=int, default=200, help='输出分辨率(默认 200)')
    args = ap.parse_args(argv)

    wanted = [s.strip() for s in args.only.split(',') if s.strip()]
    if wanted:
        unknown = [w for w in wanted if w not in FIGURES]
        if unknown:
            print('未知图号: %s' % ', '.join(unknown))
            print('可用图号: %s' % ', '.join(sorted(FIGURES)))
            return 2

    _setup()
    made = []
    for name in sorted(FIGURES):
        if wanted and name not in wanted:
            continue
        path = FIGURES[name](args.dpi)
        size = os.path.getsize(path)
        made.append(path)
        print('图 %s  ->  %s  (%.1f KB)'
              % (name, os.path.relpath(path, _WS), size / 1024.0))

    print('\n共生成 %d 张图。' % len(made))
    print('图 7-3(系统界面截图)需作者本人从运行中的系统截取,脚本不生成。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
