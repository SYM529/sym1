<template>
  <!-- 未登录：显示登录页 -->
  <LoginView v-if="!isLoggedIn" @authenticated="onAuthenticated" />

  <!-- 已登录 -->
  <template v-else>
    <Transition name="page" mode="out-in">
    <!-- 评测看板。key 随主题变化：echarts 主题在 init 时确定，切换主题必须重建实例 -->
    <DashboardView v-if="view === 'dashboard'" :dark="isDark" :key="String(isDark)" @back="view = 'chat'" />

    <!-- 对话界面：侧边栏 + 主区域 -->
    <div v-else class="app-shell">
      <SessionSidebar
        :sessions="sessions"
        :active-id="sessionId"
        :collapsed="sidebarCollapsed"
        :loading="sessionsLoading"
        :width="sidebarWidth"
        @update:width="onSidebarResize"
        @new="startNewChat"
        @select="selectSession"
        @rename="renameCurrent"
        @delete="removeSession"
      />

      <div class="main-area">
      <div class="container">
      <div class="header">
        <div class="header-left">
          <button class="hdr-btn icon-only" title="收起/展开侧边栏" @click="sidebarCollapsed = !sidebarCollapsed">☰</button>
          <h1>Agent 智能助手</h1>
        </div>
        <div class="header-right">
          <!-- 点击用户名进入个人中心 -->
          <button class="username username-clickable" title="个人中心" @click="openProfile">
            <span class="user-badge small"><svg viewBox="0 0 24 24"><path fill="#fff" d="M12 12c2.4 0 4-1.8 4-4.2S14.4 3.6 12 3.6 8 5.4 8 7.8 9.6 12 12 12zm0 2.2c-3.1 0-7 1.6-7 4.2v1h14v-1c0-2.6-3.9-4.2-7-4.2z"/></svg></span>{{ username }}
          </button>
          <!-- v-if 放在 el-tooltip 上：内层 span 隐藏时 tooltip 就没有子节点，
               会持续抛 [ElOnlyChild] no valid child node found -->
          <el-tooltip
            v-if="todayUsage && todayUsage.requests"
            content="今日所有会话的 token 消耗与成本（来自每请求埋点）"
            placement="bottom"
          >
            <span class="cost-badge">
              💰 ¥{{ Number(todayUsage.cost_cny).toFixed(4) }} · {{ todayUsage.requests }} 次
            </span>
          </el-tooltip>
          <button v-if="isAdmin" class="hdr-btn" @click="view = view === 'chat' ? 'dashboard' : 'chat'">
            {{ view === 'chat' ? '📊 看板' : '💬 对话' }}
          </button>
          <button class="hdr-btn" @click="openKnowledge">📚 知识库</button>
          <!-- 主题切换：圆形图标，与登录页同一套样式 -->
          <button
            class="theme-toggle-sm"
            type="button"
            :title="isDark ? '切换到浅色主题' : '切换到深色主题'"
            @click="toggleTheme"
          >
            <svg v-if="isDark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.5 1.5M17.2 17.2l1.5 1.5M18.7 5.3l-1.5 1.5M6.8 17.2l-1.5 1.5" />
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
            </svg>
          </button>
          <button class="hdr-btn danger" @click="logout">退出</button>
        </div>
      </div>

    <!-- 代码块"复制"与引用跳转都用事件委托处理：v-html 内容无法直接绑事件 -->
    <div class="chat-box" ref="chatBox" @click="onChatClick" @scroll="onChatScroll">
      <!-- 空状态欢迎页：顺便给访客演示所有能力 -->
      <div v-if="messages.length === 0 && !loading" class="welcome">
        <div class="welcome-title">👋 你好，我是 Agent 智能助手</div>
        <div class="welcome-sub">会算数、能查时间、可联网搜索，还能基于知识库回答项目问题——点一个试试：</div>
        <div class="chips">
          <button v-for="s in suggestions" :key="s.text" class="chip" @click="useSuggestion(s.text)">
            {{ s.label }}
          </button>
        </div>
      </div>
      <template v-for="(msg, idx) in messages" :key="idx">
        <!-- 按天分组：日期变化处插一条分隔线（时间戳由后端事件下发） -->
        <div v-if="showDayDivider(idx)" class="day-divider">
          <span>{{ dayDividerLabel(msg.ts) }}</span>
        </div>
        <div :class="['msg', msg.type]">
        <template v-if="msg.type === 'human'">
          <span class="label"><span class="user-badge"><svg viewBox="0 0 24 24"><path fill="#fff" d="M12 12c2.4 0 4-1.8 4-4.2S14.4 3.6 12 3.6 8 5.4 8 7.8 9.6 12 12 12zm0 2.2c-3.1 0-7 1.6-7 4.2v1h14v-1c0-2.6-3.9-4.2-7-4.2z"/></svg></span>你</span>
          <span class="content">{{ msg.content }}</span>
          <!-- 附件随用户消息一起留存：回看对话时才能知道当时问的是哪张图 -->
          <div v-if="msg.attachment" class="attachment-inline">
            <el-image
              v-if="msg.attachment.previewUrl"
              :src="msg.attachment.previewUrl"
              :preview-src-list="[msg.attachment.previewUrl]"
              preview-teleported
              fit="cover"
              class="thumb"
              :alt="msg.attachment.filename"
            />
            <span class="attachment-name">📎 {{ msg.attachment.filename }}</span>
          </div>
        </template>

        <template v-else-if="msg.type === 'tool'">
          <div class="tool-block">
            <div class="tool-header" @click="toggleTool(idx)">
              <span class="tool-dot"></span>
              <span class="label">🔧 {{ msg.name || '工具' }}</span>
              <span class="tool-status">已完成</span>
              <span class="toggle">{{ expandedTools[idx] ? '▲ 收起' : '▼ 查看' }}</span>
            </div>
            <pre v-show="expandedTools[idx]" class="tool-content">{{ msg.content }}</pre>

            <!-- 知识库检索的引用来源始终展示，用户据此核验答案出自哪里 -->
            <div v-if="msg.citations && msg.citations.length" class="citations">
              <div class="citations-title">引用来源</div>
              <div v-for="c in msg.citations" :key="c.index" class="citation" :data-cite-index="c.index">
                <div class="citation-meta">
                  <span class="citation-index">[{{ c.index }}]</span>
                  <span class="citation-source">{{ c.source }}</span>
                  <span v-if="c.heading" class="citation-heading">· {{ c.heading }}</span>
                  <span class="citation-score">相关度 {{ c.score }}</span>
                </div>
                <div class="citation-text">{{ c.text }}</div>
              </div>
            </div>
          </div>
        </template>

        <template v-else-if="msg.type === 'ai'">
          <span class="label"><span class="agent-badge"><svg viewBox="0 0 24 24"><path fill="#fff" d="M12 4.5 L13.7 10.3 L19.5 12 L13.7 13.7 L12 19.5 L10.3 13.7 L4.5 12 L10.3 10.3 Z"/></svg></span>Agent</span>
          <!-- 打字机进行中显示纯文本+光标：半截 Markdown 渲染出来会破碎 -->
          <div v-if="msg.typing" class="content md-plain">{{ msg.content }}<span class="type-cursor"></span></div>
          <div v-else-if="msg.content" class="content md-body" v-html="renderMarkdownWithCites(msg.content, citeIndexesFor(idx))"></div>
          <span v-else class="thinking-dots"><i></i><i></i><i></i></span>

          <!-- 单次消耗与缓存命中：让用户看得见成本，也让降本效果有据可查 -->
          <div v-if="msg.usage" class="usage">
            <span v-if="msg.cached" class="cache-badge">⚡ 缓存命中 · 本次未调用模型</span>
            <span v-else class="usage-text">
              {{ totalTokens(msg.usage.tokens) }} tokens · {{ formatCost(msg.usage.cost) }}
            </span>
          </div>
        </template>

        <template v-else-if="msg.type === 'error'">
          <span class="label">❌ 错误</span>
          <span class="content">{{ msg.content }}</span>
        </template>
        </div>
      </template>
    </div>

    <!-- 附件条：上传后一直挂着，追问同一张图时不必重新上传 -->
    <div v-if="attachment" class="attachment-bar">
      <el-image
        v-if="attachment.previewUrl"
        :src="attachment.previewUrl"
        :preview-src-list="[attachment.previewUrl]"
        preview-teleported
        fit="cover"
        class="thumb"
        :alt="attachment.filename"
      />
      <span class="attachment-name">
        📎 {{ attachment.filename }}
        <span class="attachment-kind">
          {{ attachment.kind === 'image' ? '图片' : '文档（已入库）' }}
        </span>
      </span>
      <el-button size="small" text type="danger" @click="removeAttachment">移除</el-button>
    </div>

    <div class="input-area">
      <input
        ref="fileInput"
        type="file"
        class="file-input"
        accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.md,.markdown,.txt,.csv,.html,.htm,.json,.yaml,.yml,.docx,.xlsx,.pptx"
        @change="onFilePicked"
      />
      <el-button :loading="uploading" @click="pickFile" title="上传图片或文档">
        📎 附件
      </el-button>
      <el-input
        ref="inputRef"
        v-model="input"
        placeholder="输入任务，可直接粘贴截图　|　比如：帮我算一下 123 * 456"
        @keyup.enter="send"
        :disabled="loading"
      />
      <el-button v-if="!loading" type="primary" @click="send">发送</el-button>
      <el-button v-else type="danger" @click="stopGenerate">■ 停止</el-button>
    </div>

      <!-- 智能滚动：上翻看历史时出现，一键回到底部 -->
      <transition name="fade">
        <button v-if="!autoScroll && messages.length" class="to-bottom" title="回到底部" @click="scrollToBottom(true)">↓</button>
      </transition>

    <!-- 知识库面板：搜索 + 分页 + 文档列表 + 删除 -->
    <el-drawer v-model="kbVisible" title="知识库" size="380px" v-loading="kbLoading">
      <el-input
        v-model="kbQuery"
        class="kb-search"
        size="small"
        clearable
        placeholder="🔍 搜索文件名…"
        @input="onKbSearch"
      />

      <div v-if="!kbLoading && kbTotal === 0" class="kb-empty">
        <template v-if="kbQuery">
          没有匹配「{{ kbQuery }}」的文档。
        </template>
        <template v-else>
          知识库是空的。上传一个文档，或运行
          <code>python -m agent.rag.ingest ./docs</code>
        </template>
      </div>

      <div v-for="doc in kbDocs" :key="doc.doc_id" class="kb-item">
        <div class="kb-main">
          <button class="kb-name kb-name-clickable" @click="toggleDoc(doc)">
            📄 {{ doc.source }}
            <span class="kb-caret">{{ kbExpanded === doc.doc_id ? '▾' : '▸' }}</span>
          </button>
          <div class="kb-meta">
            {{ doc.chunks }} 段 ·
            {{ doc.mine ? '我上传的' : (doc.owner ? '他人上传' : '共享文档') }}
            <span v-if="doc.ingested_at"> · {{ doc.ingested_at.slice(0, 10) }}</span>
          </div>

          <!-- 展开的原文预览：按入库顺序展示 chunk -->
          <div
            v-if="kbExpanded === doc.doc_id"
            v-loading="kbChunksLoading"
            class="kb-chunks"
          >
            <div v-for="c in kbChunks" :key="c.chunk_index" class="kb-chunk">
              <div v-if="c.heading" class="kb-chunk-heading">{{ c.heading }}</div>
              <div class="kb-chunk-text">{{ c.text }}</div>
            </div>
            <div v-if="!kbChunksLoading && kbChunks.length === 0" class="kb-chunk-text">
              （没有可展示的内容）
            </div>
          </div>
        </div>
        <!-- 自己的文档始终可删；共享文档仅管理员可删（服务端同样判定） -->
        <el-button
          v-if="doc.mine || (isAdmin && !doc.owner)"
          size="small"
          text
          type="danger"
          :disabled="kbLoading"
          @click="removeDoc(doc)"
        >删除</el-button>
      </div>

      <el-pagination
        v-if="kbTotal > kbPageSize"
        v-model:current-page="kbPage"
        class="kb-pagination"
        layout="prev, pager, next"
        :total="kbTotal"
        :page-size="kbPageSize"
        @current-change="loadKnowledge"
      />
    </el-drawer>

    <!-- 个人中心：账号信息 + 用量统计 -->
    <el-drawer v-model="profileVisible" title="个人中心" size="380px" v-loading="profileLoading">
      <div class="pf-card">
        <div class="pf-user">
          <span class="user-badge pf-avatar"><svg viewBox="0 0 24 24"><path fill="#fff" d="M12 12c2.4 0 4-1.8 4-4.2S14.4 3.6 12 3.6 8 5.4 8 7.8 9.6 12 12 12zm0 2.2c-3.1 0-7 1.6-7 4.2v1h14v-1c0-2.6-3.9-4.2-7-4.2z"/></svg></span>
          <div>
            <div class="pf-name">
              {{ profileMe.username }}
              <el-tag v-if="profileMe.is_admin" size="small" type="primary">管理员</el-tag>
              <el-tag v-else size="small" type="info">普通用户</el-tag>
            </div>
            <div class="pf-sub">用户 ID：{{ profileMe.id ?? '—' }}</div>
            <div class="pf-sub">注册时间：{{ profileMe.created_at?.slice(0, 10) || '—' }}</div>
          </div>
        </div>
      </div>

      <div class="pf-section-title">今日用量</div>
      <div class="pf-stats">
        <div class="pf-stat">
          <div class="pf-stat-value">{{ profileUsage.today?.requests ?? 0 }}</div>
          <div class="pf-stat-label">请求次数</div>
        </div>
        <div class="pf-stat">
          <div class="pf-stat-value">{{ formatTokens(profileUsage.today) }}</div>
          <div class="pf-stat-label">Token</div>
        </div>
        <div class="pf-stat">
          <div class="pf-stat-value">{{ formatCost(profileUsage.today?.cost_cny) }}</div>
          <div class="pf-stat-label">成本</div>
        </div>
      </div>

      <div class="pf-section-title">近 7 天累计</div>
      <div class="pf-stats">
        <div class="pf-stat">
          <div class="pf-stat-value">{{ profileUsage.total?.requests ?? 0 }}</div>
          <div class="pf-stat-label">请求次数</div>
        </div>
        <div class="pf-stat">
          <div class="pf-stat-value">{{ formatTokens(profileUsage) }}</div>
          <div class="pf-stat-label">Token</div>
        </div>
        <div class="pf-stat">
          <div class="pf-stat-value">{{ formatCost(profileUsage.total?.cost_cny) }}</div>
          <div class="pf-stat-label">成本</div>
        </div>
      </div>
      <div v-if="profileUsage.total?.cache_hits" class="pf-cache-note">
        其中语义缓存命中 {{ profileUsage.total.cache_hits }} 次（命中不消耗模型 token）
      </div>

      <div class="pf-section-title">会话</div>
      <div class="pf-row">
        <span>历史会话</span>
        <span class="pf-row-value">{{ profileSessionCount }} 个</span>
      </div>

      <div class="pf-section-title">我的知识库文档</div>
      <div v-if="profileDocs.length === 0" class="pf-empty">
        还没有上传过文档。在对话框点 📎 上传后会出现在这里。
      </div>
      <div v-for="doc in profileDocs" :key="doc.doc_id" class="pf-row">
        <span class="pf-doc-name">📄 {{ doc.source }}</span>
        <span class="pf-row-actions">
          <span class="pf-row-value">{{ doc.chunks }} 段</span>
          <el-button size="small" text type="danger" @click="removeProfileDoc(doc)">删除</el-button>
        </span>
      </div>

      <div class="pf-section-title">偏好</div>
      <div class="pf-row">
        <span>界面主题</span>
        <span class="pf-row-value">{{ isDark ? '深色' : '浅色' }}</span>
      </div>

      <div class="pf-section-title">操作记录</div>
      <div v-if="profileAudit.length === 0" class="pf-empty">
        暂无记录。登录、改密、删除文档等操作会出现在这里。
      </div>
      <div v-for="log in profileAudit" :key="log.id" class="pf-audit">
        <span class="pf-audit-action">{{ actionLabel(log.action) }}</span>
        <span class="pf-audit-target">{{ log.target || '-' }}</span>
        <span :class="['pf-audit-outcome', log.outcome === 'success' ? 'ok' : 'fail']">
          {{ log.outcome === 'success' ? '成功' : '失败' }}
        </span>
        <span class="pf-audit-time">{{ log.ts?.slice(5, 16).replace('T', ' ') }}</span>
      </div>

      <div class="pf-section-title">账号操作</div>
      <div class="pf-actions">
        <el-button size="small" @click="showPasswordForm = !showPasswordForm">
          {{ showPasswordForm ? '取消修改密码' : '修改密码' }}
        </el-button>
        <el-button size="small" type="danger" plain @click="clearMySessions">清空全部会话</el-button>
      </div>

      <!-- 修改密码 -->
      <div v-if="showPasswordForm" class="pf-pwd">
        <el-input
          v-model="pwdForm.old"
          type="password"
          size="small"
          show-password
          placeholder="原密码"
        />
        <el-input
          v-model="pwdForm.next"
          type="password"
          size="small"
          show-password
          placeholder="新密码（至少 6 位）"
        />
        <el-button size="small" type="primary" :loading="pwdSaving" @click="submitPassword">
          确认修改
        </el-button>
        <div class="pf-tip">修改成功后会自动登录新 token，旧设备上的登录态立即失效。</div>
      </div>
    </el-drawer>
      </div>
      </div>
    </div>
    </Transition>
  </template>
