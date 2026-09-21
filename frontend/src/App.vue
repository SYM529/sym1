<template>
  <LoginView v-if="!username" @authenticated="onAuthenticated" />

  <div v-else class="container">
    <div class="header">
      <h1>Agent 智能助手</h1>
      <div class="header-actions">
        <span class="user-tag">👋 {{ username }}</span>
        <el-button size="small" @click="newSession">新会话</el-button>
        <el-button size="small" @click="logout">退出登录</el-button>
      </div>
    </div>

    <div class="chat-box" ref="chatBox">
      <!-- 用户消息 -->
      <div v-for="(msg, idx) in messages" :key="idx" :class="['msg', msg.type]">
        <template v-if="msg.type === 'human'">
          <span class="label">👤 你</span>
          <span class="content">{{ msg.content }}</span>
        </template>

        <!-- 工具调用折叠 -->
        <template v-else-if="msg.type === 'tool'">
          <div class="tool-block">
            <div class="tool-header" @click="toggleTool(idx)">
              <span class="label">🔧 {{ msg.name || '工具' }}</span>
              <span class="toggle">{{ expandedTools[idx] ? '▲ 收起' : '▼ 查看' }}</span>
            </div>
            <pre v-show="expandedTools[idx]" class="tool-content">{{ msg.content }}</pre>
          </div>
        </template>

        <!-- Agent 回答 -->
        <template v-else-if="msg.type === 'ai'">
          <!-- 中间态：正在思考 -->
          <template v-if="!msg.content">
            <span class="label">🤖 Agent</span>
            <span class="content thinking">正在思考...</span>
          </template>
          <!-- 最终回答 -->
          <template v-else>
            <span class="label">🤖 Agent</span>
            <span class="content">{{ msg.content }}</span>
          </template>
        </template>

        <!-- 错误 -->
        <template v-else-if="msg.type === 'error'">
          <span class="label">❌ 错误</span>
          <span class="content">{{ msg.content }}</span>
        </template>
      </div>
    </div>

    <div class="input-area">
      <el-input
        v-model="input"
        placeholder="输入任务，比如：帮我算一下 123 * 456"
        @keyup.enter="send"
        :disabled="loading"
      />
      <el-button type="primary" :loading="loading" @click="send">发送</el-button>
    </div>

    <div class="session-info">当前会话：{{ sessionId }}</div>
  </div>
</template>

<script setup>
import { onMounted, ref, nextTick } from 'vue'
import { getToken, setToken, fetchMe, clearSession, chatStream } from '@/api'
import LoginView from '@/components/LoginView.vue'

const input = ref('')
const messages = ref([])
const loading = ref(false)
const chatBox = ref(null)
const sessionId = ref('session_' + Date.now())
const expandedTools = ref({})   // 记录每个工具块是否展开
const username = ref('')

let abortController = null

function toggleTool(idx) {
  expandedTools.value[idx] = !expandedTools.value[idx]
}

async function scrollToBottom() {
  await nextTick()
  if (chatBox.value) {
    chatBox.value.scrollTop = chatBox.value.scrollHeight
  }
}

function resetConversation() {
  messages.value = []
  expandedTools.value = {}
  input.value = ''
  sessionId.value = 'session_' + Date.now()
}

function onAuthenticated(name) {
  username.value = name
  resetConversation()
}

function handleError(e) {
  // token 失效时静默退回登录页
  if (e.status === 401) {
    username.value = ''
    resetConversation()
    return
  }
  messages.value.push({ type: 'error', content: String(e.message || e) })
  scrollToBottom()
}

function logout() {
  abortController?.abort()
  setToken(null)
  username.value = ''
  resetConversation()
}

onMounted(async () => {
  // 已有 token 时静默恢复登录态
  if (!getToken()) return
  try {
    const me = await fetchMe()
    username.value = me.username
  } catch {
    username.value = ''
  }
})

async function newSession() {
  abortController?.abort()
  loading.value = false
  try {
    await clearSession(sessionId.value)
  } catch (e) {
    handleError(e)
    return
  }
  resetConversation()
}

async function send() {
  const text = input.value.trim()
  if (!text || loading.value) return

  input.value = ''
  loading.value = true
  messages.value.push({ type: 'human', content: text })
  scrollToBottom()

  abortController = new AbortController()

  try {
    await chatStream({
      message: text,
      sessionId: sessionId.value,
      signal: abortController.signal,
      onEvent: (event) => {
        // 用户消息已在本地渲染，跳过后端回传的同一条
        if (event.type === 'human') return
        messages.value.push(event)
        scrollToBottom()
      },
    })
  } catch (e) {
    if (e.name !== 'AbortError') handleError(e)
  } finally {
    loading.value = false
    abortController = null
  }
}
</script>

<style scoped>
.container {
  max-width: 800px;
  margin: 0 auto;
  padding: 24px;
  font-family: system-ui, -apple-system, sans-serif;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-tag {
  font-size: 13px;
  color: #6b7280;
}

h1 {
  font-size: 24px;
  color: #1f2937;
  margin: 0;
}

.chat-box {
  min-height: 400px;
  max-height: 600px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  margin: 16px 0;
  overflow-y: auto;
  background: #fafafa;
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
}

.msg .content {
  word-break: break-word;
}

.msg.human .label { color: #2563eb; }
.msg.ai .label { color: #16a34a; }
.msg.error .label { color: #dc2626; }

.thinking {
  color: #9ca3af;
  font-style: italic;
}

/* 工具折叠块 */
.tool-block {
  width: 100%;
  border: 1px dashed #fbbf24;
  border-radius: 6px;
  padding: 8px 12px;
  background: #fffbeb;
}

.tool-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  user-select: none;
}

.tool-header .label {
  color: #ea580c;
  font-weight: bold;
  margin-right: 8px;
}

.toggle {
  font-size: 12px;
  color: #9ca3af;
}

.tool-content {
  margin: 8px 0 0 0;
  font-size: 12px;
  color: #4b5563;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  background: #fff;
  padding: 8px;
  border-radius: 4px;
}

.input-area {
  display: flex;
  gap: 12px;
}

.session-info {
  margin-top: 12px;
  font-size: 12px;
  color: #9ca3af;
  text-align: right;
}
</style>
