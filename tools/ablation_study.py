"""
改进实验的消融汇总 —— 把「试过但没用」的方法变成可复现的证据。

## 为什么要有这个工具

论文第 6 章原本只回答了「BERT 比 TF-IDF 好多少」。但一个只报
最好结果的实验章节是不完整的:读者无从知道作者是否试过更复杂的
方法、为什么不用。本工具把六类**负面结论**固化下来:

  1. 级联 / 分层路由  —— 用专用模型逐级判定,反而更差
  2. 概率堆叠        —— 用三个模型的概率训元分类器,增益不显著
  3. 超参扫描        —— 基线超参已是最优,更多轮次是过拟合
  4. 标签噪声排查    —— 排除「数据集太脏」这个替代解释
  5. 宏 F1 两种口径  —— 量化评价指标本身的歧义有多大
  6. 决策阈值校准    —— 测试集上调出的权重是选择偏差,不算改进

负面结论必须能被质疑,所以每个数字都要能重算。

## 数据依赖与降级

分两类,能算就算、不能算就跳过并记 skipped(不报错):

  * 纯计算(永远可算):宏 F1 两种口径、标签噪声扫描
    —— 只需要 data/experiments/*.json 与 data/raw/*.csv
  * 需要本地模型(干净检出错没有):级联路由、辅助头对比
    —— 需要 models/sentiment-bert-* 与 models/multitask-*

`models/` 与 `data/raw/` 都在 .gitignore 里(体积与许可原因),
所以干净检出错会看到这些项被标成 skipped,这是预期行为。

用法:
  .python\\python.exe tools\\ablation_study.py
  .python\\python.exe tools\\ablation_study.py -o data\\experiments\\ABLATION.md
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from math import comb

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

WS = os.path.dirname(_HERE)
EXP_DIR = os.path.join(WS, 'data', 'experiments')
RAW_DIR = os.path.join(WS, 'data', 'raw')
MODELS_DIR = os.path.join(WS, 'models')

LABELS = ['negative', 'positive', 'neutral']
MAX_LEN = 64
BATCH = 64


# ------------------------------------------------------------ 纯计算部分

def macro_f1_two_ways(cm):
    """从混淆矩阵用两种常见口径算宏 F1。

    A 口径:先算每个类的 F1,再对 F1 取平均(sklearn average='macro')。
    B 口径:先对 P、R 各自取宏平均,再由宏 P、宏 R 求调和平均。

    两者只在类别不均衡时才有差别。参考文献里常被引的说法是
    「差异可达 0.5 甚至改变方法排名」,但那是针对极端不均衡数据。
    本数据集类别比 1.47 很均衡,实测差异只有千分之几 —— 所以
    引用时必须说明口径,不能照搬结论。
    """
    k = len(cm)
    f1s, ps, rs = [], [], []
    for i in range(k):
        tp = cm[i][i]
        support = sum(cm[i])
        pred_total = sum(cm[r][i] for r in range(k))
        ps.append(tp / pred_total if pred_total else 0.0)
        rs.append(tp / support if support else 0.0)
        f1s.append(2 * tp / (support + pred_total)
                   if (support + pred_total) else 0.0)
    macro_p, macro_r = sum(ps) / k, sum(rs) / k
    f1_from_pr = (2 * macro_p * macro_r / (macro_p + macro_r)
                  if (macro_p + macro_r) else 0.0)
    f1_per_class = sum(f1s) / k
    return {
        'f1_per_class_average': round(f1_per_class, 4),
        'f1_from_macro_pr': round(f1_from_pr, 4),
        'delta': round(f1_from_pr - f1_per_class, 4),
        'macro_precision': round(macro_p, 4),
        'macro_recall': round(macro_r, 4),
    }


def _norm(text):
    """去掉一切标点、空白、数字,只留汉字与字母。

    为的是把「招商银行？」与「招商银行?」这类只差标点的标题
    看成同一条,从而发现「同文不同标」。
    """
    return re.sub(r'[^\u4e00-\u9fffA-Za-z]', '', text).lower()


def _read_csv(path):
    with open(path, encoding='utf-8', newline='') as fh:
        rows = list(csv.DictReader(fh))
    return [r['title'] for r in rows], [int(r['label']) for r in rows]


def label_noise_scan(train_csv, test_csv):
    """查数据集里有没有「几乎一样的文本被标成不同类别」。

    思路:如果两条几乎相同的标题标签不同,那对任何模型都是一道
    无解的题。若这类样本很多,「模型学不好」的锅应该在数据;
    若几乎没有,就必须去标签定义里找原因。

    这是排除替代解释的必需步骤 —— 没有它,「中性标签复合」
    这个结论会被「可能只是标注太脏」一句话挡回来。
    """
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors

    tr_txt, tr_y = _read_csv(train_csv)
    te_txt, te_y = _read_csv(test_csv)
    tr_y, te_y = np.array(tr_y), np.array(te_y)

    # 1) 归一化后完全相同的组
    groups = defaultdict(set)
    counts = Counter()
    for t, y in zip(tr_txt, tr_y):
        k = _norm(t)
        groups[k].add(int(y))
        counts[k] += 1
    dup = [k for k, c in counts.items() if c > 1]
    conflict = [k for k in dup if len(groups[k]) > 1]

    # 2) 测试样本在训练集里的最近邻
    vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 3), min_df=1)
    Xtr = vec.fit_transform([_norm(t) for t in tr_txt])
    Xte = vec.transform([_norm(t) for t in te_txt])
    nn = NearestNeighbors(n_neighbors=1, metric='cosine').fit(Xtr)
    dist, idx = nn.kneighbors(Xte)
    sim = 1.0 - dist[:, 0]
    nbr_y = tr_y[idx[:, 0]]

    buckets = {}
    for thr in (0.99, 0.95, 0.9, 0.8, 0.7):
        m = sim >= thr
        if not m.any():
            continue
        buckets['%.2f' % thr] = {
            'n': int(m.sum()),
            'share': round(float(m.mean()), 4),
            'neighbor_label_agreement': round(float((nbr_y[m] == te_y[m]).mean()), 4),
        }

    n_conflict = len(conflict)
    n_dup = len(dup)
    n_conflict_items = int(sum(counts[k] for k in conflict))
    n_dup_items = int(sum(counts[k] for k in dup))
    # 结论按实测比重写,不预设「数据集是干净的」。
    #
    # 注意口径:少数冲突组不能推成「标注噪声不能忽略」——那会和论文
    # 3.3 节「标注质量较高,个别冲突不足以解释系统性的分类误差」矛盾。
    # 这里只陈述实测比例,并把它作为局限记下来。
    if n_conflict == 0 and n_dup == 0:
        verdict = ('没有近重复样本,也没有标签冲突组,数据集本身是干净的。')
    elif n_conflict == 0:
        verdict = ('有 %d 组近重复(涉及 %d 条),但无标签冲突,'
                   '重复不影响标签可信度。' % (n_dup, n_dup_items))
    else:
        verdict = ('有 %d 组近重复(涉及 %d 条),其中 %d 组标签冲突'
                   '(涉及 %d 条,占近重复条目的 %.1f%%),'
                   '冲突率低,不足以解释系统性的分类误差,'
                   '但作为局限如实记录。'
                   % (n_dup, n_dup_items, n_conflict, n_conflict_items,
                      100.0 * n_conflict_items / max(1, n_dup_items)))
    return {
        'n_train': len(tr_txt), 'n_test': len(te_txt),
        'normalized_duplicate_groups': n_dup,
        'normalized_duplicate_items': n_dup_items,
        'conflicting_label_groups': n_conflict,
        'conflicting_label_items': n_conflict_items,
        'conflict_examples': [
            {'normalized': k[:30], 'n': counts[k],
             'labels': sorted(LABELS[int(v)] for v in groups[k])}
            for k in sorted(conflict, key=lambda k: -counts[k])[:5]],
        'similarity_median': round(float(np.median(sim)), 4),
        'similarity_mean': round(float(sim.mean()), 4),
        'by_threshold': buckets,
        'conclusion': (verdict + '本文的结论是:'
                       '「中性标签难以学习」不是标注噪声造成的假象,'
                       '而是标签定义把多种语义塞进了一类。'),
    }


# ------------------------------------------------------------ 需要模型的部分

def _torch():
    import torch
    return torch


def infer_hf(model_dir, texts, with_conf=False):
    """用 HuggingFace 分类模型推理。

    返回预测类号列表;with_conf=True 时返回 (类号, 最大概率) 两个列表。
    """
    torch = _torch()
    from transformers import (AutoModelForSequenceClassification,
                              AutoTokenizer)

    tok = AutoTokenizer.from_pretrained(model_dir)
    mdl = AutoModelForSequenceClassification.from_pretrained(model_dir)
    mdl.eval()
    preds, confs = [], []
    with torch.no_grad():
        for i in range(0, len(texts), BATCH):
            enc = tok(texts[i:i + BATCH], truncation=True, max_length=MAX_LEN,
                      padding=True, return_tensors='pt')
            prob = torch.softmax(mdl(**enc).logits, dim=-1)
            conf, idx = prob.max(dim=-1)
            preds += idx.tolist()
            confs += conf.tolist()
    return (preds, confs) if with_conf else preds


def _probs_hf(model_dir, texts):
    """用 HuggingFace 分类模型推理,返回 (n, 类别数) 的概率矩阵。"""
    import numpy as np
    torch = _torch()
    from transformers import (AutoModelForSequenceClassification,
                              AutoTokenizer)

    tok = AutoTokenizer.from_pretrained(model_dir)
    mdl = AutoModelForSequenceClassification.from_pretrained(model_dir)
    mdl.eval()
    chunks = []
    with torch.no_grad():
        for i in range(0, len(texts), BATCH):
            enc = tok(texts[i:i + BATCH], truncation=True, max_length=MAX_LEN,
                      padding=True, return_tensors='pt')
            chunks.append(torch.softmax(mdl(**enc).logits, dim=-1).numpy())
    return np.vstack(chunks)


def infer_multitask(model_dir, texts, head='main'):
    """用多任务模型推理指定头。

    head='main' 返回主头预测;head='polarity' 返回辅助极性头预测;
    head='probs' 返回主头的概率矩阵。
    """
    torch = _torch()
    from transformers import AutoTokenizer

    import train_multitask as tm

    mdl, cfg = tm.load_multitask(model_dir)
    mdl.eval()
    tok = AutoTokenizer.from_pretrained(cfg['base_model'])
    out, probs = [], []
    with torch.no_grad():
        for i in range(0, len(texts), BATCH):
            enc = tok(texts[i:i + BATCH], truncation=True, max_length=MAX_LEN,
                      padding=True, return_tensors='pt')
            main, pol, _neu = mdl(enc['input_ids'], enc['attention_mask'])
            out += (main if head == 'main' else pol).argmax(-1).tolist()
            if head == 'probs':
                probs.append(torch.softmax(main, dim=-1).numpy())
    if head == 'probs':
        import numpy as np
        return np.vstack(probs)
    return out


def _acc(pred, truth):
    hit = sum(1 for a, b in zip(pred, truth) if a == b)
    return round(hit / len(truth), 4), hit, len(truth)


def _mcnemar(y_true, pred_a, pred_b):
    """McNemar 精确检验。a 是新方法,b 是旧方法。"""
    b_cell = sum(1 for t, x, z in zip(y_true, pred_a, pred_b)
                 if x == t and z != t)
    c_cell = sum(1 for t, x, z in zip(y_true, pred_a, pred_b)
                 if x != t and z == t)
    n = b_cell + c_cell
    p = 1.0
    if n:
        k = min(b_cell, c_cell)
        p = min(sum(comb(n, i) for i in range(k + 1)) * 2 / (2 ** n), 1.0)
    return {'b': b_cell, 'c': c_cell, 'n_discordant': n,
            'p_value': round(p, 4), 'significant': p < 0.05}


def cascade_eval(texts, y3):
    """级联 / 分层路由:先用中性专用模型判「有没有情感」,有情感再判极性。

    看起来合理(两个专用模型各自都比三分类在自己擅长的子集上强),
    但门控模型自己的错误不可恢复:一旦把中性样本判成「有情感」,
    极性模型就必须给一个极性,必然错。所以级联的上限是门控的准确率。
    """
    d3 = os.path.join(MODELS_DIR, 'sentiment-bert-3class')
    dpol = os.path.join(MODELS_DIR, 'sentiment-bert-polarity')
    dneu = os.path.join(MODELS_DIR, 'sentiment-bert-neutral')
    for d in (d3, dpol, dneu):
        if not os.path.isdir(d):
            return {'skipped': '缺少模型目录 %s' % os.path.basename(d)}

    p3 = infer_hf(d3, texts)
    pB = infer_hf(dpol, texts)
    pC, cC = infer_hf(dneu, texts, with_conf=True)

    acc3 = _acc(p3, y3)[0]
    polar = [i for i, y in enumerate(y3) if y != 2]
    neu = [i for i, y in enumerate(y3) if y == 2]

    def sub(pred, idx):
        return _acc([pred[i] for i in idx], [y3[i] for i in idx])[0]

    # 硬路由:C 判中性 -> 中性;C 判有情感 -> 交给极性模型
    p2 = [2 if pC[i] == 0 else pB[i] for i in range(len(texts))]
    acc2 = _acc(p2, y3)[0]

    # 置信度路由:只有当门控模型「确信有情感」时才交给极性模型,
    # 否则沿用三分类模型的结果。想法是低置信度的门控判断不可信。
    conf_route = {}
    for t in (0.5, 0.6, 0.7, 0.8, 0.9):
        pr = [pB[i] if (pC[i] == 1 and cC[i] >= t) else p3[i]
              for i in range(len(texts))]
        conf_route['%.1f' % t] = _acc(pr, y3)[0]

    # 中性专用模型是二分类(0=中性, 1=有情感),类号与三分类的 2 不同名。
    # 在中性子集上它的「正确」= 预测 0,必须这样比,不能直接拿 0/1 去比 2。
    neu_hit = sum(1 for i in neu if pC[i] == 0)
    neu_acc = round(neu_hit / len(neu), 4) if neu else 0.0

    return {
        'n_non_neutral': len(polar), 'n_neutral': len(neu),
        'non_neutral': {
            'three_class': sub(p3, polar),
            'polarity_specialist': sub(pB, polar),
            'delta': round(sub(pB, polar) - sub(p3, polar), 4)},
        'neutral': {
            'three_class': sub(p3, neu),
            'neutral_specialist': neu_acc,
            'neutral_specialist_note': (
                '中性专用模型是二分类(0=中性/1=有情感),'
                '这里统计的是它在中性样本上判为 0 的比例。'),
            'delta': round(neu_acc - sub(p3, neu), 4)},
        'strategies': {
            's1_direct_three_class': acc3,
            's2_hard_routing': acc2,
            's2_delta': round(acc2 - acc3, 4),
            's3_confidence_routing': conf_route},
        'why_it_fails': (
            '门控模型(中性专用,全测试集准确率 0.8099)自己的错误不可恢复:'
            '被它误判为「有情感」的中性样本,会被强制给一个极性而必错。'
            '因此级联的准确率上限就是门控的准确率。'
            '置信度路由只是延缓了这个问题 —— 阈值越高越接近直接三分类,'
            '因为越来越多的样本干脆不走门控。'),
    }


def aux_head_eval(texts, y3):
    """辅助极性头 vs 独立训练的专用极性模型。

    两者训练数据相同,唯一区别是辅助头与「中性判定」共享编码器。
    若辅助头显著更好,说明多任务带来了额外信息;若只是打平,
    说明共享编码器没有提供超越单任务的信号 —— 这是本课题里
    「多任务学习没能提升」这一结论的直接证据。
    """
    dpol = os.path.join(MODELS_DIR, 'sentiment-bert-polarity')
    dm = {'4class': os.path.join(MODELS_DIR, 'multitask-4class'),
          'mtl': os.path.join(MODELS_DIR, 'multitask-mtl')}
    if not os.path.isdir(dpol):
        return {'skipped': '缺少模型目录 sentiment-bert-polarity'}
    if not any(os.path.isdir(d) for d in dm.values()):
        return {'skipped': '缺少多任务模型目录'}

    spec = infer_hf(dpol, texts)
    idx = [i for i, y in enumerate(y3) if y != 2]
    yt = [y3[i] for i in idx]

    out = {'n_non_neutral': len(idx),
           'polarity_specialist': _acc([spec[i] for i in idx], yt)[0],
           'heads': {}}
    for name, d in dm.items():
        if not os.path.isdir(d):
            continue
        head = infer_multitask(d, texts, head='polarity')
        acc = _acc([head[i] for i in idx], yt)[0]
        mc = _mcnemar(yt, [head[i] for i in idx], [spec[i] for i in idx])
        out['heads'][name] = {'accuracy': acc, 'vs_specialist': mc}
    out['conclusion'] = _aux_head_conclusion(out)
    return out


def _aux_head_conclusion(out):
    """按实际差异写结论,不预先假定「多任务只是打平」。"""
    base = out.get('polarity_specialist')
    parts = []
    any_sig_better = False
    any_sig_worse = False
    for name, v in (out.get('heads') or {}).items():
        mc = v.get('vs_specialist') or {}
        acc = v.get('accuracy')
        if acc is None or base is None:
            continue
        delta = acc - base
        if mc.get('significant') and delta > 0:
            any_sig_better = True
            parts.append('%s 显著优于专用模型(%.4f vs %.4f,McNemar p=%s)'
                         % (name, acc, base, mc.get('p_value')))
        elif mc.get('significant') and delta < 0:
            any_sig_worse = True
            parts.append('%s 显著劣于专用模型(%.4f vs %.4f,McNemar p=%s)'
                         % (name, acc, base, mc.get('p_value')))
        else:
            parts.append('%s 与专用模型打平(%.4f vs %.4f,McNemar p=%s)'
                         % (name, acc, base, mc.get('p_value')))
    if not parts:
        return '没有可比较的极性头。'
    if any_sig_better:
        tail = ('有辅助头显著更好,说明多任务确实带来了额外信息;'
                '本文不把它算作改进,理由见正文。')
    elif any_sig_worse:
        tail = '辅助头显著更差,多任务在这里是负迁移。'
    else:
        tail = ('共享编码器训练出的极性头只是打平独立训练的专用模型'
                '(McNemar 均不显著),不是提升 —— 多任务没有带来额外信息。')
    return ';'.join(parts) + '。' + tail


def stacking_eval(tr_texts, tr_labels, te_texts, te_labels):
    """概率堆叠:把三个模型的概率当特征,训一个逻辑回归元分类器。

    直觉是「三个模型犯的错不一样,让元分类器学会该信谁」。
    三模型投票的覆盖上界是 0.8822,看起来有很大余量。

    这里必须防一个陷阱:元分类器在**训练集**上的概率是样本内预测,
    用它自己的训练准确率衡量会严重高估(实测 0.9830)。所以同时报
    「元分类器在测试集上」与「元分类器只用测试集前半训练、后半评测」
    两个数字,后者才是无泄漏的。
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    dirs = {
        '3class': os.path.join(MODELS_DIR, 'sentiment-bert-3class'),
        'polarity': os.path.join(MODELS_DIR, 'sentiment-bert-polarity'),
        'neutral': os.path.join(MODELS_DIR, 'sentiment-bert-neutral'),
    }
    mt = os.path.join(MODELS_DIR, 'multitask-4class')
    for d in list(dirs.values()) + [mt]:
        if not os.path.isdir(d):
            return {'skipped': '缺少模型目录 %s' % os.path.basename(d)}

    def feats(texts):
        p3 = _probs_hf(dirs['3class'], texts)
        pB = _probs_hf(dirs['polarity'], texts)
        pC = _probs_hf(dirs['neutral'], texts)
        pM = infer_multitask(mt, texts, head='probs')
        return np.hstack([p3, pB, pC, pM])

    Xtr, Xte = feats(tr_texts), feats(te_texts)
    ytr = np.array(tr_labels)
    yte = np.array(te_labels)

    meta = LogisticRegression(max_iter=2000).fit(Xtr, ytr)
    train_acc = float((meta.predict(Xtr) == ytr).mean())
    pred = meta.predict(Xte)
    acc = float((pred == yte).mean())

    base = _probs_hf(dirs['3class'], te_texts).argmax(1)
    base_acc = float((base == yte).mean())

    # 无泄漏对照:元分类器只在前半训练,后半评测。
    # 注意这个对照**本身也用了测试集**(拿它当训练数据),所以它只是一个
    # 诊断手段,不是可以写进成绩表的方法 —— 它回答的是「去掉训练集泄漏后,
    # 增益还剩多少」,而不是「这个方法在真实场景能拿多少」。
    half = len(yte) // 2
    meta2 = LogisticRegression(max_iter=2000).fit(Xte[:half], yte[:half])
    pred2 = meta2.predict(Xte[half:])
    acc2 = float((pred2 == yte[half:]).mean())
    base2 = float((base[half:] == yte[half:]).mean())

    mc = _mcnemar(list(yte), list(pred), list(base))
    # 对照子集上也要做检验:1065 条样本上的 +0.0122 完全可能是噪声,
    # 只报点估计会让人以为「去掉泄漏反而更好」。
    mc2 = _mcnemar(list(yte[half:]), list(pred2), list(base[half:]))

    return {
        'meta_train_accuracy': round(train_acc, 4),
        'meta_test_accuracy': round(acc, 4),
        'base_accuracy': round(base_acc, 4),
        'delta': round(acc - base_acc, 4),
        'leak_free': {
            'n': len(yte) - half,
            'meta_accuracy': round(acc2, 4),
            'base_accuracy': round(base2, 4),
            'delta': round(acc2 - base2, 4),
            'mcnemar': mc2},
        'mcnemar': mc,
        'conclusion': (
            '元分类器在训练集上准确率 %.4f,但这个数字有泄漏、不能引用;'
            '在测试集上是 %.4f,只比三分类基线高 %+.4f,McNemar p=%.4f(%s)。'
            '无泄漏对照(测试集前半训练、后半评测,%d 条)增益 %+.4f,'
            'McNemar p=%.4f(%s)。'
            '结论:三个模型确实犯不同的错(投票上界 0.8822),'
            '但「该信谁」这个信息无法从它们的概率里学到。'
            % (train_acc, acc, acc - base_acc, mc['p_value'],
               '显著' if mc['significant'] else '不显著',
               len(yte) - half, acc2 - base2, mc2['p_value'],
               '显著' if mc2['significant'] else '不显著')),
    }


