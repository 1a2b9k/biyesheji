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

/**
 * 图表与数据配色 —— 全站唯一来源。
 *
 * 与 style.css 里的 CSS 变量同值。JS 侧拿不到 CSS 变量(图表要的是
 * 具体色值),所以两处必须一起改;chart.test.js 会锁住这些值,
 * 改错了测试会失败。
 *
 * 为什么是这两个红绿而不是常见的 #f56c6c / #67c23a:
 * 原色饱和度太高,在暖白底上刺眼,且和页面唯一强调色(墨色)打架。
 * 现在这两个都压过饱和度,红偏砖、绿偏松,和纸色底子能相处。
 */
export const COLORS = {
  pos: '#c8443a',
  neg: '#2e7d5b',
  neu: '#8a857d',
  ink: '#191713',
  muted: '#6f6862',
  line: '#e3ded4',
}

/** 涨跌幅显示:正数带 +,并给出颜色语义。 */
export function formatChangePct(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return { text: '-', color: COLORS.neu }
  const sign = n > 0 ? '+' : ''
  return {
    text: sign + n.toFixed(2) + '%',
    color: n > 0 ? COLORS.pos : n < 0 ? COLORS.neg : COLORS.neu,
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
  const volumes = rows.map((r) => ({
    value: r.volume,
    itemStyle: {
      color: r.close >= r.open ? COLORS.pos : COLORS.neg,
    },
  }))

  // 轴样式统一在这里定一次,免得每个轴各写一遍还写不一致。
  const axisLine = { lineStyle: { color: COLORS.line } }
  const axisLabel = { fontSize: 11, color: COLORS.muted }
  const splitLine = { lineStyle: { color: COLORS.line, type: 'dashed' } }

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { fontSize: 11 } },
      // 悬停读数用等宽字体,数字不会左右跳
      textStyle: { fontSize: 12 },
    },
    grid: [
      { left: 62, right: 26, top: 26, height: '56%' },
      { left: 62, right: 26, top: '74%', height: '16%' },
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, gridIndex: 0,
        axisLine, axisLabel, axisTick: { show: false },
        splitLine: { show: false } },
      { type: 'category', data: dates, gridIndex: 1,
        axisLine, axisLabel: { show: false },
        axisTick: { show: false }, splitLine: { show: false } },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, axisLine: { show: false },
        axisTick: { show: false }, axisLabel, splitLine,
        name: '价格 (元)', nameTextStyle: { fontSize: 11, color: COLORS.muted } },
      { gridIndex: 1, axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { show: false }, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], top: '93%', height: 18,
        start: 60, end: 100,
        borderColor: COLORS.line, fillerColor: 'rgba(25,23,19,0.06)',
        handleStyle: { color: COLORS.ink },
        textStyle: { fontSize: 10, color: COLORS.muted } },
    ],
    series: [
      { name: 'K线', type: 'candlestick', data: candles,
        xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: {
          color: COLORS.pos, color0: COLORS.neg,
          borderColor: COLORS.pos, borderColor0: COLORS.neg,
        } },
      { name: '成交量', type: 'bar', data: volumes,
        xAxisIndex: 1, yAxisIndex: 1, barWidth: '60%' },
    ],
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
  positive: COLORS.pos,
  negative: COLORS.neg,
  neutral: COLORS.neu,
}

export const SENTIMENT_NAMES = {
  positive: '利好',
  negative: '利空',
  neutral: '中性',
}

