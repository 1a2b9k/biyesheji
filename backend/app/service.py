"""业务层:把采集到的数据写入数据库(去重、幂等)。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import collector, models


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


def sync_stock(db: Session, code, name, market='SH', news_size=20):
    """完整同步一只股票:基本信息 + 日线 + 新闻。返回统计字典。"""
    upsert_stock(db, code, name, market)

    kline_added = 0
    news_added = 0
    errors = []

    try:
        rows = collector.compute_change_pct(collector.fetch_kline(code, market))
        kline_added = save_klines(db, code, rows)
    except Exception as exc:  # noqa: BLE001
        errors.append('kline: %s: %s' % (type(exc).__name__, exc))

    try:
        news = collector.fetch_news(name, page_size=news_size)
        news_added = save_news(db, code, news)
    except Exception as exc:  # noqa: BLE001
        errors.append('news: %s: %s' % (type(exc).__name__, exc))

    db.commit()
    return {
        'code': code,
        'name': name,
        'kline_added': kline_added,
        'news_added': news_added,
        'errors': errors,
    }
