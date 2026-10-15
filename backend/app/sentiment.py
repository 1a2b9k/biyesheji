"""
情感分析推理模块 —— 加载训练好的模型,给文本打情感标签。

用法(在代码里):
    from app import sentiment
    sentiment.predict(['明天必涨停', '又被套了'])

设计要点:
  1. **懒加载 + 单例**: BERT 权重 400 MB,加载要几秒。不能在 import 时加载,
     否则任何用到 app 的地方(包括跑测试)都会被拖慢。
  2. **缺模型不报错**: 模型文件被 .gitignore 排除,干净检出里没有。
     此时 predict() 返回 None 而不是抛异常,让系统退化成 v0.1 的样子,
     而不是整个后端起不来。
  3. **两条路线可切换**: 环境变量 FIN_SENTIMENT_MODEL 选 tfidf 或 bert。
"""

import json
import os
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_BACKEND)

MODELS_DIR = os.path.join(_ROOT, 'models')

# 标签编号 -> 名称(与训练脚本一致)
LABEL_NAMES = {0: 'negative', 1: 'positive', 2: 'neutral'}

_lock = threading.Lock()
_cache = {}


class SentimentModel:
    """已加载的情感分析模型。"""

    def __init__(self, kind, label_names, predict_fn):
        self.kind = kind
        self.label_names = label_names
        self._predict_fn = predict_fn

    def predict(self, texts):
        """批量预测。返回 [{'label':..., 'score':..., 'scores':{...}}, ...]。"""
        if not texts:
            return []
        return self._predict_fn(list(texts))


def model_dir(kind, task='3class'):
    return os.path.join(MODELS_DIR, 'sentiment-%s-%s' % (kind, task))


def available():
    """列出本机已训练好的模型。返回 ['tfidf', 'bert'] 的子集。"""
    out = []
    if os.path.isfile(os.path.join(model_dir('tfidf'), 'model.joblib')):
        out.append('tfidf')
    if os.path.isfile(os.path.join(model_dir('bert'), 'config.json')):
        out.append('bert')
    return out


def default_kind():
    """默认用哪个模型。

    优先 BERT(效果更好),没训练过就退回 TF-IDF,都没有则返回 None。
    """
    env = os.environ.get('FIN_SENTIMENT_MODEL')
    if env:
        return env if env in available() else None
    av = available()
    for k in ('bert', 'tfidf'):
        if k in av:
            return k
    return None


# ------------------------------------------------------------------ 加载

def _load_tfidf(d):
    import jieba
    import joblib

    jieba.setLogLevel(60)
    bundle = joblib.load(os.path.join(d, 'model.joblib'))
    vec = bundle['vectorizer']
    clf = bundle['classifier']
    names = bundle.get('label_names') or ['negative', 'positive', 'neutral']

    def fn(texts):
        import re
        seg = [' '.join(jieba.lcut(re.sub(r'\s+', '', t))) for t in texts]
        x = vec.transform(seg)
        probs = clf.predict_proba(x)
        classes = list(clf.classes_)
        out = []
        for row in probs:
            idx = int(row.argmax())
            out.append({
                'label': names[classes[idx]],
                'score': round(float(row[idx]), 4),
                'scores': {names[c]: round(float(p), 4)
                           for c, p in zip(classes, row)},
            })
        return out

    return SentimentModel('tfidf', names, fn)


def _load_bert(d):
    import torch
    from transformers import (AutoModelForSequenceClassification,
                              AutoTokenizer)

    # 模型在本机,不需要联网
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

    tok = AutoTokenizer.from_pretrained(d)
    model = AutoModelForSequenceClassification.from_pretrained(d)

    label_file = os.path.join(d, 'label_names.json')
    if os.path.isfile(label_file):
        with open(label_file, encoding='utf-8') as fh:
            names = json.load(fh)
    else:
        names = ['negative', 'positive', 'neutral']

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model.to(device).eval()

    def fn(texts):
        enc = tok(texts, padding=True, truncation=True,
                  max_length=64, return_tensors='pt')
        with torch.no_grad():
            logits = model(input_ids=enc['input_ids'].to(device),
                           attention_mask=enc['attention_mask'].to(device)).logits
            probs = torch.softmax(logits, dim=-1).cpu().tolist()
        out = []
        for row in probs:
            idx = int(max(range(len(row)), key=lambda i: row[i]))
            out.append({
                'label': names[idx],
                'score': round(float(row[idx]), 4),
                'scores': {n: round(float(p), 4) for n, p in zip(names, row)},
            })
        return out

    return SentimentModel('bert', names, fn)


def load(kind=None):
    """加载模型(带缓存)。没有可用模型时返回 None。"""
    kind = kind or default_kind()
    if kind is None:
        return None
    if kind in _cache:
        return _cache[kind]

    with _lock:
        if kind in _cache:          # 双检,避免并发重复加载
            return _cache[kind]
        d = model_dir(kind)
        if kind == 'bert':
            if not os.path.isfile(os.path.join(d, 'config.json')):
                return None
            m = _load_bert(d)
        elif kind == 'tfidf':
            if not os.path.isfile(os.path.join(d, 'model.joblib')):
                return None
            m = _load_tfidf(d)
        else:
            raise ValueError('未知模型类型: %s' % kind)
        _cache[kind] = m
        return m


def predict(texts, kind=None):
    """预测一批文本。没有模型时返回 None(调用方据此降级)。"""
    m = load(kind)
    if m is None:
        return None
    return m.predict(texts)


def info():
    """当前模型状态,供 /api/sentiment/info 使用。"""
    av = available()
    kind = default_kind()
    out = {'available': av, 'active': kind, 'labels': list(LABEL_NAMES.values())}
    if kind:
        d = model_dir(kind)
        metrics = os.path.join(_ROOT, 'data', 'experiments',
                               '%s-3class.json' % kind)
        if os.path.isfile(metrics):
            with open(metrics, encoding='utf-8') as fh:
                m = json.load(fh)
            out['metrics'] = {
                'accuracy': m.get('accuracy'),
                'macro_f1': m.get('macro_f1'),
                'n_test': m.get('n_test'),
            }
        out['model_path'] = os.path.relpath(d, _ROOT).replace('\\', '/')
    return out
