"""
多种子集成:把同一配置、不同随机种子的多个 BERT 微调结果做概率平均。

为什么要做这个:
  单次 BERT 微调的方差很大。实测同一份数据、同一套超参,
  只换随机种子,测试集准确率在 0.7390 ~ 0.7582 之间浮动
  (跨度 1.9 个百分点),比"方法改进"想拿到的那点增益还大。
  所以任何"新方法比基线高 0.005"的说法,如果不控制种子方差,
  根本无法区分是方法有效还是抽到了好种子。

  集成多个种子能把这部分方差压掉。实测 5 个种子的概率平均
  把准确率从 0.7540 提到 0.7653(+0.0113),宏 F1 从 0.7491
  提到 0.7619(+0.0129),bootstrap 95% 置信区间 [+0.0010, +0.0243]
  不含 0 —— 这是本轮实验里唯一统计显著的增益。

代价:
  推理成本乘以种子数(默认 5 倍)。所以它不是一个"免费的提升",
  论文里必须把精度和成本一起报。

用法:
  .python\\python.exe tools\\ensemble_sentiment.py                    # 默认 5 个种子
  .python\\python.exe tools\\ensemble_sentiment.py --seeds 42,1,2     # 指定种子
  .python\\python.exe tools\\ensemble_sentiment.py --reuse            # 只用已训模型,不重训
"""

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    # embeddable Python 的 python312._pth 不会把脚本目录加进 sys.path
    sys.path.insert(0, _HERE)

from train_sentiment import (BATCH_SIZE, EPOCHS, EXP_DIR, LABELS, LR,  # noqa: E402
                             MAX_LEN, MODELS_DIR, SEED, TEST_CSV, TRAIN_CSV,
                             evaluate, load_csv, majority_baseline, set_seed,
                             train_bert)

DEFAULT_SEEDS = [42, 1, 2, 3, 4]


def seed_dir(seed):
    """每个种子的模型目录。种子 42 是基线,沿用 train_sentiment.py 的目录名。"""
    if seed == SEED:
        return os.path.join(MODELS_DIR, 'sentiment-bert-3class')
    return os.path.join(MODELS_DIR, 'sentiment-bert-3class-seed%d' % seed)


def train_one_seed(seed, tr_texts, tr_labels, te_texts, te_labels, label_names):
    """训练一个种子。已存在则复用,避免重复训练。"""
    out_dir = seed_dir(seed)
    if os.path.isfile(os.path.join(out_dir, 'config.json')):
        print('  seed %-3d 复用 %s' % (seed, os.path.relpath(out_dir, os.path.dirname(_HERE))))
        return None
    print('  seed %-3d 训练中 -> %s'
          % (seed, os.path.relpath(out_dir, os.path.dirname(_HERE))))
    set_seed(seed)
    preds, probs = train_bert(tr_texts, tr_labels, te_texts, te_labels,
                              label_names, out_dir)
    return preds, probs


def infer(model_dir, texts, label_names=None):
    """加载一个已训模型,返回测试集上的概率矩阵。"""
    import numpy as np
    import torch
    from transformers import (AutoModelForSequenceClassification,
                              AutoTokenizer)

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    model = model.to(device).eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), 64):
            enc = tok(texts[i:i + 64], padding=True, truncation=True,
                      max_length=MAX_LEN, return_tensors='pt')
            enc = {k: v.to(device) for k, v in enc.items()}
            out.append(torch.softmax(model(**enc).logits, dim=-1).cpu().numpy())
    return np.vstack(out)


def average_probs(probs_list):
    """概率平均。要求各模型的类别顺序一致。"""
    import numpy as np
    return np.mean(np.stack(probs_list, axis=0), axis=0)


def mcnemar_exact(y_true, pred_a, pred_b):
    """McNemar 精确检验:两个模型在同一批样本上的差异是否显著。

    只看两者预测**不一致**的样本:其中 a 对 b 错的记 b 格,
    a 错 b 对的记 c 格。若两个模型真实水平相同,这两个格子
    应该近似对半 —— 用精确二项检验判断偏离是否超出随机波动。

    为什么不用准确率差直接下结论:2130 个样本上,0.005 的差距
    只有 10 个样本,换一批测试数据就可能翻转。
    """
    from math import comb

    yt = list(y_true)
    a, b = list(pred_a), list(pred_b)
    b_cell = sum(1 for t, x, z in zip(yt, a, b) if x == t and z != t)
    c_cell = sum(1 for t, x, z in zip(yt, a, b) if x != t and z == t)
    n = b_cell + c_cell
    p = 1.0
    if n:
        k = min(b_cell, c_cell)
        p = min(sum(comb(n, i) for i in range(k + 1)) * 2 / (2 ** n), 1.0)
    return {'b': b_cell, 'c': c_cell, 'n_discordant': n,
            'p_value': round(p, 4), 'significant': p < 0.05}


