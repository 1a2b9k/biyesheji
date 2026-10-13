<script setup>
/**
 * 概览卡片:最新价、涨跌幅、数据量。
 */
import { computed } from 'vue'
import { formatAmount, formatChangePct } from '../utils/chart.js'

const props = defineProps({
  overview: { type: Object, default: null },
})

const change = computed(() =>
  formatChangePct(props.overview?.latest?.change_pct ?? NaN))

const cards = computed(() => {
  const o = props.overview
  if (!o) return []
  return [
    { label: '最新交易日', value: o.latest?.trade_date ?? '-' },
    { label: '收盘价', value: o.latest ? o.latest.close.toFixed(2) : '-' },
    { label: '涨跌幅', value: change.value.text, color: change.value.color },
    { label: '成交量', value: o.latest ? formatAmount(o.latest.volume) : '-' },
    { label: '成交额', value: o.latest ? formatAmount(o.latest.amount) : '-' },
    { label: '历史日线', value: (o.kline_count ?? 0).toLocaleString() + ' 条' },
    { label: '新闻', value: (o.news_count ?? 0) + ' 条' },
  ]
})
</script>

<template>
  <section class="cards">
    <div v-for="c in cards" :key="c.label" class="card">
      <div class="label">{{ c.label }}</div>
      <div class="value" :style="c.color ? { color: c.color } : null">
        {{ c.value }}
      </div>
    </div>
  </section>
</template>

<style scoped>
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.card {
  background: #fff;
  border-radius: 6px;
  padding: 14px 16px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.07);
}
.label { font-size: 12px; color: #909399; margin-bottom: 7px; }
.value { font-size: 19px; font-weight: 600; color: #303133; }
</style>
