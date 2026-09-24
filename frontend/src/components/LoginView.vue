<template>
  <div class="auth-page" :class="isDark ? 'dark' : 'light'">
    <div class="bg-grid" />
    <div class="glow glow-a" />
    <div class="glow glow-b" />

    <!-- 主题切换：深色显示太阳（点它去浅色），浅色显示月亮 -->
    <button
      class="theme-toggle"
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

    <div class="auth-shell">
      <!-- 左侧品牌区 -->
      <aside class="brand-panel">
        <div class="brand-head">
          <div class="brand-logo">
            <svg viewBox="0 0 48 48" role="img" aria-label="Agent logo">
              <defs>
                <linearGradient id="brand-lg" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stop-color="#409eff" />
                  <stop offset="1" stop-color="#7b5cff" />
                </linearGradient>
              </defs>
              <rect x="4" y="4" width="40" height="40" rx="12" fill="url(#brand-lg)" />
              <path
                d="M24 11 L27.2 20.8 L37 24 L27.2 27.2 L24 37 L20.8 27.2 L11 24 L20.8 20.8 Z"
                fill="#fff"
              />
              <circle cx="36" cy="12" r="2.6" fill="#fff" opacity="0.85" />
            </svg>
          </div>
          <div class="brand-title">
            <h1>Agent 智能助手</h1>
            <p>一个能自主调用工具完成任务的大模型助手</p>
          </div>
        </div>

        <div class="feat-grid">
          <div class="feat-card">
            <span class="feat-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
                <rect x="5" y="3" width="14" height="18" rx="2" />
                <path d="M8.5 7.5h7" />
                <circle cx="9" cy="12" r="0.6" fill="currentColor" />
                <circle cx="15" cy="12" r="0.6" fill="currentColor" />
                <circle cx="9" cy="16" r="0.6" fill="currentColor" />
                <circle cx="15" cy="16" r="0.6" fill="currentColor" />
              </svg>
            </span>
            <div class="feat-text">
              <div class="feat-title">精准计算</div>
              <div class="feat-desc">数学交给计算引擎，不会出错</div>
            </div>
          </div>

          <div class="feat-card">
            <span class="feat-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
                <circle cx="11" cy="11" r="6.5" />
                <path d="M15.8 15.8 20 20" />
                <path d="M4.5 11h13M11 4.5c2.4 1.8 2.4 11.2 0 13" />
              </svg>
            </span>
            <div class="feat-text">
              <div class="feat-title">联网搜索</div>
              <div class="feat-desc">实时获取最新信息</div>
            </div>
          </div>

          <div class="feat-card">
            <span class="feat-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5 4h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8.5L6 19.5V15H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
                <path d="M8 8.5h8M8 11.5h5" />
              </svg>
            </span>
            <div class="feat-text">
              <div class="feat-title">知识库问答</div>
              <div class="feat-desc">回答附带来源</div>
            </div>
          </div>

          <div class="feat-card">
            <span class="feat-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <rect x="4" y="5" width="16" height="14" rx="2" />
                <circle cx="9" cy="10" r="1.4" />
                <path d="M4.5 16.5 9 12.5l3.2 3 2.6-2.4 4.7 4.2" />
              </svg>
            </span>
            <div class="feat-text">
              <div class="feat-title">图片理解</div>
              <div class="feat-desc">上传图片即时问答</div>
            </div>
          </div>
        </div>
      </aside>

      <!-- 右侧玻璃登录卡 -->
      <section class="glass-card">
        <div class="card-head">
          <h2>{{ isRegister ? '注册账号' : '登录 Agent 助手' }}</h2>
          <el-button link class="switch-link" @click="switchMode">
            {{ isRegister ? '已有账号？去登录' : '没有账号？去注册' }}
          </el-button>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          @submit.prevent="submit"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              ref="usernameRef"
              v-model="form.username"
              size="large"
              autocomplete="username"
              placeholder="请输入用户名"
              @focus="onFieldFocus('username')"
            />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              ref="passwordRef"
              v-model="form.password"
              type="password"
              size="large"
              show-password
              :autocomplete="isRegister ? 'new-password' : 'current-password'"
              placeholder="至少 6 位"
              @keyup="checkCaps"
              @keydown="checkCaps"
              @blur="capsOn = false"
              @keyup.enter="submit"
              @focus="onFieldFocus('password')"
            />
            <div v-if="capsOn" class="caps-tip">⚠️ 大写锁定已开启</div>
          </el-form-item>

          <div v-if="isRegister && form.password" class="strength">
            <div class="strength-bars">
              <span
                v-for="i in 4"
                :key="i"
                class="bar"
                :class="{ on: i <= strength.score, ['lv' + strength.score]: i <= strength.score }"
              />
            </div>
            <span class="strength-label">{{ strength.label }}</span>
          </div>

          <el-button size="large" class="submit-btn" :loading="loading" @click="submit">
            {{ isRegister ? '注册并登录' : '登录' }}
          </el-button>
        </el-form>

        <el-alert v-if="error" :title="error" type="error" :closable="false" class="auth-error" />
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { login, register } from '@/api'

