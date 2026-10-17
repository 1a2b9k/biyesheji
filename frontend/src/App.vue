<script setup>
/**
 * 主页面:股票选择 + 四个功能视图(行情概览 / 情感分析 / 情感与收益 / 新闻列表)。
 *
 * 数据流:选股 → 并行拉 overview / klines / news / sentiment / returns
 * → 交给当前页签的组件渲染。
 *
 * 为什么改成页签而不是继续堆在一页:
 *   原先五块内容纵向排开,一屏放不下,用户要滚很久才看到新闻;
 *   而看盘时"先看价、再看情绪、再看新闻"本来就是分阶段的动作,
 *   同一时刻只关心其中一块。分页后每页都短,页签上带条数,
 *   不用点进去就知道哪页有数据。
 *
 * 为什么切页用 v-if 而不是 v-show:
 *   ECharts 在 display:none 的容器里初始化会拿到 0 宽度,图表画不出来;
 *   v-if 让图表在页签真正可见时才挂载,量到的尺寸是对的。
 *   代价是每次切回都要重建图表,但一次重建几十毫秒,无感。
 *
 * 为什么五份数据一次性拉完而不是进哪页拉哪页:
 *   五个请求本来就并行、总量只有几百 KB,一次拉完切页是瞬时的;
 *   按页懒加载反而会让每次切页都闪一次加载态。
 */
import { computed, onMounted, ref } from 'vue'

import { getKlines, getNews, getOverview, getSentimentInfo, getStockReturns, getStockSentiment, listStocks, syncStock } from './api'
import EChart from './components/EChart.vue'
import NavTabs from './components/NavTabs.vue'
import NewsList from './components/NewsList.vue'
import OverviewCards from './components/OverviewCards.vue'
import ReturnsPanel from './components/ReturnsPanel.vue'
import SentimentPanel from './components/SentimentPanel.vue'
import SourceBreakdown from './components/SourceBreakdown.vue'
import StockBar from './components/StockBar.vue'
import { buildKlineOption } from './utils/chart.js'

const stocks = ref([])
const current = ref('')
const overview = ref(null)
const klines = ref([])
const news = ref([])
const sentiment = ref(null)
const sentimentInfo = ref(null)
const returns = ref(null)
const loading = ref(false)
const syncing = ref(false)
const message = ref('')
const activeTab = ref('overview')

const klineOption = computed(() => buildKlineOption(klines.value))

const currentName = computed(() =>
  stocks.value.find((s) => s.code === current.value)?.name ?? '')

/**
 * 页签定义。badge 是"这一页有多少条",为 0 时照样显示 ——
 * 0 本身是有用信息(该股没有这类数据),藏起来反而让人以为还没加载。
 */
const tabs = computed(() => [
  { key: 'overview', label: '行情概览', hint: '读数 · K 线', badge: klines.value.length },
  { key: 'sentiment', label: '情感分析', hint: '分布 · 来源', badge: sentiment.value?.total ?? 0 },
  { key: 'returns', label: '情感与收益', hint: '相关性 · 散点', badge: returns.value?.stats?.n ?? 0 },
  { key: 'news', label: '新闻列表', hint: '逐条标注', badge: news.value.length },
])

async function loadAll(code) {
  if (!code) return
  loading.value = true
  message.value = ''
  try {
    const [o, k, n, s, r] = await Promise.all([
      getOverview(code),
      getKlines(code, 250),
      getNews(code, 50),
      // 情感数据失败不该让整页打不开:模型可能压根没训练,
      // 这时后端返回空统计,单独 catch 更稳妥。
      getStockSentiment(code).catch(() => null),
      // 关联分析同理:样本不足是常态,不该阻断主页面。
      getStockReturns(code).catch(() => null),
    ])
    overview.value = o
    klines.value = k
    news.value = n
    sentiment.value = s
    returns.value = r
    if (!k.length && !n.length) {
      message.value = '该股票还没有数据,请点击「采集最新数据」。'
    }
  } catch (err) {
    message.value = '加载失败:' + (err?.message || err)
  } finally {
    loading.value = false
  }
}

