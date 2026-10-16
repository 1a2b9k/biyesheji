"""
多任务学习 / 标签重构训练器 —— 针对「中性标签复合性」的两条改进路线。

背景(见 data/experiments/NEUTRAL_ANALYSIS.md):
    BERT 三分类基线 acc 0.7540 / macro F1 0.7491。实测发现三分类模型
    在**中性判别**上反而强于中性专用模型(0.8186 vs 0.6739),但在
    **极性判别**上明显弱于极性专用模型(0.7093 vs 0.8435)。说明三个类
    挤在一个 softmax 里互相稀释。

本工具实现两条路线:

  mode=mtl     多任务学习:共享 BERT 编码器 + 3 个头
               (主头 3 分类 / 极性头 / 中性头),辅助头只在对应子集上算损失。
               目的:既保住三分类的中性判别力,又拿到极性专用模型的极性判别力。

  mode=4class  标签重构:把复合的中性类按「是否提问」拆成两类,
               变成 4 分类。目的:验证档 2 提出的「中性标签复合」假设
               —— 若拆分后指标改善,说明原标签确实在混语义。

用法:
    .python\\python.exe tools\\train_multitask.py --mode mtl
    .python\\python.exe tools\\train_multitask.py --mode 4class
    .python\\python.exe tools\\train_multitask.py --mode both

产物:
    models/multitask-<mode>/         模型权重(state_dict)与配置
    data/experiments/<mode>.json     指标,与 bert-3class 基线对比

退出码 0 = 成功。

为什么单独一个文件而不是塞进 train_sentiment.py:
    train_sentiment.py 是「两条技术路线」的对比(论文第 6 章的基线部分),
    它必须保持稳定、可复现;本文件是**改进实验**,会反复调参。
    分开后基线不会因为调参而漂移。
"""

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)  # embeddable Python 不把脚本目录放进 sys.path

# 离线运行: 模型已下载到 models/ 下,不要再访问网络
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
os.environ.setdefault('HF_HOME', os.path.join(_WS, '.tmp', 'hf-home'))

from train_sentiment import (BASE_MODEL, BATCH_SIZE, EPOCHS, EXP_DIR,  # noqa: E402
                             LABELS, LR, MAX_LEN, MODELS_DIR, SEED,
                             TEST_CSV, TRAIN_CSV, evaluate, load_csv,
                             majority_baseline, set_seed)
from analyze_neutral import is_question  # noqa: E402

# 4 分类的类别顺序:先极性后中性,保证 0/1 仍是极性、>=2 都是中性,
# 这样「主头 < 2 即为有极性」这个判据对两种 mode 都成立。
FOUR_LABELS = ['negative', 'positive', 'neutral_question', 'neutral_statement']

# 中性类的起始下标(两种 mode 都是 2)
NEUTRAL_FROM = 2


def build_labels(texts, labels, mode):
    """按 mode 生成主任务标签。返回 (labels, label_names)。

    两种 mode 都保证:0/1 = 极性类,>= 2 = 中性类。辅助头据此派生。
    """
    if mode == 'mtl':
        return list(labels), list(LABELS)
    if mode == '4class':
        out = []
        for t, lb in zip(texts, labels):
            if lb != 2:
                out.append(lb)
            else:
                out.append(2 if is_question(t) else 3)
        return out, list(FOUR_LABELS)
    raise SystemExit('未知 mode: %s' % mode)


# ------------------------------------------------------------------ 模型

def build_model(base_path, n_main, dropout=0.1):
    """共享编码器 + 3 个头。

    encoder 作为参数传入而不是在内部加载,是为了让测试能塞一个小模型进来,
    不必下载/加载 390 MB 的 bert-base-chinese。
    """
    import torch
    import torch.nn as nn
    from transformers import AutoModel

    encoder = AutoModel.from_pretrained(base_path)

    class MultiTaskBert(nn.Module):
        def __init__(self, enc, n_main, dropout):
            super().__init__()
            self.encoder = enc
            hidden = enc.config.hidden_size
            self.dropout = nn.Dropout(dropout)
            self.head_main = nn.Linear(hidden, n_main)   # 主任务
            self.head_pol = nn.Linear(hidden, 2)         # 辅助:极性
            self.head_neu = nn.Linear(hidden, 2)         # 辅助:是否中性
            self.hidden_size = hidden

        def forward(self, input_ids, attention_mask):
            out = self.encoder(input_ids=input_ids,
                               attention_mask=attention_mask)
            # bert 的 pooler 就是 [CLS] 过一层线性 + tanh;没有 pooler 时退回 [CLS]
            pooled = getattr(out, 'pooler_output', None)
            if pooled is None:
                pooled = out.last_hidden_state[:, 0]
            pooled = self.dropout(pooled)
            return (self.head_main(pooled), self.head_pol(pooled),
                    self.head_neu(pooled))

    return MultiTaskBert(encoder, n_main, dropout)


