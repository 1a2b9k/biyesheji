"""
对比实验报告生成器。

读 data/experiments/*.json(由 tools/train_sentiment.py 产出),
渲染成 Markdown 表格,直接作为论文"实验"章节的素材。

为什么要有这个工具:
  论文里的表格必须能由原始结果一键重建。手抄数字进 Word 是
  不可复现的,改一次实验就得手工同步一遍,迟早对不上。

用法:
  .python\\python.exe tools\\experiment_report.py            # 打印到屏幕
  .python\\python.exe tools\\experiment_report.py -o out.md  # 写入文件
"""

import argparse
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP_DIR = os.path.join(WS, 'data', 'experiments')

TASK_TITLES = {
    '3class': '任务 A:三分类(负面/正面/中性)',
    'polarity': '任务 B:二分类极性(剔除中性)',
    'neutral': '任务 C:二分类(中性 vs 有情感)',
}
MODEL_TITLES = {'tfidf': 'TF-IDF + 逻辑回归', 'bert': 'BERT 微调'}


def load_results(exp_dir=EXP_DIR):
    """读全部实验结果,返回 {(task, model): dict}。

    文件名约定 <model>-<task>.json。名字对不上的文件直接跳过,
    而不是猜 —— 猜错了会把别的实验混进表格。
    """
    out = {}
    if not os.path.isdir(exp_dir):
        return out
    for fn in sorted(os.listdir(exp_dir)):
        if not fn.endswith('.json'):
            continue
        stem = fn[:-5]
        if '-' not in stem:
            continue
        model, _, task = stem.rpartition('-')
        if model not in MODEL_TITLES:
            continue
        with open(os.path.join(exp_dir, fn), encoding='utf-8') as f:
            out[(task, model)] = json.load(f)
    return out


def fmt(x, nd=4):
    return f'{x:.{nd}f}' if isinstance(x, (int, float)) else '-'


def prf(v):
    """取 precision/recall/f1。

    f1 若结果文件里没写就由 precision 与 recall 现算,这样早先
    版本训练脚本产出的 json 也能直接渲染,不用重跑训练。
    """
    p, r = v.get('precision'), v.get('recall')
    f = v.get('f1')
    if f is None and isinstance(p, (int, float)) and isinstance(r, (int, float)):
        f = 0.0 if p + r == 0 else 2 * p * r / (p + r)
    return p, r, f


def macro_avg(per_class):
    """从 per_class 现算宏平均。

    不从 json 里读:早先版本没存 macro_precision/macro_recall,
    而这两个数完全可由 per_class 推出,没必要为此重跑训练。
    """
    vals = list((per_class or {}).values())
    if not vals:
        return None, None
    ps = [v.get('precision') for v in vals]
    rs = [v.get('recall') for v in vals]
    if any(x is None for x in ps) or any(x is None for x in rs):
        return None, None
    return sum(ps) / len(ps), sum(rs) / len(rs)


def delta(a, b):
    """b 相对 a 的提升,带正负号。"""
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return '-'
    d = b - a
    return f'{d:+.4f}'


def render(results):
    lines = []
    lines.append('# 情感分析对比实验')
    lines.append('')
    lines.append('本文件由 `tools/experiment_report.py` 从 `data/experiments/*.json` '
                 '自动生成,请勿手工修改。')
    lines.append('')

    if not results:
        lines.append('> 尚无实验结果。先运行 '
                     '`python tools/train_sentiment.py --model both`。')
        return '\n'.join(lines) + '\n'

    tasks = [t for t in TASK_TITLES if any(k[0] == t for k in results)]
    models = [m for m in MODEL_TITLES if any(k[1] == m for k in results)]

    # ---------------- 总览表
    lines.append('## 1 总览')
    lines.append('')
    head = '| 任务 | ' + ' | '.join(MODEL_TITLES[m] for m in models)
    head += ' | 提升(acc) | 提升(macro-F1) |'
    lines.append(head)
    lines.append('|---' * (len(models) + 3) + '|')

    for t in tasks:
        cells = []
        for m in models:
            r = results.get((t, m))
            cells.append(fmt(r['accuracy']) if r else '-')
        d_acc = d_f1 = '-'
        if 'tfidf' in models and 'bert' in models:
            a = results.get((t, 'tfidf'))
            b = results.get((t, 'bert'))
            if a and b:
                d_acc = delta(a['accuracy'], b['accuracy'])
                d_f1 = delta(a['macro_f1'], b['macro_f1'])
        lines.append(f'| {TASK_TITLES[t]} | ' + ' | '.join(cells)
                     + f' | {d_acc} | {d_f1} |')
    lines.append('')

    # ---------------- 每任务明细
    lines.append('## 2 分类明细')
    for t in tasks:
        lines.append('')
        lines.append(f'### {TASK_TITLES[t]}')
        lines.append('')
        for m in models:
            r = results.get((t, m))
            if not r:
                continue
            lines.append(f'**{MODEL_TITLES[m]}**'
                         f'(训练样本 {r.get("n_train", "-")} / '
                         f'测试样本 {r.get("n_test", "-")},'
                         f'耗时 {r.get("elapsed_sec", "-")} s)')
            lines.append('')
            lines.append('| 类别 | precision | recall | f1-score | support |')
            lines.append('|---|---|---|---|---|')
            for name, v in (r.get('per_class') or {}).items():
                p, rc, f1 = prf(v)
                lines.append(f'| {name} | {fmt(p)} | '
                             f'{fmt(rc)} | {fmt(f1)} | '
                             f'{v["support"]} |')
            lines.append(f'| **accuracy** | | | **{fmt(r["accuracy"])}** | '
                         f'{r.get("n_test", "-")} |')
            mp, mr = macro_avg(r.get('per_class'))
            lines.append(f'| macro avg | {fmt(mp)} | '
                         f'{fmt(mr)} | '
                         f'**{fmt(r["macro_f1"])}** | {r.get("n_test", "-")} |')
            lines.append('')

            cm = r.get('confusion_matrix')
            if cm:
                lines.append('混淆矩阵(行=真实,列=预测):')
                lines.append('')
                labels = list((r.get('per_class') or {}).keys())
                lines.append('| 真实\\预测 | ' + ' | '.join(labels) + ' |')
                lines.append('|---' * (len(labels) + 1) + '|')
                for i, row in enumerate(cm):
                    lab = labels[i] if i < len(labels) else str(i)
                    lines.append(f'| {lab} | '
                                 + ' | '.join(str(x) for x in row) + ' |')
                lines.append('')

            if 'majority_baseline' in r:
                mb = r['majority_baseline']
                # 早先版本写成纯数字,新版写成 {label, accuracy} —— 两种都收
                acc = mb['accuracy'] if isinstance(mb, dict) else mb
                lab = mb.get('label') if isinstance(mb, dict) else None
                extra = f'(全部猜 `{lab}`)' if lab is not None else ''
                lines.append(f'> 多数类基线准确率 {fmt(acc)}{extra},'
                             f'本模型高出 {delta(acc, r["accuracy"])}。')
                lines.append('')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description='生成情感分析对比实验报告')
    ap.add_argument('-o', '--out', help='输出 Markdown 文件路径')
    ap.add_argument('--exp-dir', default=EXP_DIR)
    args = ap.parse_args(argv)

    results = load_results(args.exp_dir)
    text = render(results)

    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'[ok] 已写入 {args.out}({len(results)} 份实验结果)')
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
