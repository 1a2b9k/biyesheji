"""
下载并校验情感分析数据集。

用法:
    .python\\python.exe tools\\fetch_dataset.py            # 下载(已存在则跳过)
    .python\\python.exe tools\\fetch_dataset.py --force    # 强制重新下载
    .python\\python.exe tools\\fetch_dataset.py --check    # 只校验本地文件

数据集:HikasaHana/eastmoney_guba_title
    东方财富股吧标题,**人工标注**情感,三元标签
    (0 负面 / 1 正面 / 2 中性)

实测(2026-10-13):train 8516 条 + test 2130 条,训练/测试无重叠。
详见 `数据集实测报告.md`。

下载走 hf-mirror.com 镜像 —— HuggingFace 官方域名在本机时通时不通。
数据落在 data/raw/(已被 gitignore)。
"""

import argparse
import os
import sys
import urllib.request
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
OUT_DIR = os.path.join(_WS, 'data', 'raw')

BASE = 'https://hf-mirror.com/datasets/HikasaHana/eastmoney_guba_title/resolve/main'
FILES = ['train.csv', 'test.csv']
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

LABEL_NAMES = {'0': '负面', '1': '正面', '2': '中性'}

# 实测基线,用于校验下载结果是否完整
EXPECTED_MIN = {'train.csv': 8000, 'test.csv': 2000}


def local_path(name):
    return os.path.join(OUT_DIR, 'eastmoney_' + name)


def download(name, force=False):
    dest = local_path(name)
    if os.path.exists(dest) and not force:
        size = os.path.getsize(dest)
        print('  [skip] %-12s 已存在 %d bytes' % (name, size))
        return dest

    url = '%s/%s' % (BASE, name)
    req = urllib.request.Request(url)
    req.add_header('User-Agent', UA)
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()

    with open(dest, 'wb') as fh:
        fh.write(data)
    print('  [ok]   %-12s %d bytes' % (name, len(data)))
    return dest


def read_rows(path):
    """读 CSV。标题里可能含逗号,故按最后一个逗号切分。"""
    with open(path, encoding='utf-8', errors='replace') as fh:
        lines = fh.read().splitlines()
    rows = []
    for ln in lines[1:]:
        if not ln.strip():
            continue
        idx = ln.rfind(',')
        if idx < 0:
            continue
        rows.append((ln[:idx].strip().strip('"'), ln[idx + 1:].strip()))
    return rows


def check():
    """校验本地文件:存在性、样本量、标签合法性、划分是否干净。"""
    print('校验本地数据集…')
    print()
    problems = []
    data = {}

    for name in FILES:
        p = local_path(name)
        if not os.path.exists(p):
            problems.append('%s 不存在' % name)
            continue
        rows = read_rows(p)
        data[name] = rows

        counter = Counter(r[1] for r in rows)
        print('%-12s %5d 条' % (name, len(rows)))
        for lab in sorted(counter):
            label = LABEL_NAMES.get(lab, '(未知标签!)')
            print('               %s %s : %d' % (lab, label, counter[lab]))

        if len(rows) < EXPECTED_MIN.get(name, 0):
            problems.append('%s 样本量偏少(%d),可能下载不完整'
                            % (name, len(rows)))

        bad = [r[1] for r in rows if r[1] not in LABEL_NAMES]
        if bad:
            problems.append('%s 含非法标签: %s' % (name, set(bad)))

        empty = [r for r in rows if not r[0]]
        if empty:
            problems.append('%s 含 %d 条空标题' % (name, len(empty)))

    # 划分是否干净 —— 这是实验可信度的关键
    if len(data) == 2:
        train_titles = {r[0] for r in data['train.csv']}
        test_titles = {r[0] for r in data['test.csv']}
        overlap = train_titles & test_titles
        print()
        print('训练/测试重叠标题: %d 条' % len(overlap))
        if overlap:
            problems.append('训练集与测试集有 %d 条重叠,存在数据泄漏风险'
                            % len(overlap))
        else:
            print('  -> 划分干净,无数据泄漏')

        total = len(data['train.csv']) + len(data['test.csv'])
        print('合计: %d 条' % total)

    print()
    if problems:
        print('发现问题:')
        for p in problems:
            print('  - %s' % p)
        return 1

    print('校验通过:数据集可用。')
    print('详见 数据集实测报告.md')
    return 0


def main():
    ap = argparse.ArgumentParser(description='下载并校验情感分析数据集')
    ap.add_argument('--force', action='store_true', help='强制重新下载')
    ap.add_argument('--check', action='store_true', help='只校验,不下载')
    args = ap.parse_args()

    if args.check:
        return check()

    os.makedirs(OUT_DIR, exist_ok=True)
    print('下载数据集到 %s' % OUT_DIR)
    try:
        for name in FILES:
            download(name, force=args.force)
    except Exception as exc:
        print('下载失败: %s: %s' % (type(exc).__name__, exc))
        print('提示:HuggingFace 官方域名在本机不稳定,本脚本已默认走 hf-mirror.com')
        return 2

    print()
    return check()


if __name__ == '__main__':
    sys.exit(main())
