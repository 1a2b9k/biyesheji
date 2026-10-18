"""FastAPI 应用入口与接口定义。"""

from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import analysis, config, models, sentiment, service
from .db import get_db, init_db

# 前端开发服务器的来源。只列具体来源,不用 '*':
# Starlette 在 allow_credentials=True 时会回显请求方 Origin,
# 配 '*' 等于任何站点都能带凭据调用本服务。
# 前端正常走 vite 的 /api 代理,同源,不触发 CORS;这里只服务直连调试。
DEV_ORIGINS = [
    'http://127.0.0.1:5173',
    'http://localhost:5173',
    'http://127.0.0.1:4173',
    'http://localhost:4173',
]



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
    version='0.5.0',
    description='行情与新闻采集展示 + 情感分析',
    lifespan=lifespan,
)

# 开发期允许前端跨域。不给 credentials:本服务不靠 Cookie 认证,
# 开了它反而要求 Origin 精确匹配,而 '*' 与它组合会被浏览器拒绝。
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_credentials=False,
    allow_methods=['GET', 'POST'],
    allow_headers=['*'],
)


@app.get('/api/health')
def health():
    """健康检查。"""
    return {'status': 'ok', 'version': app.version}


@app.get('/api/stocks')
def list_stocks(db: Session = Depends(get_db)):
    """股票列表,附带已入库的数据量。

    数据量用两条 group by 一次算完。早先的写法是每只股票各发两次
    count 查询(2N 次往返),13 只股票就是 26 次,股票一多就明显变慢。
    """
    stocks = db.scalars(select(models.Stock).order_by(models.Stock.code)).all()

    kline_counts = dict(db.execute(
        select(models.Kline.code, func.count())
        .group_by(models.Kline.code)
    ).all())
    news_counts = dict(db.execute(
        select(models.News.code, func.count())
        .group_by(models.News.code)
    ).all())

    return [{
        'code': s.code,
        'name': s.name,
        'market': s.market,
        'kline_count': kline_counts.get(s.code, 0),
        'news_count': news_counts.get(s.code, 0),
    } for s in stocks]


@app.get('/api/stocks/{code}/klines')
def get_klines(code: str, limit: int = Query(120, ge=1, le=20000),
               db: Session = Depends(get_db)):
    """日线行情。默认返回最近 120 个交易日(按日期升序)。

    上限取 20000 而不是 5000:实测平安银行(000001)有 8497 个交易日,
    5000 的上限会让最早 3497 条永远取不到。
    """
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

    # 来源的"家数"必须单独数:上面只取了前 10 家,
    # 用 len(sources) 当总数会把长尾来源全部抹掉(600519 实际有 52 家)。
    source_count = db.scalar(
        select(func.count(func.distinct(models.News.source)))
        .where(models.News.code == code)) or 0

    return {
        'code': stock.code,
        'name': stock.name,
        'market': stock.market,
        'kline_count': kline_count,
        'news_count': news_count,
        'news_source_count': source_count,
        'latest': None if latest is None else {
            'trade_date': latest.trade_date,
            'close': latest.close,
            'change_pct': latest.change_pct,
            'volume': latest.volume,
            'amount': latest.amount,
        },
        # 只返回前 10 家(按条数降序)。前端若需要"共多少条",
        # 要用 news_count 而不是把这里的 count 相加。
        'news_sources': [{'source': s or '(未知)', 'count': c} for s, c in sources],
    }


@app.post('/api/stocks/{code}/sync')
def sync(code: str, news_size: int = Query(20, ge=1, le=100),
         news_pages: int = Query(1, ge=1, le=100),
         db: Session = Depends(get_db)):
    """触发一次采集(行情 + 新闻 + 情感分析)。

    news_pages 控制新闻翻页数 —— 翻得越多入库样本越大,默认 1 页。
    """
    _require_stock(db, code)
    stock = db.get(models.Stock, code)
    return service.sync_stock(db, stock.code, stock.name, stock.market,
                              news_size=news_size, news_pages=news_pages)


