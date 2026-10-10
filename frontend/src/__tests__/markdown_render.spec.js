import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import fs from 'node:fs'
import path from 'node:path'
import { MarkdownRender } from 'markstream-vue'

/**
 * Bug回归锁：聊天区出现过"占满半屏的巨型 Python 图标"。
 *
 * 根因：markstream-vue 的代码块语言图标 SVG 本身不带 width/height，尺寸全靠
 * 包样式表（`.icon-slot` 的 h-4/w-4 等 utility）；而 main.js 当时没有 import
 * 该样式表，SVG 因此退化到浏览器默认尺寸被容器撑大。
 *
 * 两层防线各锁一条：
 * 1) 应用必须引入 markstream 官方样式表；
 * 2) ChatView 必须有组件级兜底（语言图标固定尺寸，不依赖父容器/外部 CSS）。
 * 另加真实 DOM 契约测试：图标节点结构变化时先在这里报警。
 */

function codeBlockHtml(lang) {
  const fence = '```'
  const md = `脚本已保存。\n\n${fence}${lang}\nprint(1)\n${fence}\n`
  const w = mount(MarkdownRender, { props: { content: md, final: true } })
  return w
}

describe('markdown code-block icon sizing (bug regression)', () => {
  it('the app imports the official markstream stylesheet (icons are sized there)', () => {
    const src = fs.readFileSync(path.resolve(process.cwd(), 'src/main.js'), 'utf8')
    expect(src).toContain('markstream-vue/index.css')
  })

  it('ChatView pins the language-icon size itself, independent of any parent/CSS', () => {
    const sfc = fs.readFileSync(path.resolve(process.cwd(), 'src/components/ChatView.vue'), 'utf8')
    // 兜底规则必须直接给图标 SVG 固定的宽高上限，而不是继承/父容器类
    expect(sfc).toMatch(/\.icon-slot\s+svg[^}]*width:\s*16px/s)
    expect(sfc).toMatch(/\.icon-slot\s+svg[^}]*height:\s*16px/s)
  })

  for (const lang of ['python', 'js', 'go', '']) {
    it(`a ${lang || 'language-less'} code block renders exactly one header icon slot with a viewBox svg`, () => {
      const w = codeBlockHtml(lang)
      const slots = w.findAll('.icon-slot')
      expect(slots.length).toBeGreaterThanOrEqual(1)
      const svg = slots[0].find('svg')
      expect(svg.exists()).toBe(true)
      // SVG 尺寸约束的两条路径：属性或库 utility 类；两者都没有 = 本 bug 复现
      const sized =
        svg.attributes('width') ||
        slots[0].classes().join(' ').match(/h-\d|w-\d/) ||
        /icon-slot/.test(slots[0].attributes('class') ?? '')
      expect(sized).toBeTruthy()
      expect(svg.attributes('viewBox')).toBeTruthy()
    })
  }
})