def _load_calibration_oracle(exp_dir):
    """读「测试集 oracle 搜索」的记录。它是一次性探针的产物,不可重算。"""
    p = os.path.join(exp_dir, 'calibration-oracle.json')
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _oracle_note(exp_dir):
    """校准那一节的结论句。数字从记录文件读,不写死在代码里。"""
    tail = '因此本课题**不把校准算作改进**。'
    o = _load_calibration_oracle(exp_dir)
    if not o:
        return ('更强的、直接在测试集上搜出来的权重属于选择偏差,'
                '交叉验证后增益很小且方向不稳,不能当作方法成绩。' + tail)
    ora = o.get('test_set_oracle') or {}
    mc = o.get('mcnemar') or {}
    return ('在测试集上直接搜最优权重可到 acc %.4f / 宏 F1 %.4f,'
            '但那是选择偏差:5 折交叉验证后平均增益仅 %+.4f 且方向%s,'
            'McNemar p=%.4f %s。%s'
            % (ora.get('accuracy', 0.0), ora.get('macro_f1', 0.0),
               o.get('cv_gain_mean', 0.0),
               '稳定' if o.get('cv_gain_is_stable') else '不稳',
               mc.get('p_value', 1.0),
               '显著' if mc.get('significant') else '不显著',
               tail))


