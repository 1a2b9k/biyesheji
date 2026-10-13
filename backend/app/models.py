"""数据模型:股票、日线行情、新闻。"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Stock(Base):
    """股票基本信息。"""

    __tablename__ = 'stock'

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False, default='SH')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    klines: Mapped[list['Kline']] = relationship(
        back_populates='stock', cascade='all, delete-orphan'
    )
    news: Mapped[list['News']] = relationship(
        back_populates='stock', cascade='all, delete-orphan'
    )


class Kline(Base):
    """日线行情。一条 = 某股票某一天。"""

    __tablename__ = 'kline'
    __table_args__ = (
        UniqueConstraint('code', 'trade_date', name='uq_kline_code_date'),
        Index('ix_kline_code_date', 'code', 'trade_date'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), ForeignKey('stock.code'), nullable=False)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD

    open: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    amount: Mapped[float] = mapped_column(Float)
    amplitude: Mapped[float] = mapped_column(Float, default=0.0)  # 振幅 %
    change_pct: Mapped[float] = mapped_column(Float, default=0.0)  # 涨跌幅 %

    stock: Mapped[Stock] = relationship(back_populates='klines')


class News(Base):
    """新闻。一条 = 一篇文章的标题与元信息。"""

    __tablename__ = 'news'
    __table_args__ = (
        UniqueConstraint('code', 'url', name='uq_news_code_url'),
        Index('ix_news_code_date', 'code', 'publish_time'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), ForeignKey('stock.code'), nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    source: Mapped[str] = mapped_column(String(128), default='')
    publish_time: Mapped[str] = mapped_column(String(32), default='')  # 原始字符串,便于排序

    # 情感分析结果(v0.2 填充;v0.1 留空)
    sentiment: Mapped[str] = mapped_column(String(16), default='')      # positive/neutral/negative
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)  # 置信度

    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    stock: Mapped[Stock] = relationship(back_populates='news')
