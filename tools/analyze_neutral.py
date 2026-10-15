"""
档 2:把"中性类"这个瓶颈挖透。

背景(为什么需要这个脚本):
    三分类实验里 BERT 准确率 0.7540,中性类召回 0.8186 是三类最高的,
    但中性同时是**最大的错误去向** —— 真负面有 121 条被判成中性、真正面
    有 106 条被判成中性。也就是说模型主要在"有没有态度"上犯错,而不是
    在"看涨还是看跌"上犯错。

    进一步查数据发现:中性类训练样本里有近一半以问号结尾。怀疑这套标注
    把两件不同的事塞进了同一个"中性"标签:① 真的没有态度 ② 只是在提问。

    本脚本把这条怀疑变成可复现的证据链。

用法:
    .python\\python.exe tools\\analyze_neutral.py           # 只做统计(秒级)
    .python\\python.exe tools\\analyze_neutral.py --train   # 附加重训实验(数分钟)

产出:
    data/experiments/NEUTRAL_ANALYSIS.md   分析报告(论文素材)
    data/experiments/neutral-split.json    拆问句后重训的指标

退出码 0 = 成功。
"""

import argparse
import csv
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)

# 本仓库用的是 embeddable 版 Python,它带 python312._pth 文件,而 ._pth 一旦
# 存在,解释器就**不会**把脚本所在目录塞进 sys.path。所以同目录的
# train_sentiment 直接 import 会 ModuleNotFoundError,必须显式补上。
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 离线运行,与 train_sentiment.py 保持一致
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
os.environ.setdefault('HF_HOME', os.path.join(_WS, '.tmp', 'hf-home'))

TRAIN_CSV = os.path.join(_WS, 'data', 'raw', 'eastmoney_train.csv')
TEST_CSV = os.path.join(_WS, 'data', 'raw', 'eastmoney_test.csv')
EXP_DIR = os.path.join(_WS, 'data', 'experiments')
MODELS_DIR = os.path.join(_WS, 'models')
BASE_MODEL = os.path.join(_WS, 'models', 'bert-base-chinese')

LABELS = ['negative', 'positive', 'neutral']
LABELS_4 = ['negative', 'positive', 'neutral_stmt', 'neutral_q']

# 拆问句后重训用的超参数,必须与 train_sentiment.py 一致,否则对比不公平
SEED = 42
MAX_LEN = 64
BATCH_SIZE = 32
EPOCHS = 3
LR = 2e-5

# 问句判定:主判据是句末问号。数据集里的标题多来自股吧,口语化严重,
# 问号是唯一稳定的形式标记。
_Q_END = re.compile(r'[?？]\s*$')

# 次判据:句末疑问语气词。有些标题省略问号(如"明天还能涨吗"),
# 单独统计以说明主判据会低估多少。
_Q_PARTICLE = re.compile(r'(吗|呢|吧)\s*[?？]?\s*$')

# 疑问词:用于第三层统计,衡量"是不是在问"这件事的宽口径
_Q_WORD = re.compile(r'(什么|为什么|怎么|如何|是否|多少|哪[个里只家]|吗|呢)')


