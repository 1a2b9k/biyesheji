/**
 * 源码完整性检查。
 *
 * 为什么需要这个:jsdom 不加载 CSS,所以"引用了不存在的文件"
 * 这类错误在组件测试里**测不出来**,但会让整个页面白屏
 * (曾经真的发生过:main.js 引用了已删除的 style.css)。
 *
 * 这里直接静态检查所有 import 的相对路径是否真实存在。
 */

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(HERE, '..', 'src')

/** 递归收集 src 下的所有源文件。 */
function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) out.push(...walk(full))
    else out.push(full)
  }
  return out
}

/** 提取一行里所有相对路径 import。 */
function relativeImports(code) {
  const found = []
  const re = /(?:import\s+[^'"]*?from\s*|import\s*|require\()\s*['"](\.[^'"]+)['"]/g
  let m
  while ((m = re.exec(code)) !== null) found.push(m[1])
  return found
}

/** 解析相对导入,补全扩展名(与 Vite 的解析规则一致)。 */
function resolves(fromFile, spec) {
  const base = resolve(dirname(fromFile), spec)
  const candidates = [
    base,
    base + '.js',
    base + '.vue',
    base + '.css',
    base + '.json',
    join(base, 'index.js'),
    join(base, 'index.vue'),
  ]
  return candidates.some((p) => existsSync(p))
}

describe('源码完整性', () => {
  const files = walk(SRC).filter((f) => /\.(js|vue)$/.test(f))

  it('src 下有源文件', () => {
    expect(files.length).toBeGreaterThan(0)
  })

  it('每个相对 import 都指向真实存在的文件', () => {
    const broken = []
    for (const file of files) {
      const code = readFileSync(file, 'utf8')
      for (const spec of relativeImports(code)) {
        if (!resolves(file, spec)) {
          broken.push(`${file.replace(SRC, 'src')} -> ${spec}`)
        }
      }
    }
    // 失败时把断链全部列出,便于一次性修完
    expect(broken).toEqual([])
  })

  it('入口文件存在且挂载到 #app', () => {
    const main = join(SRC, 'main.js')
    expect(existsSync(main)).toBe(true)
    const code = readFileSync(main, 'utf8')
    expect(code).toContain("mount('#app')")
  })

  it('index.html 含有挂载点 #app', () => {
    const html = readFileSync(resolve(HERE, '..', 'index.html'), 'utf8')
    expect(html).toContain('id="app"')
    expect(html).toContain('/src/main.js')
  })
})
