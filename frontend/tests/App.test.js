/**
 * 主页面集成测试。
 *
 * 用 jsdom 真实挂载整个 App(含子组件),只把网络请求打桩。
 * 这样验证的是"页面组合起来能不能正确渲染",而不只是单个函数。
 * ECharts 依赖 canvas,在 jsdom 下无法初始化,故整体打桩 ——
 * 图表配置的正确性由 chart.test.js 覆盖。
 *
 * 页面按功能分成四个页签后,不在当前页签的内容不会被渲染(v-if),
 * 所以每个用例都先声明自己在看哪一页(见 mountTab)。
 * 这顺带成了一条额外断言:若某个组件漏了 v-if 而一直留在 DOM 里,
 * "不在该页时不应出现"的用例会立刻抓到。
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

const RETURNS = {
  code: '600519',
  news_total: 4,
  kline_total: 2,
  stats: {
    n: 40,
    pearson: 0.412,
    spearman: 0.398,
    p_value: 0.0084,
    polarity_mean: 0.21,
    return_mean: 0.15,
    groups: { low: -1.2, mid: 0.05, high: 1.65 },
    hit_rate: 0.625,
    hit_n: 32,
  },
  pairs: [
    { date: '2026-10-12', polarity: -1, return: -1.8, n: 2 },
    { date: '2026-10-13', polarity: 0.5, return: 0.9, n: 1 },
    { date: '2026-10-14', polarity: 1, return: 1.7, n: 3 },
  ],
}

// 打桩:网络层与图表组件
vi.mock('../src/api', () => ({
  listStocks: vi.fn(() => Promise.resolve(STOCKS)),
  getOverview: vi.fn(() => Promise.resolve(OVERVIEW)),
  getKlines: vi.fn(() => Promise.resolve(KLINES)),
  getNews: vi.fn(() => Promise.resolve(NEWS)),
  getSentimentInfo: vi.fn(() => Promise.resolve(SENTIMENT_INFO)),
  getStockSentiment: vi.fn(() => Promise.resolve(SENTIMENT)),
  getStockReturns: vi.fn(() => Promise.resolve(RETURNS)),
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
 * 挂载并切到指定页签。
 *
 * 默认页签是「行情概览」,所以 overview 可以直接 mountApp;
 * 其余三页都要先点一下页签。
 */
async function mountTab(tab) {
  const w = await mountApp()
  if (tab !== 'overview') {
    await w.find(`[data-tab="${tab}"]`).trigger('click')
    await flushPromises()
  }
  return w
}

