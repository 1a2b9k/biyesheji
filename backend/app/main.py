"""FastAPI 应用入口与接口定义。"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, models, service
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
    version='0.1.0',
    description='行情与新闻采集展示(v0.1 基础版;情感分析在 v0.2 加入)',
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
    """触发一次采集(行情 + 新闻)。"""
    _require_stock(db, code)
    stock = db.get(models.Stock, code)
    return service.sync_stock(db, stock.code, stock.name, stock.market,
                              news_size=news_size)


def _require_stock(db: Session, code: str):
    stock = db.get(models.Stock, code)
    if stock is None:
        raise HTTPException(status_code=404, detail='股票不存在: %s' % code)
    return stock
