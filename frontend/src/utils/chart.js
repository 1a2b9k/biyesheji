/**
 * 纯函数:把后端返回的数据整理成 ECharts 能直接用的结构。
 *
 * 单独抽出来是为了能脱离浏览器单元测试 —— 图表配置最容易出错,
 * 而这部分逻辑本身不依赖 DOM。
 */

/** 格式化数字,大额自动转成「万 / 亿」。 */
export function formatAmount(value) {
  // 注意:Number(null) === 0、Number('') === 0,都需先挡掉
  if (value === null || value === undefined || value === '') return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  const abs = Math.abs(n)
  if (abs >= 1e8) return (n / 1e8).toFixed(2) + ' 亿'
  if (abs >= 1e4) return (n / 1e4).toFixed(2) + ' 万'
  return n.toFixed(2)
}

/** 涨跌幅显示:正数带 +,并给出颜色语义。 */
export function formatChangePct(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return { text: '-', color: '#909399' }
  const sign = n > 0 ? '+' : ''
  return {
    text: sign + n.toFixed(2) + '%',
    color: n > 0 ? '#f56c6c' : n < 0 ? '#67c23a' : '#909399',
  }
}

/**
 * 构造 K 线图配置。
 * 上区为蜡烛图,下区为成交量柱。
 */
export function buildKlineOption(rows) {
  const dates = rows.map((r) => r.trade_date)
  // ECharts 蜡烛图数据顺序:[开, 收, 低, 高]
  const candles = rows.map((r) => [r.open, r.close, r.low, r.high])
  const volumes = rows.map((r, i) => ({
    value: r.volume,
    itemStyle: {
      color: r.close >= r.open ? '#f56c6c' : '#67c23a',
    },
  }))

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    grid: [
      { left: 60, right: 30, top: 30, height: '55%' },
      { left: 60, right: 30, top: '72%', height: '18%' },
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, gridIndex: 0,
        axisLabel: { fontSize: 10 } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, name: '价格' },
      { gridIndex: 1, name: '成交量', axisLabel: { show: false },
        splitLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], top: '92%', start: 60, end: 100 },
    ],
    series: [
      { name: 'K线', type: 'candlestick', data: candles,
        xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: {
          color: '#f56c6c', color0: '#67c23a',
          borderColor: '#f56c6c', borderColor0: '#67c23a',
        } },
      { name: '成交量', type: 'bar', data: volumes,
        xAxisIndex: 1, yAxisIndex: 1 },
    ],
  }
}

/** 构造新闻来源分布饼图配置。 */
export function buildSourcePieOption(sources) {
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
    series: [{
      name: '新闻来源',
      type: 'pie',
      radius: ['40%', '68%'],
      center: ['50%', '45%'],
      data: sources.map((s) => ({ name: s.source, value: s.count })),
      label: { fontSize: 11 },
    }],
  }
}

// ------------------------------------------------------------------ 情感分析

/**
 * 情感配色。
 *
 * 与 K 线保持一致:A 股习惯红涨绿跌,所以「利好」用红、「利空」用绿。
 * 若这里改成国际惯例的绿涨红跌,同一页面上两张图会互相矛盾。
 */
export const SENTIMENT_COLORS = {
  positive: '#f56c6c',
  negative: '#67c23a',
  neutral: '#909399',
}

export const SENTIMENT_NAMES = {
  positive: '利好',
  negative: '利空',
  neutral: '中性',
}

/**
 * 构造情感分布饼图配置。
 * counts 形如 { positive: 12, negative: 3, neutral: 5 }。
 */
export function buildSentimentPieOption(counts) {
  const order = ['positive', 'negative', 'neutral']
  const data = order
    .map((k) => ({
      name: SENTIMENT_NAMES[k],
      value: counts?.[k] ?? 0,
      itemStyle: { color: SENTIMENT_COLORS[k] },
    }))
    .filter((d) => d.value > 0)

  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 条 ({d}%)' },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    series: [{
      name: '情感分布',
      type: 'pie',
      radius: ['40%', '68%'],
      center: ['50%', '45%'],
      data,
      label: { fontSize: 11 },
    }],
  }
}

/**
 * 构造情感日线堆叠柱状图。
 *
 * 用堆叠而非折线:每天新闻条数很少(常常个位数),折线会把
 * 「某天只有 1 条」渲染成和「某天有 50 条」一样粗的趋势线,
 * 堆叠柱能同时表达数量和构成。
 */
export function buildSentimentTrendOption(daily) {
  const rows = Array.isArray(daily) ? daily : []
  const dates = rows.map((d) => d.date)
  const order = ['positive', 'negative', 'neutral']

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: 45, right: 20, top: 20, bottom: 55 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 10, rotate: dates.length > 12 ? 45 : 0 },
    },
    yAxis: { type: 'value', name: '条数', minInterval: 1 },
    series: order.map((k) => ({
      name: SENTIMENT_NAMES[k],
      type: 'bar',
      stack: 'total',
      itemStyle: { color: SENTIMENT_COLORS[k] },
      data: rows.map((d) => d?.[k] ?? 0),
    })),
  }
}
