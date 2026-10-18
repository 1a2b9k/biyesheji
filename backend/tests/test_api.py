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

    # mkdtemp 建的目录不在 pytest 的 tmp_path 体系里,不主动删就会
    # 一直堆在工作区 .tmp/ 下(每次跑留一个 36 KB 的 test.db)。
    engine.dispose()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- 基础

def test_health(client):
    r = client.get('/api/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'


def test_health_version_matches_readme(client):
    """`app.version` 与 README 头部标的版本必须同一条线。

    这两处各写一遍,很容易只改一处:本次复查前 README 已到 v0.5,
    `main.py` 还停在 0.2.0,而 `/api/health` 直接把后者吐给调用方。
    """
    from app.main import app

    readme = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), 'README.md')
    assert 'v0.5' in ''.join(open(readme, encoding='utf-8').readlines()[:5])
    assert app.version.startswith('0.5'), app.version
    assert client.get('/api/health').json()['version'] == app.version


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


def test_stock_counts_reflect_written_rows(client, monkeypatch):
    """计数必须反映真实入库量,不能一律是 0。"""
    _seed(client, monkeypatch)
    by_code = {s['code']: s for s in client.get('/api/stocks').json()}
    assert by_code['600519']['kline_count'] == 2
    assert by_code['600519']['news_count'] == 2
    # 没采集过的股票仍是 0,不能张冠李戴
    assert by_code['300750']['news_count'] == 0


def test_list_stocks_does_not_scale_queries_with_stock_count(client):
    """`/api/stocks` 的查询次数不能随股票数增长。

    早先每只股票各发两次 count(2N 次往返),13 只就是 26 次。
    改成两条 group by 后应该是固定 3 条 SELECT(股票表 + 两张计数)。
    这里用 SQLAlchemy 的 before_cursor_execute 数真实发出去的语句。
    """
    from sqlalchemy import event

    from app import db as db_module

    seen = []

    def _count(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(db_module.engine, 'before_cursor_execute', _count)
    try:
        r = client.get('/api/stocks')
    finally:
        event.remove(db_module.engine, 'before_cursor_execute', _count)

    selects = [s for s in seen if s.strip().upper().startswith('SELECT')]
    assert r.status_code == 200
    assert len(r.json()) >= 2, '至少要有两只股票,否则这条测试没意义'
    # 股票表 1 条 + 行情分组 1 条 + 新闻分组 1 条 = 3,与股票数无关
    assert len(selects) <= 3, '查询数 %d 条,疑似仍有 N+1:\n%s' % (
        len(selects), '\n'.join(selects))


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


def test_kline_limit_allows_full_history(client):
    """上限必须能覆盖最长的股票历史,否则老数据永远取不到。

    实测平安银行(000001)有 8497 个交易日,原来的上限 5000 会让
    最早 3497 条永远取不到。这里不真取 8000 条数据,只验证参数
    校验不把 8000 拒掉 —— 被拒会返回 422。
    """
    r = client.get('/api/stocks/600519/klines?limit=8000')
    assert r.status_code == 200


def test_kline_limit_rejects_absurd_value(client):
    """上限放宽了,但仍要有边界,避免一次把整库拖出来。"""
    r = client.get('/api/stocks/600519/klines?limit=20001')
    assert r.status_code == 422


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
    assert o['news_source_count'] == 2


def test_overview_source_count_is_not_capped_at_ten(client, monkeypatch):
    """来源家数必须单独数。

    `news_sources` 只返回前 10 家,若前端拿 len(news_sources) 当家数,
    600519 的 52 家会被说成 10 家;同理把明细的 count 相加会少报条数。
    """
    _seed(client, monkeypatch)

    from datetime import datetime

    from app import db as db_module
    from app import models

    with db_module.SessionLocal() as s:
        for i in range(12):
            s.add(models.News(
                code='600519', title=f'补的第{i}条', url=f'https://t/{i}',
                source=f'媒体{i}', publish_time=datetime(2026, 10, 12, 9, 0, 0),
                sentiment='', sentiment_score=None,
                fetched_at=datetime(2026, 10, 12, 10, 0, 0),
            ))
        s.commit()

    o = client.get('/api/stocks/600519/overview').json()
    # 明细仍只有 10 条(2 家已有 + 12 家新增 = 14 家,取前 10)
    assert len(o['news_sources']) == 10
    # 但家数与条数是全的
    assert o['news_source_count'] == 14
    assert o['news_count'] == 14
    listed = sum(s['count'] for s in o['news_sources'])
    assert listed < o['news_count']


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
    """texts 缺失 / 为空 / 类型不对都要被拒,而不是 500。

    改成 Pydantic 模型后由 FastAPI 统一校验,状态码是 422
    (原来是手写 if 抛的 400)。两种都接受:关键是不能 500,
    也不能带着空列表往下跑。
    """
    for body in ({}, {'texts': []}, {'texts': 'not-a-list'}):
        code = client.post('/api/sentiment/analyze', json=body).status_code
        assert code in (400, 422), body


def test_sentiment_analyze_rejects_too_many_texts(client):
    """超过 200 条要明确报错,不能静默截断。

    早先 `texts[:200]` 会悄悄丢掉多余的部分,调用方拿到 200 条结果
    还以为全都分析过了。
    """
    from app.main import MAX_ANALYZE_TEXTS

    ok = client.post('/api/sentiment/analyze',
                     json={'texts': ['测试'] * MAX_ANALYZE_TEXTS})
    assert ok.status_code != 422, '正好 200 条不该被拒'

    too_many = client.post('/api/sentiment/analyze',
                           json={'texts': ['测试'] * (MAX_ANALYZE_TEXTS + 1)})
    assert too_many.status_code == 422
    assert str(MAX_ANALYZE_TEXTS) in too_many.text


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


def test_sync_commit_failure_does_not_report_writes(client, monkeypatch):
    """commit 失败时不能报"新增 N 条" —— 回滚了就是一条都没写。

    早先 sync_stock 无条件 commit:commit 抛异常会直接冒到接口变成 500,
    调用方看不到 errors;若换个写法只 catch 不归零,就会报出根本没落库
    的条数。这里把 commit 打成必然失败,断言接口仍 200、errors 里记了
    commit,且三个 added 全为 0。
    """
    from sqlalchemy.orm import Session

    calls = {'commit': 0}
    real_commit = Session.commit

    def broken_commit(self):
        calls['commit'] += 1
        raise RuntimeError('database is locked')

    monkeypatch.setattr(Session, 'commit', broken_commit)

    body = _seed(client, monkeypatch).json()
    assert calls['commit'] >= 1
    assert any(e.startswith('commit:') for e in body['errors']), body
    assert body['kline_added'] == 0
    assert body['news_added'] == 0
    assert body['sentiment_added'] == 0

    # 恢复后清理:后面还有用例要用同一个 engine
    monkeypatch.setattr(Session, 'commit', real_commit)


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
