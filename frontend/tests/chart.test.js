import { describe, expect, it } from 'vitest'

import {
  COLORS,
  buildKlineOption,
  buildReturnsScatterOption,
  buildSentimentPieOption,
  buildSentimentTrendOption,
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

describe('COLORS', () => {
  // 这些色值同时写在 src/style.css 的 CSS 变量里(JS 读不到 CSS 变量,
  // 图表要的是具体色值)。锁住它们,改一处漏一处就会在这里失败。
  it('红涨绿跌且与 style.css 变量同值', () => {
    expect(COLORS.pos).toBe('#c8443a')
    expect(COLORS.neg).toBe('#2e7d5b')
    expect(COLORS.neu).toBe('#8a857d')
  })

  it('强调色为墨色而非品牌蓝', () => {
    // 页面唯一强调色必须是墨色 —— 饱和蓝会和红绿数据色抢注意力
    expect(COLORS.ink).toBe('#191713')
  })
})

describe('formatChangePct', () => {
  it('上涨带 + 且为红', () => {
    const r = formatChangePct(1.98)
    expect(r.text).toBe('+1.98%')
    expect(r.color).toBe(COLORS.pos)
  })

  it('下跌为绿且不带 +', () => {
    const r = formatChangePct(-1.02)
    expect(r.text).toBe('-1.02%')
    expect(r.color).toBe(COLORS.neg)
  })

  it('零为灰', () => {
    const r = formatChangePct(0)
    expect(r.text).toBe('0.00%')
    expect(r.color).toBe(COLORS.neu)
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

  /** 造 n 根长度无关紧要的日线,只用来验可视区间换算。 */
  function manyRows(n) {
    return Array.from({ length: n }, (_, i) => ({
      trade_date: `2025-${String((i % 12) + 1).padStart(2, '0')}-01`,
      open: 10, close: 10, low: 10, high: 10, volume: 1,
    }))
  }

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
    expect(o.series[1].data[0].itemStyle.color).toBe(COLORS.pos)
    // 第二条收 < 开,绿
    expect(o.series[1].data[1].itemStyle.color).toBe(COLORS.neg)
  })

  it('空数据不报错', () => {
    const o = buildKlineOption([])
    expect(o.xAxis[0].data).toEqual([])
    expect(o.series[0].data).toEqual([])
  })

  it('初始可视区间由 visibleBars 换算,不写死百分比', () => {
    // 250 根默认只显示最近 120 根 -> start = round((1 - 120/250) * 100) = 52
    const o = buildKlineOption(manyRows(250), { visibleBars: 120 })
    for (const z of o.dataZoom) {
      expect(z.start).toBe(52)
      expect(z.end).toBe(100)
    }
  })

  it('数据量少于可视根数时从 0 开始,全量显示', () => {
    const o = buildKlineOption(rows, { visibleBars: 120 })
    for (const z of o.dataZoom) {
      expect(z.start).toBe(0)
      expect(z.end).toBe(100)
    }
  })

  it('默认只显示最近 120 根', () => {
    // 写死 60 时 250 根只露约 100 根,而标题写着「共 250 个交易日」——
    // 这条断言就是防止再退回写死百分比。
    const o = buildKlineOption(manyRows(250))
    const shown = Math.round(((o.dataZoom[0].end - o.dataZoom[0].start) / 100) * 250)
    expect(shown).toBeGreaterThanOrEqual(118)
    expect(shown).toBeLessThanOrEqual(122)
  })
})

describe('buildSentimentPieOption', () => {
  it('翻译成中文标签并固定配色', () => {
    const o = buildSentimentPieOption({ positive: 5, negative: 3, neutral: 2 })
    expect(o.series[0].data).toEqual([
      { name: '利好', value: 5, itemStyle: { color: COLORS.pos } },
      { name: '利空', value: 3, itemStyle: { color: COLORS.neg } },
      { name: '中性', value: 2, itemStyle: { color: COLORS.neu } },
    ])
  })

  it('剔除 0 值类别,避免饼图出现零面积扇区', () => {
    const o = buildSentimentPieOption({ positive: 4, negative: 0, neutral: 0 })
    expect(o.series[0].data).toHaveLength(1)
    expect(o.series[0].data[0].name).toBe('利好')
  })

  it('缺字段按 0 处理', () => {
    expect(buildSentimentPieOption({ positive: 1 }).series[0].data)
      .toHaveLength(1)
  })

  it('空对象与 undefined 都不报错', () => {
    expect(buildSentimentPieOption({}).series[0].data).toEqual([])
    expect(buildSentimentPieOption(undefined).series[0].data).toEqual([])
  })

  it('利好为红、利空为绿 —— 与 K 线一致', () => {
    const o = buildSentimentPieOption({ positive: 1, negative: 1, neutral: 0 })
    const byName = Object.fromEntries(
      o.series[0].data.map((d) => [d.name, d.itemStyle.color]))
    expect(byName['利好']).toBe(COLORS.pos)
    expect(byName['利空']).toBe(COLORS.neg)
  })

  it('不画引导线标签,避免小类标签互相压字', () => {
    // 占比常严重倾斜(中性九成、小类一两条),引导线标签会挤在一起。
    // 数字由面板上方的计数条给出,饼图只表达比例形状。
    const o = buildSentimentPieOption({ positive: 1, negative: 1, neutral: 22 })
    expect(o.series[0].label.show).toBe(false)
    expect(o.series[0].labelLine.show).toBe(false)
  })
})

describe('buildSentimentTrendOption', () => {
  const daily = [
    { date: '2026-10-01', positive: 3, negative: 1, neutral: 2 },
    { date: '2026-10-02', positive: 0, negative: 4, neutral: 1 },
  ]

  it('x 轴取日期,三条序列按日取值', () => {
    const o = buildSentimentTrendOption(daily)
    expect(o.xAxis.data).toEqual(['2026-10-01', '2026-10-02'])
    expect(o.series).toHaveLength(3)
    const pos = o.series.find((s) => s.name === '利好')
    expect(pos.data).toEqual([3, 0])
    const neg = o.series.find((s) => s.name === '利空')
    expect(neg.data).toEqual([1, 4])
  })

  it('三条序列堆叠在同一柱上', () => {
    const o = buildSentimentTrendOption(daily)
    expect(o.series.every((s) => s.stack === 'total')).toBe(true)
  })

  it('缺字段按 0 处理', () => {
    const o = buildSentimentTrendOption([{ date: '2026-10-03', positive: 2 }])
    const neg = o.series.find((s) => s.name === '利空')
    expect(neg.data).toEqual([0])
  })

  it('空数组与 undefined 都不报错', () => {
    expect(buildSentimentTrendOption([]).xAxis.data).toEqual([])
    expect(buildSentimentTrendOption(undefined).xAxis.data).toEqual([])
  })
})

describe('buildReturnsScatterOption', () => {
  const pairs = [
    { polarity: -1, return: -2 },
    { polarity: -0.5, return: -1 },
    { polarity: 0, return: 0 },
    { polarity: 0.5, return: 1 },
    { polarity: 1, return: 2 },
  ]

  it('散点取 [情感指数, 收益] 二元组', () => {
    const o = buildReturnsScatterOption(pairs)
    const scatter = o.series.find((s) => s.name === '样本')
    expect(scatter.type).toBe('scatter')
    expect(scatter.data[0]).toEqual([-1, -2])
    expect(scatter.data).toHaveLength(5)
  })

  it('横轴固定 -1..1,让不同股票的图可以直接对比', () => {
    const o = buildReturnsScatterOption(pairs)
    expect(o.xAxis.min).toBe(-1)
    expect(o.xAxis.max).toBe(1)
  })

  it('样本够时画拟合线,斜率与数据方向一致', () => {
    const o = buildReturnsScatterOption(pairs)
    const fit = o.series.find((s) => s.name === '拟合线')
    expect(fit).toBeTruthy()
    expect(fit.type).toBe('line')
    // 完美线性:y = 2x,两端点应为 (-1,-2) 与 (1,2)
    expect(fit.data[0]).toEqual([-1, -2])
    expect(fit.data[1]).toEqual([1, 2])
  })

  it('拟合线不响应鼠标,避免 tooltip 抢散点的位置', () => {
    const o = buildReturnsScatterOption(pairs)
    expect(o.series.find((s) => s.name === '拟合线').silent).toBe(true)
  })

  it('样本少于 3 个不画拟合线', () => {
    const o = buildReturnsScatterOption(pairs.slice(0, 2))
    expect(o.series.find((s) => s.name === '拟合线')).toBeUndefined()
    expect(o.series).toHaveLength(1)
  })

  it('情感指数全相同(方差为 0)时不画拟合线', () => {
    // 分母为 0 会算出 Infinity,必须挡住
    const flat = [
      { polarity: 0.5, return: 1 },
      { polarity: 0.5, return: 2 },
      { polarity: 0.5, return: 3 },
    ]
    const o = buildReturnsScatterOption(flat)
    expect(o.series.find((s) => s.name === '拟合线')).toBeUndefined()
  })

  it('空数组与 undefined 都不报错', () => {
    expect(buildReturnsScatterOption([]).series[0].data).toEqual([])
    expect(buildReturnsScatterOption(undefined).series[0].data).toEqual([])
  })
})
