"""
预训练模型下载器 —— 把 HuggingFace 模型拉到工作区内,供离线使用。

用法:
    .python\\python.exe tools\\fetch_model.py                # 下默认模型
    .python\\python.exe tools\\fetch_model.py --list         # 列出可选模型
    .python\\python.exe tools\\fetch_model.py --check        # 只校验已下载的模型
    .python\\python.exe tools\\fetch_model.py --repo hfl/rbt3

退出码 0 = 成功;非 0 = 失败。

为什么不能直接用 from_pretrained('bert-base-chinese'):
------------------------------------------------------
本机踩到三个坑,每个都会让"标准用法"失败:

  坑一:huggingface.co 直连不通。
        本机 hosts 被本机加速工具接管,github.com / huggingface.co 等域名
        被解析到 127.0.0.1。必须走 hf-mirror.com(HF_ENDPOINT)。

  坑二:xet 传输协议在镜像上不可用。
        huggingface_hub >= 1.x 默认走 xet,会请求
        /api/models/<repo>/xet-read-token/<sha>,镜像返回 404。
        必须设 HF_HUB_DISABLE_XET=1 退回普通 HTTP。

  坑三:默认缓存目录不可写。
        huggingface_hub 默认缓存到 C:\\Users\\<user>\\.cache\\huggingface,
        DSH 沙箱下该目录不可写,会刷一堆
        "Ignored error while writing commit hash ... [WinError 5] 拒绝访问"。
        必须把 HF_HOME 指到工作区内。

另外 HF 仓库同时放了 pytorch_model.bin / model.safetensors / flax_model.msgpack /
tf_model.h5 四份等价的权重(每份 ~400 MB)。只取 PyTorch 需要的那一份,
否则白白多下 1.2 GB。
"""

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)

# 必须在 import huggingface_hub 之前设好,否则不生效
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('HF_HOME', os.path.join(_WS, '.tmp', 'hf-home'))

MODELS_DIR = os.path.join(_WS, 'models')

# 只要 PyTorch 权重 + 分词器;跳过 flax/tf 的重复权重
META = ['config.json', 'tokenizer.json', 'tokenizer_config.json',
        'vocab.txt', 'special_tokens_map.json', 'added_tokens.json']

# 权重文件按优先级排列。**同一仓库只会取其中一个** —— 两个都列进
# allow_patterns 会让 HF 把两份等价权重全下下来(BERT 上是白下 392 MB)。
WEIGHTS = ['model.safetensors', 'pytorch_model.bin']

# 兼容旧名字
ALLOW = META + WEIGHTS

# 候选模型:名称 -> (仓库, 说明)
CATALOG = {
    'bert-base-chinese': (
        'bert-base-chinese',
        'Google 原版中文 BERT,102M 参数,392 MB。通用基线,最稳妥'),
    'rbt3': (
        'hfl/rbt3',
        '哈工大 3 层 RoBERTa,体积约为 BERT 的 1/4,训练快,适合快速实验'),
    'chinese-roberta-wwm-ext': (
        'hfl/chinese-roberta-wwm-ext',
        '哈工大全词掩码 RoBERTa,102M 参数。中文任务上通常优于原版 BERT'),
}

DEFAULT = 'bert-base-chinese'


def local_dir(name):
    return os.path.join(MODELS_DIR, name)


def pick_weight(repo):
    """查出仓库里实际存在的权重文件,按 WEIGHTS 优先级返回第一个。

    BERT 这类仓库同时放了 model.safetensors 和 pytorch_model.bin(内容等价)。
    先问一次文件清单再决定下哪个,避免把两份都拉下来。
    """
    try:
        from huggingface_hub import HfApi
        siblings = HfApi().model_info(repo).siblings or []
        names = {s.rfilename for s in siblings}
    except Exception as exc:
        # 查不到清单就退化成"两个都允许",宁可多下也不要下不到
        print('[warn] 无法获取 %s 的文件清单(%s),将尝试全部权重格式'
              % (repo, type(exc).__name__))
        return list(WEIGHTS)

    for w in WEIGHTS:
        if w in names:
            return [w]
    return list(WEIGHTS)


