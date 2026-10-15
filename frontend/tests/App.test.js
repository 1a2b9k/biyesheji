/**
 * 主页面集成测试。
 *
 * 用 jsdom 真实挂载整个 App(含子组件),只把网络请求打桩。
 * 这样验证的是"页面组合起来能不能正确渲染",而不只是单个函数。
 * ECharts 依赖 canvas,在 jsdom 下无法初始化,故整体打桩 ——
 * 图表配置的正确性由 chart.test.js 覆盖。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const STOCKS = [
  { code: '600519', name: '贵州茅台', market: 'SH', kline_count: 2, news_count: 2 },
  { code: '300750', name: '宁德时代', market: 'SZ', kline_count: 0, news_count: 0 },
]

const OVERVIEW = {
  code: '600519',
  name: '贵州茅台',
  market: 'SH',
  kline_count: 2,
  news_count: 2,
  latest: {
    trade_date: '2026-10-13', close: 1274.89, change_pct: -1.02,
    volume: 26573, amount: 3393315572,
  },
  news_sources: [
    { source: '新华财经', count: 1 },
    { source: '北京商报', count: 1 },
  ],
}

const KLINES = [
  { trade_date: '2026-10-12', open: 1262.95, close: 1288, high: 1288, low: 1261, volume: 31556, amount: 4e9, amplitude: 2.14, change_pct: 1.98 },
  { trade_date: '2026-10-13', open: 1287, close: 1274.89, high: 1288.48, low: 1268.11, volume: 26573, amount: 3.4e9, amplitude: 1.58, change_pct: -1.02 },
]

const NEWS = [
  { id: 1, title: '贵州茅台重回A股股王', url: 'https://x/1', source: '新华财经', publish_time: '2026-10-12 16:08:01', sentiment: '', sentiment_score: 0 },
  { id: 2, title: '11只白酒股下跌', url: 'https://x/2', source: '北京商报', publish_time: '2026-10-13 17:15:22', sentiment: '', sentiment_score: 0 },
]

const SENTIMENT = {
  code: '600519',
  model: 'bert',
  total: 4,
  zero: false,
  counts: { positive: 3, negative: 1, neutral: 0 },
  ratio: { positive: 0.75, negative: 0.25, neutral: 0 },
  daily: [
    { date: '2026-10-12', positive: 2, negative: 0, neutral: 0 },
    { date: '2026-10-13', positive: 1, negative: 1, neutral: 0 },
  ],
}

const SENTIMENT_INFO = {
  available: ['bert'],
  active: 'bert',
  labels: ['negative', 'positive', 'neutral'],
  metrics: { accuracy: 0.754, macro_f1: 0.7491, n_test: 2130 },
}

// 打桩:网络层与图表组件
vi.mock('../src/api', () => ({
  listStocks: vi.fn(() => Promise.resolve(STOCKS)),
  getOverview: vi.fn(() => Promise.resolve(OVERVIEW)),
  getKlines: vi.fn(() => Promise.resolve(KLINES)),
  getNews: vi.fn(() => Promise.resolve(NEWS)),
  getSentimentInfo: vi.fn(() => Promise.resolve(SENTIMENT_INFO)),
  getStockSentiment: vi.fn(() => Promise.resolve(SENTIMENT)),
  syncStock: vi.fn(() => Promise.resolve({ kline_added: 5, news_added: 3, sentiment_added: 2, errors: [] })),
}))

vi.mock('../src/components/EChart.vue', () => ({
  default: { name: 'EChart', props: ['option', 'height'], template: '<div class="echart-stub" />' },
}))

import App from '../src/App.vue'
import { COLORS } from '../src/utils/chart.js'

async function mountApp() {
  const w = mount(App)
  await flushPromises()
  await flushPromises()
  return w
}

/**
 * 按 series 名找图表配置。
 *
 * 不用下标:页面改布局(例如把来源分布挪到右栏)会让图表顺序变化,
 * 下标断言会因此误报,而"哪个图拿到哪份数据"才是真正要测的。
 * 同名 series 出现在多张图里时用 type 再筛一层。
 */
