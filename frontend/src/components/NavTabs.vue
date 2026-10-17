<script setup>
/**
 * 功能导航:把原先堆在一页里的四块内容分成四个视图。
 *
 * 为什么用「页签」而不是侧边栏:
 *   侧边栏要占掉两百来像素的横向空间,而这一页最吃宽度的恰恰是
 *   K 线与新闻列表;页签只占竖直方向一行,把横向空间全留给数据。
 *
 * 为什么每个页签带一个计数:
 *   切页本身有成本,用户得先判断"值不值得点进去"。把条数写在页签上,
 *   不点就知道哪一页有数据、哪一页是空的。
 *
 * 为什么不用 vue-router:
 *   四个视图共用同一份已加载的数据,也没有"深链接到某一页"的需求;
 *   引入路由只会多一层状态同步,还要处理刷新后数据重拉。
 *   一个受控组件(父级持 activeTab)就够,并且好测。
 */
defineProps({
  tabs: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <nav class="tabs" role="tablist">
    <button
      v-for="t in tabs"
      :key="t.key"
      class="tab"
      :class="{ on: t.key === modelValue }"
      :data-tab="t.key"
      :title="t.hint || t.label"
      role="tab"
      :aria-selected="t.key === modelValue"
      @click="emit('update:modelValue', t.key)"
    >
      <span class="label">{{ t.label }}</span>
      <span v-if="t.badge !== null && t.badge !== undefined" class="badge num">
        {{ t.badge }}
      </span>
      <span v-if="t.hint" class="hint">{{ t.hint }}</span>
    </button>
  </nav>
</template>

<style scoped>
.tabs {
  display: flex;
  align-items: stretch;
  gap: 2px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.tab {
  position: relative;
  display: flex;
  align-items: baseline;
  gap: 7px;
  padding: 9px 16px 11px;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--muted);
  transition: color 0.15s ease;
}

.tab:hover {
  color: var(--ink-2);
}

/* 选中态:文字转墨色 + 底部一条 2px 墨线。
   线压在容器的 1px 分隔线上(bottom: -1px),看起来像"这一页被翻开"。 */
.tab.on {
  color: var(--ink);
}
.tab.on::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: var(--ink);
}

.label {
  font-size: var(--fs-lead);
  font-weight: 600;
  letter-spacing: -0.01em;
  white-space: nowrap;
}

.badge {
  font-size: var(--fs-label);
  color: var(--muted-2);
  font-weight: 400;
}
.tab.on .badge {
  color: var(--ink-2);
}

/* 说明文字只在宽屏出现:窄屏上页签会折行,再加两行小字就散了 */
.hint {
  font-size: 11px;
  color: var(--muted-2);
  white-space: nowrap;
}

@media (max-width: 900px) {
  .hint {
    display: none;
  }
  .tab {
    padding: 9px 12px 11px;
  }
}
</style>