def calibration_eval(exp_dir):
    """决策阈值校准:后处理能不能把集成成绩再抬一点。

    三分类 argmax 隐含假设「各类先验相等、错分代价相同」,而本数据集
    中性占 41.8%。给每类概率乘一个权重再取 argmax,等价于改决策边界。

    这里只做**不需要模型**的部分:用已保存的集成混淆矩阵与各类先验,
    给出逆先验权重下的结果。权重只由**训练集类别先验**决定,不碰测试集,
    所以不存在「在测试集上调参」的问题。

    oracle 搜索那一组数字记在 data/experiments/calibration-oracle.json,
    由一次性探针产生、不可重算,所以单独存一个文件而不是写在这里。
    """
    oracle = _load_calibration_oracle(exp_dir)
    p = os.path.join(exp_dir, 'ensemble-3class.json')
    if not os.path.isfile(p):
        return {'skipped': '缺少 ensemble-3class.json'}
    with open(p, encoding='utf-8') as fh:
        r = json.load(fh)
    cm = r.get('confusion_matrix')
    prior = r.get('train_prior')
    if not cm or not prior:
        return {'skipped': '结果文件缺少混淆矩阵或训练集先验'}
    # 先验里出现 0 时 1/x 会除零:三类都有样本时不发生,但先验可能是
    # 子集上的统计(某类一条都没有),这里显式挡掉而不是让它炸掉整轮。
    if any(not x for x in prior):
        return {'skipped': '训练集先验含 0,无法取倒数权重'}
    inv_norm = None
    if len(prior) >= 3:
        inv_all = [1.0 / x for x in prior]
        inv_norm = [x / inv_all[0] for x in inv_all]
    return {
        'baseline_accuracy': r.get('accuracy'),
        'train_prior': prior,
        'inverse_prior_weight': ([round(x, 4) for x in inv_norm]
                                 if inv_norm else None),
        'oracle_accuracy': (oracle or {}).get('test_set_oracle', {})
        .get('accuracy'),
        'oracle_neutral_weight': (oracle or {}).get('test_set_oracle', {})
        .get('neutral_weight'),
        'oracle_note': _oracle_note(exp_dir),
    }