/**
 * 构造情感分布饼图配置。
 * counts 形如 { positive: 12, negative: 3, neutral: 5 }。
 *
 * 不画引导线标签:三类占比常严重倾斜(中性动辄九成),小类只有一两条,
 * 引导线标签会挤在一起互相压字。数字由面板上方的计数条给出,饼图只负责
 * 表达"比例形状",配底部图例即可。
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
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 条 ({d}%)',
      textStyle: { fontSize: 12 },
    },
    legend: {
      bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8,
      textStyle: { fontSize: 11, color: COLORS.muted },
    },
    series: [{
      name: '情感分布',
      type: 'pie',
      radius: ['46%', '70%'],
      center: ['50%', '44%'],
      itemStyle: { borderColor: '#fffefb', borderWidth: 2 },
      data,
      label: { show: false },
      labelLine: { show: false },
      emphasis: { scale: true, scaleSize: 4 },
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
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      textStyle: { fontSize: 12 },
    },
    legend: {
      bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8,
      textStyle: { fontSize: 11, color: COLORS.muted },
    },
    grid: { left: 42, right: 16, top: 16, bottom: 56 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: COLORS.line } },
      axisTick: { show: false },
      axisLabel: {
        fontSize: 10, color: COLORS.muted,
        rotate: dates.length > 12 ? 45 : 0,
      },
    },
    yAxis: {
      type: 'value', minInterval: 1,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { fontSize: 11, color: COLORS.muted },
      splitLine: { lineStyle: { color: COLORS.line, type: 'dashed' } },
    },
    series: order.map((k) => ({
      name: SENTIMENT_NAMES[k],
      type: 'bar',
      stack: 'total',
      barWidth: '58%',
      itemStyle: { color: SENTIMENT_COLORS[k] },
      data: rows.map((d) => d?.[k] ?? 0),
    })),
  }
}

/**
 * 构造「情感指数 vs 次日收益」散点图。
 *
 * 横轴是情感指数 polarity(-1 全负面 .. +1 全正面),纵轴是之后第 lag 个
 * 交易日的涨跌幅。散点比折线更合适:折线会暗示两列数据在时间上连续,
 * 而这里要表达的是「两个变量的联合分布」。
 *
 * 同时画一条最小二乘拟合线 —— 斜率就是相关性的可视化版本,
 * 让读者一眼看出方向,而不必去读数字。
 */
export function buildReturnsScatterOption(pairs) {
  const rows = Array.isArray(pairs) ? pairs : []
  const points = rows.map((p) => [p.polarity, p.return])

  // 最小二乘拟合 y = a + b*x,样本太少时不画
  let fit = []
  if (points.length >= 3) {
    const n = points.length
    const mx = points.reduce((s, p) => s + p[0], 0) / n
    const my = points.reduce((s, p) => s + p[1], 0) / n
    let num = 0
    let den = 0
    for (const [x, y] of points) {
      num += (x - mx) * (y - my)
      den += (x - mx) ** 2
    }
    if (den !== 0) {
      const b = num / den
      const a = my - b * mx
      const xs = points.map((p) => p[0])
      const minX = Math.min(...xs)
      const maxX = Math.max(...xs)
      fit = [
        [minX, a + b * minX],
        [maxX, a + b * maxX],
      ]
    }
  }

  return {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        if (p.seriesName === '拟合线') return ''
        return `情感 ${p.value[0]}<br/>次日收益 ${p.value[1]}%`
      },
      textStyle: { fontSize: 12 },
    },
    grid: { left: 52, right: 20, top: 20, bottom: 44 },
    xAxis: {
      type: 'value', name: '情感指数', nameTextStyle: { fontSize: 11 },
      min: -1, max: 1,
      axisLine: { lineStyle: { color: COLORS.line } },
      axisTick: { show: false },
      axisLabel: { fontSize: 11, color: COLORS.muted },
      splitLine: { lineStyle: { color: COLORS.line, type: 'dashed' } },
    },
    yAxis: {
      type: 'value', name: '次日收益 %', nameTextStyle: { fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { fontSize: 11, color: COLORS.muted },
      splitLine: { lineStyle: { color: COLORS.line, type: 'dashed' } },
    },
    series: [
      {
        name: '样本',
        type: 'scatter',
        symbolSize: 7,
        itemStyle: { color: COLORS.pos, opacity: 0.7 },
        data: points,
      },
      ...(fit.length
        ? [{
            name: '拟合线',
            type: 'line',
            showSymbol: false,
            silent: true,
            lineStyle: { color: COLORS.ink, width: 1.5, type: 'dashed' },
            data: fit,
          }]
        : []),
    ],
  }
}
