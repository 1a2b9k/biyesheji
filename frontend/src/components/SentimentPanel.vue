<script setup>
/**
 * 情感分析面板:模型状态 + 分布饼图 + 日线趋势。
 *
 * 设计要点:
 *   - 模型没训练时后端返回 zero=true,这里显示引导文案而不是空图。
 *   - 指标(准确率/宏F1)来自测试集,直接显示在标题旁,避免
 *     用户误以为这是"实时准确率"。
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

/** 占比最高的一类,用于一句话总结。 */
const dominant = computed(() => {
  const c = props.data?.counts
  if (!c) return null
  const order = ['positive', 'negative', 'neutral']
  const names = { positive: '利好', negative: '利空', neutral: '中性' }
  let best = null
  for (const k of order) {
    if (best === null || (c[k] ?? 0) > (c[best] ?? 0)) best = k
  }
  return (c[best] ?? 0) > 0 ? names[best] : null
})
</script>

<template>
  <section class="panel">
    <h2>
      情感分析
      <span v-if="modelReady" class="badge">{{ info.active.toUpperCase() }}</span>
      <span v-if="metrics" class="hint">
        测试集准确率 {{ pct(metrics.accuracy) }}
        · 宏 F1 {{ pct(metrics.macro_f1) }}
        ({{ metrics.n_test }} 条)
      </span>
    </h2>

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
        共 {{ data.total }} 条已标注新闻
        <template v-if="dominant">
          ,其中「{{ dominant }}」占比最高
        </template>
      </p>

      <div class="grid">
        <div>
          <h3>整体分布</h3>
          <EChart :option="pieOption" height="260px" />
        </div>
        <div>
          <h3>日线趋势 <span class="hint2">按发布日堆叠</span></h3>
          <EChart :option="trendOption" height="260px" />
        </div>
      </div>

      <ul class="counts">
        <li class="pos">
          利好 <b>{{ data.counts.positive }}</b>
          <span>{{ pct(data.ratio.positive) }}</span>
        </li>
        <li class="neg">
          利空 <b>{{ data.counts.negative }}</b>
          <span>{{ pct(data.ratio.negative) }}</span>
        </li>
        <li class="neu">
          中性 <b>{{ data.counts.neutral }}</b>
          <span>{{ pct(data.ratio.neutral) }}</span>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.panel {
  background: #fff; border-radius: 6px; padding: 16px 18px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.07); margin-bottom: 16px;
}
h2 { font-size: 15px; margin: 0 0 12px; color: #303133; }
h3 { font-size: 13px; margin: 0 0 6px; color: #606266; font-weight: 500; }
.badge {
  background: #ecf5ff; color: #409eff; font-size: 11px;
  padding: 1px 6px; border-radius: 3px; margin-left: 6px;
  font-weight: 400; vertical-align: middle;
}
.hint { font-size: 12px; color: #909399; font-weight: 400; margin-left: 8px; }
.hint2 { font-size: 11px; color: #c0c4cc; font-weight: 400; }
.empty { color: #909399; font-size: 13px; padding: 18px 0; }
.empty code {
  background: #f4f4f5; padding: 1px 5px; border-radius: 3px;
  font-size: 12px;
}
.summary { font-size: 13px; color: #606266; margin: 0 0 12px; }
.grid {
  display: grid; grid-template-columns: 1fr 1.4fr; gap: 18px;
}
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
.counts {
  list-style: none; display: flex; gap: 22px; margin: 14px 0 0;
  padding: 12px 0 0; border-top: 1px solid #f0f2f5; font-size: 13px;
}
.counts li { color: #606266; }
.counts b { font-size: 16px; margin: 0 4px; }
.counts span { color: #909399; font-size: 12px; }
.counts .pos b { color: #f56c6c; }
.counts .neg b { color: #67c23a; }
.counts .neu b { color: #909399; }
</style>
