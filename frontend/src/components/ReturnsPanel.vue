<script setup>
/**
 * 情感—收益关联面板:散点图 + 相关性读数 + 分组收益。
 *
 * 设计取向:
 *   - 相关性是「有没有」的问题,不是「多少」的问题,所以读数区
 *     把 p 值和样本量放在同一行,避免用户只看 r 就下结论。
 *   - 分组收益用三条横条对比(低/中/高情感组),横条长度即收益,
 *     正负用颜色区分,比表格更快看出单调性。
 *   - 样本不足时明确说「样本太少」而不是画一张空散点图 ——
 *     20 个点算出来的相关系数不该被当成结论。
 */
import { computed } from 'vue'

import EChart from './EChart.vue'
import { buildReturnsScatterOption } from '../utils/chart.js'

const props = defineProps({
  data: { type: Object, default: null },
})

const stats = computed(() => props.data?.stats ?? null)
const pairs = computed(() => props.data?.pairs ?? [])

const scatterOption = computed(() => buildReturnsScatterOption(pairs.value))

/** 样本数低于这个值时,相关系数不足以支撑结论。 */
const MIN_RELIABLE = 30

const n = computed(() => stats.value?.n ?? 0)
const reliable = computed(() => n.value >= MIN_RELIABLE)
const hasData = computed(() => n.value > 0)

function num(v, digits = 3) {
  const x = Number(v)
  return Number.isFinite(x) ? x.toFixed(digits) : '-'
}

function pct(v) {
  const x = Number(v)
  return Number.isFinite(x) ? (x >= 0 ? '+' : '') + x.toFixed(2) + '%' : '-'
}

/** p 值小于 0.001 时直接写「<0.001」,避免一长串 0。 */
const pText = computed(() => {
  const p = stats.value?.p_value
  if (!Number.isFinite(Number(p))) return '-'
  return Number(p) < 0.001 ? '< 0.001' : Number(p).toFixed(3)
})

/** 相关性是否在 0.05 水平上显著。 */
const significant = computed(() => {
  const p = Number(stats.value?.p_value)
  return Number.isFinite(p) && p < 0.05
})

/** 分组收益:低/中/高情感组各自的平均次日收益。 */
const groups = computed(() => {
  const g = stats.value?.groups ?? {}
  return [
    { key: 'low', name: '低情感组', value: g.low },
    { key: 'mid', name: '中情感组', value: g.mid },
    { key: 'high', name: '高情感组', value: g.high },
  ]
})

/** 横条以最大绝对值为基准缩放,让三组可比。 */
const groupMax = computed(() => {
  const vals = groups.value.map((x) => Math.abs(Number(x.value) || 0))
  return Math.max(...vals, 0.01)
})

function barWidth(v) {
  const x = Math.abs(Number(v) || 0)
  return (x / groupMax.value) * 100
}
</script>

<template>
  <section class="panel">
    <header class="head">
      <h2>情感与收益</h2>
      <span class="meta num">
        情感指数 vs 次日涨跌幅 · {{ n }} 个股票-日样本
      </span>
    </header>

    <p v-if="!hasData" class="empty">
      还没有可用的配对样本。先采集新闻并完成情感标注,
      再确保该股票有对应的日线行情。
    </p>

    <template v-else>
      <!-- 读数区:p 值和样本量与 r 并列,防止只看 r 就下结论 -->
      <ul class="stats">
        <li>
          <span class="k">Pearson r</span>
          <b class="v num">{{ num(stats.pearson) }}</b>
        </li>
        <li>
          <span class="k">Spearman ρ</span>
          <b class="v num">{{ num(stats.spearman) }}</b>
        </li>
        <li>
          <span class="k">p 值</span>
          <b class="v num" :class="{ sig: significant }">{{ pText }}</b>
        </li>
        <li>
          <span class="k">方向命中率</span>
          <b class="v num">
            {{ stats.hit_n ? num(stats.hit_rate) : '-' }}
            <small v-if="stats.hit_n" class="sub num">n={{ stats.hit_n }}</small>
          </b>
        </li>
      </ul>

      <p v-if="!reliable" class="warn">
        样本仅 {{ n }} 个,低于 {{ MIN_RELIABLE }} 个时相关系数波动很大,
        下面的数值只作参考,不宜作为结论。
      </p>

      <!-- 分组收益:横条长度即平均收益 -->
      <h3>分组平均次日收益</h3>
      <ul class="groups">
        <li v-for="g in groups" :key="g.key">
          <span class="gname">{{ g.name }}</span>
          <div class="track">
            <div
              class="fill"
              :class="{ up: Number(g.value) >= 0, down: Number(g.value) < 0 }"
              :style="{ width: barWidth(g.value) + '%' }"
            />
          </div>
          <span class="gval num" :class="{ up: Number(g.value) >= 0, down: Number(g.value) < 0 }">
            {{ pct(g.value) }}
          </span>
        </li>
      </ul>

      <h3>散点与拟合线 <span class="hint">每点为一个交易日</span></h3>
      <EChart :option="scatterOption" height="300px" />
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
  margin: 18px 0 8px;
  color: var(--muted);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.meta {
  font-size: var(--fs-label);
  color: var(--muted);
  margin-left: auto;
}

.empty {
  color: var(--muted);
  font-size: var(--fs-body);
  padding: 10px 0 6px;
  margin: 0;
}

/* —— 读数区 —— */
.stats {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin: 0;
  padding: 0;
}
.stats li {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.k {
  font-size: var(--fs-label);
  color: var(--muted);
  font-weight: 600;
}
.v {
  font-size: var(--fs-title);
  color: var(--ink);
  font-weight: 600;
}
.v.sig {
  color: var(--pos);
}
.sub {
  font-size: 10px;
  color: var(--muted-2);
  font-weight: 400;
  margin-left: 4px;
}

.warn {
  background: var(--surface-2);
  border-left: 3px solid var(--muted-2);
  color: var(--muted);
  font-size: var(--fs-label);
  padding: 8px 12px;
  margin: 14px 0 0;
  border-radius: 2px;
}

/* —— 分组收益横条 —— */
.groups {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.groups li {
  display: grid;
  grid-template-columns: 80px 1fr 66px;
  align-items: center;
  gap: 10px;
}
.gname {
  font-size: var(--fs-label);
  color: var(--muted);
  font-weight: 600;
}
.track {
  height: 5px;
  background: var(--line-2);
  border-radius: 3px;
  overflow: hidden;
}
.fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.35s ease;
}
.gval {
  font-size: var(--fs-label);
  font-weight: 600;
  text-align: right;
}
.up { color: var(--pos); }
.down { color: var(--neg); }
.fill.up { background: var(--pos); }
.fill.down { background: var(--neg); }

.hint {
  font-size: 10px;
  color: var(--muted-2);
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
}

@media (max-width: 900px) {
  .stats { grid-template-columns: repeat(2, 1fr); }
  .meta { margin-left: 0; }
}
</style>
