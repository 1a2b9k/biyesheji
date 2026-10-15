<script setup>
/**
 * 情感分析面板:模型状态 + 分布饼图 + 日线趋势 + 计数条。
 *
 * 设计取向:
 *   - 模型没训练时后端返回 zero=true,这里显示引导文案而不是空图。
 *   - 指标(准确率/宏F1)来自测试集,直接显示在标题旁,避免
 *     用户误以为这是"实时准确率"。
 *   - 计数条用「同色底 + 大号等宽数字 + 一条按占比伸缩的横条」,
 *     而不是三个并列色块:横条长度本身就是比例,不用读百分数。
 */
import { computed } from 'vue'

import EChart from './EChart.vue'
import {
  buildSentimentPieOption,
  buildSentimentTrendOption,
} from '../utils/chart.js'

const props = defineProps({
  data: { type: Object, default: null },
  info: { type: Object, default: null },
})

const pieOption = computed(() =>
  buildSentimentPieOption(props.data?.counts ?? {}))
const trendOption = computed(() =>
  buildSentimentTrendOption(props.data?.daily ?? []))

const hasData = computed(() => props.data && props.data.total > 0)

/** 模型是否已训练 —— 决定提示文案是"没模型"还是"没数据"。 */
const modelReady = computed(() => Boolean(props.info?.active))

const metrics = computed(() => props.info?.metrics ?? null)

function pct(v) {
  const n = Number(v)
  return Number.isFinite(n) ? (n * 100).toFixed(2) + '%' : '-'
}

/** 计数条:每类一行,含数量、占比、以及用于画横条的比例。 */
const rows = computed(() => {
  const c = props.data?.counts ?? {}
  const total = props.data?.total ?? 0
  const defs = [
    { key: 'positive', name: '利好', cls: 'pos' },
    { key: 'negative', name: '利空', cls: 'neg' },
    { key: 'neutral', name: '中性', cls: 'neu' },
  ]
  return defs.map((d) => {
    const n = c[d.key] ?? 0
    return {
      ...d,
      n,
      pctText: pct(total ? n / total : 0),
      width: total ? (n / total) * 100 : 0,
    }
  })
})

/** 占比最高的一类,用于一句话总结。 */
const dominant = computed(() => {
  const hit = [...rows.value].sort((a, b) => b.n - a.n)[0]
  return hit && hit.n > 0 ? hit.name : null
})
</script>

<template>
  <section class="panel">
    <header class="head">
      <h2>情感分析</h2>
      <span v-if="modelReady" class="badge num">
        {{ info.active.toUpperCase() }}
      </span>
      <span v-if="metrics" class="metrics num">
        测试集准确率 {{ pct(metrics.accuracy) }}
        · 宏 F1 {{ pct(metrics.macro_f1) }}
        · {{ metrics.n_test }} 条
      </span>
    </header>

    <!-- 三种状态:没模型 / 有模型没数据 / 有数据 -->
    <p v-if="!modelReady" class="empty">
      尚未训练情感模型。运行
      <code>python tools/train_sentiment.py --model both</code> 后重启后端。
    </p>

    <p v-else-if="!hasData" class="empty">
      该股票还没有情感标注。点击右上角「采集最新数据」,新抓到的新闻会自动标注。
    </p>

    <template v-else>
      <p class="summary">
        共 <b class="num">{{ data.total }}</b> 条已标注新闻<template
          v-if="dominant"
        >,其中「{{ dominant }}」占比最高</template>。
      </p>

      <!-- 计数条:横条长度即占比 -->
      <ul class="counts">
        <li v-for="r in rows" :key="r.key" :class="r.cls">
          <div class="top">
            <span class="name">{{ r.name }}</span>
            <span class="n num">{{ r.n }}</span>
            <span class="p num">{{ r.pctText }}</span>
          </div>
          <div class="track">
            <div class="fill" :style="{ width: r.width + '%' }" />
          </div>
        </li>
      </ul>

      <div class="grid">
        <div>
          <h3>整体分布</h3>
          <EChart :option="pieOption" height="250px" />
        </div>
        <div>
          <h3>日线趋势 <span class="hint2">按发布日堆叠</span></h3>
          <EChart :option="trendOption" height="250px" />
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
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
h3 {
  font-size: var(--fs-label);
  margin: 0 0 6px;
  color: var(--muted);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.badge {
  background: var(--ink);
  color: var(--accent-ink);
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 2px;
  letter-spacing: 0.06em;
}
.metrics {
  font-size: var(--fs-label);
  color: var(--muted);
  font-weight: 400;
  margin-left: auto;
}

.empty {
  color: var(--muted);
  font-size: var(--fs-body);
  padding: 10px 0 6px;
  margin: 0;
}
.empty code {
  background: var(--surface-2);
  border: 1px solid var(--line);
  padding: 1px 6px;
  border-radius: 2px;
  font-family: var(--font-num);
  font-size: var(--fs-label);
  color: var(--ink-2);
}

.summary {
  font-size: var(--fs-body);
  color: var(--ink-2);
  margin: 0 0 16px;
}
.summary b {
  color: var(--ink);
  font-size: var(--fs-lead);
}

/* —— 计数条 —— */
.counts {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
  margin: 0 0 20px;
  padding: 0;
}

.top {
  display: flex;
  align-items: baseline;
  gap: 7px;
  margin-bottom: 6px;
}
.name {
  font-size: var(--fs-label);
  color: var(--muted);
  font-weight: 600;
}
.n {
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--ink);
  margin-left: auto;
}
.p {
  font-size: var(--fs-label);
  color: var(--muted-2);
  min-width: 52px;
  text-align: right;
}

.track {
  height: 4px;
  background: var(--line-2);
  border-radius: 2px;
  overflow: hidden;
}
.fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.35s ease;
}
.counts .pos .fill { background: var(--pos); }
.counts .neg .fill { background: var(--neg); }
.counts .neu .fill { background: var(--neu); }

/* —— 图表 —— */
.grid {
  display: grid;
  grid-template-columns: 1fr 1.5fr;
  gap: 22px;
}
.hint2 {
  font-size: 10px;
  color: var(--muted-2);
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
}

@media (max-width: 900px) {
  .grid { grid-template-columns: 1fr; }
  .counts { grid-template-columns: 1fr; gap: 12px; }
  .metrics { margin-left: 0; }
}
</style>