# ------------------------------------------------------------ 情感分析

@app.get('/api/sentiment/info')
def sentiment_info():
    """当前情感分析模型的可用性与指标。"""
    return sentiment.info()


# 单次文本分析上限。前端没有接这个接口,它只服务调试与演示。
MAX_ANALYZE_TEXTS = 200


class AnalyzeRequest(BaseModel):
    """POST /api/sentiment/analyze 的请求体。

    早先收的是裸 dict:坏请求只能靠手写 if 兜,而且 /docs 里看不到字段说明。
    """

    texts: List[str] = Field(..., min_length=1, max_length=MAX_ANALYZE_TEXTS,
                             description='待分析文本,最多 %d 条'
                                         % MAX_ANALYZE_TEXTS)
    model: Optional[str] = Field(None, description='模型名,省略则用默认模型')


@app.post('/api/sentiment/analyze')
def sentiment_analyze(payload: AnalyzeRequest):
    """对任意文本做情感分析(演示 / 调试用)。

    请求体: {'texts': ['...', '...'], 'model': 'bert'}   model 可省略
    返回  : {'model': 'bert', 'results': [{'text','label','score','scores'}]}
    """
    # 显式报错而不是静默截断:发 300 条只回 200 条,调用方会误以为
    # 后 100 条"判不出来"。超长由 AnalyzeRequest 的 max_length 拦下(422)。
    texts = [str(t) for t in payload.texts]

    kind = payload.model
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

    计数与按日趋势都只取 limit 条之内。早先 counts 按 limit 取、daily 却是
    全表 group by —— 两张图的口径对不上,而且每天全表扫一次。
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
    by_date = {}
    for r in rows:
        label = r.sentiment
        if label not in counts:
            continue
        counts[label] += 1
        day = (r.publish_time or '')[:10]
        if not day:
            continue
        by_date.setdefault(day, {'positive': 0, 'neutral': 0, 'negative': 0})
        by_date[day][label] += 1
    total = sum(counts.values())

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


@app.get('/api/stocks/{code}/returns')
def get_returns(code: str, lag: int = Query(1, ge=0, le=5),
                min_news: int = Query(1, ge=1, le=100),
                db: Session = Depends(get_db)):
    """情感指数与未来收益的关联分析。

    返回每日情感指数、对齐后的样本点,以及相关系数等统计量。
    lag 表示用之后第几个交易日的收益 —— 默认 1,即次日。
    """
    _require_stock(db, code)

    news = db.scalars(
        select(models.News)
        .where(models.News.code == code)
        .where(models.News.sentiment != '')
        .order_by(models.News.publish_time)
    ).all()
    klines = db.scalars(
        select(models.Kline)
        .where(models.Kline.code == code)
        .order_by(models.Kline.trade_date)
    ).all()

    rows = [{'publish_time': n.publish_time, 'sentiment': n.sentiment,
             'sentiment_score': n.sentiment_score} for n in news]
    ks = [{'trade_date': k.trade_date, 'change_pct': k.change_pct}
          for k in klines]

    result = analysis.analyze(rows, ks, lag=lag)
    # analyze 已经把落在同一收益日的样本合并了(非交易日/长假会让多个新闻日
    # 共享同一个收益值,不合并就是伪重复)。这里的 min_news 作用于合并后的
    # 条数,即"这一天合计有多少条新闻"。
    pairs = [p for p in result['pairs'] if p['n'] >= min_news]
    stats = analysis.summarize(pairs)
    stats['lag'] = lag
    stats['days_with_news'] = result['stats']['days_with_news']
    stats['aligned_n'] = result['stats']['aligned_n']

    return {
        'code': code,
        'news_total': len(rows),
        'kline_total': len(ks),
        'stats': stats,
        'pairs': pairs,
    }


def _require_stock(db: Session, code: str):
    stock = db.get(models.Stock, code)
    if stock is None:
        raise HTTPException(status_code=404, detail='股票不存在: %s' % code)
    return stock
