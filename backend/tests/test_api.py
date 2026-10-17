"""
存储层与接口层测试。

用独立的临时 SQLite 库,不碰开发库;采集函数被打桩,不发真实网络请求。
"""

import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def stub_sentiment(monkeypatch):
    """默认把情感模型换成假模型。

    真模型有 400 MB、加载要好几秒,而且被 .gitignore 排除 ——
    若测试依赖它,干净检出上就会跑出不一样的结果。需要验证真实
    模型行为的用例自己再 monkeypatch 覆盖。
    """
    from app import sentiment

    class Fake:
        kind = 'stub'

        def predict(self, texts):
            return [{'label': 'neutral', 'score': 0.5,
                     'scores': {'negative': 0.25, 'positive': 0.25,
                                'neutral': 0.5}} for _ in texts]

    monkeypatch.setattr(sentiment, 'load', lambda kind=None: Fake())
    monkeypatch.setattr(sentiment, 'default_kind', lambda: 'stub')


@pytest.fixture()
def client(monkeypatch):
    """构造一个用临时库的测试客户端。"""
    tmpdir = tempfile.mkdtemp(prefix='fin-test-')
    db_path = os.path.join(tmpdir, 'test.db')
    url = 'sqlite:///' + db_path.replace('\\', '/')

    # 必须在导入 app 之前改配置,否则 engine 已绑定旧地址
    from app import config
    monkeypatch.setattr(config, 'DATABASE_URL', url)

    from app import db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url, connect_args={'check_same_thread': False})
    monkeypatch.setattr(db_module, 'engine', engine)
    monkeypatch.setattr(db_module, 'SessionLocal',
                        sessionmaker(bind=engine, autoflush=False,
                                     expire_on_commit=False))

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------- 基础