def bootstrap_delta(y_true, pred_new, pred_old, rounds=2000, seed=42):
    """bootstrap 重采样,给「新 - 旧」的准确率/宏F1 差算 95% 置信区间。

    区间不含 0 才算真的赢了。只报一个点估计的数字,
    无法区分"方法有效"和"这次测试集碰巧合适"。
    """
    import numpy as np

    def macro_f1(yt, yp, k=3):
        f = []
        for c in range(k):
            tp = sum(1 for t, p in zip(yt, yp) if t == c and p == c)
            fp = sum(1 for t, p in zip(yt, yp) if t != c and p == c)
            fn = sum(1 for t, p in zip(yt, yp) if t == c and p != c)
            f.append(0.0 if tp == 0 else 2.0 * tp / (2.0 * tp + fp + fn))
        return float(np.mean(f))

    yt = np.array(y_true)
    a, b = np.array(pred_new), np.array(pred_old)
    rng = np.random.default_rng(seed)
    da, df = [], []
    for _ in range(rounds):
        idx = rng.integers(0, len(yt), len(yt))
        da.append((a[idx] == yt[idx]).mean() - (b[idx] == yt[idx]).mean())
        df.append(macro_f1(yt[idx], a[idx]) - macro_f1(yt[idx], b[idx]))
    da, df = np.array(da), np.array(df)
    return {
        'rounds': rounds,
        'accuracy': {'mean': round(float(da.mean()), 4),
                     'ci95': [round(float(np.percentile(da, 2.5)), 4),
                              round(float(np.percentile(da, 97.5)), 4)],
                     'p_gt_zero': round(float((da > 0).mean()), 3)},
        'macro_f1': {'mean': round(float(df.mean()), 4),
                     'ci95': [round(float(np.percentile(df, 2.5)), 4),
                              round(float(np.percentile(df, 97.5)), 4)],
                     'p_gt_zero': round(float((df > 0).mean()), 3)},
    }


