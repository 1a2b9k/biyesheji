"""
情感分析模型训练器 —— 两条技术路线的可复现实现。

用法:
    .python\\python.exe tools\\train_sentiment.py --model tfidf
    .python\\python.exe tools\\train_sentiment.py --model bert
    .python\\python.exe tools\\train_sentiment.py --model both
    .python\\python.exe tools\\train_sentiment.py --model bert --task polarity

任务(task):
    3class    三分类: 0 负面 / 1 正面 / 2 中性  ← 默认,系统实际使用的任务
    polarity  二分类极性: 只保留 0/1,剔除中性样本
    neutral   二分类: 2=中性 vs 0/1=有情感

产物:
    models/sentiment-<model>/            模型权重与配置
    data/experiments/<model>-<task>.json 指标(准确率 / 宏 F1 / 混淆矩阵)

退出码 0 = 成功。

为什么训练脚本要单独抽出来:
    之前用 .tmp 下的临时脚本跑实验,结论写进了交接文档,但脚本本身丢了,
    换个环境就复现不出来。论文里的每个数字都必须能重跑出来,所以
    数据集划分、随机种子、超参数全部固化在这里。
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)

# 离线运行: 模型已下载到 models/ 下,不要再访问网络
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
os.environ.setdefault('HF_HOME', os.path.join(_WS, '.tmp', 'hf-home'))

TRAIN_CSV = os.path.join(_WS, 'data', 'raw', 'eastmoney_train.csv')
TEST_CSV = os.path.join(_WS, 'data', 'raw', 'eastmoney_test.csv')
BASE_MODEL = os.path.join(_WS, 'models', 'bert-base-chinese')
MODELS_DIR = os.path.join(_WS, 'models')
EXP_DIR = os.path.join(_WS, 'data', 'experiments')

LABELS = ['negative', 'positive', 'neutral']

# 超参数集中在此,便于论文里引用
SEED = 42
MAX_LEN = 64
BATCH_SIZE = 32
EPOCHS = 3
LR = 2e-5
TFIDF_MAX_FEATURES = 50000
TFIDF_NGRAM = (1, 2)
TFIDF_MIN_DF = 2


def set_seed(seed=SEED):
    """固定所有随机源,保证结果可复现。"""
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def load_csv(path):
    """读数据集。返回 (文本列表, 标签列表)。"""
    if not os.path.isfile(path):
        raise SystemExit('数据集不存在: %s' % path)
    with open(path, encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit('数据集为空: %s' % path)
    texts = [r['title'] for r in rows]
    labels = [int(r['label']) for r in rows]
    return texts, labels


def apply_task(texts, labels, task):
    """按任务筛选样本并重映射标签。

    返回 (texts, labels, label_names)。
    """
    if task == '3class':
        return texts, labels, list(LABELS)

    if task == 'polarity':
        keep = [i for i, y in enumerate(labels) if y in (0, 1)]
        return ([texts[i] for i in keep], [labels[i] for i in keep],
                [LABELS[0], LABELS[1]])

    if task == 'neutral':
        return texts, [0 if y == 2 else 1 for y in labels], ['neutral', 'sentiment']

    raise SystemExit('未知任务: %s' % task)


def clean(text):
    """分词前清洗:去掉空白,避免 jieba 切出无意义片段。"""
    return re.sub(r'\s+', '', text)


# ------------------------------------------------------------------ 基线

def train_tfidf(tr_texts, tr_labels, te_texts, te_labels, label_names, out_dir):
    """TF-IDF + 逻辑回归基线。

    这是"传统机器学习"路线的代表:词袋 + 线性分类器。
    它不建模词序,因此对"正话反说"和长距离依赖无能为力 —— 这正是
    与 BERT 对比时要说明的差异来源。
    """
    import jieba
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    jieba.setLogLevel(60)  # 关掉初始化日志

    def seg(texts):
        return [' '.join(jieba.lcut(clean(t))) for t in texts]

    print('  分词中 ...')
    t0 = time.time()
    tr_seg = seg(tr_texts)
    te_seg = seg(te_texts)

    vec = TfidfVectorizer(max_features=TFIDF_MAX_FEATURES,
                          ngram_range=TFIDF_NGRAM, min_df=TFIDF_MIN_DF)
    x_tr = vec.fit_transform(tr_seg)
    x_te = vec.transform(te_seg)
    print('  特征维度 %d,耗时 %.1fs' % (x_tr.shape[1], time.time() - t0))

    clf = LogisticRegression(max_iter=1000, random_state=SEED)
    clf.fit(x_tr, tr_labels)

    preds = clf.predict(x_te)
    probs = clf.predict_proba(x_te)

    os.makedirs(out_dir, exist_ok=True)
    joblib.dump({'vectorizer': vec, 'classifier': clf,
                 'label_names': label_names},
                os.path.join(out_dir, 'model.joblib'))

    return preds, probs


# ------------------------------------------------------------------ BERT

def train_bert(tr_texts, tr_labels, te_texts, te_labels, label_names, out_dir):
    """BERT 微调。"""
    import numpy as np
    import torch
    from torch.utils.data import DataLoader, TensorDataset
    from transformers import (AutoModelForSequenceClassification,
                              AutoTokenizer)

    if not os.path.isdir(BASE_MODEL):
        raise SystemExit(
            '预训练模型缺失: %s\n先跑 .python\\python.exe tools\\fetch_model.py'
            % BASE_MODEL)

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print('  设备 %s' % device)

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=len(label_names)).to(device)

    tr_enc = tok(tr_texts, padding=True, truncation=True,
                 max_length=MAX_LEN, return_tensors='pt')
    te_enc = tok(te_texts, padding=True, truncation=True,
                 max_length=MAX_LEN, return_tensors='pt')

    tr_dl = DataLoader(
        TensorDataset(tr_enc['input_ids'], tr_enc['attention_mask'],
                      torch.tensor(tr_labels)),
        batch_size=BATCH_SIZE, shuffle=True)
    te_dl = DataLoader(
        TensorDataset(te_enc['input_ids'], te_enc['attention_mask'],
                      torch.tensor(te_labels)),
        batch_size=64)

    opt = torch.optim.AdamW(model.parameters(), lr=LR)
    lossf = torch.nn.CrossEntropyLoss()

    t0 = time.time()
    for ep in range(EPOCHS):
        model.train()
        total = 0.0
        for ids, am, y in tr_dl:
            opt.zero_grad()
            out = model(input_ids=ids.to(device), attention_mask=am.to(device))
            loss = lossf(out.logits, y.to(device))
            loss.backward()
            opt.step()
            total += loss.item() * len(y)
        print('  epoch %d/%d  loss=%.4f  (%.0fs)'
              % (ep + 1, EPOCHS, total / len(tr_labels), time.time() - t0))

    model.eval()
    preds, probs = [], []
    with torch.no_grad():
        for ids, am, _ in te_dl:
            logits = model(input_ids=ids.to(device),
                           attention_mask=am.to(device)).logits
            probs.extend(torch.softmax(logits, dim=-1).cpu().tolist())
            preds.extend(logits.argmax(-1).cpu().tolist())

    os.makedirs(out_dir, exist_ok=True)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    with open(os.path.join(out_dir, 'label_names.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(label_names, fh, ensure_ascii=False)

    return preds, np.array(probs)


# ------------------------------------------------------------------ 评估

def evaluate(y_true, y_pred, label_names, probs=None):
    """算指标。返回可直接写进报告的字典。

    宏平均一律显式传 `labels`,让 F1 / 精确率 / 召回率三者口径一致:
    不传时 sklearn 只对「真实值或预测值里出现过的类」求平均,
    而下面 per_class 的宏平均是对全部 label_names 求平均。某个类一条
    都没被判出时,两种口径会给出不同的数,报告里就会自相矛盾。
    """
    from sklearn.metrics import (accuracy_score, classification_report,
                                 confusion_matrix, f1_score)

    label_ids = list(range(len(label_names)))
    acc = float(accuracy_score(y_true, y_pred))
    macro_f1 = float(f1_score(y_true, y_pred, average='macro',
                              labels=label_ids, zero_division=0))
    weighted_f1 = float(f1_score(y_true, y_pred, average='weighted',
                                 labels=label_ids, zero_division=0))

    cm = confusion_matrix(y_true, y_pred, labels=label_ids).tolist()
    report = classification_report(
        y_true, y_pred, labels=label_ids,
        target_names=label_names, digits=4, zero_division=0)

    out = {
        'accuracy': round(acc, 4),
        'macro_f1': round(macro_f1, 4),
        'weighted_f1': round(weighted_f1, 4),
        'confusion_matrix': cm,
        'label_names': label_names,
        'per_class': {},
    }
    for i, name in enumerate(label_names):
        tp = cm[i][i]
        support = sum(cm[i])
        pred_total = sum(cm[r][i] for r in range(len(label_names)))
        out['per_class'][name] = {
            'precision': round(tp / pred_total, 4) if pred_total else 0.0,
            'recall': round(tp / support, 4) if support else 0.0,
            'f1': round(2 * tp / (support + pred_total), 4)
            if (support + pred_total) else 0.0,
            'support': support,
        }
    # 宏平均也存一份,方便报告工具直接读;没有类别时留 None 而不是 0,
    # 0 会被误读成"模型全错"。
    if label_names:
        out['macro_precision'] = round(
            sum(v['precision'] for v in out['per_class'].values())
            / len(label_names), 4)
        out['macro_recall'] = round(
            sum(v['recall'] for v in out['per_class'].values())
            / len(label_names), 4)
    out['report_text'] = report

    if probs is not None:
        out['mean_confidence'] = round(
            float(sum(max(p) for p in probs) / len(probs)), 4)
    return out


def majority_baseline(tr_labels, te_labels):
    """多数类基线: 永远预测训练集里最多的那一类。"""
    from collections import Counter
    from sklearn.metrics import accuracy_score
    top = Counter(tr_labels).most_common(1)[0][0]
    return {
        'label': top,
        'accuracy': round(float(accuracy_score(
            te_labels, [top] * len(te_labels))), 4),
    }


# ------------------------------------------------------------------ 主流程

def run_one(model_name, task, quiet=False):
    print('=== %s / %s ===' % (model_name, task))
    tr_texts, tr_labels = load_csv(TRAIN_CSV)
    te_texts, te_labels = load_csv(TEST_CSV)
    tr_texts, tr_labels, names = apply_task(tr_texts, tr_labels, task)
    te_texts, te_labels, names2 = apply_task(te_texts, te_labels, task)
    assert names == names2, '训练/测试集标签名不一致'

    print('  训练 %d 条 / 测试 %d 条 / %d 类'
          % (len(tr_texts), len(te_texts), len(names)))

    set_seed(SEED)
    out_dir = os.path.join(MODELS_DIR, 'sentiment-%s-%s' % (model_name, task))

    _t0 = time.time()
    if model_name == 'tfidf':
        preds, probs = train_tfidf(tr_texts, tr_labels, te_texts, te_labels,
                                   names, out_dir)
    else:
        preds, probs = train_bert(tr_texts, tr_labels, te_texts, te_labels,
                                  names, out_dir)
    elapsed = time.time() - _t0

    metrics = evaluate(te_labels, list(preds), names, probs)
    metrics['model'] = model_name
    metrics['task'] = task
    metrics['n_train'] = len(tr_texts)
    metrics['n_test'] = len(te_texts)
    metrics['seed'] = SEED
    # 训练耗时:论文里比较两条路线时"效果/成本"要一起给,
    # 只报准确率会让人以为 BERT 是免费提升。
    metrics['elapsed_sec'] = round(elapsed, 1)
    metrics['majority_baseline'] = majority_baseline(tr_labels, te_labels)

    if model_name == 'bert':
        metrics['hyperparams'] = {
            'max_len': MAX_LEN, 'batch_size': BATCH_SIZE,
            'epochs': EPOCHS, 'learning_rate': LR,
            'base_model': 'bert-base-chinese',
        }
    else:
        metrics['hyperparams'] = {
            'max_features': TFIDF_MAX_FEATURES,
            'ngram_range': list(TFIDF_NGRAM),
            'min_df': TFIDF_MIN_DF,
            'classifier': 'LogisticRegression',
        }

    os.makedirs(EXP_DIR, exist_ok=True)
    path = os.path.join(EXP_DIR, '%s-%s.json' % (model_name, task))
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)

    print('  准确率 %.4f  宏F1 %.4f  (多数类基线 %.4f)'
          % (metrics['accuracy'], metrics['macro_f1'],
             metrics['majority_baseline']['accuracy']))
    print('  已写入 %s' % os.path.relpath(path, _WS))
    print()
    return metrics


def main(argv=None):
    ap = argparse.ArgumentParser(description='情感分析模型训练器')
    ap.add_argument('--model', default='both',
                    choices=['bert', 'tfidf', 'both'],
                    help='训练哪条路线(默认 both)')
    ap.add_argument('--task', default='3class',
                    choices=['3class', 'polarity', 'neutral'],
                    help='任务切分方式(默认 3class)')
    args = ap.parse_args(argv)

    models = ['tfidf', 'bert'] if args.model == 'both' else [args.model]
    results = {}
    for m in models:
        results[m] = run_one(m, args.task)

    if len(results) == 2:
        d_acc = results['bert']['accuracy'] - results['tfidf']['accuracy']
        d_f1 = results['bert']['macro_f1'] - results['tfidf']['macro_f1']
        print('=== 对比 ===')
        print('  BERT - TF-IDF:  准确率 %+.4f  宏F1 %+.4f' % (d_acc, d_f1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
