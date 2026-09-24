// Markdown 渲染工具：AI 回答的统一出口。
//
// 安全边界：html:false —— 模型输出里的原始 HTML 一律不渲染，
// 否则一条"输出 <script> 的回答"就是存储型 XSS 的入口。
// 代码内容经过 highlight 转义，文本节点由 markdown-it 转义。
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import json from 'highlight.js/lib/languages/json'
import bash from 'highlight.js/lib/languages/bash'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import markdown from 'highlight.js/lib/languages/markdown'
import sql from 'highlight.js/lib/languages/sql'
import java from 'highlight.js/lib/languages/java'
import cpp from 'highlight.js/lib/languages/cpp'
import yaml from 'highlight.js/lib/languages/yaml'
import 'highlight.js/styles/github.css'

// 按需注册语言：全量注册会让 bundle 多出几百 KB
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('json', json)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('java', java)
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('yaml', yaml)

const md = new MarkdownIt({
  html: false,     // 见上：安全边界
  linkify: true,   // 自动把 URL 变成链接
  breaks: true,    // 单个换行渲染成 <br>，符合聊天习惯
})

// 代码块：高亮 + 语言标签 + 复制按钮。
// 复制动作不在渲染层做（这里产出的是纯字符串），由聊天容器的事件委托统一处理。
md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  const lang = (token.info || '').trim().split(/\s+/)[0]

  let body
  if (lang && hljs.getLanguage(lang)) {
    try {
      body = hljs.highlight(token.content, { language: lang }).value
    } catch {
      // 未注册的语言等异常：降级为转义后的纯文本
    }
  }
  if (body === undefined) {
    body = md.utils.escapeHtml(token.content)
  }

  return (
    `<div class="code-block">` +
    `<div class="code-bar">` +
    `<span class="code-lang">${md.utils.escapeHtml(lang || 'text')}</span>` +
    `<button class="copy-btn" type="button">复制</button>` +
    `</div>` +
    `<pre><code class="hljs">${body}</code></pre>` +
    `</div>`
  )
}

// 外链一律新窗口打开，避免把用户带离应用
const defaultLinkOpen =
  md.renderer.rules.link_open ||
  ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

export function renderMarkdown(text) {
  return md.render(text || '')
}

/**
 * 渲染 AI 回答，并把正文里的 [n] 引用标记变成可点击的跳转锚点。
 *
 * 只处理确实存在的引用编号（由调用方传入集合），否则一个恰好写成
 * "[1]" 的数组下标也会被误判成引用。
 * <pre> 代码块内的方括号是代码语法（比如 arr[1]），必须跳过。
 */
export function renderMarkdownWithCites(text, citeIndexes) {
  const html = md.render(text || '')
  if (!citeIndexes || !citeIndexes.size) return html

  // 奇数段是 <pre>...</pre> 原样保留，偶数段才做引用标记替换
  return html
    .split(/(<pre>[\s\S]*?<\/pre>)/g)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part.replace(/\[(\d{1,2})\]/g, (matched, n) =>
            citeIndexes.has(Number(n))
              ? `<span class="cite-ref" data-cite="${n}">[${n}]</span>`
              : matched,
          ),
    )
    .join('')
}