</template>

<script setup>
import { reactive, ref, nextTick, onMounted, onBeforeUnmount, defineAsyncComponent } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import LoginView from '@/components/LoginView.vue'

// 异步加载：看板带着 echarts，不该让每个打开聊天页的人一起下载
const DashboardView = defineAsyncComponent(() => import('@/components/DashboardView.vue'))
import SessionSidebar from '@/components/SessionSidebar.vue'
import {
  getToken, setToken, fetchMe, clearSession, chatStream, uploadFile,
  listKnowledge, deleteKnowledge, fetchKnowledgeContent, listSessions, fetchSession,
  renameSession as renameSessionApi, fetchUsage, changePassword, clearAllSessions,
  fetchAudit, ApiError,
} from '@/api'
import { renderMarkdownWithCites } from '@/markdown'

const isLoggedIn = ref(false)
const username = ref('')
// 管理员身份：决定"看板"入口是否显示。真实判定在服务端（/api/reports 有守卫），
// 这里只是展示层配合——不然接口照样能被直接调
const isAdmin = ref(false)
// 当前视图：chat（对话）/ dashboard（评测看板）。
// 只有一个页面需要切换，为此引入 vue-router 得不偿失。
const view = ref('chat')
const input = ref('')
const messages = ref([])
const loading = ref(false)
const chatBox = ref(null)
const sessionId = ref('session_' + Date.now())
const expandedTools = ref({})

