"""FastAPI 应用入口与接口定义。"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, models, sentiment, service
from .db import get_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_defaults()
    yield


def _seed_defaults():
    """首次启动时写入默认关注的股票(已有则跳过)。"""
    from .db import SessionLocal
    db = SessionLocal()
    try:
        for code, name, market in config.DEFAULT_STOCKS:
            service.upsert_stock(db, code, name, market)
        db.commit()
    finally:
        db.close()


app = FastAPI(
    title='财经舆情分析平台 API',
    version='0.2.0',
    description='行情与新闻采集展示 + 情感分析',
    lifespan=lifespan,
)

# 开发期允许前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/api/health')
def health():
    """健康检查。"""
    return {'status': 'ok', 'version': app.version}


@app.get('/api/stocks')
def list_stocks(db: Session = Depends(get_db)):
    """股票列表,附带已入库的数据量。"""
    stocks = db.scalars(select(models.Stock).order_by(models.Stock.code)).all()
    out = []
    for s in stocks:
        kline_count = db.scalar(
            select(func.count()).select_from(models.Kline)
            .where(models.Kline.code == s.code)) or 0
        news_count = db.scalar(
            select(func.count()).select_from(models.News)
            .where(models.News.code == s.code)) or 0
        out.append({
            'code': s.code,
            'name': s.name,
            'market': s.market,
            'kline_count': kline_count,
            'news_count': news_count,
        })
    return out


@app.get('/api/stocks/{code}/klines')
def get_klines(code: str, limit: int = Query(120, ge=1, le=5000),
               db: Session = Depends(get_db)):
    """日线行情。默认返回最近 120 个交易日(按日期升序)。"""
    _require_stock(db, code)
    rows = db.scalars(
        select(models.Kline)
        .where(models.Kline.code == code)
        .order_by(models.Kline.trade_date.desc())
        .limit(limit)
    ).all()
    rows = list(reversed(rows))
    return [{
        'trade_date': r.trade_date,
        'open': r.open, 'close': r.close, 'high': r.high, 'low': r.low,
        'volume': r.volume, 'amount': r.amount,
        'amplitude': r.amplitude, 'change_pct': r.change_pct,
    } for r in rows]


@app.get('/api/stocks/{code}/news')
def get_news(code: str, limit: int = Query(50, ge=1, le=500),
             db: Session = Depends(get_db)):
    """新闻列表,按时间倒序。"""
    _require_stock(db, code)
    rows = db.scalars(
        select(models.News)
        .where(models.News.code == code)
        .order_by(models.News.publish_time.desc())
        .limit(limit)
    ).all()
    return [{
        'id': r.id,
        'title': r.title,
        'url': r.url,
        'source': r.source,
        'publish_time': r.publish_time,
        'sentiment': r.sentiment,
        'sentiment_score': r.sentiment_score,
    } for r in rows]


@app.get('/api/stocks/{code}/overview')
def get_overview(code: str, db: Session = Depends(get_db)):
    """概览:最新价、涨跌幅、数据量、新闻来源分布。"""
    _require_stock(db, code)
    stock = db.get(models.Stock, code)

    latest = db.scalars(
        select(models.Kline).where(models.Kline.code == code)
        .order_by(models.Kline.trade_date.desc()).limit(1)
    ).first()

    kline_count = db.scalar(
        select(func.count()).select_from(models.Kline)
        .where(models.Kline.code == code)) or 0
    news_count = db.scalar(
        select(func.count()).select_from(models.News)
        .where(models.News.code == code)) or 0

    sources = db.execute(
        select(models.News.source, func.count())
        .where(models.News.code == code)
        .group_by(models.News.source)
        .order_by(func.count().desc())
        .limit(10)
    ).all()

    return {
        'code': stock.code,
        'name': stock.name,
        'market': stock.market,
        'kline_count': kline_count,
        'news_count': news_count,
        'latest': None if latest is None else {
            'trade_date': latest.trade_date,
            'close': latest.close,
            'change_pct': latest.change_pct,
            'volume': latest.volume,
            'amount': latest.amount,
        },
        'news_sources': [{'source': s or '(未知)', 'count': c} for s, c in sources],
    }


@app.post('/api/stocks/{code}/sync')
def sync(code: str, news_size: int = Query(20, ge=1, le=100),
         db: Session = Depends(get_db)):
    """触发一次采集(行情 + 新闻 + 情感分析)。"""
    _require_stock(db, code)
    stock = db.get(models.Stock, code)
    return service.sync_stock(db, stock.code, stock.name, stock.market,
                              news_size=news_size)


# ------------------------------------------------------------ 情感分析

@app.get('/api/sentiment/info')
def sentiment_info():
    """当前情感分析模型的可用性与指标。"""
    return sentiment.info()


@app.post('/api/sentiment/analyze')
def sentiment_analyze(payload: dict):
    """对任意文本做情感分析(演示 / 调试用)。

    请求体: {'texts': ['...', '...'], 'model': 'bert'}   model 可省略
    返回  : {'model': 'bert', 'results': [{'text','label','score','scores'}]}
    """
    texts = (payload or {}).get('texts')
    if not isinstance(texts, list) or not texts:
        raise HTTPException(status_code=400, detail='texts 必须是非空数组')
    texts = [str(t) for t in texts][:200]

    kind = (payload or {}).get('model') or None
    if kind and kind not in sentiment.available():
        raise HTTPException(status_code=400, detail='模型不可用: %s' % kind)

    results = sentiment.predict(texts, kind=kind)
    if results is None:
        raise HTTPException(
            status_code=503,
            detail='没有可用的情感分析模型,请先跑 tools/train_sentiment.py')
    return {
        'model': kind or sentiment.default_kind(),
        'results': [dict(text=t, **r) for t, r in zip(texts, results)],
    }


@app.get('/api/stocks/{code}/sentiment')
def get_sentiment(code: str, limit: int = Query(500, ge=1, le=5000),
                  db: Session = Depends(get_db)):
    """某只股票新闻的情绪分布。

    只统计已标注情感的行。若一条都没有,返回 zero=True,前端据此提示
    先点「采集最新数据」。
    """
    _require_stock(db, code)

    rows = db.scalars(
        select(models.News)
        .where(models.News.code == code)
        .where(models.News.sentiment != '')
        .order_by(models.News.publish_time.desc())
        .limit(limit)
    ).all()

    counts = {'positive': 0, 'neutral': 0, 'negative': 0}
    for r in rows:
        if r.sentiment in counts:
            counts[r.sentiment] += 1
    total = sum(counts.values())

    daily = db.execute(
        select(models.News.publish_time, models.News.sentiment,
               func.count())
        .where(models.News.code == code)
        .where(models.News.sentiment != '')
        .group_by(models.News.publish_time, models.News.sentiment)
        .order_by(models.News.publish_time)
    ).all()

    by_date = {}
    for date, label, n in daily:
        day = (date or '')[:10]
        if not day:
            continue
        by_date.setdefault(day, {'positive': 0, 'neutral': 0, 'negative': 0})
        if label in by_date[day]:
            by_date[day][label] += n

    return {
        'code': code,
        'model': sentiment.default_kind(),
        'total': total,
        'zero': total == 0,
        'counts': counts,
        'ratio': {k: (round(v / total, 4) if total else 0.0)
                  for k, v in counts.items()},
        'daily': [dict(date=d, **v) for d, v in sorted(by_date.items())],
    }


def _require_stock(db: Session, code: str):
    stock = db.get(models.Stock, code)
    if stock is None:
        raise HTTPException(status_code=404, detail='股票不存在: %s' % code)
    return stock