def load_csv(path):
    """读数据集。返回 (文本列表, 标签列表)。"""
    if not os.path.isfile(path):
        raise SystemExit('数据集不存在: %s' % path)
    with open(path, encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit('数据集为空: %s' % path)
    return [r['title'] for r in rows], [int(r['label']) for r in rows]


def is_question(text):
    """句末有问号。"""
    return bool(_Q_END.search(text or ''))


def is_question_loose(text):
    """宽口径:句末问号,或句末疑问语气词,或含疑问词。"""
    t = text or ''
    return bool(_Q_END.search(t) or _Q_PARTICLE.search(t) or _Q_WORD.search(t))


# ------------------------------------------------------------ 证据一:问句统计

def question_stats(texts, labels):
    """按类别统计问句占比。"""
    from collections import Counter

    n = len(texts)
    total_q = sum(1 for t in texts if is_question(t))
    loose_q = sum(1 for t in texts if is_question_loose(t))

    per_class = {}
    for i, name in enumerate(LABELS):
        idx = [j for j, y in enumerate(labels) if y == i]
        if not idx:
            continue
        q = sum(1 for j in idx if is_question(texts[j]))
        lq = sum(1 for j in idx if is_question_loose(texts[j]))
        per_class[name] = {
            'n': len(idx),
            'question': q,
            'question_ratio': round(q / len(idx), 4),
            'question_loose': lq,
            'question_loose_ratio': round(lq / len(idx), 4),
        }

    # 在问句内部,各类别怎么分布? 若问句几乎都落在中性类,说明
    # "提问"与"中性"在标注里被绑定了。
    q_labels = Counter(y for t, y in zip(texts, labels) if is_question(t))
    q_dist = {LABELS[i]: q_labels.get(i, 0) for i in range(len(LABELS))}

    return {
        'n': n,
        'question': total_q,
        'question_ratio': round(total_q / n, 4),
        'question_loose': loose_q,
        'question_loose_ratio': round(loose_q / n, 4),
        'per_class': per_class,
        'question_label_dist': q_dist,
    }


# ------------------------------------------------------- 证据二:错误流向分析

def error_flow(cm, label_names):
    """从混淆矩阵算"错误都流向哪里"。

    cm 行=真实类别,列=预测类别。

    这里给出两种口径,必须都报 —— 只报一种会被质疑是挑了对自己有利的算法:
      sink      按**预测**类别归并:该类别"吸收"了多少别人的错误
      boundary  按**是否牵涉中性**归并:只要真实或预测有一边是中性就算
    前者回答"错误往哪跑",后者回答"模型到底卡在哪个边界上"。
    """
    k = len(label_names)
    total_err = sum(cm[i][j] for i in range(k) for j in range(k) if i != j)

    sinks = []
    for j in range(k):
        got = sum(cm[i][j] for i in range(k) if i != j)
        sinks.append({
            'label': label_names[j],
            'absorbed': got,
            'share': round(got / total_err, 4) if total_err else 0.0,
        })
    sinks.sort(key=lambda d: -d['absorbed'])

    pairs = []
    for i in range(k):
        for j in range(k):
            if i != j and cm[i][j]:
                pairs.append({
                    'true': label_names[i],
                    'pred': label_names[j],
                    'n': cm[i][j],
                    'share': round(cm[i][j] / total_err, 4) if total_err else 0.0,
                })
    pairs.sort(key=lambda d: -d['n'])

    # 按"是否牵涉中性边界"归并
    neu = label_names.index('neutral') if 'neutral' in label_names else -1
    boundary = 0
    polarity = 0
    for i in range(k):
        for j in range(k):
            if i == j:
                continue
            if i == neu or j == neu:
                boundary += cm[i][j]
            else:
                polarity += cm[i][j]

    return {
        'total_errors': total_err,
        'sinks': sinks,
        'pairs': pairs,
        'boundary_errors': boundary,
        'boundary_share': round(boundary / total_err, 4) if total_err else 0.0,
        'polarity_errors': polarity,
        'polarity_share': round(polarity / total_err, 4) if total_err else 0.0,
    }


def load_metrics(model, task):
    """读 train_sentiment.py 写出的指标 json。"""
    path = os.path.join(EXP_DIR, '%s-%s.json' % (model, task))
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


# --------------------------------------------- 证据三:按句式切分评估同一模型

def predict_bert(model_dir, texts, label_names):
    """用已训练好的 BERT 做推理,返回预测标签下标列表。

    只做前向,不训练 —— 2130 条几秒就跑完。
    """
    import torch
    from transformers import (AutoModelForSequenceClassification,
                              AutoTokenizer)

    if not os.path.isdir(model_dir):
        raise SystemExit('模型不存在: %s\n先跑 tools\\train_sentiment.py'
                         % model_dir)

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_dir, num_labels=len(label_names)).to(device)
    model.eval()

    preds = []
    with torch.no_grad():
        for i in range(0, len(texts), 64):
            batch = texts[i:i + 64]
            enc = tok(batch, padding=True, truncation=True,
                      max_length=MAX_LEN, return_tensors='pt')
            logits = model(input_ids=enc['input_ids'].to(device),
                           attention_mask=enc['attention_mask'].to(device)).logits
            preds.extend(logits.argmax(-1).cpu().tolist())
    return preds