function optionOf(w, seriesName, seriesType) {
  const hit = w.findAllComponents({ name: 'EChart' })
    .map((c) => c.props('option'))
    .find((o) => (o.series ?? []).some(
      (s) => s.name === seriesName && (!seriesType || s.type === seriesType)))
  if (!hit) {
    throw new Error(`找不到 series 为 ${seriesName} 的图表`)
  }
  return hit
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('App 集成', () => {
  it('加载后渲染股票选择器', async () => {
    const w = await mountApp()
    const opts = w.findAll('option')
    expect(opts).toHaveLength(2)
    expect(opts[0].text()).toContain('贵州茅台')
    expect(opts[0].text()).toContain('600519')
  })

  it('渲染概览读数与最新价', async () => {
    const w = await mountApp()
    const text = w.text()
    expect(text).toContain('最新收盘')
    expect(text).toContain('2026-10-13')
    expect(text).toContain('1274.89')
  })

  it('涨跌幅带符号显示', async () => {
    const w = await mountApp()
    expect(w.text()).toContain('-1.02%')
  })

  it('渲染新闻列表', async () => {
    const w = await mountApp()
    expect(w.text()).toContain('贵州茅台重回A股股王')
    expect(w.text()).toContain('11只白酒股下跌')
  })

  it('渲染三个图表位(K线 + 情感分布 + 情感趋势)', async () => {
    const w = await mountApp()
    expect(w.findAll('.echart-stub')).toHaveLength(3)
  })

  it('K线图收到的配置含正确的日期轴', async () => {
    const w = await mountApp()
    const kline = optionOf(w, 'K线')
    expect(kline.xAxis[0].data).toEqual([
      '2026-10-12', '2026-10-13',
    ])
  })

  it('来源分布不再是彩色饼图,而是条状列表', async () => {
    const w = await mountApp()
    // 页面里不应再有任何 series 名为「新闻来源」的图表
    const opts = w.findAllComponents({ name: 'EChart' })
      .map((c) => c.props('option'))
    expect(opts.some((o) =>
      (o.series ?? []).some((s) => s.name === '新闻来源'))).toBe(false)
    // 但来源名仍要出现,由 SourceBreakdown 以文字渲染
    expect(w.text()).toContain('新华财经')
    expect(w.text()).toContain('北京商报')
  })

  it('数据量为 0 时给出采集提示', async () => {
    const api = await import('../src/api')
    api.getKlines.mockResolvedValueOnce([])
    api.getNews.mockResolvedValueOnce([])

    const w = mount(App)
    await flushPromises()
    await flushPromises()
    expect(w.text()).toContain('还没有数据')
  })

  it('点击采集按钮后显示采集结果', async () => {
    const w = await mountApp()
    await w.find('button.btn').trigger('click')
    // sync 里先 await 采集、再 await loadAll,需要多轮微任务
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(w.text()).toContain('采集完成')
    expect(w.text()).toContain('新增日线 5 条')
  })

  it('后端不可用时给出提示而不是崩溃', async () => {
    const api = await import('../src/api')
    api.listStocks.mockRejectedValueOnce(new Error('connect ECONNREFUSED'))

    const w = mount(App)
    await flushPromises()
    await flushPromises()
    expect(w.text()).toContain('无法连接后端')
  })
})

describe('情感分析面板', () => {
  it('展示模型名与测试集指标', async () => {
    const w = await mountApp()
    const text = w.text()
    expect(text).toContain('BERT')
    expect(text).toContain('75.40%')
    expect(text).toContain('74.91%')
    expect(text).toContain('2130')
  })

  it('展示情感条数与占比', async () => {
    const w = await mountApp()
    const text = w.text()
    expect(text).toContain('共 4 条已标注新闻')
    expect(text).toContain('75.00%')
    expect(text).toContain('25.00%')
  })

  it('总结占比最高的一类', async () => {
    const w = await mountApp()
    expect(w.text()).toContain('「利好」占比最高')
  })

  it('情感图表配置正确', async () => {
    const w = await mountApp()
    const pie = optionOf(w, '情感分布')
    expect(pie.series[0].data).toEqual([
      { name: '利好', value: 3, itemStyle: { color: COLORS.pos } },
      { name: '利空', value: 1, itemStyle: { color: COLORS.neg } },
    ])
    // 趋势图的三条 series 都叫情感名,用 type=bar 与饼图区分开
    const trend = optionOf(w, '利好', 'bar')
    expect(trend.xAxis.data).toEqual(['2026-10-12', '2026-10-13'])
    expect(trend.series.map((s) => s.name)).toEqual(['利好', '利空', '中性'])
  })

  it('没有模型时提示先训练', async () => {
    const api = await import('../src/api')
    api.getSentimentInfo.mockResolvedValueOnce({
      available: [], active: null, labels: [],
    })

    const w = mount(App)
    await flushPromises()
    await flushPromises()
    expect(w.text()).toContain('尚未训练情感模型')
  })

  it('有模型但该股无标注时提示去采集', async () => {
    const api = await import('../src/api')
    api.getStockSentiment.mockResolvedValueOnce({
      code: '600519', model: 'bert', total: 0, zero: true,
      counts: { positive: 0, negative: 0, neutral: 0 },
      ratio: { positive: 0, negative: 0, neutral: 0 }, daily: [],
    })

    const w = mount(App)
    await flushPromises()
    await flushPromises()
    expect(w.text()).toContain('还没有情感标注')
  })

  it('情感接口失败不影响页面其余部分', async () => {
    const api = await import('../src/api')
    api.getStockSentiment.mockRejectedValueOnce(new Error('503'))

    const w = await mountApp()
    // 新闻与概览照常渲染
    expect(w.text()).toContain('贵州茅台重回A股股王')
    expect(w.text()).toContain('1274.89')
  })

  it('采集结果包含情感标注条数', async () => {
    const w = await mountApp()
    await w.find('button.btn').trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(w.text()).toContain('情感标注 2 条')
  })
})