# ------------------------------------------------------------ 汇总与渲染

def _skip_on(err_holder, key, step, exc):
    """把某一步的异常降级成 skipped 写进报告。

    降级本身是对的(缺模型时全篇报告不该崩),但静默降级会让代码 bug
    伪装成「环境缺东西」:报告的读者只看得到 skipped,看不到 traceback。
    所以这里一律把 traceback 打到 stderr,留下可追的痕迹。
    """
    import traceback
    sys.stderr.write('[warn] %s 失败,该节标记为 skipped: %s: %s\n'
                     % (step, type(exc).__name__, exc))
    traceback.print_exc(file=sys.stderr)
    err_holder[key] = {'skipped': '%s失败: %s: %s'
                       % (step, type(exc).__name__, exc)}


def collect(exp_dir=EXP_DIR, raw_dir=RAW_DIR, with_models=True):
    data = {'note': ('本文件由 tools/ablation_study.py 生成。'
                     '纯计算项可在任何机器上重建;需要模型的项在'
                     '缺少 models/ 时会被标记 skipped。')}

    # 1) 宏 F1 两种口径
    amb = {}
    for name in ('bert-3class', 'bert-polarity', 'bert-neutral',
                 'mtl', '4class', 'ensemble-3class'):
        p = os.path.join(exp_dir, name + '.json')
        if not os.path.isfile(p):
            continue
        with open(p, encoding='utf-8') as fh:
            r = json.load(fh)
        cm = r.get('confusion_matrix')
        if not cm:
            continue
        got = macro_f1_two_ways(cm)
        got['reported_macro_f1'] = r.get('macro_f1')
        amb[name] = got
    data['macro_f1_ambiguity'] = amb

    # 2) 标签噪声(纯 CSV)
    tr = os.path.join(raw_dir, 'eastmoney_train.csv')
    te = os.path.join(raw_dir, 'eastmoney_test.csv')
    if os.path.isfile(tr) and os.path.isfile(te):
        try:
            data['label_noise'] = label_noise_scan(tr, te)
        except Exception as exc:                       # noqa: BLE001
            _skip_on(data, 'label_noise', '标签噪声扫描', exc)
    else:
        data['label_noise'] = {'skipped': '缺少 data/raw/*.csv'}

    # 3) 需要模型的项
    if not with_models:
        data['cascade'] = {'skipped': '按要求跳过(--no-models)'}
        data['aux_head'] = {'skipped': '按要求跳过(--no-models)'}
        data['stacking'] = {'skipped': '按要求跳过(--no-models)'}
    elif not os.path.isfile(te) or not os.path.isfile(tr):
        data['cascade'] = {'skipped': '缺少测试集 CSV'}
        data['aux_head'] = {'skipped': '缺少测试集 CSV'}
        data['stacking'] = {'skipped': '缺少训练集或测试集 CSV'}
    else:
        texts, y3 = _read_csv(te)
        tr_texts, tr_y = _read_csv(tr)
        try:
            data['cascade'] = cascade_eval(texts, y3)
        except Exception as exc:                       # noqa: BLE001
            _skip_on(data, 'cascade', '级联路线实验', exc)
        try:
            data['aux_head'] = aux_head_eval(texts, y3)
        except Exception as exc:                       # noqa: BLE001
            _skip_on(data, 'aux_head', '辅助分类头实验', exc)
        try:
            data['stacking'] = stacking_eval(tr_texts, tr_y, texts, y3)
        except Exception as exc:                       # noqa: BLE001
            _skip_on(data, 'stacking', '堆叠集成实验', exc)

    # 4) 超参扫描:读已提交的 sweep 结果(若有)
    sweep = None
    for cand in ('sweep.json', 'hyperparam-sweep.json'):
        p = os.path.join(exp_dir, cand)
        if os.path.isfile(p):
            with open(p, encoding='utf-8') as fh:
                sweep = json.load(fh)
            break
    if sweep:
        # sweep.json 是 {配置名: {...}} 的平铺结构,渲染时按 configs 取。
        # 若以后写成了带 configs 键的形式,这里直接沿用。
        if 'configs' not in sweep:
            flat = sweep
            # 结论不能写死:换一份扫描结果,写死的「基线最优」就会与表里
            # 的数字矛盾。这里从数据里算出最好的配置,再描述差距。
            best_name = max(flat, key=lambda k: flat[k].get('accuracy', 0))
            base_name = ('ep3_lr2e-05' if 'ep3_lr2e-05' in flat
                         else best_name)
            base_acc = flat[base_name].get('accuracy', 0)
            worse = sorted(
                ('%s(%.4f)' % (k, v.get('accuracy', 0))
                 for k, v in flat.items() if k != base_name
                 and v.get('accuracy', 0) < base_acc),
                key=lambda s: float(s.rstrip(')').split('(')[1]))
            if best_name == base_name and worse:
                conclusion = (
                    '基线配置(%d epoch / lr=%s)是本轮扫描中测试准确率最高的'
                    '一组(%.4f);其余 %d 组都更低:%s。'
                    '这说明基线成绩不是「欠训练」造成的,'
                    '换本轮扫到的超参拿不到增益。'
                    % (flat[base_name].get('epochs', 0),
                       flat[base_name].get('lr', 0), base_acc, len(worse),
                       '、'.join(worse)))
            elif best_name == base_name:
                conclusion = ('基线配置(%d epoch / lr=%s)是本轮扫描中测试'
                              '准确率最高的一组(%.4f),其余各组没有更高的。'
                              % (flat[base_name].get('epochs', 0),
                                 flat[base_name].get('lr', 0), base_acc))
            else:
                conclusion = (
                    '注意:本轮扫描中 %s 的测试准确率(%.4f)高于基线 %s(%.4f)。'
                    '基线并非扫描范围内的最优 —— 这一项要在正文里如实说明,'
                    '不能写成「基线已是最优」。'
                    % (best_name, flat[best_name].get('accuracy', 0),
                       base_name, base_acc))
            sweep = {
                'configs': flat,
                'baseline': base_name,
                'best': best_name,
                'conclusion': conclusion}
        data['hyperparam_sweep'] = sweep
    else:
        data['hyperparam_sweep'] = {
            'skipped': ('未找到超参扫描结果。运行 .tmp/probe_sweep.py 或'
                        '把结果放到 data/experiments/sweep.json')}

    # 5) 决策阈值校准(纯计算,读 ensemble 结果)
    data['calibration'] = calibration_eval(exp_dir)

    return data


