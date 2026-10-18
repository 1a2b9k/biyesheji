import { createApp } from 'vue'
import './style.css'
import App from './App.vue'

const app = createApp(App)

/**
 * 全局错误兜底。
 *
 * 组件内部的 try/catch 只覆盖我们想到了的失败;模板渲染、计算属性里
 * 抛出的异常(比如某个接口返回了预期外的结构)默认只会进浏览器控制台,
 * 页面停在一半、用户看不到任何提示。这里至少把它记下来。
 *
 * 不在这里弹 UI:错误提示的位置属于各面板自己的事,
 * 一个全局弹窗反而会挡住已经正常渲染的部分。
 */
app.config.errorHandler = (err, instance, info) => {
  // 保留原始堆栈,便于在控制台按 errorHandler 关键字定位
  console.error('[app error]', info, err)
}

app.mount('#app')
