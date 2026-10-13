import { describe, expect, it } from 'vitest'

import {
  buildKlineOption,
  buildSourcePieOption,
  formatAmount,
  formatChangePct,
} from '../src/utils/chart.js'

describe('formatAmount', () => {
  it('大额转亿', () => {
    expect(formatAmount(3393315572)).toBe('33.93 亿')
  })

  it('中等转万', () => {
    expect(formatAmount(26573)).toBe('2.66 万')
  })

  it('小额原样保留两位', () => {
    expect(formatAmount(123.456)).toBe('123.46')
  })

  it('非法输入返回占位符', () => {
    expect(formatAmount(null)).toBe('-')
    expect(formatAmount(undefined)).toBe('-')
    expect(formatAmount('abc')).toBe('-')
  })

  it('负数按绝对值选单位', () => {
    expect(formatAmount(-2e8)).toBe('-2.00 亿')
  })
})

describe('formatChangePct', () => {
  it('上涨带 + 且为红', () => {
    const r = formatChangePct(1.98)
    expect(r.text).toBe('+1.98%')
    expect(r.color).toBe('#f56c6c')
  })

  it('下跌为绿且不带 +', () => {
    const r = formatChangePct(-1.02)
    expect(r.text).toBe('-1.02%')
    expect(r.color).toBe('#67c23a')
  })

  it('零为灰', () => {
    const r = formatChangePct(0)
    expect(r.text).toBe('0.00%')
    expect(r.color).toBe('#909399')
  })

  it('非法输入返回占位符', () => {
    expect(formatChangePct(NaN).text).toBe('-')
  })
})

describe('buildKlineOption', () => {
  const rows = [
    { trade_date: '2026-10-12', open: 1262.95, close: 1288, low: 1261, high: 1288, volume: 31556 },
    { trade_date: '2026-10-13', open: 1287, close: 1274.89, low: 1268.11, high: 1288.48, volume: 26573 },
  ]

  it('x 轴为日期', () => {
    const o = buildKlineOption(rows)
    expect(o.xAxis[0].data).toEqual(['2026-10-12', '2026-10-13'])
  })

  it('蜡烛图数据顺序为 [开, 收, 低, 高]', () => {
    const o = buildKlineOption(rows)
    expect(o.series[0].data[0]).toEqual([1262.95, 1288, 1261, 1288])
  })

  it('含两个 series:K 线与成交量', () => {
    const o = buildKlineOption(rows)
    expect(o.series).toHaveLength(2)
    expect(o.series[0].type).toBe('candlestick')
    expect(o.series[1].type).toBe('bar')
  })

  it('两个 grid 分别承载价格与成交量', () => {
    const o = buildKlineOption(rows)
    expect(o.grid).toHaveLength(2)
    expect(o.xAxis).toHaveLength(2)
    expect(o.yAxis).toHaveLength(2)
  })

  it('成交量柱按涨跌着色', () => {
    const o = buildKlineOption(rows)
    // 第一条收 >= 开,红
    expect(o.series[1].data[0].itemStyle.color).toBe('#f56c6c')
    // 第二条收 < 开,绿
    expect(o.series[1].data[1].itemStyle.color).toBe('#67c23a')
  })

  it('空数据不报错', () => {
    const o = buildKlineOption([])
    expect(o.xAxis[0].data).toEqual([])
    expect(o.series[0].data).toEqual([])
  })
})

describe('buildSourcePieOption', () => {
  it('映射为 name/value', () => {
    const o = buildSourcePieOption([
      { source: '新华财经', count: 3 },
      { source: '界面新闻', count: 2 },
    ])
    expect(o.series[0].data).toEqual([
      { name: '新华财经', value: 3 },
      { name: '界面新闻', value: 2 },
    ])
  })

  it('空数组不报错', () => {
    expect(buildSourcePieOption([]).series[0].data).toEqual([])
  })
})