def test_health(client):
    r = client.get('/api/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'


def test_default_stocks_seeded(client):
    r = client.get('/api/stocks')
    assert r.status_code == 200
    codes = {s['code'] for s in r.json()}
    assert '600519' in codes
    assert '300750' in codes


def test_stock_counts_start_at_zero(client):
    stocks = client.get('/api/stocks').json()
    for s in stocks:
        assert s['kline_count'] == 0
        assert s['news_count'] == 0


# ---------------------------------------------------------------- 404

def test_unknown_stock_klines_404(client):
    assert client.get('/api/stocks/999999/klines').status_code == 404


def test_unknown_stock_news_404(client):
    assert client.get('/api/stocks/999999/news').status_code == 404


def test_unknown_stock_overview_404(client):
    assert client.get('/api/stocks/999999/overview').status_code == 404


# ---------------------------------------------------------------- 写入与读取

def _seed(client, monkeypatch):
    """打桩采集,写入两条行情两条新闻。"""
    from app import collector

    monkeypatch.setattr(collector, 'fetch_kline', lambda code, market='SH': [
        {'trade_date': '2026-10-12', 'open': 1.0, 'close': 2.0, 'high': 3.0,
         'low': 0.5, 'volume': 100.0, 'amount': 200.0, 'amplitude': 1.0},
        {'trade_date': '2026-10-13', 'open': 2.0, 'close': 3.0, 'high': 4.0,
         'low': 1.5, 'volume': 150.0, 'amount': 300.0, 'amplitude': 1.5},
    ])
    monkeypatch.setattr(collector, 'fetch_news_pages',
                        lambda kw, pages=1, page_size=20, sleep=0.3: [
        {'title': '测试新闻A', 'url': 'https://t/a', 'source': '来源A',
         'publish_time': '2026-10-13 10:00:00'},
        {'title': '测试新闻B', 'url': 'https://t/b', 'source': '来源B',
         'publish_time': '2026-10-12 09:00:00'},
    ])
    return client.post('/api/stocks/600519/sync')


def test_sync_inserts_data(client, monkeypatch):
    r = _seed(client, monkeypatch)
    assert r.status_code == 200
    body = r.json()
    assert body['kline_added'] == 2
    assert body['news_added'] == 2
    assert body['errors'] == []


def test_sync_is_idempotent(client, monkeypatch):
    """重复采集不应产生重复数据。"""
    _seed(client, monkeypatch)
    r2 = client.post('/api/stocks/600519/sync')
    body = r2.json()
    assert body['kline_added'] == 0
    assert body['news_added'] == 0


def test_klines_returned_ascending(client, monkeypatch):
    _seed(client, monkeypatch)
    rows = client.get('/api/stocks/600519/klines').json()
    assert len(rows) == 2
    assert rows[0]['trade_date'] == '2026-10-12'
    assert rows[1]['trade_date'] == '2026-10-13'


def test_kline_limit(client, monkeypatch):
    _seed(client, monkeypatch)
    rows = client.get('/api/stocks/600519/klines?limit=1').json()
    assert len(rows) == 1
    # limit 取最近 N 条,但仍按升序返回
    assert rows[0]['trade_date'] == '2026-10-13'


def test_news_returned_descending(client, monkeypatch):
    _seed(client, monkeypatch)
    rows = client.get('/api/stocks/600519/news').json()
    assert len(rows) == 2
    assert rows[0]['publish_time'] > rows[1]['publish_time']


def test_overview_after_sync(client, monkeypatch):
    _seed(client, monkeypatch)
    o = client.get('/api/stocks/600519/overview').json()
    assert o['name'] == '贵州茅台'
    assert o['kline_count'] == 2
    assert o['news_count'] == 2
    assert o['latest']['trade_date'] == '2026-10-13'
    assert o['latest']['close'] == 3.0
    sources = {s['source'] for s in o['news_sources']}
    assert sources == {'来源A', '来源B'}


def test_overview_latest_change_pct(client, monkeypatch):
    """涨跌幅应由 service 层按前收计算。"""
    _seed(client, monkeypatch)
    o = client.get('/api/stocks/600519/overview').json()
    # 前收 2.0 -> 收 3.0,涨幅 50%
    assert o['latest']['change_pct'] == 50.0


def test_sync_records_collector_error(client, monkeypatch):
    """采集失败应被记录,而不是让整个请求崩掉。"""
    from app import collector

    def boom(*a, **kw):
        raise RuntimeError('模拟网络故障')

    monkeypatch.setattr(collector, 'fetch_kline', boom)
    monkeypatch.setattr(collector, 'fetch_news_pages', boom)

    r = client.post('/api/stocks/600519/sync')
    assert r.status_code == 200
    body = r.json()
    assert len(body['errors']) == 2
    assert body['kline_added'] == 0


# ---------------------------------------------------------------- 情感分析接口

def test_sentiment_info(client):
    """模型状态接口:即使没训练过模型也必须返回 200。"""
    r = client.get('/api/sentiment/info')
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body['available'], list)
    assert set(body['labels']) == {'negative', 'positive', 'neutral'}


def test_sentiment_analyze_requires_texts(client):
    """texts 缺失或为空应返回 400,而不是 500。"""
    assert client.post('/api/sentiment/analyze', json={}).status_code == 400
    assert client.post('/api/sentiment/analyze',
                       json={'texts': []}).status_code == 400
    assert client.post('/api/sentiment/analyze',
                       json={'texts': 'not-a-list'}).status_code == 400


def test_sentiment_analyze_unknown_model(client):
    """指定不存在的模型应 400。"""
    r = client.post('/api/sentiment/analyze',
                    json={'texts': ['测试'], 'model': 'nope'})
    assert r.status_code == 400


def test_sentiment_analyze_returns_results(client):
    """有模型时返回逐条结果;没有则 503(两种都算通过)。"""
    r = client.post('/api/sentiment/analyze', json={'texts': ['明天必涨停']})
    if r.status_code == 503:
        assert '模型' in r.json()['detail']
        return
    assert r.status_code == 200
    body = r.json()
    assert len(body['results']) == 1
    assert body['results'][0]['label'] in ('negative', 'positive', 'neutral')
    assert 0.0 <= body['results'][0]['score'] <= 1.0


def test_sentiment_analyze_without_model_503(client, monkeypatch):
    """模型缺失时明确报 503 并说明怎么办。"""
    from app import sentiment
    monkeypatch.setattr(sentiment, 'predict', lambda texts, kind=None: None)
    r = client.post('/api/sentiment/analyze', json={'texts': ['测试']})
    assert r.status_code == 503


