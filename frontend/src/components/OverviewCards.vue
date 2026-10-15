<script setup>
/**
 * 概览数据条:最新交易日、收盘价、涨跌幅、成交量、成交额、数据量。
 *
 * 设计取向:把「价格」做成主读数(大号等宽数字),其余做成次级读数,
 * 而不是七个同样大小的方块。数据页需要一眼看出哪个数字最重要;
 * 等大的卡片墙会强迫用户逐个读过去。
 *
 * 数字一律用 .num(等宽 + tabular-nums),上下两行的小数点会对齐。
 */
import { computed } from 'vue'

import { formatAmount, formatChangePct } from '../utils/chart.js'

const props = defineProps({
  overview: { type: Object, default: null },
})

const change = computed(() =>
  formatChangePct(props.overview?.latest?.change_pct ?? NaN))

const close = computed(() => {
  const c = props.overview?.latest?.close
  return Number.isFinite(Number(c)) ? Number(c).toFixed(2) : '-'
})

/** 次级读数:价格以外的六项。 */
const facts = computed(() => {
  const o = props.overview
  if (!o) return []
  const l = o.latest
  return [
    { label: '成交量', value: l ? formatAmount(l.volume) : '-' },
    { label: '成交额', value: l ? formatAmount(l.amount) : '-' },
    { label: '历史日线', value: (o.kline_count ?? 0).toLocaleString(), unit: '条' },
    { label: '新闻', value: String(o.news_count ?? 0), unit: '条' },
  ]
})
</script>

<template>
  <section class="overview">
    <!-- 主读数 -->
    <div class="primary">
      <div class="eyebrow">最新收盘</div>
      <div class="close num">{{ close }}</div>
      <div class="meta">
        <span class="num" :style="{ color: change.color }">{{ change.text }}</span>
        <span class="sep">|</span>
        <span class="date num">{{ overview?.latest?.trade_date ?? '-' }}</span>
      </div>
    </div>

    <!-- 次级读数 -->
    <dl class="facts">
      <div v-for="f in facts" :key="f.label" class="fact">
        <dt>{{ f.label }}</dt>
        <dd>
          <span class="num">{{ f.value }}</span>
          <span v-if="f.unit" class="unit">{{ f.unit }}</span>
        </dd>
      </div>
    </dl>
  </section>
</template>

<style scoped>
.overview {
  display: grid;
  grid-template-columns: minmax(230px, 1fr) 3fr;
  gap: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r);
  margin-bottom: 16px;
  overflow: hidden;
}

/* 主读数区:用浅一档的底色把价格和其余数字分开,不靠投影 */
.primary {
  padding: 18px 22px;
  background: var(--surface-2);
  border-right: 1px solid var(--line);
}

.close {
  font-size: 40px;
  font-weight: 600;
  line-height: 1.05;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin: 8px 0 6px;
}

.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-body);
  font-weight: 600;
}
.meta .sep {
  color: var(--line);
}
.meta .date {
  color: var(--muted);
  font-weight: 400;
  font-size: var(--fs-label);
}

.facts {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin: 0;
  padding: 0;
}

.fact {
  padding: 18px 20px;
  border-right: 1px solid var(--line-2);
}
.fact:last-child {
  border-right: none;
}

.fact dt {
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted-2);
  font-weight: 600;
  margin-bottom: 9px;
}

.fact dd {
  margin: 0;
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--ink);
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.fact .unit {
  font-size: var(--fs-label);
  font-weight: 400;
  color: var(--muted);
}

@media (max-width: 980px) {
  .overview {
    grid-template-columns: 1fr;
  }
  .primary {
    border-right: none;
    border-bottom: 1px solid var(--line);
  }
  .facts {
    grid-template-columns: repeat(2, 1fr);
  }
  .fact:nth-child(2n) {
    border-right: none;
  }
  .fact:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line-2);
  }
}
</style>