// 当前挂着的附件。刻意做成"粘性的"：发送后不自动清空，
// 这样追问"它是什么颜色的？"不用重新上传——图片本身服务端已经存好了，
// 每轮只要继续带上同一个 file_id。
const attachment = ref(null)
const uploading = ref(false)
const fileInput = ref(null)

// 知识库面板
const kbVisible = ref(false)
const kbDocs = ref([])
const kbLoading = ref(false)
const kbQuery = ref('')
const kbPage = ref(1)
const kbPageSize = 10
const kbTotal = ref(0)
let kbSearchTimer = null
// 点开查看的文档：记录 doc_id，内容懒加载（点开才请求）
const kbExpanded = ref(null)
const kbChunks = ref([])
const kbChunksLoading = ref(false)

// 个人中心
const profileVisible = ref(false)
const profileLoading = ref(false)
const profileMe = ref({})
const profileUsage = ref({})
const profileDocs = ref([])
const profileAudit = ref([])
const showPasswordForm = ref(false)
const pwdForm = reactive({ old: '', next: '' })
const pwdSaving = ref(false)

// 会话侧边栏。窄屏默认收起，避免挤占对话区域
const sessions = ref([])
const sessionsLoading = ref(false)
const sidebarCollapsed = ref(window.innerWidth < 900)
// 侧边栏宽度可拖拽调节，记忆到 localStorage：下次打开保持用户习惯
const SIDEBAR_MIN = 200
const SIDEBAR_MAX = 480
const sidebarWidth = ref(
  Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, Number(localStorage.getItem('sidebar_width')) || 256)),
)

function onSidebarResize(width) {
  sidebarWidth.value = width
  localStorage.setItem('sidebar_width', String(width))
}

// ---------- 暗色模式 ----------
// Element Plus 的暗色变量靠 html.dark 类启用，自定义颜色走 CSS 变量
const isDark = ref(localStorage.getItem('theme') === 'dark')

function applyTheme() {
  document.documentElement.classList.toggle('dark', isDark.value)
}

function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
  applyTheme()
}

applyTheme()

// ---------- 智能滚动 ----------
// 用户上翻看历史时不被自动滚动打断；只有贴着底部才跟随新消息
const autoScroll = ref(true)

function onChatScroll() {
  const el = chatBox.value
  if (!el) return
  autoScroll.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 80
}

async function scrollToBottom(force = false) {
  if (!force && !autoScroll.value) return
  await nextTick()
  if (chatBox.value) {
    chatBox.value.scrollTop = chatBox.value.scrollHeight
  }
}

