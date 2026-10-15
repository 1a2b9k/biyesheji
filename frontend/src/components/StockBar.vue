<script setup>
/**
 * 报头:站名 + 数据源说明 + 股票选择 + 手动采集。
 *
 * 设计取向:做成"金融报纸报头"而不是常见的深色导航条。
 * 深色条是后台模板的默认指纹,且会在浅色页面上凭空插一块暗区;
 * 报头用纸色 + 一条粗墨线分栏,既贴合主题,也让页面只有一个色调。
 */
import { computed } from 'vue'

const props = defineProps({
  stocks: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
  syncing: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'sync'])

const currentName = computed(() => {
  const hit = props.stocks.find((s) => s.code === props.modelValue)
  return hit ? hit.name : ''
})

function onChange(e) {
  emit('update:modelValue', e.target.value)
}
</script>

<template>
  <header class="masthead">
    <div class="rule-top" />

    <div class="row">
      <div class="brand">
        <h1>财经舆情分析平台</h1>
        <p class="sub">
          <span class="eyebrow">A 股股吧短文本 · 情感分析</span>
          <span class="dot">·</span>
          <span>数据源 东方财富</span>
        </p>
      </div>

      <div class="controls">
        <label class="field">
          <span class="field-label">当前标的</span>
          <select
            :value="modelValue"
            class="picker"
            :title="currentName"
            @change="onChange"
          >
            <option v-for="s in stocks" :key="s.code" :value="s.code">
              {{ s.name }} ({{ s.code }})
            </option>
          </select>
        </label>

        <button class="btn" :disabled="syncing || !modelValue" @click="emit('sync')">
          <span v-if="syncing" class="spin" aria-hidden="true" />
          {{ syncing ? '采集中…' : '采集最新数据' }}
        </button>
      </div>
    </div>

    <div class="rule-bottom" />
  </header>
</template>

<style scoped>
.masthead {
  background: var(--surface);
  padding: 0 var(--pad-x);
}

/* 报头上下各一条线,粗的在下 —— 报纸分栏的做法,不靠投影 */
.rule-top {
  height: 1px;
  background: var(--line);
}
.rule-bottom {
  height: 2px;
  background: var(--ink);
}

.row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  padding: 22px 0 14px;
}

.brand h1 {
  font-size: var(--fs-display);
  line-height: 1.1;
  letter-spacing: -0.02em;
  font-weight: 700;
  margin: 0;
}

.sub {
  margin: 7px 0 0;
  font-size: var(--fs-label);
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sub .dot {
  color: var(--muted-2);
}

.controls {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.field-label {
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted-2);
  font-weight: 600;
}

.picker {
  padding: 8px 11px;
  border-radius: var(--r);
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink);
  font-size: var(--fs-body);
  min-width: 210px;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.picker:hover {
  border-color: var(--muted-2);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 18px;
  border-radius: var(--r);
  border: 1px solid var(--accent);
  background: var(--accent);
  color: var(--accent-ink);
  font-size: var(--fs-body);
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s ease, transform 0.1s ease;
}
.btn:hover:not(:disabled) {
  opacity: 0.86;
}
.btn:active:not(:disabled) {
  transform: translateY(1px);
}
.btn:disabled {
  opacity: 0.38;
  cursor: not-allowed;
}

.spin {
  width: 11px;
  height: 11px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 720px) {
  .row {
    align-items: flex-start;
  }
  .controls {
    width: 100%;
  }
  .picker {
    min-width: 0;
    flex: 1;
  }
}
</style>