/**
 * 按 series 名找图表配置。
 *
 * 不用下标:页面改布局会让图表顺序变化,下标断言会因此误报,
 * 而"哪个图拿到哪份数据"才是真正要测的。
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

describe('功能导航', () => {
  it('渲染四个页签', async () => {
    const w = await mountApp()
    const tabs = w.findAll('[role="tab"]')
    expect(tabs).toHaveLength(4)
    expect(tabs.map((t) => t.find('.label').text())).toEqual([
      '行情概览', '情感分析', '情感与收益', '新闻列表',
    ])
  })

  it('默认停在行情概览', async () => {
    const w = await mountApp()
    const on = w.find('[role="tab"][aria-selected="true"]')
    expect(on.attributes('data-tab')).toBe('overview')
  })

  it('页签上带各页条数', async () => {
    const w = await mountApp()
    // K 线 2 条、情感 4 条、关联 40 个样本、新闻 2 条
    expect(w.find('[data-tab="overview"] .badge').text()).toBe('2')
    expect(w.find('[data-tab="sentiment"] .badge').text()).toBe('4')
    expect(w.find('[data-tab="returns"] .badge').text()).toBe('40')
    expect(w.find('[data-tab="news"] .badge').text()).toBe('2')
  })

  it('点击页签切换当前视图', async () => {
    const w = await mountApp()
    await w.find('[data-tab="news"]').trigger('click')
    await flushPromises()
    expect(w.find('[role="tab"][aria-selected="true"]').attributes('data-tab')).toBe('news')
    expect(w.text()).toContain('贵州茅台重回A股股王')
  })

  it('同一时刻只渲染一页的内容', async () => {
    const w = await mountTab('news')
    // 新闻页:有新闻,没有概览读数与 K 线
    expect(w.text()).toContain('贵州茅台重回A股股王')
    expect(w.text()).not.toContain('最新收盘')
    expect(w.findAll('.echart-stub')).toHaveLength(0)
  })

  it('四个页签的内容互不重叠', async () => {
    const overview = await mountTab('overview')
    expect(overview.text()).toContain('最新收盘')
    expect(overview.text()).not.toContain('相关新闻')

    const sentiment = await mountTab('sentiment')
    expect(sentiment.text()).toContain('情感分析')
    expect(sentiment.text()).not.toContain('最新收盘')

    const returns = await mountTab('returns')
    expect(returns.text()).toContain('情感与收益')
    expect(returns.text()).not.toContain('最新收盘')
  })

  it('切换页签后数据不丢,切回不用重新请求', async () => {
    const api = await import('../src/api')
    const w = await mountApp()
    const before = api.getKlines.mock.calls.length

    await w.find('[data-tab="news"]').trigger('click')
    await flushPromises()
    await w.find('[data-tab="overview"]').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('最新收盘')
    expect(api.getKlines.mock.calls.length).toBe(before)
  })
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
    const w = await mountTab('overview')
    const text = w.text()
    expect(text).toContain('最新收盘')
    expect(text).toContain('2026-10-13')
    expect(text).toContain('1274.89')
  })

  it('涨跌幅带符号显示', async () => {
    const w = await mountTab('overview')
    expect(w.text()).toContain('-1.02%')
  })

  it('渲染新闻列表', async () => {
    const w = await mountTab('news')
    expect(w.text()).toContain('贵州茅台重回A股股王')
    expect(w.text()).toContain('11只白酒股下跌')
  })

  it('四个图表分属三个页签,各页只画自己的图', async () => {
    // 分页前这条断言是"整页共 4 个图";分页后每个页签各自持有自己的图,
    // 数量不能相加 —— 加在一起就说明 v-if 没起作用。
    expect((await mountTab('overview')).findAll('.echart-stub')).toHaveLength(1)
    expect((await mountTab('sentiment')).findAll('.echart-stub')).toHaveLength(2)
    expect((await mountTab('returns')).findAll('.echart-stub')).toHaveLength(1)
    expect((await mountTab('news')).findAll('.echart-stub')).toHaveLength(0)
  })

  it('K线图收到的配置含正确的日期轴', async () => {
    const w = await mountTab('overview')
    const kline = optionOf(w, 'K线')
    expect(kline.xAxis[0].data).toEqual([
      '2026-10-12', '2026-10-13',
    ])
  })

  it('来源分布不再是彩色饼图,而是条状列表', async () => {
    const w = await mountTab('sentiment')
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

  it('采集提示在切换页签后仍然可见', async () => {
    // 提示挂在页签之外(StockBar 下面),属于全局状态,不该随页签消失
    const w = await mountApp()
    await w.find('button.btn').trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    await w.find('[data-tab="news"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('采集完成')
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
    const w = await mountTab('sentiment')
    const text = w.text()
    expect(text).toContain('BERT')
    expect(text).toContain('75.40%')
    expect(text).toContain('74.91%')
    expect(text).toContain('2130')
  })

  it('展示情感条数与占比', async () => {
    const w = await mountTab('sentiment')
    const text = w.text()
    expect(text).toContain('共 4 条已标注新闻')
    expect(text).toContain('75.00%')
    expect(text).toContain('25.00%')
  })

  it('总结占比最高的一类', async () => {
    const w = await mountTab('sentiment')
    expect(w.text()).toContain('「利好」占比最高')
  })

  it('情感图表配置正确', async () => {
    const w = await mountTab('sentiment')
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
    await w.find('[data-tab="sentiment"]').trigger('click')
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
    await w.find('[data-tab="sentiment"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('还没有情感标注')
  })

  it('情感接口失败不影响页面其余部分', async () => {
    const api = await import('../src/api')
    api.getStockSentiment.mockRejectedValueOnce(new Error('503'))

    const w = await mountApp()
    // 概览页照常渲染
    expect(w.text()).toContain('1274.89')
    // 新闻页照常渲染
    await w.find('[data-tab="news"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('贵州茅台重回A股股王')
  })

  it('情感接口失败时不谎称「还没有标注」', async () => {
    // 503 与"确实没有数据"要分开讲:说成"还没有标注"会把用户指向
    // 一个无效动作(去点采集),采回来照样取不到。
    const api = await import('../src/api')
    api.getStockSentiment.mockRejectedValueOnce(new Error('503'))

    const w = await mountApp()
    await w.find('[data-tab="sentiment"]').trigger('click')
    await flushPromises()

    const text = w.text()
    expect(text).toContain('情感数据加载失败')
    expect(text).not.toContain('该股票还没有情感标注')
  })

  it('快速切股时迟到的响应不覆盖当前股票', async () => {
    // 先后两次 loadAll 并发,先发的可能后返回;没有请求序号时
    // 页面会显示上一只股票的行情配新股票的名字。
    const api = await import('../src/api')
    let resolveSlow
    const slow = new Promise((r) => { resolveSlow = r })

    // 第一次(600519)的 overview 卡住,第二次(300750)立刻返回
    api.getOverview
      .mockImplementationOnce(() => slow)
      .mockImplementationOnce(() => Promise.resolve({
        ...OVERVIEW,
        code: '300750',
        name: '宁德时代',
        latest: { ...OVERVIEW.latest, close: 11.11 },
      }))

    const w = mount(App)
    await flushPromises()
    await flushPromises()

    // 切到第二只股票
    await w.find('select.picker').setValue('300750')
    await flushPromises()
    expect(w.text()).toContain('11.11')

    // 第一只的 overview 此时才回来:不该把画面改回 1274.89
    resolveSlow({ ...OVERVIEW, latest: { ...OVERVIEW.latest, close: 1274.89 } })
    await flushPromises()
    await flushPromises()

    expect(w.text()).toContain('11.11')
    expect(w.text()).not.toContain('1274.89')
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

describe('情感与收益面板', () => {
  it('展示相关系数与样本量', async () => {
    const w = await mountTab('returns')
    const text = w.text()
    expect(text).toContain('0.412')
    expect(text).toContain('0.398')
    expect(text).toContain('40 个股票-日样本')
  })

  it('p 值显著时给出具体数值', async () => {
    const w = await mountTab('returns')
    expect(w.text()).toContain('0.008')
  })

  it('样本充足时不显示可靠性警告', async () => {
    const w = await mountTab('returns')
    expect(w.text()).not.toContain('低于 30 个时相关系数波动很大')
  })

  it('样本不足时明确提示相关系数不可靠', async () => {
    const api = await import('../src/api')
    api.getStockReturns.mockResolvedValueOnce({
      ...RETURNS,
      stats: { ...RETURNS.stats, n: 12 },
    })

    const w = mount(App)
    await flushPromises()
    await flushPromises()
    await w.find('[data-tab="returns"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('低于 30 个时相关系数波动很大')
  })

  it('散点图配置正确', async () => {
    const w = await mountTab('returns')
    const scatter = optionOf(w, '样本', 'scatter')
    expect(scatter.series[0].data).toEqual([
      [-1, -1.8], [0.5, 0.9], [1, 1.7],
    ])
    expect(scatter.xAxis.min).toBe(-1)
    expect(scatter.xAxis.max).toBe(1)
  })

  it('展示分组平均收益', async () => {
    const w = await mountTab('returns')
    const text = w.text()
    expect(text).toContain('低情感组')
    expect(text).toContain('高情感组')
    expect(text).toContain('-1.20%')
    expect(text).toContain('+1.65%')
  })

  it('没有配对样本时给出说明而不是空图', async () => {
    const api = await import('../src/api')
    api.getStockReturns.mockResolvedValueOnce({
      code: '600519', news_total: 0, kline_total: 0,
      stats: { n: 0, pearson: null, spearman: null, p_value: null,
        groups: {}, hit_rate: null, hit_n: 0 },
      pairs: [],
    })

    const w = mount(App)
    await flushPromises()
    await flushPromises()
    await w.find('[data-tab="returns"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('还没有可用的配对样本')
  })

  it('有样本但算不出相关系数时不显示成 0 且显著', async () => {
    // 后端在样本过少或某一侧方差为零时返回 pearson/p_value = null。
    // Number(null) === 0,直接喂给 toFixed 会显示 r=0.000、p<0.001 并标绿,
    // 把「无法估计」讲成「等于零且显著」——这是必须挡住的一条。
    const api = await import('../src/api')
    api.getStockReturns.mockResolvedValueOnce({
      ...RETURNS,
      stats: { ...RETURNS.stats, n: 3, pearson: null, spearman: null,
        p_value: null, hit_rate: null, hit_n: 0 },
    })

    const w = mount(App)
    await flushPromises()
    await flushPromises()
    await w.find('[data-tab="returns"]').trigger('click')
    await flushPromises()

    const text = w.text()
    expect(text).toContain('无法估计')
    expect(text).toContain('这一组样本算不出相关系数')
    // 不能出现伪造的读数
    expect(text).not.toContain('0.000')
    expect(text).not.toContain('< 0.001')
    // 显著性标记:sig 类名不该落到 p 值上
    const sigCount = w.findAll('.v.sig').length
    expect(sigCount).toBe(0)
  })

  it('分组收益缺值时不标成上涨', async () => {
    const api = await import('../src/api')
    api.getStockReturns.mockResolvedValueOnce({
      ...RETURNS,
      stats: { ...RETURNS.stats, groups: { low: null, mid: 0.0012, high: -0.0088 } },
    })

    const w = mount(App)
    await flushPromises()
    await flushPromises()
    await w.find('[data-tab="returns"]').trigger('click')
    await flushPromises()

    const rows = w.findAll('.groups li')
    expect(rows.length).toBe(3)
    // 第一组缺值:数值显示 '-'，且不该带 up/down 任一着色
    const first = rows[0]
    expect(first.text()).toContain('-')
    expect(first.find('.gval').classes()).not.toContain('up')
    expect(first.find('.gval').classes()).not.toContain('down')
  })

  it('关联接口失败不影响页面其余部分', async () => {
    const api = await import('../src/api')
    api.getStockReturns.mockRejectedValueOnce(new Error('503'))

    const w = await mountApp()
    await w.find('[data-tab="news"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('贵州茅台重回A股股王')

    await w.find('[data-tab="returns"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('还没有可用的配对样本')
  })
})
