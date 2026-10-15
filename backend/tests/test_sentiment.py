"""
情感分析模块测试。

原则:
  - **不加载真实模型**。BERT 权重 400 MB、加载数秒,放进单元测试会让
    每次跑测试都慢十几秒。这里用假模型验证"调用链是否正确",
    真实模型的准确率由 data/experiments/*.json 记录,由 tools/ 下的
    训练脚本负责产出。
  - **覆盖降级路径**。模型文件被 .gitignore 排除,干净检出里没有,
    系统必须能不带情感分析正常跑起来 —— 这条路径比正常路径更需要测。
"""

import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_BACKEND = os.path.join(_REPO_ROOT, 'backend')
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app import sentiment  # noqa: E402


class FakeModel:
    """假模型:按关键词给标签,行为完全可预测。"""

    kind = 'fake'

    def __init__(self):
        self.label_names = ['negative', 'positive', 'neutral']
        self.calls = []

    def predict(self, texts):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            if '涨' in t or '冲' in t:
                label = 'positive'
            elif '跌' in t or '套' in t:
                label = 'negative'
            else:
                label = 'neutral'
            out.append({'label': label, 'score': 0.9,
                        'scores': {'negative': 0.05, 'positive': 0.05,
                                   'neutral': 0.9}})
        return out


@pytest.fixture()
def fake(monkeypatch):
    """把 sentiment.load 换成假模型,并清掉缓存。"""
    m = FakeModel()
    monkeypatch.setattr(sentiment, 'load', lambda kind=None: m)
    monkeypatch.setattr(sentiment, 'default_kind', lambda: 'fake')
    sentiment._cache.clear()
    yield m
    sentiment._cache.clear()


# ---------------------------------------------------------------- 标签体系

def test_label_names_are_three_classes():
    """标签编号与训练脚本必须一致:0 负 / 1 正 / 2 中。"""
    assert sentiment.LABEL_NAMES == {0: 'negative', 1: 'positive',
                                     2: 'neutral'}


def test_model_dir_layout():
    """模型目录命名必须与训练脚本写出的目录一致。"""
    d = sentiment.model_dir('bert')
    assert d.endswith(os.path.join('models', 'sentiment-bert-3class'))
    assert sentiment.model_dir('tfidf').endswith(
        os.path.join('models', 'sentiment-tfidf-3class'))


# ---------------------------------------------------------------- 可用性

def test_available_returns_list():
    """available() 永远返回列表,即使一个模型都没训练。"""
    assert isinstance(sentiment.available(), list)


def test_default_kind_respects_env(monkeypatch):
    """环境变量能强制指定模型,但只能指定真的存在的。"""
    monkeypatch.setenv('FIN_SENTIMENT_MODEL', 'tfidf')
    monkeypatch.setattr(sentiment, 'available', lambda: ['tfidf', 'bert'])
    assert sentiment.default_kind() == 'tfidf'


def test_default_kind_rejects_unknown_env(monkeypatch):
    """指定了不存在的模型应返回 None,而不是让调用方拿到坏名字。"""
    monkeypatch.setenv('FIN_SENTIMENT_MODEL', 'nonexistent')
    monkeypatch.setattr(sentiment, 'available', lambda: ['bert'])
    assert sentiment.default_kind() is None


def test_default_kind_prefers_bert(monkeypatch):
    """两个模型都在时优先 BERT(准确率更高)。"""
    monkeypatch.delenv('FIN_SENTIMENT_MODEL', raising=False)
    monkeypatch.setattr(sentiment, 'available', lambda: ['tfidf', 'bert'])
    assert sentiment.default_kind() == 'bert'


def test_default_kind_falls_back_to_tfidf(monkeypatch):
    monkeypatch.delenv('FIN_SENTIMENT_MODEL', raising=False)
    monkeypatch.setattr(sentiment, 'available', lambda: ['tfidf'])
    assert sentiment.default_kind() == 'tfidf'


def test_default_kind_none_when_nothing_available(monkeypatch):
    monkeypatch.delenv('FIN_SENTIMENT_MODEL', raising=False)
    monkeypatch.setattr(sentiment, 'available', lambda: [])
    assert sentiment.default_kind() is None


# ---------------------------------------------------------------- 降级路径

def test_predict_returns_none_without_model(monkeypatch):
    """没有模型时必须返回 None,而不是抛异常。

    这是"干净检出也能启动"的关键:模型被 .gitignore 排除,
    别人克隆下来是没训练过的。
    """
    monkeypatch.setattr(sentiment, 'load', lambda kind=None: None)
    assert sentiment.predict(['随便一句话']) is None


def test_info_works_without_model(monkeypatch):
    """info() 在没模型时也要能返回,供前端显示状态。"""
    monkeypatch.setattr(sentiment, 'available', lambda: [])
    monkeypatch.setattr(sentiment, 'default_kind', lambda: None)
    i = sentiment.info()
    assert i['available'] == []
    assert i['active'] is None
    assert 'negative' in i['labels']
    assert 'metrics' not in i


def test_info_includes_metrics_when_trained():
    """训练过就应带上准确率,前端直接显示,不用再算。"""
    if 'bert' not in sentiment.available():
        pytest.skip('本机未训练 BERT 模型')
    i = sentiment.info()
    assert i['active'] in ('bert', 'tfidf')
    assert 'metrics' in i
    assert 0.0 <= i['metrics']['accuracy'] <= 1.0
    assert i['metrics']['n_test'] > 0


# ---------------------------------------------------------------- 推理

def test_predict_empty_list():
    """空输入不该触发模型加载。"""
    assert sentiment.predict([]) == []


def test_predict_uses_model(fake):
    r = sentiment.predict(['明天必涨停', '又被套了', '今天天气不错'])
    assert [x['label'] for x in r] == ['positive', 'negative', 'neutral']
    assert len(fake.calls) == 1
    assert len(fake.calls[0]) == 3


def test_predict_result_shape(fake):
    r = sentiment.predict(['测试'])
    assert set(r[0]) == {'label', 'score', 'scores'}
    assert 0.0 <= r[0]['score'] <= 1.0


def test_load_is_cached(monkeypatch):
    """同一模型只加载一次 —— BERT 加载要好几秒。"""
    calls = []

    def fake_load(d):
        calls.append(d)
        return FakeModel()

    monkeypatch.setattr(sentiment, '_load_tfidf', fake_load)
    monkeypatch.setattr(sentiment, 'available', lambda: ['tfidf'])
    sentiment._cache.clear()
    sentiment.load('tfidf')
    sentiment.load('tfidf')
    sentiment.load('tfidf')
    sentiment._cache.clear()
    assert len(calls) == 1


def test_load_unknown_kind_raises(monkeypatch):
    monkeypatch.setattr(sentiment, 'available', lambda: ['tfidf'])
    with pytest.raises(ValueError):
        sentiment.load('nope')