def load_multitask(model_dir):
    """读回训练好的多任务模型(供分析/推理使用)。"""
    import torch

    with open(os.path.join(model_dir, 'config.json'), encoding='utf-8') as fh:
        cfg = json.load(fh)
    model = build_model(cfg['base_model'], cfg['n_main'])
    model.load_state_dict(
        torch.load(os.path.join(model_dir, 'model.pt'), map_location='cpu'))
    model.eval()
    return model, cfg


# ------------------------------------------------------------------ 训练

def train(tr_texts, tr_labels, te_texts, te_labels, label_names, out_dir,
          epochs=EPOCHS, lam_pol=1.0, lam_neu=1.0, seed=SEED):
    """训练多任务模型。返回 (主头预测, 极性头预测, 主头概率, 辅助头信息)。

    辅助头只在**有定义的子集**上算损失:
      * 极性头:只在主标签 < 2(即真正有极性)的样本上
      * 中性头:全部样本,标签 = 主标签 >= 2
    否则中性样本会被强行拉去学一个它没有的极性。
    """
    import numpy as np
    import torch
    from torch.utils.data import DataLoader, TensorDataset
    from transformers import AutoTokenizer

    if not os.path.isdir(BASE_MODEL):
        raise SystemExit(
            '预训练模型缺失: %s\n先跑 .python\\python.exe tools\\fetch_model.py'
            % BASE_MODEL)

    set_seed(seed)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print('  设备 %s' % device)

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = build_model(BASE_MODEL, len(label_names)).to(device)

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
    ce = torch.nn.CrossEntropyLoss()

    t0 = time.time()
    for ep in range(epochs):
        model.train()
        total = 0.0
        for ids, am, y in tr_dl:
            ids, am, y = ids.to(device), am.to(device), y.to(device)
            opt.zero_grad()
            main, pol, neu = model(ids, am)
            loss = ce(main, y)
            # 极性头:只在主标签属于极性类的样本上算
            mask = y < NEUTRAL_FROM
            if lam_pol and bool(mask.any()):
                loss = loss + lam_pol * ce(pol[mask], y[mask])
            # 中性头:全部样本,二分类「是否中性」
            if lam_neu:
                loss = loss + lam_neu * ce(neu, (y >= NEUTRAL_FROM).long())
            loss.backward()
            opt.step()
            total += loss.item() * len(y)
        print('  epoch %d/%d  loss=%.4f  (%.0fs)'
              % (ep + 1, epochs, total / len(tr_labels), time.time() - t0))

    model.eval()
    p_main, p_pol, p_neu, probs = [], [], [], []
    with torch.no_grad():
        for ids, am, _ in te_dl:
            ids, am = ids.to(device), am.to(device)
            main, pol, neu = model(ids, am)
            p_main.extend(main.argmax(-1).cpu().tolist())
            p_pol.extend(pol.argmax(-1).cpu().tolist())
            p_neu.extend(neu.argmax(-1).cpu().tolist())
            probs.extend(torch.softmax(main, dim=-1).cpu().tolist())

    os.makedirs(out_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(out_dir, 'model.pt'))
    with open(os.path.join(out_dir, 'config.json'), 'w',
              encoding='utf-8') as fh:
        json.dump({'base_model': BASE_MODEL, 'n_main': len(label_names),
                   'label_names': label_names, 'hidden_size': model.hidden_size,
                   'lam_pol': lam_pol, 'lam_neu': lam_neu,
                   'epochs': epochs, 'seed': seed},
                  fh, ensure_ascii=False, indent=2)

    return p_main, p_pol, p_neu, np.array(probs)


def combine(p_main, p_pol):
    """组合策略:主头判为中性就用主头,否则用极性头定极性。

    主头在「是不是中性」上更准,极性头在「哪个极性」上更准,
    这个组合试图同时吃到两边长处(实测增益很小,见报告)。
    """
    out = []
    for m, b in zip(p_main, p_pol):
        out.append(m if m >= NEUTRAL_FROM else b)
    return out


# ------------------------------------------------------------------ 主流程

