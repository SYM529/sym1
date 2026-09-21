<template>
  <div class="auth-container">
    <el-card class="auth-card">
      <template #header>
        <div class="auth-header">
          <span class="auth-title">{{ isRegister ? '注册账号' : '登录 Agent 助手' }}</span>
          <el-button link type="primary" @click="switchMode">
            {{ isRegister ? '已有账号？去登录' : '没有账号？去注册' }}
          </el-button>
        </div>
      </template>

      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input
            v-model="form.username"
            autocomplete="username"
            placeholder="请输入用户名"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="至少 6 位"
            @keyup.enter="submit"
          />
        </el-form-item>

        <el-button type="primary" class="submit-btn" :loading="loading" @click="submit">
          {{ isRegister ? '注册并登录' : '登录' }}
        </el-button>
      </el-form>

      <el-alert v-if="error" :title="error" type="error" :closable="false" class="auth-error" />
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { login, register } from '@/api'

const emit = defineEmits(['authenticated'])

const isRegister = ref(false)
const loading = ref(false)
const error = ref('')
const form = reactive({ username: '', password: '' })

function switchMode() {
  isRegister.value = !isRegister.value
  error.value = ''
}

async function submit() {
  const username = form.username.trim()
  const password = form.password

  if (!username || !password) {
    error.value = '请输入用户名和密码'
    return
  }
  if (password.length < 6) {
    error.value = '密码至少 6 位'
    return
  }

  loading.value = true
  error.value = ''
  try {
    if (isRegister.value) {
      await register(username, password)
    }
    const data = await login(username, password)
    form.password = ''
    emit('authenticated', data.username)
  } catch (e) {
    error.value = e.message || '操作失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f4f6;
  padding: 24px;
}

.auth-card {
  width: 100%;
  max-width: 380px;
}

.auth-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.auth-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.submit-btn {
  width: 100%;
}

.auth-error {
  margin-top: 16px;
}
</style>
