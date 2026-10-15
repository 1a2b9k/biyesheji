<script setup>
/**
 * 主页面:股票选择 → 概览读数 + K 线 + 新闻 + 情感分析。
 *
 * 数据流:选股 → 并行拉 overview / klines / news / sentiment → 交给子组件渲染。
 *
 * 布局:两栏。左栏是"行情"(读数 + K 线),右栏是"舆情"(来源分布 + 情感)。
 * 这样同一时刻的价与情可以对照着看,比上下堆叠更符合分析场景。
 */
import { computed, onMounted, ref } from 'vue'

import { getKlines, getNews, getOverview, getSentimentInfo, getStockSentiment, listStocks, syncStock } from './api'
import EChart from './components/EChart.vue'
import NewsList from './components/NewsList.vue'
import OverviewCards from './components/OverviewCards.vue'
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
const loading = ref(false)
const syncing = ref(false)
const message = ref('')

const klineOption = computed(() => buildKlineOption(klines.value))

const currentName = computed(() =>
  stocks.value.find((s) => s.code === current.value)?.name ?? '')

async function loadAll(code) {
  if (!code) return
  loading.value = true
  message.value = ''
  try {
    const [o, k, n, s] = await Promise.all([
      getOverview(code),
      getKlines(code, 250),
      getNews(code, 50),
      // 情感数据失败不该让整页打不开:模型可能压根没训练,
      // 这时后端返回空统计,单独 catch 更稳妥。
      getStockSentiment(code).catch(() => null),
    ])
    overview.value = o
    klines.value = k
    news.value = n
    sentiment.value = s
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

      <OverviewCards :overview="overview" />

      <!--
        版面按"宽度需求"分行,而不是硬凑两栏等高:
        K 线和新闻需要横向空间,给整行;情感与来源都是卡片式内容,并排即可。
        这样每行左右高度天然接近,不会出现某栏底下空一大块的情况。
      -->
      <section class="panel">
        <header class="head">
          <h2>K 线走势</h2>
          <span class="meta num">
            {{ currentName }} · 最近 {{ klines.length }} 个交易日
          </span>
        </header>
        <EChart v-if="klines.length" :option="klineOption" height="440px" />
        <p v-else class="empty">暂无行情数据</p>
      </section>

      <div class="cols">
        <div class="col">
          <SentimentPanel :data="sentiment" :info="sentimentInfo" />
        </div>
        <div class="col">
          <SourceBreakdown :sources="overview?.news_sources ?? []" />
        </div>
      </div>

      <NewsList :news="news" />
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
.col .panel:last-child {
  margin-bottom: 0;
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