def test_stock_sentiment_empty(client):
    """没有标注数据时返回 zero=True,前端据此提示先采集。"""
    r = client.get('/api/stocks/600519/sentiment')
    assert r.status_code == 200
    body = r.json()
    assert body['zero'] is True
    assert body['total'] == 0
    assert body['counts'] == {'positive': 0, 'neutral': 0, 'negative': 0}
    assert body['ratio']['positive'] == 0.0


def test_stock_sentiment_unknown_404(client):
    assert client.get('/api/stocks/999999/sentiment').status_code == 404


def test_stock_sentiment_counts(client, monkeypatch):
    """有标注数据时统计分布与日线聚合都要对。"""
    _seed(client, monkeypatch)

    # 直接改库里的 sentiment 字段(采集路径已由 test_sync_* 覆盖)
    from app.db import SessionLocal
    from app import models
    db = SessionLocal()
    try:
        rows = db.query(models.News).order_by(models.News.id).all()
        rows[0].sentiment = 'positive'
        rows[0].sentiment_score = 0.95
        rows[1].sentiment = 'negative'
        rows[1].sentiment_score = 0.88
        db.commit()
    finally:
        db.close()

    body = client.get('/api/stocks/600519/sentiment').json()
    assert body['zero'] is False
    assert body['total'] == 2
    assert body['counts']['positive'] == 1
    assert body['counts']['negative'] == 1
    assert body['counts']['neutral'] == 0
    assert body['ratio']['positive'] == 0.5
    assert len(body['daily']) == 2
    dates = [d['date'] for d in body['daily']]
    assert dates == sorted(dates)


def test_stock_sentiment_ignores_unlabelled(client, monkeypatch):
    """未标注(sentiment='')的新闻不进统计,否则分布会失真。"""
    from app import sentiment as sent_mod
    monkeypatch.setattr(sent_mod, 'load', lambda kind=None: None)

    _seed(client, monkeypatch)
    body = client.get('/api/stocks/600519/sentiment').json()
    assert body['total'] == 0
    assert body['zero'] is True


def test_sync_annotates_sentiment(client, monkeypatch):
    """采集流程应给新闻打上情感标签。"""
    from app import sentiment as sent_mod

    class FakeModel:
        kind = 'fake'

        def predict(self, texts):
            return [{'label': 'positive', 'score': 0.9,
                     'scores': {'negative': 0.05, 'positive': 0.9,
                                'neutral': 0.05}} for _ in texts]

    monkeypatch.setattr(sent_mod, 'load', lambda kind=None: FakeModel())

    r = _seed(client, monkeypatch)
    body = r.json()
    assert body['sentiment_added'] == 2
    assert body['sentiment_model'] == 'fake'

    s = client.get('/api/stocks/600519/sentiment').json()
    assert s['counts']['positive'] == 2


def test_sync_without_model_still_works(client, monkeypatch):
    """没有模型时采集照常成功,只是标注数为 0 —— 不能因此报错。"""
    from app import sentiment as sent_mod
    monkeypatch.setattr(sent_mod, 'load', lambda kind=None: None)

    body = _seed(client, monkeypatch).json()
    assert body['news_added'] == 2
    assert body['sentiment_added'] == 0
    assert body['errors'] == []


def test_sync_sentiment_failure_isolated(client, monkeypatch):
    """情感分析崩了不能连累采集。"""
    from app import sentiment as sent_mod

    def boom(kind=None):
        raise RuntimeError('模型损坏')

    monkeypatch.setattr(sent_mod, 'load', boom)

    body = _seed(client, monkeypatch).json()
    assert body['news_added'] == 2
    assert any('sentiment' in e for e in body['errors'])


# --------------------------------------------------- 情感—股价关联分析接口

