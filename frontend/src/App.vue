<template>
  <!-- 未登录：显示登录页 -->
  <LoginView v-if="!isLoggedIn" @authenticated="onAuthenticated" />

  <!-- 已登录：显示对话界面 -->
  <div v-else class="container">
    <div class="header">
      <h1>Agent 智能助手</h1>
      <div class="header-right">
        <span class="username">👤 {{ username }}</span>
        <el-button size="small" @click="newSession">新会话</el-button>
        <el-button size="small" type="danger" plain @click="logout">退出</el-button>
      </div>
    </div>

    <div class="chat-box" ref="chatBox">
      <div v-for="(msg, idx) in messages" :key="idx" :class="['msg', msg.type]">
        <template v-if="msg.type === 'human'">
          <span class="label">👤 你</span>
          <span class="content">{{ msg.content }}</span>
        </template>

        <template v-else-if="msg.type === 'tool'">
          <div class="tool-block">
            <div class="tool-header" @click="toggleTool(idx)">
              <span class="label">🔧 {{ msg.name || '工具' }}</span>
              <span class="toggle">{{ expandedTools[idx] ? '▲ 收起' : '▼ 查看' }}</span>
            </div>
            <pre v-show="expandedTools[idx]" class="tool-content">{{ msg.content }}</pre>
          </div>
        </template>

        <template v-else-if="msg.type === 'ai'">
          <span class="label">🤖 Agent</span>
          <span v-if="msg.content" class="content">{{ msg.content }}</span>
          <span v-else class="content thinking">正在思考...</span>
        </template>

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
import { ref, nextTick, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import LoginView from '@/components/LoginView.vue'
import { getToken, setToken, fetchMe, clearSession, chatStream, ApiError } from '@/api'

const isLoggedIn = ref(false)
const username = ref('')
const input = ref('')
const messages = ref([])
const loading = ref(false)
const chatBox = ref(null)
const sessionId = ref('session_' + Date.now())
const expandedTools = ref({})

function toggleTool(idx) {
  expandedTools.value[idx] = !expandedTools.value[idx]
}

async function scrollToBottom() {
  await nextTick()
  if (chatBox.value) {
    chatBox.value.scrollTop = chatBox.value.scrollHeight
  }
}

function onAuthenticated(name) {
  username.value = name
  isLoggedIn.value = true
}

async function tryRestoreSession() {
  // 页面刷新后，尝试用已存的 token 恢复登录
  if (!getToken()) return
  try {
    const me = await fetchMe()
    username.value = me.username
    isLoggedIn.value = true
  } catch {
    setToken(null)
  }
}

function logout() {
  setToken(null)
  isLoggedIn.value = false
  username.value = ''
  messages.value = []
  expandedTools.value = {}
  input.value = ''
  sessionId.value = 'session_' + Date.now()
}

async function newSession() {
  try {
    await clearSession(sessionId.value)
  } catch (e) {
    // 清空失败不阻塞，可能是会话本来就不存在
    console.warn('清空会话失败', e)
  }
  messages.value = []
  expandedTools.value = {}
  input.value = ''
  sessionId.value = 'session_' + Date.now()
}

async function send() {
  const text = input.value.trim()
  if (!text || loading.value) return

  input.value = ''
  loading.value = true

  try {
    await chatStream({
      message: text,
      sessionId: sessionId.value,
      onEvent: (event) => {
        messages.value.push(event)
        scrollToBottom()
      },
    })
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      logout()
    } else {
      messages.value.push({ type: 'error', content: e.message || String(e) })
      scrollToBottom()
    }
  } finally {
    loading.value = false
  }
}

onMounted(tryRestoreSession)
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

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.username {
  font-size: 14px;
  color: #4b5563;
  margin-right: 4px;
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