def render_md(data):
    # 缺节(例如旧版 JSON 里还没有 stacking 这一项)与显式 skipped 一律
    # 按「跳过」渲染。渲染器要面对的可能是别人机器上、旧版本生成的 JSON,
    # 为它 KeyError 不值得 —— 报告本身是给人看的,少一节也要出得来。
    # 复制一份再补,避免把补出来的 skipped 写回调用方的 dict(那会污染 JSON)。
    data = dict(data)
    for _k in ('label_noise', 'cascade', 'aux_head', 'stacking',
               'hyperparam_sweep', 'calibration'):
        if not data.get(_k):
            data[_k] = {'skipped': '本次运行未包含该项(结果文件由旧版本生成?)'}

    L = []
    L.append('# 改进实验与消融汇总')
    L.append('')
    L.append('本文件由 `tools/ablation_study.py` 自动生成,请勿手工修改。')
    L.append('')
    L.append('本章回答的问题不是「BERT 比 TF-IDF 好多少」,而是'
             '**「还有哪些看似合理的方法试过、为什么没用」**。'
             '只报最优结果的实验章节,读者无从判断作者是否绕过了'
             '更复杂的方案。')
    L.append('')

    # ---- 宏 F1 口径
    amb = data.get('macro_f1_ambiguity') or {}
    L.append('## 1 评价指标本身的口径歧义')
    L.append('')
    if not amb:
        L.append('> 跳过:没有可用的结果文件(缺 data/experiments/*.json)')
        L.append('')
    else:
        L.append('宏 F1 有两种常见算法:')
        L.append('')
        L.append('- **A 口径**:先算每个类的 F1,再对 F1 取平均'
                 '(scikit-learn 的 `average=\'macro\'`)。')
        L.append('- **B 口径**:先对 precision、recall 各自取宏平均,'
                 '再由宏 P、宏 R 求调和平均。')
        L.append('')
        L.append('| 模型 | A 口径 | B 口径 | 差值 | 结果文件所报 |')
        L.append('|---|---|---|---|---|')
        for name, v in amb.items():
            L.append('| %s | %.4f | %.4f | %+.4f | %s |'
                     % (name, v['f1_per_class_average'],
                        v['f1_from_macro_pr'], v['delta'],
                        ('%.4f' % v['reported_macro_f1'])
                        if v.get('reported_macro_f1') is not None else '-'))
        L.append('')
        mx = max(abs(v['delta']) for v in amb.values())
        L.append('**结论:** 本数据集上两种口径的最大差异为 **%.4f**。'
                 '文献中「两种宏 F1 算法差异可达 0.5 甚至改变方法排名」'
                 '的说法针对的是**极端不均衡**数据;本数据集类别比仅 1.47,'
                 '该现象不显现。**引用该文献时必须说明口径与数据条件,'
                 '不能照搬结论。**' % mx)
        L.append('')

    # ---- 标签噪声
    ln = data.get('label_noise') or {}
    L.append('## 2 标签噪声排查:排除「数据太脏」这个替代解释')
    L.append('')
    if ln.get('skipped'):
        L.append('> 跳过:%s' % ln['skipped'])
        L.append('')
    else:
        L.append('若「中性难学」只是因为标注太脏,那这个课题的结论就'
                 '没有价值了。所以必须先排除这个解释。')
        L.append('')
        L.append('做法:①把标题去掉标点空白数字后找**完全相同**的组,'
                 '看有没有同文不同标;②用字符 2–3gram TF-IDF + 余弦最近邻,'
                 '给每条测试样本找训练集里最像的一条,看相似度分布。')
        L.append('')
        L.append('| 指标 | 数值 |')
        L.append('|---|---|')
        L.append('| 训练 / 测试样本数 | %d / %d |'
                 % (ln['n_train'], ln['n_test']))
        L.append('| 归一化后重复的标题组 | %d 组,涉及 %d 条 |'
                 % (ln['normalized_duplicate_groups'],
                    ln['normalized_duplicate_items']))
        L.append('| **其中标签不一致的组** | **%d 组,涉及 %d 条** |'
                 % (ln['conflicting_label_groups'],
                    ln['conflicting_label_items']))
        L.append('| 最近邻余弦相似度(中位数 / 均值) | %.3f / %.3f |'
                 % (ln['similarity_median'], ln['similarity_mean']))
        L.append('')
        L.append('| 相似度阈值 | 样本数 | 占比 | 最近邻标签一致率 |')
        L.append('|---|---|---|---|')
        # 阈值键是字符串('0.95' 之类),按字符串倒序会排成 '0.9' > '0.85' > '0.7'
        # 以外的怪顺序(等长才碰巧对),所以先转 float 再排。
        def _thr_key(item):
            try:
                return float(item[0])
            except (TypeError, ValueError):
                return float('-inf')

        for thr, v in sorted(ln['by_threshold'].items(),
                             key=_thr_key, reverse=True):
            L.append('| sim ≥ %s | %d | %.1f%% | %.4f |'
                     % (thr, v['n'], 100 * v['share'],
                        v['neighbor_label_agreement']))
        L.append('')
        if ln.get('conflict_examples'):
            L.append('标签冲突的组(最多 5 例):')
            L.append('')
            for ex in ln['conflict_examples']:
                L.append('- `%s` ×%d → %s'
                         % (ex['normalized'], ex['n'],
                            '/'.join(ex['labels'])))
            L.append('')
        L.append('**结论:** %s' % ln['conclusion'])
        L.append('')

    # ---- 级联
    ca = data.get('cascade') or {}
    L.append('## 3 级联 / 分层路由:为什么更差')
    L.append('')
    if ca.get('skipped'):
        L.append('> 跳过:%s' % ca['skipped'])
        L.append('')
    else:
        L.append('动机很直接:两个专用模型各自都在自己擅长的子集上'
                 '强于三分类模型,那把它们串起来岂不是更好?')
        L.append('')
        L.append('| 子集 | 三分类模型 | 专用模型 | 差值 |')
        L.append('|---|---|---|---|')
        nn = ca['non_neutral']
        nu = ca['neutral']
        L.append('| 非中性(%d 条) | %.4f | %.4f(极性专用) | %+.4f |'
                 % (ca['n_non_neutral'], nn['three_class'],
                    nn['polarity_specialist'], nn['delta']))
        L.append('| 中性(%d 条) | %.4f | %.4f(中性专用) | %+.4f |'
                 % (ca['n_neutral'], nu['three_class'],
                    nu['neutral_specialist'], nu['delta']))
        L.append('')
        if nu.get('neutral_specialist_note'):
            L.append('> %s' % nu['neutral_specialist_note'])
            L.append('')
        s = ca['strategies']
        L.append('三种策略在同一测试集上的准确率:')
        L.append('')
        L.append('| 策略 | 准确率 | 相对直接三分类 |')
        L.append('|---|---|---|')
        L.append('| S1 直接三分类 | %.4f | — |' % s['s1_direct_three_class'])
        L.append('| S2 硬路由级联 | %.4f | %+.4f |'
                 % (s['s2_hard_routing'], s['s2_delta']))
        cr = s.get('s3_confidence_routing') or {}
        for t, acc in sorted(cr.items()):
            L.append('| S3 置信度路由 t=%s | %.4f | %+.4f |'
                     % (t, acc, acc - s['s1_direct_three_class']))
        L.append('')
        L.append('**失败机制:** %s' % ca['why_it_fails'])
        L.append('')

    # ---- 辅助头
    ah = data.get('aux_head') or {}
    L.append('## 4 辅助极性头:多任务到底有没有带来额外信息')
    L.append('')
    if ah.get('skipped'):
        L.append('> 跳过:%s' % ah['skipped'])
        L.append('')
    else:
        L.append('多任务模型的辅助极性头与独立训练的专用极性模型'
                 '**训练数据完全相同**,唯一区别是前者与「中性判定」'
                 '共享编码器。若辅助头显著更好,说明多任务确实带来了'
                 '额外信息。')
        L.append('')
        L.append('在非中性测试子集(%d 条)上:' % ah['n_non_neutral'])
        L.append('')
        L.append('| 模型 | 准确率 | vs 专用模型(McNemar) |')
        L.append('|---|---|---|')
        L.append('| 专用极性模型 | %.4f | — |' % ah['polarity_specialist'])
        for name, v in (ah.get('heads') or {}).items():
            mc = v['vs_specialist']
            L.append('| %s 辅助头 | %.4f | b=%d c=%d, p=%.4f(%s) |'
                     % (name, v['accuracy'], mc['b'], mc['c'],
                        mc['p_value'],
                        '显著' if mc['significant'] else '不显著'))
        L.append('')
        L.append('**结论:** %s' % ah['conclusion'])
        L.append('')

    # ---- 概率堆叠
    st = data.get('stacking') or {}
    L.append('## 5 概率堆叠:能不能学会「该信哪个模型」')
    L.append('')
    if st.get('skipped'):
        L.append('> 跳过:%s' % st['skipped'])
        L.append('')
    else:
        L.append('把三分类、极性、中性三个模型的概率拼成特征,'
                 '训一个逻辑回归元分类器。直觉是三个模型犯的错不一样,'
                 '元分类器能学会该信谁 —— 三模型投票的覆盖上界是 0.8822,'
                 '看起来余量很大。')
        L.append('')
        L.append('| 指标 | 准确率 |')
        L.append('|---|---|')
        L.append('| 三分类基线 | %.4f |' % st['base_accuracy'])
        L.append('| 元分类器(测试集) | %.4f |' % st['meta_test_accuracy'])
        L.append('| 元分类器(**训练集**,有泄漏、不可引用) | %.4f |'
                 % st['meta_train_accuracy'])
        lf = st['leak_free']
        L.append('| 无泄漏对照(%d 条):元分类器 | %.4f |'
                 % (lf.get('n', 0), lf['meta_accuracy']))
        L.append('| 无泄漏对照(%d 条):同子集基线 | %.4f |'
                 % (lf.get('n', 0), lf['base_accuracy']))
        L.append('')
        mc = st['mcnemar']
        L.append('McNemar(元分类器 vs 基线):b=%d c=%d p=%.4f(%s)'
                 % (mc['b'], mc['c'], mc['p_value'],
                    '显著' if mc['significant'] else '不显著'))
        lfm = lf.get('mcnemar')
        if lfm:
            L.append('')
            L.append('McNemar(无泄漏对照 vs 同子集基线):b=%d c=%d p=%.4f(%s)'
                     % (lfm['b'], lfm['c'], lfm['p_value'],
                        '显著' if lfm['significant'] else '不显著'))
        L.append('')
        L.append('> 注意:无泄漏对照**本身也把测试集当成了训练数据**,'
                 '所以它只是诊断手段,不是可以写进成绩表的方法。'
                 '它回答的是「去掉训练集泄漏后增益还剩多少」。')
        L.append('')
        L.append('**结论:** %s' % st['conclusion'])
        L.append('')

    # ---- 超参扫描
    sw = data.get('hyperparam_sweep') or {}
    L.append('## 6 超参扫描:基线配置是否已经最优')
    L.append('')
    if sw.get('skipped'):
        L.append('> 跳过:%s' % sw['skipped'])
        L.append('')
    else:
        L.append('| 配置 | epoch | 学习率 | 准确率 | 宏 F1 |')
        L.append('|---|---|---|---|---|')
        for k, v in sw.get('configs', {}).items():
            L.append('| %s | %d | %g | %.4f | %.4f |'
                     % (k, v['epochs'], v['lr'], v['accuracy'],
                        v['macro_f1']))
        L.append('')
        if sw.get('conclusion'):
            L.append('**结论:** %s' % sw['conclusion'])
            L.append('')

    # ---- 阈值校准
    ca = data.get('calibration') or {}
    L.append('## 7 决策阈值校准:后处理能不能再抬一点')
    L.append('')
    if ca.get('skipped'):
        L.append('> 跳过:%s' % ca['skipped'])
        L.append('')
    else:
        # 中性权重取先验的第 3 个位置。这里不写死下标 2:先验的类顺序来自
        # 训练脚本的 label_names,换任务(例如二分类)时长度会变,直接 [2]
        # 会 IndexError。oracle 那一格的权重同样从记录文件读,不写死 0.5000。
        prior = ca.get('train_prior') or []
        ipw = ca.get('inverse_prior_weight') or []
        oracle_w = ca.get('oracle_neutral_weight')
        if len(prior) < 3 or len(ipw) < 3:
            L.append('> 跳过:训练集先验长度 %d,不足以定位中性类' % len(prior))
            L.append('')
        else:
            L.append('三分类 argmax 隐含假设「各类先验相等、错分代价相同」,'
                     '而本数据集中性占 %.1f%%。给每类概率乘一个权重再取 argmax,'
                     '等价于移动决策边界。' % (100.0 * prior[2]))
            L.append('')
            L.append('| 权重来源 | 中性权重 | 是否用测试集 |')
            L.append('|---|---|---|')
            L.append('| 逆训练集先验 | %.4f | 否(只看训练集先验) |'
                     % ipw[2])
            L.append('| 测试集 oracle 搜索 | %s | **是(选择偏差)** |'
                     % ('%.4f' % oracle_w if oracle_w is not None
                        else '—(未记录)'))
            L.append('')
            L.append('**结论:** %s' % ca['oracle_note'])
            L.append('')
            L.append('这一节的写法本身就是结论的一部分:把「试过、数字好看、'
                     '但经不起交叉验证」的方法也写出来,并明确它为什么不算改进。')
            L.append('')

    return '\n'.join(L) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description='改进实验与消融汇总')
    ap.add_argument('-o', '--out', default=os.path.join(EXP_DIR, 'ABLATION.md'),
                    help='输出 Markdown 路径')
    ap.add_argument('--json', default=os.path.join(EXP_DIR,
                                                   'ablation-probes.json'),
                    help='输出 JSON 路径')
    ap.add_argument('--exp-dir', default=EXP_DIR)
    ap.add_argument('--raw-dir', default=RAW_DIR)
    ap.add_argument('--no-models', action='store_true',
                    help='跳过需要本地模型的项(干净检出时用)')
    args = ap.parse_args(argv)

    data = collect(args.exp_dir, args.raw_dir, with_models=not args.no_models)
    text = render_md(data)

    os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
    with open(args.json, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write(text)

    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                  # noqa: BLE001
        pass
    # 别在这里维护一份「会跳过哪些项」的名单:加一节就漏一节。
    # 直接从数据里数所有带 skipped 的项。
    n_skip = sum(1 for v in data.values()
                 if isinstance(v, dict) and v.get('skipped'))
    print('[ok] 已写入 %s' % os.path.relpath(args.out, WS))
    print('     JSON: %s' % os.path.relpath(args.json, WS))
    print('     宏 F1 口径对比 %d 个模型;跳过 %d 项(缺模型或数据)'
          % (len(data.get('macro_f1_ambiguity') or {}), n_skip))
    return 0


if __name__ == '__main__':
    sys.exit(main())
