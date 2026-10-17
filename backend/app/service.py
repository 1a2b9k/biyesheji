"""业务层:把采集到的数据写入数据库(去重、幂等)。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import collector, models, sentiment


def upsert_stock(db: Session, code, name, market='SH'):
    """写入或更新股票基本信息。"""
    stock = db.get(models.Stock, code)
    if stock is None:
        stock = models.Stock(code=code, name=name, market=market)
        db.add(stock)
    else:
        stock.name = name
        stock.market = market
    db.flush()
    return stock


def save_klines(db: Session, code, rows):
    """写入日线,已存在的跳过。返回新增条数。

    用 (code, trade_date) 判重,因此重复采集是幂等的。
    """
    if not rows:
        return 0

    existing = set(db.scalars(
        select(models.Kline.trade_date).where(models.Kline.code == code)
    ).all())

    added = 0
    for row in rows:
        if row['trade_date'] in existing:
            continue
        db.add(models.Kline(
            code=code,
            trade_date=row['trade_date'],
            open=row['open'],
            close=row['close'],
            high=row['high'],
            low=row['low'],
            volume=row['volume'],
            amount=row['amount'],
            amplitude=row.get('amplitude', 0.0),
            change_pct=row.get('change_pct', 0.0),
        ))
        existing.add(row['trade_date'])
        added += 1
    db.flush()
    return added


def save_news(db: Session, code, rows):
    """写入新闻,按 url 判重。返回新增条数。"""
    if not rows:
        return 0

    existing = set(db.scalars(
        select(models.News.url).where(models.News.code == code)
    ).all())

    added = 0
    for row in rows:
        if row['url'] in existing:
            continue
        db.add(models.News(
            code=code,
            title=row['title'],
            url=row['url'],
            source=row.get('source', ''),
            publish_time=row.get('publish_time', ''),
        ))
        existing.add(row['url'])
        added += 1
    db.flush()
    return added


def annotate_sentiment(db: Session, code, limit=None):
    """给尚未标注情感的新闻打情感标签。返回 (标注条数, 用的模型名)。

    单独一遍扫描(而不是在 save_news 里顺手标)有两个好处:
      1. 老数据也能补标 —— v0.1 存进去的新闻 sentiment 是空的
      2. 模型缺失时不影响采集,只是标注数为 0

    批量推理而不是逐条: BERT 单条推理要几十毫秒,批量能摊薄固定开销。
    """
    rows = db.scalars(
        select(models.News)
        .where(models.News.code == code)
        .where(models.News.sentiment == '')
        .order_by(models.News.id)
    ).all()
    if limit:
        rows = rows[:limit]
    if not rows:
        return 0, sentiment.default_kind()

    model = sentiment.load()
    if model is None:
        return 0, None

    texts = [r.title for r in rows]
    BATCH = 64
    done = 0
    for i in range(0, len(texts), BATCH):
        chunk = texts[i:i + BATCH]
        results = model.predict(chunk)
        for row, res in zip(rows[i:i + BATCH], results):
            row.sentiment = res['label']
            row.sentiment_score = res['score']
            done += 1
    db.flush()
    return done, model.kind


def sync_stock(db: Session, code, name, market='SH', news_size=20, news_pages=1):
    """完整同步一只股票:基本信息 + 日线 + 新闻 + 情感标注。返回统计字典。

    news_pages > 1 时会翻多页新闻 —— 这是把样本量做大的主要手段。
    每页 news_size 条,实际入库量受去重影响。
    """
    upsert_stock(db, code, name, market)

    kline_added = 0
    news_added = 0
    sentiment_added = 0
    sentiment_model = None
    errors = []

    try:
        rows = collector.compute_change_pct(collector.fetch_kline(code, market))
        kline_added = save_klines(db, code, rows)
    except Exception as exc:  # noqa: BLE001
        errors.append('kline: %s: %s' % (type(exc).__name__, exc))

    try:
        news = collector.fetch_news_pages(name, pages=news_pages,
                                          page_size=news_size)
        news_added = save_news(db, code, news)
    except Exception as exc:  # noqa: BLE001
        errors.append('news: %s: %s' % (type(exc).__name__, exc))

    try:
        sentiment_added, sentiment_model = annotate_sentiment(db, code)
    except Exception as exc:  # noqa: BLE001
        errors.append('sentiment: %s: %s' % (type(exc).__name__, exc))

    db.commit()
    return {
        'code': code,
        'name': name,
        'kline_added': kline_added,
        'news_added': news_added,
        'sentiment_added': sentiment_added,
        'sentiment_model': sentiment_model,
        'errors': errors,
    }