async function onSync() {
  if (!current.value) return
  syncing.value = true
  message.value = ''
  try {
    const r = await syncStock(current.value)
    const parts = [`新增日线 ${r.kline_added} 条`, `新闻 ${r.news_added} 条`]
    if (r.sentiment_added) parts.push(`情感标注 ${r.sentiment_added} 条`)
    if (r.errors?.length) parts.push(`失败 ${r.errors.length} 项`)
    // 先刷新数据再写提示 —— loadAll 开头会清空 message,
    // 若顺序反过来,用户永远看不到"采集完成"。
    await loadAll(current.value)
    message.value = '采集完成:' + parts.join(',')
  } catch (err) {
    message.value = '采集失败:' + (err?.message || err)
  } finally {
    syncing.value = false
  }
}

function onSelect(code) {
  current.value = code
  loadAll(code)
}

onMounted(async () => {
  try {
    // 模型状态与股票列表互不依赖,并行拉;模型状态失败不影响主流程
    const [list, info] = await Promise.all([
      listStocks(),
      getSentimentInfo().catch(() => null),
    ])
    stocks.value = list
    sentimentInfo.value = info
    if (stocks.value.length) {
      current.value = stocks.value[0].code
      await loadAll(current.value)
    }
  } catch (err) {
    message.value = '无法连接后端,请确认服务已启动。'
  }
})
</script>

<template>
  <div class="page">
    <StockBar
      :stocks="stocks"
      :model-value="current"
      :syncing="syncing"
      @update:model-value="onSelect"
      @sync="onSync"
    />

    <main class="body">
      <p v-if="message" class="msg">{{ message }}</p>
      <p v-if="loading" class="msg loading">正在加载…</p>

      <NavTabs v-model="activeTab" :tabs="tabs" />

      <template v-if="activeTab === 'overview'">
        <OverviewCards :overview="overview" />

        <!-- K 线需要横向空间,单独占整行 -->
        <section class="panel">
          <header class="head">
            <h2>K 线走势</h2>
            <span class="meta num">
              {{ currentName }} · 最近 {{ klines.length }} 个交易日
            </span>
          </header>
          <EChart v-if="klines.length" :option="klineOption" height="460px" />
          <p v-else class="empty">暂无行情数据</p>
        </section>
      </template>

      <div v-else-if="activeTab === 'sentiment'" class="cols">
        <!-- 情感与来源并排:两者都是卡片式内容,宽度需求相近 -->
        <div class="col">
          <SentimentPanel :data="sentiment" :info="sentimentInfo" />
        </div>
        <div class="col">
          <SourceBreakdown :sources="overview?.news_sources ?? []" />
        </div>
      </div>

      <ReturnsPanel v-else-if="activeTab === 'returns'" :data="returns" />

      <NewsList v-else-if="activeTab === 'news'" :news="news" />
    </main>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  background: var(--bg);
}

.body {
  padding: 18px var(--pad-x) 40px;
  max-width: var(--maxw);
  margin: 0 auto;
}

.msg {
  background: var(--surface);
  border: 1px solid var(--line);
  border-left: 3px solid var(--ink);
  color: var(--ink-2);
  padding: 10px 14px;
  border-radius: var(--r);
  font-size: var(--fs-body);
  margin: 0 0 16px;
}
.msg.loading {
  border-left-color: var(--muted-2);
  color: var(--muted);
}

/* 情感与来源并排:两者都是卡片式内容,宽度需求相近 */
.cols {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}

.col {
  min-width: 0;
}

.col > :last-child {
  margin-bottom: 0;
}

.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r);
  padding: 18px 22px;
  margin-bottom: 16px;
}

.head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 2px solid var(--ink);
  margin-bottom: 14px;
}

h2 {
  font-size: var(--fs-title);
  margin: 0;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.meta {
  font-size: var(--fs-label);
  color: var(--muted);
  margin-left: auto;
}

.empty {
  color: var(--muted);
  font-size: var(--fs-body);
  padding: 34px 0;
  text-align: center;
  margin: 0;
}

@media (max-width: 1080px) {
  .cols {
    grid-template-columns: 1fr;
  }
}
</style>
