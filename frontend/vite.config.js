import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],

  server: {
    port: 5173,
    // 把 /api 代理到后端,开发期无需处理跨域
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },

  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.js'],
    globals: false,
    // 沙箱下不能用 forks(子进程 + 管道 stdio 会 EPERM);
    // threads 走 worker_threads,不经过命名管道。
    pool: 'threads',
  },
})