def _seed_returns(client, monkeypatch):
    """写入一批带情感的新闻 + 足够长的行情,用于关联分析接口。

    构造思路:情感越高、次日涨得越多,这样相关系数应该显著为正,
    断言才有明确的方向可验。

    注意 sync_stock 会用 compute_change_pct 从收盘价**重算**涨跌幅,
    所以这里必须由目标收益率反推收盘价,直接写 change_pct 会被覆盖。
    """
    from app import collector

    klines = []
    news = []
    close = 100.0
    # 10 个交易日,收益率从 -4.5% 递增到 +4.5%,与情感同向
    for i in range(10):
        day = '2026-03-%02d' % (i + 2)  # 03-02 .. 03-11,全在周内
        ret = -4.5 + i
        klines.append({
            'trade_date': day, 'open': close, 'close': close * (1 + ret / 100),
            'high': close * 1.01, 'low': close * 0.99,
            'volume': 100.0, 'amount': 200.0, 'amplitude': 1.0,
        })
        close = close * (1 + ret / 100)
        label = 'positive' if i >= 5 else 'negative'
        news.append({
            'title': '新闻%d' % i, 'url': 'https://r/%d' % i,
            'source': '来源', 'publish_time': day + ' 15:00:00',
            '_label': label,
        })

    monkeypatch.setattr(collector, 'fetch_kline',
                        lambda code, market='SH': [dict(k) for k in klines])
    monkeypatch.setattr(collector, 'fetch_news_pages',
                        lambda kw, pages=1, page_size=20, sleep=0.3: [
        {k: v for k, v in n.items() if k != '_label'} for n in news])

    from app import sentiment as sent_mod
    labels = {n['title']: n['_label'] for n in news}

    class FakeModel:
        kind = 'fake'

        def predict(self, texts):
            return [{'label': labels.get(t, 'neutral'), 'score': 0.9,
                     'scores': {'negative': 0.05, 'positive': 0.9,
                                'neutral': 0.05}} for t in texts]

    monkeypatch.setattr(sent_mod, 'load', lambda kind=None: FakeModel())
    return client.post('/api/stocks/600519/sync')


def test_returns_404_for_unknown_stock(client):
    assert client.get('/api/stocks/999999/returns').status_code == 404


def test_returns_empty_when_no_data(client):
    """没采过数据时应返回空统计,而不是报错。"""
    r = client.get('/api/stocks/600519/returns')
    assert r.status_code == 200
    body = r.json()
    assert body['stats']['n'] == 0
    assert body['pairs'] == []


def test_returns_after_sync(client, monkeypatch):
    _seed_returns(client, monkeypatch)
    r = client.get('/api/stocks/600519/returns')
    assert r.status_code == 200
    body = r.json()

    assert body['news_total'] == 10
    assert body['kline_total'] == 10
    # 每个有情感的日子都要有样本,但最后一天没有"下一个交易日"所以少一条
    assert body['stats']['n'] == 9
    assert len(body['pairs']) == 9

    # 情感与次日收益同向构造 -> 相关系数应为正
    assert body['stats']['pearson'] is not None
    assert body['stats']['pearson'] > 0.5


def test_returns_lag_zero_is_allowed(client, monkeypatch):
    _seed_returns(client, monkeypatch)
    r = client.get('/api/stocks/600519/returns?lag=0')
    assert r.status_code == 200
    assert r.json()['stats']['lag'] == 0


def test_returns_rejects_out_of_range_lag(client):
    assert client.get('/api/stocks/600519/returns?lag=9').status_code == 422
    assert client.get('/api/stocks/600519/returns?lag=-1').status_code == 422


def test_returns_min_news_filter(client, monkeypatch):
    """min_news 高于当天条数时,样本应被过滤掉。"""
    _seed_returns(client, monkeypatch)
    body = client.get('/api/stocks/600519/returns?min_news=2').json()
    assert body['stats']['n'] == 0


def test_sync_news_pages_parameter_passed(client, monkeypatch):
    """news_pages 参数应真的传到采集层,否则翻页开关是假的。"""
    from app import collector

    seen = {}

    def fake_pages(kw, pages=1, page_size=20, sleep=0.3):
        seen['pages'] = pages
        seen['page_size'] = page_size
        return []

    monkeypatch.setattr(collector, 'fetch_kline', lambda code, market='SH': [])
    monkeypatch.setattr(collector, 'fetch_news_pages', fake_pages)

    client.post('/api/stocks/600519/sync?news_pages=4&news_size=30')
    assert seen['pages'] == 4
    assert seen['page_size'] == 30


def test_sync_news_pages_out_of_range_rejected(client):
    assert client.post('/api/stocks/600519/sync?news_pages=0').status_code == 422
    assert client.post('/api/stocks/600519/sync?news_pages=101').status_code == 422