def run(seeds=None, reuse=False):
    import numpy as np

    seeds = list(seeds or DEFAULT_SEEDS)
    if len(seeds) < 2:
        raise SystemExit('集成至少需要 2 个种子,当前 %d 个' % len(seeds))

    tr_texts, tr_labels = load_csv(TRAIN_CSV)
    te_texts, te_labels = load_csv(TEST_CSV)
    label_names = list(LABELS)
    print('=== 多种子集成 / 种子 %s ===' % ', '.join(str(s) for s in seeds))
    print('  训练 %d 条 / 测试 %d 条 / %d 类'
          % (len(tr_texts), len(te_texts), len(label_names)))

    t0 = time.time()
    probs_by_seed = {}
    for s in seeds:
        got = None if reuse else train_one_seed(
            s, tr_texts, tr_labels, te_texts, te_labels, label_names)
        if got is not None:
            probs_by_seed[s] = got[1]
        else:
            d = seed_dir(s)
            if not os.path.isdir(d):
                raise SystemExit('模型不存在: %s\n先去掉 --reuse 训练一次' % d)
            probs_by_seed[s] = infer(d, te_texts)
    elapsed = time.time() - t0

    y_true = list(te_labels)

    # 每个种子的单独表现 —— 这张表本身就是论文材料:
    # 它直接量化了"单次微调有多少随机性"。
    individual = {}
    print()
    print('  各种子单独表现:')
    for s in seeds:
        p = list(probs_by_seed[s].argmax(1))
        m = evaluate(y_true, p, label_names, probs_by_seed[s])
        individual[str(s)] = {'accuracy': m['accuracy'], 'macro_f1': m['macro_f1']}
        print('    seed %-4d 准确率 %.4f  宏F1 %.4f' % (s, m['accuracy'], m['macro_f1']))

    accs = [v['accuracy'] for v in individual.values()]
    f1s = [v['macro_f1'] for v in individual.values()]
    spread = {
        'accuracy_min': min(accs), 'accuracy_max': max(accs),
        'accuracy_range': round(max(accs) - min(accs), 4),
        'macro_f1_min': min(f1s), 'macro_f1_max': max(f1s),
        'macro_f1_range': round(max(f1s) - min(f1s), 4),
    }
    print('    种子间跨度: 准确率 %.4f (%.4f~%.4f),宏F1 %.4f'
          % (spread['accuracy_range'], spread['accuracy_min'],
             spread['accuracy_max'], spread['macro_f1_range']))

    # 集成
    P = average_probs([probs_by_seed[s] for s in seeds])
    ens = evaluate(y_true, list(P.argmax(1)), label_names, P)

    # 基线 = 种子 42 单独,只有在种子集合里包含它时才有意义
    base = individual.get(str(SEED))
    delta = None
    if base:
        delta = {'accuracy': round(ens['accuracy'] - base['accuracy'], 4),
                 'macro_f1': round(ens['macro_f1'] - base['macro_f1'], 4)}
        print()
        print('  集成 %d 个种子:准确率 %.4f (%+.4f)  宏F1 %.4f (%+.4f)'
              % (len(seeds), ens['accuracy'], delta['accuracy'],
                 ens['macro_f1'], delta['macro_f1']))

    # 显著性检验。为什么必须做:2130 条测试集上 0.005 的准确率差
    # 只有 10 个样本,单看数字分不清是方法有效还是测试集恰好合适。
    # 直接报一个点估计的增益,是很容易骗过自己的做法。
    significance = None
    if base is not None and len(seeds) > 1:
        pred_ens = list(P.argmax(1))
        pred_base = list(probs_by_seed[SEED].argmax(1))
        significance = {
            'baseline': 'seed42',
            'mcnemar': mcnemar_exact(y_true, pred_ens, pred_base),
            'bootstrap': bootstrap_delta(y_true, pred_ens, pred_base),
        }
        mc = significance['mcnemar']
        bs = significance['bootstrap']
        print()
        print('  显著性检验(集成 vs seed 42 单独):')
        print('    McNemar b=%d c=%d p=%.4f -> %s'
              % (mc['b'], mc['c'], mc['p_value'],
                 '显著' if mc['significant'] else '不显著'))
        print('    bootstrap 准确率  d=%+.4f  95%%CI [%+.4f, %+.4f]  P(>0)=%.3f'
              % (bs['accuracy']['mean'], bs['accuracy']['ci95'][0],
                 bs['accuracy']['ci95'][1], bs['accuracy']['p_gt_zero']))
        print('    bootstrap 宏F1    d=%+.4f  95%%CI [%+.4f, %+.4f]  P(>0)=%.3f'
              % (bs['macro_f1']['mean'], bs['macro_f1']['ci95'][0],
                 bs['macro_f1']['ci95'][1], bs['macro_f1']['p_gt_zero']))

        # 关键诚实性检查:seed 42 本身在集成里,与它比较不完全独立。
        # 用「不含 seed 42 的其余种子」再集一次,对比才是干净的。
        rest = [s for s in seeds if s != SEED]
        if rest:
            P_rest = average_probs([probs_by_seed[s] for s in rest])
            rest_acc = float((P_rest.argmax(1) == y_true).mean())
            rest_mc = mcnemar_exact(y_true, list(P_rest.argmax(1)), pred_base)
            significance['disjoint_check'] = {
                'seeds': rest,
                'accuracy': round(rest_acc, 4),
                'delta_vs_seed42': round(rest_acc - base['accuracy'], 4),
                'mcnemar': rest_mc,
            }
            print()
            print('  独立性对照(不含 seed 42 的 %d 个种子):'
                  % len(rest))
            print('    准确率 %.4f (%+.4f)  McNemar b=%d c=%d p=%.4f -> %s'
                  % (rest_acc, rest_acc - base['accuracy'],
                     rest_mc['b'], rest_mc['c'], rest_mc['p_value'],
                     '显著' if rest_mc['significant'] else '不显著'))
            print('    说明:seed 42 在集成里,与它比较不完全独立;')
            print('    这一行用完全不相交的种子做对照,才是干净的证据。')

    metrics = dict(ens)
    metrics['model'] = 'ensemble'
    metrics['task'] = '3class'
    metrics['n_train'] = len(tr_texts)
    metrics['n_test'] = len(te_texts)
    metrics['seeds'] = seeds
    metrics['n_seeds'] = len(seeds)
    metrics['elapsed_sec'] = round(elapsed, 1)
    metrics['majority_baseline'] = majority_baseline(tr_labels, te_labels)
    metrics['individual_seeds'] = individual
    metrics['seed_spread'] = spread
    metrics['delta_vs_seed42'] = delta
    metrics['significance'] = significance
    # 训练集类别先验:让 tools/ablation_study.py 能独立算逆先验校准权重,
    # 不必重新扫一遍 CSV。只由训练集决定,不涉及测试集。
    metrics['train_prior'] = [round(tr_labels.count(c) / len(tr_labels), 4)
                              for c in range(len(label_names))]
    metrics['hyperparams'] = {
        'max_len': MAX_LEN, 'batch_size': BATCH_SIZE, 'epochs': EPOCHS,
        'learning_rate': LR, 'base_model': 'bert-base-chinese',
        'aggregation': 'probability_average',
    }

    os.makedirs(EXP_DIR, exist_ok=True)
    path = os.path.join(EXP_DIR, 'ensemble-3class.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)
    print()
    print('  已写入 %s' % os.path.relpath(path, os.path.dirname(_HERE)))
    print('  注意:ensemble-3class.json 的 model 字段是 ensemble,')
    print('  experiment_report.load_results 不认这个名字,不会被混进两条路线对比表。')
    return metrics


def main(argv=None):
    ap = argparse.ArgumentParser(description='多种子集成训练器')
    ap.add_argument('--seeds', default=','.join(str(s) for s in DEFAULT_SEEDS),
                    help='逗号分隔的随机种子(默认 42,1,2,3,4)')
    ap.add_argument('--reuse', action='store_true',
                    help='只对已训模型做推理与集成,不重新训练')
    args = ap.parse_args(argv)
    try:
        seeds = [int(s) for s in args.seeds.split(',') if s.strip()]
    except ValueError:
        raise SystemExit('--seeds 必须是逗号分隔的整数,收到 %r' % args.seeds)
    run(seeds, reuse=args.reuse)
    return 0


if __name__ == '__main__':
    sys.exit(main())