def verify(name, quiet=False):
    """校验模型可离线加载并跑一次前向。返回 (ok, detail)。"""
    d = local_dir(name)
    if not os.path.isdir(d):
        return False, '目录不存在: %s' % d

    need = ['config.json', 'tokenizer.json', 'vocab.txt']
    weights = [f for f in ('model.safetensors', 'pytorch_model.bin')
               if os.path.exists(os.path.join(d, f))]
    missing = [f for f in need if not os.path.exists(os.path.join(d, f))]
    if missing:
        return False, '缺少文件: %s' % ', '.join(missing)
    if not weights:
        return False, '缺少权重文件(model.safetensors 或 pytorch_model.bin)'

    size = sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d)
               if os.path.isfile(os.path.join(d, f)))
    try:
        os.environ['HF_HUB_OFFLINE'] = '1'
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        tok = AutoTokenizer.from_pretrained(d)
        model = AutoModelForSequenceClassification.from_pretrained(d, num_labels=3)
        model.eval()
        enc = tok(['测试文本'], padding=True, truncation=True,
                  max_length=32, return_tensors='pt')
        with torch.no_grad():
            logits = model(**enc).logits
        n_params = sum(p.numel() for p in model.parameters())
        return True, ('%d 参数 / %.1f MB / logits %s / vocab %d'
                      % (n_params, size / 1048576, tuple(logits.shape),
                         tok.vocab_size))
    except Exception as exc:
        return False, '%s: %s' % (type(exc).__name__, str(exc)[:120])


def fetch(name, repo=None, workers=4):
    """下载模型到 models/<name>/。返回 (ok, detail)。"""
    repo = repo or CATALOG.get(name, (name, ''))[0]
    dest = local_dir(name)
    print('[fetch] %s  ->  %s' % (repo, dest))
    print('[fetch] 镜像 %s  (xet 已禁用)' % os.environ['HF_ENDPOINT'])
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return False, 'huggingface_hub 未安装,先跑: .python\\python.exe .pysandbox\\pipp.py install huggingface_hub'

    t = time.time()
    weight = pick_weight(repo)
    print('[fetch] 权重: %s' % ', '.join(weight))
    try:
        path = snapshot_download(repo, local_dir=dest,
                                 allow_patterns=META + weight,
                                 max_workers=workers)
    except Exception as exc:
        return False, '%s: %s' % (type(exc).__name__, str(exc)[:200])

    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(dest) for f in fs)
    return True, '%s  (%.1f MB, %.1fs)' % (path, size / 1048576, time.time() - t)


def main():
    ap = argparse.ArgumentParser(
        description='把 HuggingFace 预训练模型拉到工作区(离线可用)')
    ap.add_argument('--repo', help='直接指定 HF 仓库名,如 hfl/rbt3')
    ap.add_argument('--name', help='本地目录名(默认取仓库末段)')
    ap.add_argument('--list', action='store_true', help='列出可选模型')
    ap.add_argument('--check', action='store_true', help='只校验已下载的模型')
    ap.add_argument('--workers', type=int, default=4, help='并发下载数(默认 4)')
    args = ap.parse_args()

    if args.list:
        print('可选模型:')
        for name, (repo, desc) in CATALOG.items():
            mark = ' [默认]' if name == DEFAULT else ''
            got = '已下载' if os.path.isdir(local_dir(name)) else '未下载'
            print('  %-24s %-30s %s%s' % (name, repo, desc, mark))
            print('  %-24s %s' % ('', '状态: %s' % got))
        return 0

    if args.check:
        print('=== 模型自检 ===')
        bad = 0
        for name in CATALOG:
            if not os.path.isdir(local_dir(name)):
                print('  [SKIP] %-24s 未下载' % name)
                continue
            ok, detail = verify(name)
            print('  [%s] %-24s %s' % ('PASS' if ok else 'FAIL', name, detail))
            if not ok:
                bad += 1
        if bad:
            print('RESULT: %d 个模型校验失败' % bad)
            return 1
        print('RESULT: 全部通过')
        return 0

    if args.repo:
        name = args.name or args.repo.split('/')[-1]
    elif args.name:
        name = args.name
    else:
        name = DEFAULT
    if name not in CATALOG and not args.repo:
        print('未知模型 %s,用 --list 看可选项' % name)
        return 2

    ok, detail = fetch(name, repo=args.repo, workers=args.workers)
    if not ok:
        print('[FAIL] %s' % detail)
        return 1
    print('[ok] 已下载: %s' % detail)

    print()
    ok, detail = verify(name)
    print('  [%s] 加载校验  %s' % ('PASS' if ok else 'FAIL', detail))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
