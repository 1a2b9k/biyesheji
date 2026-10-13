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
