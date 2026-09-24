<template>
  <aside class="sidebar" :class="{ collapsed }" :style="collapsed ? null : { width: width + 'px' }">
    <button class="new-btn" @click="$emit('new')">＋ 新建对话</button>

    <input v-model="search" class="search" type="text" placeholder="🔍 搜索会话" />

    <div class="list" v-loading="loading">
      <div
        v-for="s in filteredSessions"
        :key="s.session_id"
        :class="['item', { active: s.session_id === activeId }]"
        @click="$emit('select', s.session_id)"
      >
        <div class="item-main">
          <div class="item-title" :title="s.title">{{ s.title }}</div>
          <div class="item-time">{{ relativeTime(s.updated_at) }}</div>
        </div>
        <div class="item-actions">
          <button class="act" title="重命名" @click.stop="$emit('rename', s)">✎</button>
          <button class="del" title="删除会话" @click.stop="$emit('delete', s)">🗑</button>
        </div>
      </div>

      <div v-if="!loading && filteredSessions.length === 0" class="empty">
        {{ search ? '没有匹配的会话' : '还没有对话记录，发送第一条消息开始吧' }}
      </div>
    </div>

    <!-- 拖拽手柄：贴在右缘 6px 区域，双击恢复默认宽度 -->
    <div
      class="resizer"
      title="拖动调整宽度，双击恢复默认"
      @mousedown="startResize"
      @dblclick="$emit('update:width', DEFAULT_WIDTH)"
    ></div>
  </aside>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  collapsed: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  width: { type: Number, default: DEFAULT_WIDTH },
})

const emit = defineEmits(['new', 'select', 'delete', 'rename', 'update:width'])

const MIN_WIDTH = 200
const MAX_WIDTH = 480
const DEFAULT_WIDTH = 256

// 会话搜索：纯前端过滤，会话量级（个位数到几十）不需要后端搜索
const search = ref('')
const filteredSessions = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  if (!keyword) return props.sessions
  return props.sessions.filter((s) => (s.title || '').toLowerCase().includes(keyword))
})

function startResize(e) {
  e.preventDefault()
  const startX = e.clientX
  const startWidth = props.width

  const onMove = (ev) => {
    const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + ev.clientX - startX))
    emit('update:width', next)
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
  // 拖拽期间锁住光标形态并禁止选中文本，否则鼠标扫过列表会大片选中
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function relativeTime(iso) {
  if (!iso) return ''
  const time = new Date(iso).getTime()
  if (Number.isNaN(time)) return ''

  const diffMinutes = Math.floor((Date.now() - time) / 60000)
  if (diffMinutes < 1) return '刚刚'
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`

  const diffHours = Math.floor(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours} 小时前`

  const diffDays = Math.floor(diffHours / 24)
  if (diffDays === 1) return '昨天'
  if (diffDays < 7) return `${diffDays} 天前`

  const date = new Date(time)
  return `${date.getMonth() + 1}-${String(date.getDate()).padStart(2, '0')}`
}
</script>

<style scoped>
.sidebar {
  /* 实际宽度由父组件的 width prop 控制，这里是 SSR/首帧兜底 */
  width: 256px;
  flex-shrink: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  border-right: 1px solid var(--border-1);
  background: var(--panel-bg-2);
  position: relative;
}

/* 收起时直接移除布局空间，主区域自动铺满 */
.sidebar.collapsed {
  display: none;
}

/* 拖拽手柄：不可见但命中区域 6px，悬停时给出提示色 */
.resizer {
  position: absolute;
  top: 0;
  right: -3px;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 20;
  transition: background 0.15s;
}

.resizer:hover {
  background: var(--primary-border);
}

.new-btn {
  padding: 10px;
  border: 1px solid var(--border-1);
  border-radius: 8px;
  background: var(--panel-bg);
  color: var(--text-1);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.15s;
}

.search {
  padding: 8px 10px;
  border: 1px solid var(--border-1, #ebeef5);
  border-radius: 8px;
  background: var(--panel-bg, #fff);
  color: var(--text-1, #303133);
  font-size: 13px;
  outline: none;
}

.search:focus {
  border-color: var(--primary-border);
}

.new-btn:hover {
  background: var(--primary-soft);
  border-color: var(--primary-border);
  color: var(--color-primary);
}

.list {
  flex: 1;
  overflow-y: auto;
}

.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 10px;
  margin-bottom: 4px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}

.item:hover {
  background: var(--hover-bg);
}

.item.active {
  background: var(--active-bg);
}

.item-main {
  min-width: 0;
  flex: 1;
  overflow: hidden;
}

/* 不再写死 max-width：标题跟随侧边栏宽度自适应，靠 flex + overflow 截断 */
.item-title {
  font-size: 13px;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item.active .item-title {
  color: #409eff;
  font-weight: 600;
}

.item-time {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-3);
}

/* 操作按钮只在悬停时出现：常用操作不喧宾夺主 */
.item-actions {
  flex-shrink: 0;
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s;
}

.item:hover .item-actions {
  opacity: 1;
}

.act,
.del {
  flex-shrink: 0;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 13px;
  padding: 2px;
}

.act:hover {
  color: #409eff;
}

.del:hover {
  color: #f56c6c;
}

.empty {
  padding: 16px 12px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.8;
  text-align: center;
}
</style>