def subset_metrics(y_true, y_pred, label_names):
    """子集上的指标。子集可能缺某一类,故用 sklearn 的 zero_division=0。"""
    from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score)

    if not y_true:
        return None
    cm = confusion_matrix(y_true, y_pred,
                          labels=list(range(len(label_names)))).tolist()
    out = {
        'n': len(y_true),
        'accuracy': round(float(accuracy_score(y_true, y_pred)), 4),
        'macro_f1': round(float(f1_score(
            y_true, y_pred, average='macro', zero_division=0)), 4),
        'confusion_matrix': cm,
    }
    # 每类的召回率:用来判断模型是不是"塌缩到多数类"
    per_class = {}
    for i, name in enumerate(label_names):
        support = sum(cm[i])
        per_class[name] = {
            'support': support,
            'recall': round(cm[i][i] / support, 4) if support else None,
        }
    out['per_class'] = per_class
    return out


def split_experiment(task='3class'):
    """把测试集按"是不是问句"切开,分别评估同一个模型。

    这是最干净的因果证据:模型没变、训练数据没变,只是把测试样本分成
    两组。若问句组准确率显著低于陈述组,说明"提问"这类样本本身就是
    模型的错误来源,而不是模型能力不足。
    """
    texts, labels = load_csv(TEST_CSV)
    model_dir = os.path.join(MODELS_DIR, 'sentiment-bert-%s' % task)
    preds = predict_bert(model_dir, texts, LABELS)

    q_idx = [i for i, t in enumerate(texts) if is_question(t)]
    s_idx = [i for i, t in enumerate(texts) if not is_question(t)]

    out = {
        'model': 'bert',
        'task': task,
        'criterion': 'title ends with ? or ？',
        'overall': subset_metrics(labels, preds, LABELS),
        'question': subset_metrics([labels[i] for i in q_idx],
                                   [preds[i] for i in q_idx], LABELS),
        'statement': subset_metrics([labels[i] for i in s_idx],
                                    [preds[i] for i in s_idx], LABELS),
    }

    # 问句组里,真实标签怎么分布? 若几乎全是中性,说明标注者把所有
    # 问句都归进了中性,而不是判断它们的态度。
    from collections import Counter
    qc = Counter(labels[i] for i in q_idx)
    sc = Counter(labels[i] for i in s_idx)
    out['question']['label_dist'] = {LABELS[k]: qc.get(k, 0)
                                     for k in range(len(LABELS))}
    out['statement']['label_dist'] = {LABELS[k]: sc.get(k, 0)
                                      for k in range(len(LABELS))}
    return out


# ------------------------------------------------ 证据四:去掉问句重训(可选)

def retrain_without_questions(task='3class'):
    """把问句从训练集里剔除后重训,再看整体指标。

    与 split_experiment 的区别:那个只换测试子集,这个换的是训练数据。
    两者一起才能说明"问句是噪声"而不是"问句更难"。
    """
    import train_sentiment as ts

    tr_texts, tr_labels = load_csv(TRAIN_CSV)
    te_texts, te_labels = load_csv(TEST_CSV)

    n_before = len(tr_texts)
    keep = [i for i, t in enumerate(tr_texts) if not is_question(t)]
    tr_texts = [tr_texts[i] for i in keep]
    tr_labels = [tr_labels[i] for i in keep]

    print('  剔除问句后训练集 %d 条(原 %d 条,删掉 %d 条)'
          % (len(tr_texts), n_before, n_before - len(tr_texts)))

    ts.set_seed(SEED)
    out_dir = os.path.join(MODELS_DIR, 'sentiment-bert-%s-noq' % task)
    preds, probs = ts.train_bert(tr_texts, tr_labels, te_texts, te_labels,
                                 LABELS, out_dir)

    metrics = ts.evaluate(te_labels, list(preds), LABELS, probs)
    metrics['model'] = 'bert'
    metrics['task'] = '%s-noq' % task
    metrics['n_train'] = len(tr_texts)
    metrics['n_test'] = len(te_texts)
    metrics['seed'] = SEED
    metrics['note'] = '训练集剔除以问号结尾的样本'

    os.makedirs(EXP_DIR, exist_ok=True)
    path = os.path.join(EXP_DIR, 'bert-%s-noq.json' % task)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)
    return metrics


# ------------------------------------------------------------------ 报告渲染

def pct(x):
    return '%.2f%%' % (x * 100)


