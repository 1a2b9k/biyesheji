<script setup>
/**
 * 主页面:股票选择 → 概览卡片 + K 线图 + 新闻列表。
 *
 * 数据流:选股 → 并行拉 overview / klines / news → 交给子组件渲染。
 */
import { computed, onMounted, ref } from 'vue'

import { getKlines, getNews, getOverview, getSentimentInfo, getStockSentiment, listStocks, syncStock } from './api'
import EChart from './components/EChart.vue'
import NewsList from './components/NewsList.vue'
import OverviewCards from './components/OverviewCards.vue'
import SentimentPanel from './components/SentimentPanel.vue'
import StockBar from './components/StockBar.vue'
import { buildKlineOption, buildSourcePieOption } from './utils/chart.js'

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
const pieOption = computed(() =>
  buildSourcePieOption(overview.value?.news_sources ?? []))

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
      <p v-if="loading" class="msg">加载中…</p>

      <OverviewCards :overview="overview" />

      <div class="grid">
        <div class="panel">
          <h2>K 线走势 <span class="hint">最近 {{ klines.length }} 个交易日</span></h2>
          <EChart v-if="klines.length" :option="klineOption" height="420px" />
          <p v-else class="empty">暂无行情数据</p>
        </div>

        <div class="panel">
          <h2>新闻来源分布</h2>
          <EChart
            v-if="overview?.news_sources?.length"
            :option="pieOption"
            height="420px"
          />
          <p v-else class="empty">暂无新闻数据</p>
        </div>
      </div>

      <NewsList :news="news" />

      <SentimentPanel :data="sentiment" :info="sentimentInfo" />
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; background: #f0f2f5; }
.body { padding: 20px; max-width: 1500px; margin: 0 auto; }
.msg {
  background: #ecf5ff; color: #409eff; padding: 9px 14px;
  border-radius: 4px; font-size: 13px; margin: 0 0 14px;
}
.grid {
  display: grid; grid-template-columns: 2fr 1fr; gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }
.panel {
  background: #fff; border-radius: 6px; padding: 16px 18px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.07);
}
h2 { font-size: 15px; margin: 0 0 10px; color: #303133; }
.hint { font-size: 12px; color: #909399; font-weight: 400; }
.empty { color: #909399; font-size: 13px; padding: 30px 0; text-align: center; }
</style>