// ---------- 按天分组 ----------
// 时间戳来自后端 SSE 事件；历史回放的消息没有时间戳，不参与分组
function localDay(d) {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

function showDayDivider(idx) {
  const cur = messages.value[idx]
  if (!cur?.ts) return false
  const prev = messages.value[idx - 1]
  // 上一条没有时间戳（历史回放）也视为跨段，让新消息归到所属日期下
  if (!prev?.ts) return true
  const a = new Date(prev.ts)
  const b = new Date(cur.ts)
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return false
  return localDay(a) !== localDay(b)
}

function dayDividerLabel(ts) {
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  if (localDay(date) === localDay(now)) return '今天'
  if (localDay(date) === localDay(new Date(now.getTime() - 86400000))) return '昨天'
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`
}

// ---------- 今日成本徽章 ----------
const todayUsage = ref(null)

async function loadUsage() {
  try {
    const res = await fetchUsage()
    todayUsage.value = res.today
  } catch {
    // 顶栏徽章是装饰性的，读取失败静默即可
  }
}

// ---------- 全局快捷键 ----------
// "/" 聚焦输入框（非输入状态时）；Alt+N 新建会话
const inputRef = ref(null)

function onGlobalKeydown(e) {
  const target = e.target
  const typing =
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target.isContentEditable

  if (e.key === '/' && !typing) {
    e.preventDefault()
    inputRef.value?.focus()
  } else if (e.altKey && (e.key === 'n' || e.key === 'N') && isLoggedIn.value) {
    e.preventDefault()
    startNewChat()
  }
}

// ---------- 空状态欢迎页 ----------
const suggestions = [
  { label: '🧮 算一下 123 × 456', text: '帮我算一下 123 乘以 456' },
  { label: '🕐 现在几点了', text: '现在几点了？' },
  { label: '📚 会话保存在哪里？', text: '这个项目的会话保存在哪里？保存多久？' },
  { label: '🌐 搜一下今天的 AI 新闻', text: '帮我搜一下今天有什么 AI 领域的新闻' },
]

function useSuggestion(text) {
  input.value = text
  send()
}

// ---------- 引用联动 ----------
// AI 正文里的 [n] 点击后滚动到最近的引用卡片并高亮一下
function citeIndexesFor(idx) {
  for (let i = idx; i >= 0; i--) {
    const m = messages.value[i]
    if (m.type === 'tool' && m.citations?.length) {
      return new Set(m.citations.map((c) => c.index))
    }
  }
  return null
}

function jumpToCitation(el) {
  const index = el.dataset.cite
  // 引用卡片挂在它所属工具块里：从点击的 AI 消息向上找最近的那个
  let node = el.closest('.msg')?.previousElementSibling
  while (node) {
    const card = node.querySelector?.(`.citations [data-cite-index="${index}"]`)
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' })
      card.classList.remove('cite-flash')
      void card.offsetWidth // 强制重排，保证连续点击也能重启动画
      card.classList.add('cite-flash')
      setTimeout(() => card.classList.remove('cite-flash'), 1200)
      return
    }
    node = node.previousElementSibling
  }
}

async function renameCurrent(session) {
  try {
    const { value } = await ElMessageBox.prompt('新的会话名称', '重命名会话', {
      inputValue: session.title,
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
    await renameSessionApi(session.session_id, value.trim())
    const target = sessions.value.find((s) => s.session_id === session.session_id)
    if (target) target.title = value.trim()
    ElMessage.success('已重命名')
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '重命名失败')
    }
  }
}

function toggleTool(idx) {
  expandedTools.value[idx] = !expandedTools.value[idx]
}

function onAuthenticated(user) {
  username.value = user.name
  isAdmin.value = !!user.isAdmin
  isLoggedIn.value = true
  // 用户可能登录页上切过主题：登录页直接写 localStorage 和 html.dark，
  // 这里的 ref 是启动时的快照，必须重新读一次，否则头部按钮状态会反
  isDark.value = localStorage.getItem('theme') === 'dark'
  applyTheme()
  restoreLastSession()
}

async function tryRestoreSession() {
  // 页面刷新后，尝试用已存的 token 恢复登录
  if (!getToken()) return
  try {
    const me = await fetchMe()
    username.value = me.username
    isAdmin.value = !!me.is_admin
    isLoggedIn.value = true
    await restoreLastSession()
  } catch {
    setToken(null)
  }
}

function logout() {
  setToken(null)
  isLoggedIn.value = false
  username.value = ''
  isAdmin.value = false
  messages.value = []
  expandedTools.value = {}
  input.value = ''
  sessions.value = []
  sessionId.value = 'session_' + Date.now()
}

// ---------- 会话侧边栏 ----------

async function loadSessions() {
  sessionsLoading.value = true
  try {
    const res = await listSessions()
    sessions.value = res.sessions ?? []
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      logout()
    } else {
      console.warn('读取会话列表失败', e)
    }
  } finally {
    sessionsLoading.value = false
  }
}

async function openSession(id) {
  if (id === sessionId.value && messages.value.length) return
  try {
    const res = await fetchSession(id)
    sessionId.value = id
    messages.value = res.messages ?? []
    expandedTools.value = {}
    input.value = ''
    removeAttachment()
    autoScroll.value = true
    await scrollToBottom(true)
    // 打开历史会话后自动收起侧边栏：窄屏下必须收，宽屏也顺手的
    if (window.innerWidth < 900) sidebarCollapsed.value = true
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '读取会话失败')
    }
  }
}

async function restoreLastSession() {
  // 登录 / 刷新后自动打开最近一次对话，和豆包的行为一致
  await loadSessions()
  loadUsage()
  if (sessions.value.length) {
    await openSession(sessions.value[0].session_id)
  }
}

function selectSession(id) {
  openSession(id)
}

async function removeSession(session) {
  try {
    await clearSession(session.session_id)
    sessions.value = sessions.value.filter(
      (s) => s.session_id !== session.session_id,
    )
    ElMessage.success('会话已删除')
    // 删的是当前打开的会话，就回到空白新对话
    if (session.session_id === sessionId.value) startNewChat()
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '删除失败')
    }
  }
}

function startNewChat() {
  // 关键行为变化：新建对话**不再删除**旧会话。
  // 旧会话由侧边栏的删除按钮显式管理——这就是豆包式交互的差别所在。
  sessionId.value = 'session_' + Date.now()
  messages.value = []
  expandedTools.value = {}
  input.value = ''
  removeAttachment()
  if (window.innerWidth < 900) sidebarCollapsed.value = true
}

function pickFile() {
  // 用隐藏 input 而非 el-upload：这里不需要自动上传，
  // 也不想让组件替我们维护文件列表，上传时机由我们自己控制。
  fileInput.value?.click()
}

async function onFilePicked(event) {
  const file = event.target.files?.[0]
  // 主动清空，否则连续选择同一个文件不会再触发 change 事件
  event.target.value = ''
  if (!file) return
  await uploadAndAttach(file)
}

// 全局粘贴：截图（QQ/微信/系统截图工具）或复制的文件会出现在
// clipboardData.files 里，取第一个当附件上传。
// 监听 window 而不是输入框——焦点不在输入框时粘贴也能生效；
// 纯文本粘贴（含换行、代码）不含 files，直接 return 不干预。
function onGlobalPaste(event) {
  if (!isLoggedIn.value) return
  const files = event.clipboardData?.files
  if (!files || files.length === 0) return
  event.preventDefault() // 阻止把图片二进制当乱码文本塞进输入框
  uploadAndAttach(files[0])
}

async function uploadAndAttach(file) {
  uploading.value = true
  try {
    const info = await uploadFile(file)
    // 预览用本地 blob URL：图片不必再从服务端下载一次
    attachment.value = {
      ...info,
      previewUrl: info.kind === 'image' ? URL.createObjectURL(file) : null,
    }
    if (info.kind === 'image') {
      ElMessage.success(`图片已就绪：${info.filename}`)
    } else if (info.knowledge?.ingested) {
      ElMessage.success(`文档已入库 ${info.knowledge.chunks} 个片段：${info.filename}`)
    } else {
      ElMessage.warning(`文档已上传但未能入库：${info.knowledge?.error ?? '未知原因'}`)
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '上传失败')
    }
  } finally {
    uploading.value = false
  }
}

function totalTokens(tokens) {
  if (!tokens) return '0'
  const total = tokens.total_tokens ?? (tokens.input_tokens ?? 0) + (tokens.output_tokens ?? 0)
  return total.toLocaleString('zh-CN')
}

function formatCost(cost) {
  // 单次成本常在厘级，固定 4 位小数才看得出变化
  if (cost === undefined || cost === null) return '—'
  return `¥${Number(cost).toFixed(4)}`
}

// 搜索防抖：用户打字过程中不必每个字符都请求一次
function onKbSearch() {
  clearTimeout(kbSearchTimer)
  kbSearchTimer = setTimeout(() => {
    kbPage.value = 1
    loadKnowledge()
  }, 300)
}

async function loadKnowledge() {
  kbLoading.value = true
  try {
    const res = await listKnowledge({
      q: kbQuery.value,
      page: kbPage.value,
      pageSize: kbPageSize,
    })
    kbDocs.value = res.documents ?? []
    kbTotal.value = res.total ?? 0
    // 删除后当前页可能空了：回退一页再取，避免"明明还有数据却显示空白"
    if (kbDocs.value.length === 0 && kbPage.value > 1) {
      kbPage.value -= 1
      kbLoading.value = false
      return loadKnowledge()
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '读取知识库失败')
    }
  } finally {
    kbLoading.value = false
  }
}

function openKnowledge() {
  kbVisible.value = true
  loadKnowledge()
}

async function openProfile() {
  profileVisible.value = true
  profileLoading.value = true
  showPasswordForm.value = false
  pwdForm.old = ''
  pwdForm.next = ''
  try {
    // 账号信息、用量与我的文档并行取；会话数直接用侧边栏已加载的列表
    const [me, usage, docs, auditRes] = await Promise.all([
      fetchMe(),
      fetchUsage(),
      listKnowledge({ mine: true, page: 1, pageSize: 50 }),
      fetchAudit(20),
    ])
    profileMe.value = me
    profileUsage.value = usage
    profileDocs.value = docs.documents ?? []
    profileAudit.value = auditRes.records ?? []
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '读取个人数据失败')
    }
  } finally {
    profileLoading.value = false
  }
}

async function submitPassword() {
  if (!pwdForm.old || !pwdForm.next) {
    ElMessage.warning('请填写原密码和新密码')
    return
  }
  if (pwdForm.next.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  pwdSaving.value = true
  try {
    const res = await changePassword(pwdForm.old, pwdForm.next)
    // 服务端已使旧 token 全部失效，并用新版本号签发了新 token——
    // 更新本地登录态，用户改完密码不必重新登录
    if (res.access_token) setToken(res.access_token)
    ElMessage.success('密码已修改，旧登录态已全部失效')
    showPasswordForm.value = false
    pwdForm.old = ''
    pwdForm.next = ''
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '修改失败')
    }
  } finally {
    pwdSaving.value = false
  }
}

async function clearMySessions() {
  const count = sessions.value.length
  try {
    await ElMessageBox.confirm(
      `删除全部 ${count} 个会话？此操作不可恢复，且只影响你自己的账号。`,
      '清空全部会话',
      { type: 'warning', confirmButtonText: '全部删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const res = await clearAllSessions()
    ElMessage.success(`已清空 ${res.count} 个会话`)
    // 回到全新的空白对话
    startNewChat()
    await loadSessions()
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '清空失败')
    }
  }
}

async function removeProfileDoc(doc) {
  try {
    await ElMessageBox.confirm(
      `删除「${doc.source}」的全部 ${doc.chunks} 个片段？`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const res = await deleteKnowledge(doc.doc_id)
    ElMessage.success(`已删除 ${res.chunks} 个片段`)
    profileDocs.value = profileDocs.value.filter((d) => d.doc_id !== doc.doc_id)
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '删除失败')
    }
  }
}

// 审计动作翻译成中文：审计表存的是枚举常量，展示层负责可读性
const ACTION_LABELS = {
  login: '登录',
  login_failed: '登录失败',
  register: '注册',
  change_password: '修改密码',
  delete_document: '删除文档',
  clear_session: '删除会话',
  clear_all_sessions: '清空会话',
  upload: '上传文件',
}

function actionLabel(action) {
  return ACTION_LABELS[action] || action
}

function formatTokens(usage) {
  if (!usage) return '0'
  const total = (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0)
  if (total >= 1_000_000) return `${(total / 1_000_000).toFixed(1)}M`
  if (total >= 1_000) return `${(total / 1_000).toFixed(1)}k`
  return String(total)
}

// 点击文档名：展开/收起原文预览。内容懒加载，点开才请求
async function toggleDoc(doc) {
  if (kbExpanded.value === doc.doc_id) {
    kbExpanded.value = null
    return
  }
  kbExpanded.value = doc.doc_id
  kbChunks.value = []
  kbChunksLoading.value = true
  try {
    const res = await fetchKnowledgeContent(doc.doc_id)
    kbChunks.value = res.chunks ?? []
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '读取文档内容失败')
      kbExpanded.value = null
    }
  } finally {
    kbChunksLoading.value = false
  }
}

async function removeDoc(doc) {
  // 共享文档影响所有用户，确认文案要更重，防止当成"删自己的东西"
  const shared = !doc.owner
  try {
    await ElMessageBox.confirm(
      shared
        ? `删除共享文档「${doc.source}」？共 ${doc.chunks} 个片段，删除后所有用户都无法检索到它。`
        : `删除「${doc.source}」的全部 ${doc.chunks} 个片段？`,
      shared ? '删除共享文档' : '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }

  kbLoading.value = true
  try {
    const res = await deleteKnowledge(doc.doc_id)
    ElMessage.success(`已删除 ${res.chunks} 个片段`)
    await loadKnowledge()
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      ElMessage.error(e.message || '删除失败')
    }
  } finally {
    kbLoading.value = false
  }
}

function removeAttachment() {
  // blob URL 不释放会一直占着内存 blob，直到页面刷新
  if (attachment.value?.previewUrl) URL.revokeObjectURL(attachment.value.previewUrl)
  attachment.value = null
}

// ---------- 打字机渐显 ----------
// 后端按"整条回答"推送（stream_mode=values），前端做逐字渐显。
// 打字进行中渲染纯文本，完成后才切 Markdown——半截 Markdown
// 渲染出来是破碎的（比如 "**bo"）。
const typingQueue = []
let typingTimer = null
const TYPE_SPEED = 3 // 每帧字符数：16ms 一帧约 180 字/秒，长回答也不会等太久

function enqueueTyping(item, full) {
  item.content = ''
  item.typing = true
  typingQueue.push({ item, full, pos: 0 })
  if (!typingTimer) typingTimer = setInterval(stepTyping, 16)
}

function stepTyping() {
  for (let i = typingQueue.length - 1; i >= 0; i--) {
    const entry = typingQueue[i]
    entry.pos = Math.min(entry.full.length, entry.pos + TYPE_SPEED)
    entry.item.content = entry.full.slice(0, entry.pos)
    if (entry.pos >= entry.full.length) {
      entry.item.typing = false
      typingQueue.splice(i, 1)
    }
  }
  scrollToBottom()
  if (!typingQueue.length) {
    clearInterval(typingTimer)
    typingTimer = null
  }
}

function finishTyping() {
  // 停止生成 / 中断时立即补全，不留半截话
  for (const entry of typingQueue) {
    entry.item.content = entry.full
    entry.item.typing = false
  }
  typingQueue.length = 0
  if (typingTimer) {
    clearInterval(typingTimer)
    typingTimer = null
  }
}

// ---------- 停止生成 ----------
const abortController = ref(null)

function stopGenerate() {
  abortController.value?.abort()
}

// ---------- 代码块复制（事件委托） ----------
function onChatClick(e) {
  // 引用跳转：点正文里的 [n] 滚到对应引用卡片
  const citeEl = e.target.closest('.cite-ref')
  if (citeEl) {
    jumpToCitation(citeEl)
    return
  }
  const btn = e.target.closest('.copy-btn')
  if (!btn) return
  const code = btn.closest('.code-block')?.querySelector('pre code')?.textContent ?? ''
  navigator.clipboard.writeText(code).then(() => {
    btn.textContent = '已复制'
    setTimeout(() => { btn.textContent = '复制' }, 1500)
  })
}

async function send() {
  const text = input.value.trim()
  if (!text || loading.value) return

  input.value = ''
  loading.value = true
  abortController.value = new AbortController()
  // 用户主动发送，恢复跟随滚动
  autoScroll.value = true

  // 先取快照：await 期间用户可能移除附件，
  // 本轮必须继续用它，否则发送的内容和画面会不一致。
  const file = attachment.value

  try {
    await chatStream({
      message: text,
      sessionId: sessionId.value,
      fileId: file?.file_id ?? null,
      signal: abortController.value.signal,
      onEvent: (event) => {
        if (event.type === 'usage') {
          // 用量不单独成气泡：它属于刚刚那条回答，挂上去才对得上
          const lastAi = [...messages.value].reverse().find((m) => m.type === 'ai')
          if (lastAi) {
            lastAi.usage = { tokens: event.tokens, cost: event.cost_cny }
          }
          return
        }
        if (event.type === 'human') {
          // 后端为了让模型知道有附件，会在原文后追加 [用户附带了...]，
          // 这是给模型看的标记，不该出现在用户面前，渲染前去掉。
          event.content = (event.content || '').replace(/\n?\[用户附带了[^\]]*\]\s*$/, '')
          if (file) {
            event.attachment = {
              filename: file.filename,
              previewUrl: file.kind === 'image' ? file.previewUrl : null,
              kind: file.kind,
            }
          }
        }
        messages.value.push(event)
        // AI 回答走打字机渐显（注意取的是数组里的响应式代理，直接改原始对象不会触发更新）
        const item = messages.value[messages.value.length - 1]
        if (event.type === 'ai' && event.content) {
          enqueueTyping(item, event.content)
        }
        scrollToBottom()
      },
    })
  } catch (e) {
    if (e.name === 'AbortError') {
      messages.value.push({ type: 'error', content: '已停止生成。' })
      scrollToBottom()
    } else if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      messages.value.push({ type: 'error', content: e.message || String(e) })
      scrollToBottom()
    }
  } finally {
    abortController.value = null
    loading.value = false
    finishTyping()
    // 刷新侧边栏与今日用量：新会话在这里诞生，老会话的活跃时间在这里更新
    loadSessions()
    loadUsage()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  window.addEventListener('paste', onGlobalPaste)
  tryRestoreSession()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  window.removeEventListener('paste', onGlobalPaste)
})
</script>

<style>
/* ---------- 主题变量：浅色为默认，html.dark 覆盖 ----------
   与登录页（LoginView.vue 的 token 块）同一套配色语言：
   浅色 = 朝霞暖调（桃橙→雾蓝），深色 = 深海冷调（青色主色）。
   --page-bg 是"光晕 + 底色"的复合渐变，光晕直接画在背景里，
   不需要额外的 DOM 层。 */
:root {
  --page-bg:
    radial-gradient(640px 420px at 6% -4%, rgba(251, 176, 120, 0.28), transparent 62%),
    radial-gradient(680px 460px at 98% 104%, rgba(147, 197, 253, 0.32), transparent 62%),
    linear-gradient(135deg, #ffe8d6 0%, #f7e1d7 40%, #e0f4ff 100%);
  --panel-bg: #ffffff;
  --panel-bg-2: #fbf3ec;
  --text-1: #1d2129;
  --text-2: #4e5969;
  --text-3: #86909c;
  --border-1: #e5e7eb;
  --hover-bg: rgba(22, 119, 255, 0.06);
  --active-bg: rgba(22, 119, 255, 0.1);
  --code-bg: #f8f9fb;
  --code-bar-bg: #f5f7fa;
  --inline-code-bg: #f0f2f5;
  --color-primary: #1677ff;
  --primary-soft: rgba(22, 119, 255, 0.1);
  --primary-border: rgba(22, 119, 255, 0.35);

  /* Element Plus 组件主色跟随主题（含 hover/active 的衍生档位） */
  --el-color-primary: #1677ff;
  --el-color-primary-light-3: #4d94ff;
  --el-color-primary-light-5: #8ab8ff;
  --el-color-primary-light-7: #b8d3ff;
  --el-color-primary-light-8: #d3e3ff;
  --el-color-primary-light-9: #e9f1ff;
  --el-color-primary-dark-2: #1272d9;
}

html.dark {
  --page-bg:
    radial-gradient(640px 420px at 6% -4%, rgba(56, 130, 246, 0.13), transparent 62%),
    radial-gradient(680px 460px at 98% 104%, rgba(124, 92, 255, 0.11), transparent 62%),
    linear-gradient(135deg, #07090f 0%, #111827 50%, #0b1a2b 100%);
  --panel-bg: #1b2230;
  --panel-bg-2: #161c28;
  --text-1: #f0f4f8;
  --text-2: #c9d1d9;
  --text-3: #8b98a5;
  --border-1: #2a3442;
  --hover-bg: rgba(37, 182, 215, 0.08);
  --active-bg: rgba(37, 182, 215, 0.12);
  --code-bg: #10141c;
  --code-bar-bg: #1a2029;
  --inline-code-bg: #2a2b2f;
  --color-primary: #25b6d7;
  --primary-soft: rgba(37, 182, 215, 0.12);
  --primary-border: rgba(37, 182, 215, 0.4);

  --el-color-primary: #25b6d7;
  --el-color-primary-light-3: #55c6de;
  --el-color-primary-light-5: #7fd3e6;
  --el-color-primary-light-7: #a8e1ee;
  --el-color-primary-light-8: #c2eaf3;
  --el-color-primary-light-9: #dbf3f8;
  --el-color-primary-dark-2: #1e92ac;
  color-scheme: dark;
}

body {
  background: var(--page-bg) fixed;
  color: var(--text-1);
}

/* highlight.js 引入的 github 主题是浅色配色，暗色下换成 github-dark 色板。
   覆盖的是常用 token 类，未覆盖的 token 继承 .hljs 的基础色。 */
html.dark .hljs {
  color: #c9d1d9;
  background: transparent;
}

html.dark .hljs-comment,
html.dark .hljs-quote {
  color: #8b949e;
  font-style: italic;
}

html.dark .hljs-keyword,
html.dark .hljs-selector-tag {
  color: #ff7b72;
}

html.dark .hljs-string,
html.dark .hljs-regexp {
  color: #a5d6ff;
}

html.dark .hljs-number,
html.dark .hljs-literal,
html.dark .hljs-built_in {
  color: #79c0ff;
}

html.dark .hljs-title,
html.dark .hljs-title.function_ {
  color: #d2a8ff;
}

html.dark .hljs-attr,
html.dark .hljs-attribute,
html.dark .hljs-variable,
html.dark .hljs-template-variable {
  color: #79c0ff;
}

html.dark .hljs-type,
html.dark .hljs-title.class_ {
  color: #ffa657;
}

html.dark .hljs-section,
html.dark .hljs-name {
  color: #7ee787;
}
</style>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
}

/* min-width:0 允许主区域收缩，长代码行才不会把侧边栏挤出屏幕 */
.main-area {
  flex: 1;
  min-width: 0;
  position: relative;
}

.container {
  max-width: 1000px;
  margin: 0 auto;
  padding: 24px;
  font-family: system-ui, -apple-system, sans-serif;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.header-left h1 {
  white-space: nowrap;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  /* 关键：任何宽度下都允许换行而不是挤压——
     按钮形状和文字方向恒定，空间不足时整行下移 */
  flex-wrap: wrap;
  row-gap: 10px;
  margin-bottom: 16px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  row-gap: 8px;
}

/* 顶栏按钮：与登录页同一套玻璃质感，替代 el-button 默认样式 */
.hdr-btn {
  padding: 6px 12px;
  border: 1px solid var(--border-1);
  border-radius: 8px;
  background: var(--panel-bg);
  color: var(--text-2);
  font-size: 13px;
  /* 任何宽度下文字都保持横排，绝不竖排换字 */
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
  transition:
    color 0.2s ease,
    border-color 0.2s ease,
    background-color 0.2s ease;
}
.hdr-btn:hover {
  color: var(--color-primary);
  border-color: var(--primary-border);
  background: var(--primary-soft);
}
.hdr-btn.icon-only {
  padding: 6px 9px;
}
.hdr-btn.danger:hover {
  color: #f56c6c;
  border-color: rgba(245, 108, 108, 0.4);
  background: rgba(245, 108, 108, 0.08);
}

/* 主题切换小圆钮：位置和尺寸与登录页 .theme-toggle 完全一致
   （44px、右上角 24/28px），fixed 定位让它脱离顶栏按钮流 */
.theme-toggle-sm {
  position: fixed;
  top: 24px;
  right: 28px;
  z-index: 30;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border: 1px solid var(--border-1);
  background: var(--panel-bg);
  color: var(--text-2);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08);
  transition:
    color 0.2s ease,
    border-color 0.2s ease,
    background-color 0.2s ease;
}
.theme-toggle-sm svg {
  width: 17px;
  height: 17px;
}
.theme-toggle-sm:hover {
  color: var(--color-primary);
  border-color: var(--primary-border);
  background: var(--primary-soft);
}

/* 窄屏：顶栏换行成两行（标题一行、按钮一行），
   按钮禁止竖排换字，成本徽章收起，悬浮钮缩小内收 */
@media (max-width: 760px) {
  .theme-toggle-sm {
    top: 12px;
    right: 12px;
    width: 36px;
    height: 36px;
  }
  .theme-toggle-sm svg {
    width: 15px;
    height: 15px;
  }
  .header {
    flex-wrap: wrap;
    row-gap: 10px;
  }
  .header-left h1 {
    font-size: 17px;
    white-space: nowrap;
  }
  .hdr-btn {
    padding: 5px 10px;
    font-size: 12px;
    white-space: nowrap;
  }
  .cost-badge {
    display: none;
  }
}

.username {
  font-size: 14px;
  color: var(--text-2);
  margin-right: 4px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.username-clickable {
  border: none;
  background: none;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background-color 0.2s ease, color 0.2s ease;
}
.username-clickable:hover {
  color: var(--color-primary);
  background: var(--primary-soft);
}

/* ---------- 个人中心 ---------- */
.pf-card {
  padding: 16px;
  border-radius: 12px;
  background: var(--panel-bg-2);
  border: 1px solid var(--border-1);
  margin-bottom: 18px;
}
.pf-user {
  display: flex;
  align-items: center;
  gap: 14px;
}
.pf-avatar {
  width: 48px;
  height: 48px;
  border-radius: 12px;
}
.pf-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-1);
  display: flex;
  align-items: center;
  gap: 8px;
}
.pf-sub {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 2px;
}
.pf-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-2);
  margin: 18px 0 10px;
}
.pf-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.pf-stat {
  padding: 12px 8px;
  border-radius: 10px;
  background: var(--panel-bg-2);
  border: 1px solid var(--border-1);
  text-align: center;
}
.pf-stat-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-1);
}
.pf-stat-label {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-3);
}
.pf-cache-note {
  margin-top: 10px;
  font-size: 12px;
  color: var(--text-3);
}
.pf-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--panel-bg-2);
  border: 1px solid var(--border-1);
  font-size: 13px;
  color: var(--text-2);
  margin-bottom: 8px;
}
.pf-row-value {
  color: var(--text-1);
  font-weight: 600;
}
.pf-empty {
  font-size: 12px;
  color: var(--text-3);
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--panel-bg-2);
  border: 1px dashed var(--border-1);
}
.pf-doc-name {
  font-size: 13px;
  color: var(--text-1);
  word-break: break-all;
  min-width: 0;
}
.pf-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: none;
}
.pf-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.pf-pwd {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border-radius: 10px;
  background: var(--panel-bg-2);
  border: 1px solid var(--border-1);
}
.pf-tip {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.5;
}

/* 操作记录 */
.pf-audit {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  margin-bottom: 6px;
  border-radius: 8px;
  background: var(--panel-bg-2);
  border: 1px solid var(--border-1);
  font-size: 12px;
}
.pf-audit-action {
  color: var(--text-1);
  font-weight: 600;
  flex: none;
}
.pf-audit-target {
  color: var(--text-3);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pf-audit-outcome.ok {
  color: #67c23a;
}
.pf-audit-outcome.fail {
  color: #f56c6c;
}
.pf-audit-time {
  color: var(--text-3);
  flex: none;
}

h1 {
  font-size: 24px;
  color: var(--text-1);
  margin: 0;
}

.chat-box {
  /* 高度跟随视口：窗口越大聊区越高，长对话不用频繁滚动 */
  min-height: 420px;
  max-height: 70vh;
  border: 1px solid var(--border-1);
  border-radius: 8px;
  padding: 16px;
  margin: 16px 0;
  overflow-y: auto;
  background: var(--panel-bg-2);
}

.msg {
  margin-bottom: 12px;
  line-height: 1.6;
  display: flex;
  align-items: flex-start;
}

.msg .label {
  font-weight: bold;
  margin-right: 8px;
  flex-shrink: 0;
  /* 徽标与文字的垂直对齐交给 flex 居中，
     vertical-align 的像素微调在不同字号和行高下不可靠 */
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* 消息角色徽标：替代 emoji，和登录页品牌标同一套视觉 */
.user-badge,
.agent-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 6px;
}

.user-badge {
  background: linear-gradient(135deg, #67c23a, #2bb673);
}

.agent-badge {
  background: linear-gradient(135deg, #409eff, #7b5cff);
}

.user-badge svg,
.agent-badge svg {
  width: 14px;
  height: 14px;
}

.user-badge.small {
  width: 18px;
  height: 18px;
  border-radius: 5px;
}

.msg .content {
  word-break: break-word;
}

.msg.human .label { color: #2563eb; }
.msg.ai .label { color: #16a34a; }
.msg.error .label { color: #dc2626; }

/* 等待首 token / 工具返回时的思考动画 */
.thinking-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.thinking-dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
  animation: dot-blink 1.2s infinite;
}

.thinking-dots i:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots i:nth-child(3) { animation-delay: 0.4s; }

@keyframes dot-blink {
  0%, 80%, 100% { opacity: 0.2; }
  40% { opacity: 1; }
}

/* 打字机光标 */
.type-cursor {
  display: inline-block;
  width: 8px;
  height: 15px;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--color-primary);
  animation: caret-blink 1s steps(1) infinite;
}

@keyframes caret-blink {
  50% { opacity: 0; }
}

.tool-block {
  width: 100%;
  border: 1px dashed #fbbf24;
  border-left: 3px solid #fbbf24;
  border-radius: 6px;
  padding: 8px 12px;
  background: var(--panel-bg-2);
}

/* 工具步骤条：状态点 + 完成徽章，过程一目了然 */
.tool-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  margin-right: 8px;
}

.tool-status {
  font-size: 12px;
  color: #16a34a;
  background: #f0fdf4;
  border-radius: 4px;
  padding: 1px 6px;
  margin-right: 8px;
}

.tool-header {
  display: flex;
  align-items: center;
  cursor: pointer;
  user-select: none;
}

.tool-header .label {
  color: #ea580c;
  font-weight: bold;
  margin-right: 8px;
  flex: 1;
}

.toggle {
  font-size: 12px;
  color: var(--text-3);
}

.tool-content {
  margin: 8px 0 0 0;
  font-size: 12px;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  background: var(--panel-bg);
  padding: 8px;
  border-radius: 4px;
}

/* 引用来源：与工具输出区分开，用蓝色系表示"可核验的原文" */
.citations {
  margin-top: 8px;
  border-top: 1px dashed #fbbf24;
  padding-top: 8px;
}

.citations-title {
  font-size: 12px;
  font-weight: 600;
  color: #d97706;
  margin-bottom: 6px;
}

.citation {
  background: var(--active-bg);
  border-left: 3px solid #60a5fa;
  border-radius: 4px;
  padding: 6px 8px;
  margin-bottom: 6px;
}

.citation-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  flex-wrap: wrap;
}

.citation-index {
  color: var(--color-primary);
  font-weight: 700;
}

.citation-source {
  color: var(--text-1);
  font-weight: 600;
}

.citation-heading {
  color: var(--text-3);
}

.citation-score {
  color: var(--text-3);
  margin-left: auto;
}

.citation-text {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 120px;
  overflow-y: auto;
}

.input-area {
  display: flex;
  gap: 12px;
  align-items: center;
}

/* 隐藏原生 file input：它的默认样式无法和界面统一，由按钮代为触发 */
.file-input {
  display: none;
}

.attachment-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  padding: 8px 12px;
  border: 1px dashed var(--border-1);
  border-radius: 8px;
  background: var(--panel-bg-2);
}

.attachment-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.thumb {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--border-1);
}

.attachment-name {
  font-size: 13px;
  color: var(--text-2);
}

.usage {
  margin-top: 6px;
}

.usage-text {
  font-size: 12px;
  color: var(--text-3);
}

.cache-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  background: #f0f9eb;
  color: #67c23a;
  font-size: 12px;
}

.kb-empty {
  font-size: 13px;
  color: var(--text-3);
  line-height: 1.8;
}

.kb-empty code {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--inline-code-bg);
  font-size: 12px;
}

.kb-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid var(--border-1);
  border-radius: 8px;
}

.kb-name {
  font-size: 14px;
  color: var(--text-1);
  word-break: break-all;
}

.kb-name-clickable {
  border: none;
  background: none;
  padding: 0;
  cursor: pointer;
  font: inherit;
  text-align: left;
  width: 100%;
}
.kb-name-clickable:hover {
  color: var(--color-primary);
}
.kb-caret {
  font-size: 11px;
  color: var(--text-3);
  margin-left: 4px;
}

.kb-chunks {
  margin-top: 8px;
  padding: 8px 10px;
  max-height: 260px;
  overflow-y: auto;
  border-radius: 6px;
  background: var(--panel-bg-2);
}
.kb-chunk {
  margin-bottom: 10px;
}
.kb-chunk:last-child {
  margin-bottom: 0;
}
.kb-chunk-heading {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
  margin-bottom: 2px;
}
.kb-chunk-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.kb-search {
  margin-bottom: 12px;
}

.kb-pagination {
  margin-top: 12px;
  justify-content: center;
}

.kb-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-3);
}

.attachment-kind {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--primary-soft);
  color: var(--color-primary);
  font-size: 12px;
}

.session-info {
  display: none;
}

/* ---------- Markdown 正文（v-html 内容，需 :deep 穿透 scoped） ---------- */
.md-body {
  width: 100%;
  line-height: 1.75;
  word-break: break-word;
}

.md-body :deep(p) {
  margin: 4px 0;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) {
  margin: 12px 0 6px;
  font-size: 15px;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 4px 0;
  padding-left: 22px;
}

.md-body :deep(a) {
  color: var(--color-primary);
}

.md-body :deep(blockquote) {
  margin: 6px 0;
  padding: 2px 10px;
  border-left: 3px solid #dcdfe6;
  color: var(--text-2);
}

/* 行内代码 */
.md-body :deep(code) {
  font-family: Consolas, Monaco, 'Courier New', monospace;
  font-size: 13px;
}

.md-body :deep(:not(pre) > code) {
  background: var(--inline-code-bg);
  padding: 1px 5px;
  border-radius: 4px;
}

/* 代码块：语言标签栏 + 复制按钮 + 高亮 */
.md-body :deep(.code-block) {
  margin: 8px 0;
  border: 1px solid var(--border-1);
  border-radius: 8px;
  overflow: hidden;
}

.md-body :deep(.code-bar) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  background: var(--code-bar-bg);
  font-size: 12px;
  color: var(--text-3);
}

.md-body :deep(.copy-btn) {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--color-primary);
  font-size: 12px;
}

.md-body :deep(.copy-btn:hover) {
  color: #66b1ff;
}

.md-body :deep(pre) {
  margin: 0;
  padding: 10px 12px;
  background: var(--code-bg);
  overflow-x: auto;
}

.md-body :deep(pre code) {
  display: block;
  background: none;
  padding: 0;
}

/* Markdown 表格：模型常输出参数对照表，不给边框会挤成一团 */
.md-body :deep(table) {
  margin: 8px 0;
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}

.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid var(--border-1);
  padding: 5px 10px;
  text-align: left;
}

.md-body :deep(th) {
  background: var(--code-bar-bg);
}

/* 正文里的 [n] 引用标记：可点击跳转 */
.md-body :deep(.cite-ref) {
  color: var(--color-primary);
  cursor: pointer;
  border-radius: 3px;
  padding: 0 1px;
}

.md-body :deep(.cite-ref:hover) {
  background: var(--active-bg);
}

/* 点击 [n] 后对应引用卡片闪烁提示 */
.citation.cite-flash {
  animation: cite-flash 0.5s ease 2;
}

@keyframes cite-flash {
  50% { background: var(--active-bg); }
}

/* ---------- 空状态欢迎页 ---------- */
.welcome {
  text-align: center;
  padding: 56px 8px 32px;
}

.welcome-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-1);
}

.welcome-sub {
  margin: 8px 0 22px;
  font-size: 13px;
  color: var(--text-3);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
}

.chip {
  padding: 8px 14px;
  border: 1px solid var(--border-1);
  border-radius: 18px;
  background: var(--panel-bg);
  color: var(--text-2);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.chip:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--active-bg);
}

/* ---------- 回到底部按钮 ---------- */
.to-bottom {
  position: absolute;
  right: 28px;
  bottom: 96px;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid var(--border-1);
  background: var(--panel-bg);
  color: var(--text-2);
  cursor: pointer;
  font-size: 16px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
  z-index: 15;
}

.to-bottom:hover {
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 页面切换（对话 ↔ 看板） */
.page-enter-active,
.page-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.page-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* ---------- 消息按天分组 ---------- */
.day-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 14px 0 10px;
  color: var(--text-3);
  font-size: 12px;
  user-select: none;
}

.day-divider::before,
.day-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--border-1);
}

/* ---------- 顶栏今日成本徽章 ---------- */
.cost-badge {
  font-size: 12px;
  color: var(--text-2);
  background: var(--panel-bg-2);
  border: 1px solid var(--border-1);
  border-radius: 12px;
  padding: 3px 10px;
  margin-right: 4px;
  cursor: default;
  white-space: nowrap;
}
</style>