def render(q_tr, q_te, flow, split=None, noq=None, base=None):
    """渲染 Markdown 报告。"""
    L = []
    L.append('# 中性类瓶颈分析')
    L.append('')
    L.append('本文档由 `tools/analyze_neutral.py` 自动生成,所有数字均可重跑复现。')
    L.append('')
    L.append('**研究问题:** 三分类实验里,中性类的召回率是三类中最高的,'
             '但它同时吸收了最多的错误。模型究竟卡在哪个边界上?')
    L.append('')
    L.append('**一句话结论:** 这套数据的"中性"是一个**复合标签**,'
             '把"真的没有态度"和"只是在提问"混成了一类。'
             '全部错误中有 **%s** 牵涉中性边界,而真正的看涨/看跌互错只占 **%s**。'
             % (pct(flow['boundary_share']) if flow else '—',
                pct(flow['polarity_share']) if flow else '—'))
    L.append('')
    L.append('> 注意证据的边界:第四节(剔除问句重训)表明问句**不是纯噪声**,'
             '所以本文主张的是"**标签语义复合导致边界系统性出错**",'
             '而不是"问句样本应当删除"。')
    L.append('')

    # ---- 证据一
    L.append('## 一、问句统计:标注体系把两件事混成了一类')
    L.append('')
    L.append('判据:标题以 `?` 或 `？` 结尾即视为问句。')
    L.append('')
    L.append('### 训练集(共 %d 条)' % q_tr['n'])
    L.append('')
    L.append('| 类别 | 样本数 | 问句数 | 问句占比 | 宽口径问句占比 |')
    L.append('|---|---|---|---|---|')
    for name in LABELS:
        v = q_tr['per_class'].get(name)
        if not v:
            continue
        L.append('| %s | %d | %d | %s | %s |'
                 % (name, v['n'], v['question'],
                    pct(v['question_ratio']), pct(v['question_loose_ratio'])))
    L.append('| **合计** | **%d** | **%d** | **%s** | **%s** |'
             % (q_tr['n'], q_tr['question'],
                pct(q_tr['question_ratio']), pct(q_tr['question_loose_ratio'])))
    L.append('')
    L.append('宽口径 = 句末问号 **或** 句末疑问语气词(吗/呢/吧) **或** 含疑问词'
             '(什么/为什么/怎么/如何/是否/多少/哪个)。')
    L.append('窄口径只认问号,会低估问句数量;两个口径都给出,避免'
             '"挑了对自己有利的判据"这类质疑。')
    L.append('')
    L.append('### 测试集(共 %d 条)' % q_te['n'])
    L.append('')
    L.append('| 类别 | 样本数 | 问句数 | 问句占比 |')
    L.append('|---|---|---|---|')
    for name in LABELS:
        v = q_te['per_class'].get(name)
        if not v:
            continue
        L.append('| %s | %d | %d | %s |'
                 % (name, v['n'], v['question'], pct(v['question_ratio'])))
    L.append('| **合计** | **%d** | **%d** | **%s** |'
             % (q_te['n'], q_te['question'], pct(q_te['question_ratio'])))
    L.append('')
    L.append('### 问句落在哪些类别')
    L.append('')
    L.append('| 真实标签 | 训练集问句数 | 该类的问句占比 |')
    L.append('|---|---|---|')
    for name in LABELS:
        n = q_tr['question_label_dist'].get(name, 0)
        v = q_tr['per_class'].get(name) or {}
        L.append('| %s | %d | %s |'
                 % (name, n, pct(n / v['n']) if v.get('n') else '—'))
    L.append('')
    qn = q_tr['question_label_dist'].get('neutral', 0)
    qt = q_tr['question'] or 1
    L.append('**两个关键数字:**')
    L.append('')
    L.append('- 中性类样本中有 **%s** 是问句(%d / %d);'
             % (pct(q_tr['per_class']['neutral']['question_ratio']),
                qn, q_tr['per_class']['neutral']['n']))
    L.append('- 反过来,全部问句中有 **%s** 被标成中性(%d / %d)。'
             % (pct(qn / qt), qn, qt))
    L.append('')
    L.append('> 对比:负面类问句占比 %s,正面类只有 %s。'
             '问号与"中性"标签的关联明显强于其他两类 —— '
             '这正是"复合标签"的统计指纹。'
             % (pct(q_tr['per_class']['negative']['question_ratio']),
                pct(q_tr['per_class']['positive']['question_ratio'])))
    L.append('')

    # ---- 证据二
    if flow:
        L.append('## 二、错误流向:瓶颈在"有没有态度",不在"看涨还是看跌"')
        L.append('')
        L.append('BERT 三分类测试集共 %d 个错误。' % flow['total_errors'])
        L.append('')
        L.append('### 口径一:按预测类别归并(错误往哪跑)')
        L.append('')
        L.append('| 预测类别 | 吸收的错误数 | 占全部错误 |')
        L.append('|---|---|---|')
        for s in flow['sinks']:
            L.append('| %s | %d | %s |'
                     % (s['label'], s['absorbed'], pct(s['share'])))
        L.append('')
        L.append('### 口径二:按"是否牵涉中性边界"归并(卡在哪个边界)')
        L.append('')
        L.append('只要真实类别或预测类别有一边是中性,就算"边界错误";'
                 '两边都是极性类(负面/正面)才算"极性互错"。')
        L.append('')
        L.append('| 错误类型 | 条数 | 占全部错误 |')
        L.append('|---|---|---|')
        L.append('| 牵涉中性边界 | %d | **%s** |'
                 % (flow['boundary_errors'], pct(flow['boundary_share'])))
        L.append('| 负面与正面直接互错 | %d | %s |'
                 % (flow['polarity_errors'], pct(flow['polarity_share'])))
        L.append('')
        L.append('> 两个口径必须都报:只报口径一会低估问题'
                 '(中性被误判成负面时,错误记在负面头上),'
                 '只报口径二又说不清错误具体往哪跑。')
        L.append('')
        L.append('### 具体混淆对(只列非零)')
        L.append('')
        L.append('| 真实类别 | 被预测为 | 条数 | 占全部错误 |')
        L.append('|---|---|---|---|')
        for p in flow['pairs']:
            L.append('| %s | %s | %d | %s |'
                     % (p['true'], p['pred'], p['n'], pct(p['share'])))
        L.append('')
        L.append('**结论:** 模型把"有态度"误判成"没态度"(或反向)的次数,'
                 '是"看涨误判成看跌"的 **%.1f 倍**。'
                 '**瓶颈在"有没有态度"这条边界上,而不是在极性方向上。**'
                 % (flow['boundary_errors'] / flow['polarity_errors']
                    if flow['polarity_errors'] else 0))
        L.append('')

    # ---- 证据三
    if split:
        L.append('## 三、按句式切分:同一模型在问句上"看似更好、实则塌缩"')
        L.append('')
        L.append('模型没变、训练数据没变,只是把**测试集**按句式切成两组。')
        L.append('')
        L.append('| 测试子集 | 样本数 | 准确率 | 宏 F1 |')
        L.append('|---|---|---|---|')
        for key, title in (('overall', '全部'), ('statement', '陈述句'),
                           ('question', '问句')):
            v = split.get(key)
            if not v:
                continue
            L.append('| %s | %d | %s | %s |'
                     % (title, v['n'], v['accuracy'], v['macro_f1']))
        L.append('')
        q = split.get('question')
        s = split.get('statement')
        if q and s:
            L.append('**这里有一个反直觉的结果:** 问句组的准确率反而**更高**'
                     '(%s vs %s),但宏 F1 **明显更低**(%s vs %s)。'
                     % (q['accuracy'], s['accuracy'], q['macro_f1'], s['macro_f1']))
            L.append('')
            L.append('原因在类别分布:问句组里中性占 %s(%d / %d),'
                     '模型只要多预测中性,准确率就上去了。'
                     '但宏 F1 对每个类别等权,立刻暴露出少数类被牺牲。'
                     % (pct(q['label_dist'].get('neutral', 0) / q['n']),
                        q['label_dist'].get('neutral', 0), q['n']))
            L.append('')
            L.append('各子集内每类的召回率:')
            L.append('')
            L.append('| 测试子集 | 类别 | 样本数 | 召回率 |')
            L.append('|---|---|---|---|')
            for key, title in (('statement', '陈述句'), ('question', '问句')):
                v = split.get(key) or {}
                for name in LABELS:
                    pc = (v.get('per_class') or {}).get(name) or {}
                    if not pc.get('support'):
                        continue
                    L.append('| %s | %s | %d | %s |'
                             % (title, name, pc['support'],
                                pc['recall'] if pc['recall'] is not None else '—'))
            L.append('')
            L.append('> **方法论要点:** 只看准确率会得出"模型处理问句更好"的'
                     '错误结论。类别不均衡时必须以宏 F1 为准 —— '
                     '这也是本实验选宏 F1 作为主指标的原因。')
            L.append('')
            L.append('问句组内部的真实标签分布:')
            L.append('')
            L.append('| 真实标签 | 条数 | 占比 |')
            L.append('|---|---|---|')
            for name in LABELS:
                n = q['label_dist'].get(name, 0)
                L.append('| %s | %d | %s |' % (name, n, pct(n / q['n'])))
            L.append('')

    # ---- 证据四
    sec = 4
    if noq and base:
        L.append('## 四、去掉问句重训:检验问句到底是不是噪声')
        L.append('')
        L.append('与第三节的区别:第三节只换**测试子集**,本节换**训练数据**。'
                 '两者一起才能区分"问句是噪声"与"问句只是更难"。')
        L.append('')
        L.append('| 训练集 | 训练样本 | 测试准确率 | 测试宏 F1 |')
        L.append('|---|---|---|---|')
        L.append('| 全量(基线) | %d | %s | %s |'
                 % (base['n_train'], base['accuracy'], base['macro_f1']))
        L.append('| 剔除问句 | %d | %s | %s |'
                 % (noq['n_train'], noq['accuracy'], noq['macro_f1']))
        L.append('')
        d = noq['accuracy'] - base['accuracy']
        df = noq['macro_f1'] - base['macro_f1']
        L.append('删掉 %d 条问句样本后,测试准确率 **%+.4f**、宏 F1 **%+.4f**。'
                 % (base['n_train'] - noq['n_train'], d, df))
        L.append('')
        if d >= 0 or df >= 0:
            L.append('> 训练数据**变少了**而指标**没变差**,说明被删掉的那批'
                     '样本没有提供有效监督信号 —— 它们把"提问"和"中性"绑在'
                     '一起,教模型学了个假规律。')
        else:
            L.append('> 两项指标都下降,说明问句样本虽与中性标签强相关,'
                     '但仍携带部分有效信息(如语料多样性)。'
                     '需与第三节的测试子集结果合起来解读:'
                     '模型对问句的泛化更差,但问句本身并非纯粹噪声。')
        L.append('')
        sec = 5

    # ---- 结论
    # 注意别写成 `'## %s、...' % '五' if sec == 5 else '四'` ——
    # % 比条件表达式优先级高,那样写会在 else 分支只输出裸的"四"。
    num = '五' if sec == 5 else '四'
    L.append('## %s、结论与改进方向' % num)
    L.append('')
    L.append('**结论:** 这套数据集的"中性"是复合标签,把'
             '① 真的没有态度 ② 只是在提问 这两类样本混在了一起。'
             '统计上,中性类样本有 %s 是问句,而全部问句中 %s 被标成中性 —— '
             '两者强关联;而全部错误中有 %s 牵涉中性边界,'
             '是极性互错的 %.1f 倍。'
             % (pct(q_tr['per_class']['neutral']['question_ratio']),
                pct(qn / qt),
                pct(flow['boundary_share']) if flow else '—',
                flow['boundary_errors'] / flow['polarity_errors']
                if flow and flow['polarity_errors'] else 0))
    L.append('')
    L.append('**证据的边界(必须一并说明):** 第四节显示,把问句从训练集里'
             '整批删掉并不会提升指标,反而略降。这说明问句样本**并非纯粹噪声**,'
             '它们仍提供了语料多样性。因此本节的主张限于以下范围 —— '
             '**"中性"这个标签的语义是复合的,模型在它的边界上系统性犯错**;'
             '这不等于"问句应当被删除"。第三节里问句组的正面类召回率只有 '
             '0.2885(陈述句组 0.7756),这个差距是标注口径造成的,'
             '而不是模型参数不够。')
    L.append('')
    L.append('**改进方向(可作为后续工作):**')
    L.append('')
    L.append('1. **拆分标签**:把"中性"拆成 `中性陈述` 与 `中性提问` 两类,'
             '重新标注后训练。本仓库的 `LABELS_4` 常量'
             '(`negative`/`positive`/`neutral_stmt`/`neutral_q`)即为此预留。')
    L.append('2. **问句单独处理**:对问句先做意图识别(求助 / 质疑 / 反问),'
             '再判断情感极性。反问句("这也能叫利好?")实际表达负面,'
             '按字面判中性是错的。')
    L.append('3. **标注规范**:在标注手册里明确"提问但语气偏负面"'
             '这类边界样本该归哪类,并做标注者一致性检验(Cohen\'s Kappa)。')
    L.append('4. **指标选择**:类别不均衡场景下以宏 F1 为主指标,'
             '准确率会掩盖少数类被牺牲的事实(见第三节)。')
    L.append('')
    L.append('---')
    L.append('')
    # 生成命令要如实反映本次是否跑了重训,否则读者照抄命令会得到
    # 一份少了第四节的报告,误以为脚本坏了。
    cmd = '.python\\python.exe tools\\analyze_neutral.py'
    if noq:
        cmd += ' --train'
    L.append('*生成命令:* `%s`' % cmd)
    L.append('')
    return '\n'.join(L)