const emit = defineEmits(['authenticated'])

const isRegister = ref(false)
const loading = ref(false)
const error = ref('')
const form = reactive({ username: '', password: '' })
const usernameRef = ref(null)
const passwordRef = ref(null)
const formRef = ref(null)
const capsOn = ref(false)

// ---------- 主题 ----------
// 与 App.vue 同一套约定：localStorage 'theme' + html.dark 类。
// 登录页自己也能切，切完写回 localStorage，登录后主界面读到的就是对的。
const isDark = ref(localStorage.getItem('theme') === 'dark')

function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
  document.documentElement.classList.toggle('dark', isDark.value)
}

// 用户名规则与后端 USERNAME_PATTERN 保持一致，前端先拦一道
const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_.-]+$/, message: '只能包含字母、数字、下划线、点和短横线', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
}

// 密码强度：长度 + 字符多样性的简单启发式，够提示用，不上 zxcvbn 那种重依赖
const strength = computed(() => {
  const p = form.password
  if (!p) return { score: 0, label: '' }
  let score = 0
  if (p.length >= 6) score++
  if (p.length >= 10) score++
  if (/[A-Za-z]/.test(p) && /\d/.test(p)) score++
  if (/[^A-Za-z0-9]/.test(p)) score++
  const labels = ['太短', '弱', '中', '良好', '强']
  return { score, label: labels[score] }
})

function checkCaps(e) {
  if (e?.getModifierState) capsOn.value = e.getModifierState('CapsLock')
}

function nativeInput(instance) {
  return instance?.input ?? instance?.textarea ?? null
}

// 浏览器自动填充直接写 DOM、不触发 input 事件，v-model 感知不到——
// 组件状态还是空串，用户一动键盘字符就"追加"在旧值后面，
// 表现为"必须先手动删掉才能输入"。这里把原生值同步回 v-model。
function syncAutofill() {
  const pairs = [
    [usernameRef.value, 'username'],
    [passwordRef.value, 'password'],
  ]
  for (const [inst, key] of pairs) {
    const el = nativeInput(inst)
    if (el?.value && !form[key]) form[key] = el.value
  }
}

function onFieldFocus(key) {
  syncAutofill()
  const inst = key === 'username' ? usernameRef.value : passwordRef.value
  // 聚焦即全选：再次登录时点进去直接输入就覆盖旧值，不用先删
  nativeInput(inst)?.select()
}

// 自动填充的时机不固定（通常在渲染后片刻），挂载后延迟同步一次；
// 就算这次没赶上，聚焦和提交前的同步也能兜住
onMounted(() => setTimeout(syncAutofill, 200))

function switchMode() {
  isRegister.value = !isRegister.value
  error.value = ''
  formRef.value?.clearValidate()
}