def run_one(mode, epochs=EPOCHS, lam_pol=1.0, lam_neu=1.0, seed=SEED):
    print('=== mode=%s ===' % mode)
    tr_texts, tr_labels = load_csv(TRAIN_CSV)
    te_texts, te_labels = load_csv(TEST_CSV)
    tr_labels, names = build_labels(tr_texts, tr_labels, mode)
    te_labels, names2 = build_labels(te_texts, te_labels, mode)
    assert names == names2, '训练/测试集标签名不一致'

    print('  训练 %d 条 / 测试 %d 条 / %d 类'
          % (len(tr_texts), len(te_texts), len(names)))

    out_dir = os.path.join(MODELS_DIR, 'multitask-%s' % mode)
    _t0 = time.time()
    p_main, p_pol, p_neu, probs = train(
        tr_texts, tr_labels, te_texts, te_labels, names, out_dir,
        epochs=epochs, lam_pol=lam_pol, lam_neu=lam_neu, seed=seed)
    elapsed = time.time() - _t0

    metrics = evaluate(te_labels, list(p_main), names, probs)
    metrics['mode'] = mode
    metrics['n_train'] = len(tr_texts)
    metrics['n_test'] = len(te_texts)
    metrics['seed'] = seed
    metrics['elapsed_sec'] = round(elapsed, 1)
    metrics['majority_baseline'] = majority_baseline(tr_labels, te_labels)
    metrics['hyperparams'] = {
        'max_len': MAX_LEN, 'batch_size': BATCH_SIZE, 'epochs': epochs,
        'learning_rate': LR, 'base_model': 'bert-base-chinese',
        'lambda_polarity': lam_pol, 'lambda_neutral': lam_neu,
    }

    # 组合策略单独记一份:论文里要对比「主头单用」与「主头+极性头」
    from sklearn.metrics import accuracy_score
    comb = combine(p_main, p_pol)
    metrics['combined'] = {
        'accuracy': round(float(accuracy_score(te_labels, comb)), 4),
        'delta_vs_main': round(
            float(accuracy_score(te_labels, comb)) - metrics['accuracy'], 4),
    }
    # 辅助头自身表现(只在有定义的子集上)
    polar_idx = [i for i, y in enumerate(te_labels) if y < NEUTRAL_FROM]
    neu_idx = [i for i, y in enumerate(te_labels) if y >= NEUTRAL_FROM]
    if polar_idx:
        metrics['aux_polarity_head_acc'] = round(float(accuracy_score(
            [te_labels[i] for i in polar_idx],
            [p_pol[i] for i in polar_idx])), 4)
    if neu_idx:
        metrics['aux_neutral_head_acc'] = round(float(accuracy_score(
            [0] * len(neu_idx), [p_neu[i] for i in neu_idx])), 4)

    os.makedirs(EXP_DIR, exist_ok=True)
    path = os.path.join(EXP_DIR, '%s.json' % mode)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)

    print('  准确率 %.4f  宏F1 %.4f  (多数类基线 %.4f)'
          % (metrics['accuracy'], metrics['macro_f1'],
             metrics['majority_baseline']['accuracy']))
    print('  组合策略 准确率 %.4f (%+.4f)'
          % (metrics['combined']['accuracy'], metrics['combined']['delta_vs_main']))
    if polar_idx:
        print('  极性头(非中性子集) %.4f' % metrics['aux_polarity_head_acc'])
    print('  已写入 %s' % os.path.relpath(path, _WS))
    print()
    return metrics


def load_baseline():
    """读三分类基线指标,用于对比。缺失时返回 None。"""
    path = os.path.join(EXP_DIR, 'bert-3class.json')
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description='多任务 / 标签重构训练器')
    ap.add_argument('--mode', default='both',
                    choices=['mtl', '4class', 'both'],
                    help='mtl=多任务学习; 4class=中性按是否提问拆开(默认 both)')
    ap.add_argument('--epochs', type=int, default=EPOCHS, help='训练轮数')
    ap.add_argument('--lambda-pol', type=float, default=1.0,
                    help='极性辅助头损失权重,0 表示关闭')
    ap.add_argument('--lambda-neu', type=float, default=1.0,
                    help='中性辅助头损失权重,0 表示关闭')
    ap.add_argument('--seed', type=int, default=SEED, help='随机种子')
    args = ap.parse_args(argv)

    modes = ['mtl', '4class'] if args.mode == 'both' else [args.mode]
    results = {}
    for m in modes:
        results[m] = run_one(m, epochs=args.epochs, lam_pol=args.lambda_pol,
                             lam_neu=args.lambda_neu, seed=args.seed)

    base = load_baseline()
    if base:
        print('=== 对比基线 bert-3class ===')
        print('  基线            准确率 %.4f  宏F1 %.4f'
              % (base['accuracy'], base['macro_f1']))
        for m, r in results.items():
            print('  %-14s 准确率 %.4f (%+.4f)  宏F1 %.4f (%+.4f)'
                  % (m, r['accuracy'], r['accuracy'] - base['accuracy'],
                     r['macro_f1'], r['macro_f1'] - base['macro_f1']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