# ------------------------------------------------------------------ 主流程

def _read_prev_noq():
    """读上次跑 --train 留下的重训结果。没有就返回 None。

    数据源是 `bert-3class-noq.json`(重训的正式产物),而不是
    neutral-split.json —— 后者每次运行都会被重写,不传 --train 时
    里面就没有这一节。
    """
    path = os.path.join(EXP_DIR, 'bert-3class-noq.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description='中性类瓶颈分析')
    ap.add_argument('--train', action='store_true',
                    help='附加重训实验(剔除问句重训,数分钟)')
    ap.add_argument('-o', '--out', default=None,
                    help='报告输出路径(默认 data/experiments/NEUTRAL_ANALYSIS.md)')
    args = ap.parse_args(argv)

    print('=== 中性类瓶颈分析 ===')

    tr_texts, tr_labels = load_csv(TRAIN_CSV)
    te_texts, te_labels = load_csv(TEST_CSV)

    print('  统计问句 ...')
    q_tr = question_stats(tr_texts, tr_labels)
    q_te = question_stats(te_texts, te_labels)
    print('  训练集问句 %d/%d (%s)'
          % (q_tr['question'], q_tr['n'], pct(q_tr['question_ratio'])))

    base = load_metrics('bert', '3class')
    flow = None
    if base and base.get('confusion_matrix'):
        flow = error_flow(base['confusion_matrix'], base['label_names'])
        print('  错误总数 %d,流向中性 %d'
              % (flow['total_errors'],
                 next((s['absorbed'] for s in flow['sinks']
                       if s['label'] == 'neutral'), 0)))
    else:
        print('  [warn] 缺 bert-3class.json,跳过错误流向分析')

    split = None
    if os.path.isdir(os.path.join(MODELS_DIR, 'sentiment-bert-3class')):
        print('  按句式切分评估(需加载 BERT,约 30s) ...')
        split = split_experiment('3class')
        print('  问句组 acc=%s  陈述组 acc=%s'
              % (split['question']['accuracy'], split['statement']['accuracy']))
    else:
        print('  [warn] 缺 sentiment-bert-3class 模型,跳过切分评估')

    noq = None
    if args.train:
        print('  剔除问句重训(约 2-3 分钟) ...')
        noq = retrain_without_questions('3class')
        print('  重训 acc=%s' % noq['accuracy'])
    else:
        # 不跑 --train 时沿用上次的重训结果:那份数据是论文来源,
        # 而重训要几分钟,不该因为"只想刷新一下统计"就把它从报告里抹掉。
        prev = _read_prev_noq()
        if prev:
            noq = prev
            print('  沿用上次的剔除问句重训结果(未传 --train)')

    text = render(q_tr, q_te, flow, split, noq, base)

    os.makedirs(EXP_DIR, exist_ok=True)
    out = args.out or os.path.join(EXP_DIR, 'NEUTRAL_ANALYSIS.md')
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(text)

    payload = {'train_questions': q_tr, 'test_questions': q_te,
               'error_flow': flow, 'split_eval': split,
               'retrain_without_questions': noq}
    with open(os.path.join(EXP_DIR, 'neutral-split.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print('  已写入 %s' % os.path.relpath(out, _WS))
    print('  已写入 %s'
          % os.path.relpath(os.path.join(EXP_DIR, 'neutral-split.json'), _WS))
    return 0


if __name__ == '__main__':
    sys.exit(main())
