/**
 * DSH 沙箱垫片 —— 让 Vite / Vitest 能在受限环境下启动。
 *
 * 背景(实测):
 *   Vite 在 Windows 上会调用 optimizeSafeRealPathSync(),
 *   内部执行 `exec("net use")` 来探测网络驱动器映射。
 *   DSH 沙箱禁止受限进程用命名管道捕获子进程输出,
 *   该 spawn 直接以 EPERM 失败,导致 vitest 连配置文件都加载不了。
 *
 * 做法:
 *   拦截 node:child_process 的 exec,对 `net use` 这一条直接返回空结果。
 *   这不会影响任何真实功能 —— 该调用的唯一用途是构建"网络盘→本地盘"映射表,
 *   而本机没有映射的网络盘(返回空表时 Vite 会回退到 fs.realpathSync.native)。
 *
 * 用法(必须先于 vitest 加载):
 *   node --import ./tools/vite-sandbox-shim.mjs node_modules/vitest/vitest.mjs run
 */

import { createRequire } from 'node:module'
import Module from 'node:module'

const require = createRequire(import.meta.url)
const childProcess = require('node:child_process')

const originalExec = childProcess.exec

childProcess.exec = function patchedExec(command, options, callback) {
  // 兼容 exec(cmd, cb) 的调用形式
  if (typeof options === 'function') {
    callback = options
    options = {}
  }

  if (typeof command === 'string' && command.trim() === 'net use') {
    // 返回空输出:本机无映射网络盘,Vite 会走 fs.realpathSync.native 分支
    process.nextTick(() => callback && callback(null, '', ''))
    return { kill() {}, on() {}, once() {} }
  }

  return originalExec.call(this, command, options, callback)
}

// 让 `import { exec } from 'node:child_process'` 也能看到补丁
Module.syncBuiltinESMExports()