async function submit() {
  // 提交前也同步一次：用户可能全程没碰输入框（自动填充后直接点登录）
  syncAutofill()

  const valid = await formRef.value.validate().then(() => true).catch(() => false)
  if (!valid) return

  const username = form.username.trim()
  const password = form.password

  loading.value = true
  error.value = ''
  try {
    if (isRegister.value) {
      await register(username, password)
    }
    const data = await login(username, password)
    form.password = ''
    // 整包传给主界面：用户名 + 管理员身份（决定主界面是否显示"看板"入口）
    emit('authenticated', { name: data.username, isAdmin: !!data.is_admin })
  } catch (e) {
    error.value = e.message || '操作失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<!-- 设计 token：全局块（:root / html.dark 在 scoped 里匹配不到根元素） -->
<style>
:root {
  /* 页面背景：两套渐变都常驻，用双层交叉淡入实现"渐变也能过渡" */
  --bg-page-light: linear-gradient(135deg, #ffe8d6 0%, #f7e1d7 40%, #e0f4ff 100%);
  --bg-page-dark: linear-gradient(135deg, #07090f 0%, #111827 50%, #0b1a2b 100%);

  --bg-card: #ffffff;
  --text-title: #1d2129;
  --text-body: #4e5969;
  --text-placeholder: #86909c;
  --border-input: #e5e7eb;
  --color-primary: #1677ff;
  --shadow-card: 0 10px 40px rgba(255, 180, 120, 0.25);

  /* 补齐的表面 token */
  --glow-warm: rgba(251, 176, 120, 0.35);
  --glow-cool: rgba(147, 197, 253, 0.4);
  --bg-feat: rgba(255, 255, 255, 0.78);
  --border-feat: rgba(226, 232, 240, 0.9);
  --bg-input: rgba(255, 255, 255, 0.92);
  --bg-input-focus: #ffffff;
  --border-card: rgba(255, 255, 255, 0.9);
  --btn-gradient: linear-gradient(135deg, #22d3ee, #1677ff);
  --focus-ring:
    0 0 0 1.5px #38bdf8 inset,
    0 0 10px rgba(56, 189, 248, 0.25);
  --shadow-btn:
    0 10px 26px rgba(34, 211, 238, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.35);
  --icon-color: #3b82f6;
  --icon-bg: rgba(59, 130, 246, 0.1);
  --grid-line: rgba(30, 64, 120, 0.05);
  --bar-bg: #e2e8f0;
}

html.dark {
  --bg-card: rgba(30, 36, 48, 0.35);
  --text-title: #f0f4f8;
  --text-body: #c9d1d9;
  --text-placeholder: #8b98a5;
  --border-input: rgba(37, 182, 215, 0.25);
  --color-primary: #25b6d7;
  /* 中性深色投影：立体感来自明暗而不是彩色光晕 */
  --shadow-card: 0 8px 24px rgba(0, 0, 0, 0.35);

  --glow-warm: rgba(56, 130, 246, 0.16);
  --glow-cool: rgba(124, 92, 255, 0.12);
  --bg-feat: rgba(255, 255, 255, 0.05);
  --border-feat: rgba(255, 255, 255, 0.08);
  --bg-input: rgba(255, 255, 255, 0.05);
  --bg-input-focus: rgba(255, 255, 255, 0.08);
  --border-card: rgba(148, 163, 255, 0.28);
  --btn-gradient: linear-gradient(135deg, #25b6d7, #3b82f6);
  --focus-ring:
    0 0 0 1px rgba(56, 189, 248, 0.85) inset,
    0 0 14px rgba(56, 189, 248, 0.35);
  --shadow-btn:
    0 10px 26px rgba(37, 182, 215, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.35);
  --icon-color: #7dd3fc;
  --icon-bg: rgba(56, 189, 248, 0.12);
  --grid-line: rgba(148, 178, 255, 0.05);
  --bar-bg: rgba(148, 163, 255, 0.2);
}
</style>

<style scoped>
/* ================= 页面 ================= */
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  padding: 24px;
}

/* 渐变背景不能直接 transition，拆成两层交叉淡入，
   其它颜色类属性正常 0.3s 过渡。
   注意必须显式给 z-index：::after 在树序上位于 .auth-shell 之后，
   同为定位元素时会盖住内容——这里手动把背景层压到最底 */
.auth-page::before,
.auth-page::after {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  transition: opacity 0.3s ease;
}
.auth-page::before {
  background: var(--bg-page-light);
  opacity: 1;
}
.auth-page::after {
  background: var(--bg-page-dark);
  opacity: 0;
}
.auth-page.dark::before {
  opacity: 0;
}
.auth-page.dark::after {
  opacity: 1;
}

/* 低对比网格纹理，越靠边越淡 */
.bg-grid {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background-image:
    linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size: 44px 44px;
  -webkit-mask-image: radial-gradient(ellipse at center, #000 25%, transparent 72%);
  mask-image: radial-gradient(ellipse at center, #000 25%, transparent 72%);
  transition: background-image 0.3s ease;
}

/* 光晕：浅色左暖右冷（朝霞），深色冷蓝紫 */
.glow {
  position: absolute;
  z-index: 1;
  border-radius: 50%;
  filter: blur(100px);
  pointer-events: none;
  transition: background 0.3s ease;
}
.glow-a {
  width: 520px;
  height: 520px;
  top: -160px;
  left: -140px;
  background: var(--glow-warm);
}
.glow-b {
  width: 460px;
  height: 460px;
  bottom: -180px;
  right: -120px;
  background: var(--glow-cool);
}

/* 主题切换 0.3s 柔和过渡：只过渡颜色类属性，不动布局 */
.auth-page,
.glass-card,
.feat-card,
.theme-toggle,
.brand-title h1,
.brand-title p,
.feat-title,
.feat-desc,
.card-head h2 {
  transition:
    background-color 0.3s ease,
    color 0.3s ease,
    border-color 0.3s ease,
    box-shadow 0.3s ease;
}

/* ================= 主题切换按钮 ================= */
.theme-toggle {
  position: fixed;
  top: 24px;
  right: 28px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 10;
  border: 1px solid var(--border-feat);
  background: var(--bg-feat);
  color: var(--text-body);
  backdrop-filter: blur(10px);
}
.theme-toggle svg {
  width: 20px;
  height: 20px;
}
.theme-toggle:hover {
  color: var(--text-title);
  border-color: var(--color-primary);
}

/* ================= 布局 ================= */
.auth-shell {
  display: flex;
  align-items: center;
  gap: 72px;
  position: relative;
  z-index: 2;
  animation: rise 0.5s ease-out both;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ================= 品牌区 ================= */
.brand-panel {
  width: 420px;
}

.brand-head {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: 36px;
}

.brand-logo {
  width: 60px;
  height: 60px;
  flex: none;
}
.brand-logo svg {
  display: block;
  width: 100%;
  height: 100%;
  filter: drop-shadow(0 8px 20px rgba(64, 158, 255, 0.4));
}

.brand-title h1 {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
  color: var(--text-title);
}
.brand-title p {
  margin: 6px 0 0;
  font-size: 13.5px;
  color: var(--text-body);
}

/* 功能卡片：两行两列 */
.feat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.feat-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px 14px;
  border-radius: 12px;
  background: var(--bg-feat);
  border: 1px solid var(--border-feat);
  box-shadow: var(--shadow-card);
}
.feat-card:hover {
  border-color: var(--color-primary);
}

.feat-icon {
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--icon-color);
  background: var(--icon-bg);
}
.feat-icon svg {
  width: 19px;
  height: 19px;
}

.feat-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-title);
}
.feat-desc {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-body);
}

/* ================= 玻璃登录卡 ================= */
.glass-card {
  width: 420px;
  padding: 36px 34px 30px;
  border-radius: 20px;
  background: var(--bg-card);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--border-card);
  box-shadow: var(--shadow-card);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 24px;
}

.card-head h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-title);
}
/* 深色下标题用青蓝渐变字，呼应主色 */
.auth-page.dark .card-head h2 {
  background: linear-gradient(90deg, #67e8f9, #60a5fa);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.switch-link {
  color: var(--color-primary);
  font-size: 13px;
}

/* 输入框：玻璃底，聚焦主色光 */
.glass-card :deep(.el-form-item__label) {
  color: var(--text-body);
  font-size: 13px;
}

.glass-card :deep(.el-input__wrapper) {
  border-radius: 10px;
  background: var(--bg-input);
  box-shadow: 0 0 0 1px var(--border-input) inset;
  transition: box-shadow 0.25s ease, background-color 0.3s ease;
}
.glass-card :deep(.el-input__wrapper.is-focus) {
  background: var(--bg-input-focus);
  box-shadow: var(--focus-ring);
}
.glass-card :deep(.el-input__inner) {
  color: var(--text-title);
}
.glass-card :deep(.el-input__inner::placeholder) {
  color: var(--text-placeholder);
}

.caps-tip {
  margin-top: 6px;
  font-size: 12px;
  color: #e6a23c;
}

/* 密码强度条 */
.strength {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: -6px 0 14px;
}
.strength-bars {
  display: flex;
  gap: 4px;
  flex: 1;
}
.bar {
  height: 4px;
  flex: 1;
  border-radius: 2px;
  background: var(--bar-bg);
  transition: background 0.2s;
}
.bar.on.lv1 {
  background: #f56c6c;
}
.bar.on.lv2 {
  background: #e6a23c;
}
.bar.on.lv3 {
  background: #409eff;
}
.bar.on.lv4 {
  background: #67c23a;
}
.strength-label {
  font-size: 12px;
  color: var(--text-placeholder);
  min-width: 32px;
  text-align: right;
}

/* 主按钮：主色渐变 + 顶部高光 */
.submit-btn {
  width: 100%;
  margin-top: 6px;
  border: none !important;
  font-weight: 600;
  letter-spacing: 2px;
  color: #fff !important;
  background: var(--btn-gradient) !important;
  box-shadow: var(--shadow-btn);
  transition: filter 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}
.submit-btn:hover {
  filter: brightness(1.08);
  transform: translateY(-1px);
}

.auth-error {
  margin-top: 16px;
}

/* ================= 窄屏 ================= */
@media (max-width: 960px) {
  .auth-shell {
    flex-direction: column;
    gap: 32px;
  }
  .brand-panel {
    width: 100%;
    max-width: 420px;
  }
  .glass-card {
    width: 100%;
    max-width: 420px;
  }
}
</style>
