<script setup>
/**
 * 顶部工具栏:股票选择 + 手动采集。
 */
defineProps({
  stocks: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
  syncing: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'sync'])

function onChange(e) {
  emit('update:modelValue', e.target.value)
}
</script>

<template>
  <header class="bar">
    <h1>财经舆情分析平台 <span class="ver">v0.1 基础版</span></h1>

    <div class="right">
      <select :value="modelValue" @change="onChange" class="picker">
        <option v-for="s in stocks" :key="s.code" :value="s.code">
          {{ s.name }} ({{ s.code }})
        </option>
      </select>

      <button class="btn" :disabled="syncing || !modelValue" @click="emit('sync')">
        {{ syncing ? '采集中…' : '采集最新数据' }}
      </button>
    </div>
  </header>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 20px;
  background: #1f2d3d;
  color: #fff;
  flex-wrap: wrap;
}
h1 { font-size: 17px; margin: 0; font-weight: 600; }
.ver { font-size: 12px; opacity: 0.6; font-weight: 400; margin-left: 6px; }
.right { display: flex; gap: 10px; align-items: center; }
.picker {
  padding: 7px 10px; border-radius: 4px; border: 1px solid #4a5a6a;
  background: #2c3e50; color: #fff; font-size: 13px; min-width: 190px;
}
.btn {
  padding: 7px 16px; border-radius: 4px; border: none; cursor: pointer;
  background: #409eff; color: #fff; font-size: 13px;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
