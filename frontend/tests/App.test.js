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

// 打桩:网络层与图表组件
vi.mock('../src/api', () => ({
  listStocks: vi.fn(() => Promise.resolve(STOCKS)),
  getOverview: vi.fn(() => Promise.resolve(OVERVIEW)),
  getKlines: vi.fn(() => Promise.resolve(KLINES)),
  getNews: vi.fn(() => Promise.resolve(NEWS)),
  syncStock: vi.fn(() => Promise.resolve({ kline_added: 5, news_added: 3, errors: [] })),
}))

vi.mock('../src/components/EChart.vue', () => ({
  default: { name: 'EChart', props: ['option', 'height'], template: '<div class="echart-stub" />' },
}))

import App from '../src/App.vue'

async function mountApp() {
  const w = mount(App)
  await flushPromises()
  await flushPromises()
  return w
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

  it('渲染概览卡片与最新价', async () => {
    const w = await mountApp()
    const text = w.text()
    expect(text).toContain('最新交易日')
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

  it('渲染两个图表位(K线 + 来源分布)', async () => {
    const w = await mountApp()
    expect(w.findAll('.echart-stub')).toHaveLength(2)
  })

  it('K线图收到的配置含正确的日期轴', async () => {
    const w = await mountApp()
    const charts = w.findAllComponents({ name: 'EChart' })
    const klineChart = charts[0]
    expect(klineChart.props('option').xAxis[0].data).toEqual([
      '2026-10-12', '2026-10-13',
    ])
  })

  it('饼图收到的配置来自 news_sources', async () => {
    const w = await mountApp()
    const charts = w.findAllComponents({ name: 'EChart' })
    const pie = charts[1]
    expect(pie.props('option').series[0].data).toEqual([
      { name: '新华财经', value: 1 },
      { name: '北京商报', value: 1 },
    ])
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
