<script setup>
/**
 * 新闻来源分布。
 *
 * 为什么不是饼图:来源有十几个,饼图必须给每类分配一个颜色,
 * 于是页面里出现一条 12 色彩虹 —— 这是最典型的"模板感"来源,
 * 而且会和红/绿数据语义色抢注意力。同一页面上情感面板已经用了
 * 红绿灰三色,再来一圈彩虹,读者分不清哪个颜色有意义。
 *
 * 改成横向条形:用单一墨色的深浅阶梯表示份额,颜色本身不承载新信息,
 * 长度才是数据。这也让"哪几家媒体在说话"一眼可读,不必对着图例找。
 */
import { computed } from 'vue'

const props = defineProps({
  sources: { type: Array, default: () => [] },
  /**
   * 该股票的新闻总条数。
   *
   * 后端 sources 只返回占比最高的 10 家(其余在长尾里),所以不能把
   * sources 的 count 相加当总数 —— 那样「共 N 条」永远偏小
   * (600519 有 52 家来源 493 条,前 10 家只合到 328 条)。
   */
  total: { type: Number, default: 0 },
  /** 来源总家数(后端只给前 10 家的明细,家数要单独传)。 */
  sourceCount: { type: Number, default: 0 },
})

/** 按条数降序,最多显示 8 家,其余合并。 */
const rows = computed(() => {
  const all = [...(props.sources ?? [])]
    .filter((s) => s && s.count > 0)
    .sort((a, b) => b.count - a.count)
  if (!all.length) return { items: [], max: 1, rest: null }

  const head = all.slice(0, 8)
  const tail = all.slice(8)
  const max = head[0].count
  const items = head.map((s, i) => ({
    name: s.source || '未知来源',
    count: s.count,
    // 墨色阶梯:最深的给最大的一家,后面的逐步变浅但仍有区分度
    opacity: 1 - Math.min(i, 7) * 0.085,
    width: (s.count / max) * 100,
  }))
  const rest = tail.length
    ? { name: `其他 ${tail.length} 家`, count: tail.reduce((a, b) => a + b.count, 0) }
    : null
  return { items, max, rest }
})

/** 已列出的 10 家合计;没有 total 时退化为这个值。 */
const listedTotal = computed(() =>
  (props.sources ?? []).reduce((a, s) => a + (s?.count ?? 0), 0))

/** 新闻总条数:优先用后端给的准确值,缺省才退回已列出的合计。 */
const total = computed(() => (props.total > 0 ? props.total : listedTotal.value))

/** 未列出的长尾条数(总数 - 已列出),为 0 时不显示说明。 */
const unlisted = computed(() =>
  props.total > 0 ? Math.max(0, props.total - listedTotal.value) : 0)

/** 来源总家数:优先用后端给的准确值,缺省才退回已列出的家数。 */
const sourceCount = computed(() =>
  props.sourceCount > 0 ? props.sourceCount : (props.sources ?? []).length)
</script>

<template>
  <section class="panel">
    <header class="head">
      <h2>新闻来源分布</h2>
      <span class="meta num">
        共 {{ total }} 条 · {{ sourceCount }} 家
        <template v-if="unlisted">（下列仅前 {{ sources.length }} 家）</template>
      </span>
    </header>

    <p v-if="!rows.items.length" class="empty">暂无新闻数据</p>

    <ul v-else class="rows">
      <li v-for="r in rows.items" :key="r.name">
        <div class="line">
          <span class="name">{{ r.name }}</span>
          <span class="n num">{{ r.count }}</span>
        </div>
        <div class="track">
          <div
            class="fill"
            :style="{ width: r.width + '%', opacity: r.opacity }"
          />
        </div>
      </li>
      <li v-if="rows.rest" class="rest">
        <div class="line">
          <span class="name">{{ rows.rest.name }}</span>
          <span class="n num">{{ rows.rest.count }}</span>
        </div>
      </li>
    </ul>
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
.meta {
  font-size: var(--fs-label);
  color: var(--muted);
  margin-left: auto;
}

.empty {
  color: var(--muted);
  font-size: var(--fs-body);
  padding: 22px 0;
  margin: 0;
}

.rows {
  list-style: none;
  margin: 0;
  padding: 0;
}
.rows li {
  padding: 7px 0;
}

.line {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 5px;
}
.name {
  font-size: var(--fs-body);
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.n {
  font-size: var(--fs-label);
  color: var(--muted);
  margin-left: auto;
  flex-shrink: 0;
}

.track {
  height: 5px;
  background: var(--line-2);
  border-radius: 2px;
  overflow: hidden;
}
.fill {
  height: 100%;
  background: var(--ink);
  border-radius: 2px;
  transition: width 0.35s ease;
}

.rest {
  border-top: 1px solid var(--line-2);
  margin-top: 6px;
  padding-top: 10px !important;
}
.rest .name {
  color: var(--muted);
  font-size: var(--fs-label);
}
</style>
