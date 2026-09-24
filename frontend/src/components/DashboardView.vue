<template>
  <div class="dashboard" v-loading="loading">
    <div class="dash-header">
      <h1>评测看板</h1>
      <el-button size="small" @click="$emit('back')">返回对话</el-button>
    </div>

    <div v-if="error" class="dash-error">{{ error }}</div>

    <template v-else-if="data && data.latest">
      <!-- 最新一轮端到端指标 -->
      <div class="cards">
        <div class="card">
          <div class="card-num">{{ pct(data.latest.pass_rate) }}</div>
          <div class="card-label">综合通过率</div>
        </div>
        <div class="card">
          <div class="card-num">{{ pct(data.latest.tool_call_accuracy) }}</div>
          <div class="card-label">工具调用准确率</div>
        </div>
        <div class="card">
          <div class="card-num">{{ pct(data.latest.citation_accuracy) }}</div>
          <div class="card-label">引用准确率</div>
        </div>
        <div class="card">
          <div class="card-num">{{ fmtSec(data.latest.p50) }} / {{ fmtSec(data.latest.p95) }}</div>
          <div class="card-label">P50 / P95 延迟</div>
        </div>
        <div class="card">
          <div class="card-num">{{ data.latest.total_cases }}</div>
          <div class="card-label">用例数（repeat × {{ data.latest.repeat }}）</div>
        </div>
        <div class="card">
          <div class="card-num">¥{{ fmtCost(data.latest.cost_cny) }}</div>
          <div class="card-label">单次全量成本</div>
        </div>
      </div>
      <div class="dash-meta">
        报告：<code>{{ data.latest.file }}</code>
        <span v-if="data.latest.generated_at"> · {{ data.latest.generated_at.replace('T', ' ') }}</span>
      </div>

      <!-- 趋势 -->
      <div class="section-title trend-bar">
        <span>通过率趋势（每次全量评测一个点）</span>
        <el-select v-model="rangeFilter" size="small" class="range-select">
          <el-option v-for="r in RANGES" :key="r.value" :label="r.label" :value="r.value" />
        </el-select>
      </div>
      <div ref="trendChart" class="chart tall"></div>

      <div class="section-title">延迟趋势</div>
      <div ref="latencyChart" class="chart"></div>

      <!-- 分类通过率 -->
      <div class="section-title">分类通过率（最新报告）</div>
      <div ref="categoryChart" class="chart tall"></div>

      <!-- 检索指标 -->
      <template v-if="latestRetrieval">
        <div class="section-title">检索质量（最新检索评测）</div>
        <div class="cards">
          <div class="card">
            <div class="card-num">{{ pct(latestRetrieval.recall_at_1_fused) }}</div>
            <div class="card-label">Recall@1 · 融合排序</div>
          </div>
          <div class="card">
            <div class="card-num highlight">{{ pct(latestRetrieval.recall_at_1_reranked) }}</div>
            <div class="card-label">Recall@1 · 精排后</div>
          </div>
          <div class="card">
            <div class="card-num">{{ pct(latestRetrieval.recall_at_3_reranked) }}</div>
            <div class="card-label">Recall@3 · 精排后</div>
          </div>
          <div class="card">
            <div class="card-num">{{ latestRetrieval.mrr ?? '—' }}</div>
            <div class="card-label">MRR</div>
          </div>
          <div class="card">
            <div class="card-num">{{ pct(latestRetrieval.faithfulness) }}</div>
            <div class="card-label">忠实度</div>
          </div>
        </div>
        <div class="dash-meta">
          精排把 Recall@1 从 {{ pct(latestRetrieval.recall_at_1_fused) }}
          提升到 {{ pct(latestRetrieval.recall_at_1_reranked) }}
          ——两行卡片的差值就是 cross-encoder 的直接收益。
        </div>
      </template>

      <!-- 缓存标定 -->
      <template v-if="data.calibration">
        <div class="section-title">语义缓存阈值标定</div>
        <div class="cards">
          <div class="card">
            <div class="card-num">{{ data.calibration.chosen_threshold }}</div>
            <div class="card-label">选定阈值</div>
          </div>
          <div class="card">
            <div class="card-num">{{ data.calibration.false_hits_at_chosen }}</div>
            <div class="card-label">评测集上的误命中</div>
          </div>
          <div class="card">
            <div class="card-num">{{ data.calibration.max_distinct_similarity }}</div>
            <div class="card-label">不同问题的最大相似度</div>
          </div>
          <div class="card">
            <div class="card-num">{{ data.calibration.cacheable_questions }} / {{ data.calibration.questions }}</div>
            <div class="card-label">可缓存用例 / 总数</div>
          </div>
        </div>
      </template>

      <!-- 报告对比 -->
      <template v-if="evalReportsDesc.length >= 2">
        <div class="section-title">报告对比</div>
        <div class="diff-selects">
          <el-select v-model="diffBase" size="small" class="diff-select">
            <el-option
              v-for="r in evalReportsDesc"
              :key="r.file"
              :label="`${r.tag}（${(r.generated_at || '').slice(0, 10)}）`"
              :value="r.file"
            />
          </el-select>
          <span class="diff-arrow">→</span>
          <el-select v-model="diffCmp" size="small" class="diff-select">
            <el-option
              v-for="r in evalReportsDesc"
              :key="r.file"
              :label="`${r.tag}（${(r.generated_at || '').slice(0, 10)}）`"
              :value="r.file"
            />
          </el-select>
        </div>
        <table class="diff-table">
          <thead>
            <tr><th>指标</th><th>基线</th><th>对比</th><th>变化</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in diffRows" :key="row.name">
              <td>{{ row.name }}</td>
              <td>{{ fmtValue(row.va, row.fmt) }}</td>
              <td>{{ fmtValue(row.vb, row.fmt) }}</td>
              <td :class="row.same ? 'same' : (row.improved ? 'good' : 'bad')">
                {{ fmtDelta(row) }}
              </td>
            </tr>
          </tbody>
        </table>
      </template>
    </template>

    <div v-else-if="!loading" class="dash-error">
      还没有评测报告。先运行：<code>python -m evals.run_eval --skip-network --tag demo</code>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, MarkLineComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fetchReports, ApiError } from '@/api'

// 按需注册：全量引入 echarts 会让包凭空多出几百 KB
echarts.use([
  LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent,
  MarkLineComponent, CanvasRenderer,
])

const props = defineProps({
  // 暗色模式下 echarts 需要换主题重绘（主题在 init 时确定）
  dark: { type: Boolean, default: false },
})

defineEmits(['back'])

const loading = ref(false)
const error = ref('')
const data = ref(null)

const trendChart = ref(null)
const latencyChart = ref(null)
const categoryChart = ref(null)
const instances = []

// ---------- 时间范围筛选 ----------
const rangeFilter = ref('all')
const RANGES = [
  { value: 'all', label: '全部' },
  { value: '7', label: '最近 7 天' },
  { value: '30', label: '最近 30 天' },
]

const filteredTrend = computed(() => {
  const list = data.value?.trend ?? []
  if (rangeFilter.value === 'all') return list
  const cutoff = Date.now() - Number(rangeFilter.value) * 86400000
  return list.filter((r) => {
    const time = new Date(r.generated_at).getTime()
    return !Number.isNaN(time) && time >= cutoff
  })
})

// ---------- 报告对比 ----------
const diffBase = ref('')
const diffCmp = ref('')

// 新的在前：下拉框里先看到最近跑的报告
const evalReportsDesc = computed(() => [...(data.value?.trend ?? [])].reverse())

// 默认拿最近两次做对比，用户再自行切换
watch(evalReportsDesc, (list) => {
  if (!diffBase.value && list.length >= 2) {
    diffBase.value = list[1].file
    diffCmp.value = list[0].file
  }
}, { immediate: true })

const diffRows = computed(() => {
  const base = data.value?.trend.find((r) => r.file === diffBase.value)
  const cmp = data.value?.trend.find((r) => r.file === diffCmp.value)
  if (!base || !cmp) return []

  // lowerBetter：延迟与成本是越低越好，涨了要标红而不是标绿
  const defs = [
    ['综合通过率', 'pass_rate', 'pct', false],
    ['工具调用准确率', 'tool_call_accuracy', 'pct', false],
    ['引用准确率', 'citation_accuracy', 'pct', false],
    ['P50 延迟', 'p50', 'sec', true],
    ['P95 延迟', 'p95', 'sec', true],
    ['Token 总量', 'total_tokens', 'int', true],
    ['估算成本 (CNY)', 'cost_cny', 'cost', true],
  ]
  return defs.map(([name, key, fmt, lowerBetter]) => {
    const va = base[key]
    const vb = cmp[key]
    const delta = (vb ?? 0) - (va ?? 0)
    return {
      name, fmt, lowerBetter, va, vb, delta,
      improved: lowerBetter ? delta < 0 : delta > 0,
      same: Math.abs(delta) < 1e-9,
    }
  })
})

function fmtValue(value, fmt) {
  if (value === undefined || value === null) return '—'
  if (fmt === 'pct') return `${(value * 100).toFixed(1)}%`
  if (fmt === 'sec') return `${value}s`
  if (fmt === 'cost') return `¥${Number(value).toFixed(4)}`
  return Number(value).toLocaleString('zh-CN')
}

function fmtDelta(row) {
  if (row.same) return '持平'
  const arrow = row.delta > 0 ? '↑' : '↓'
  if (row.fmt === 'pct') return `${arrow} ${Math.abs(row.delta * 100).toFixed(1)}pp`
  if (row.fmt === 'cost') return `${arrow} ¥${Math.abs(row.delta).toFixed(4)}`
  return `${arrow} ${Math.abs(row.delta).toLocaleString('zh-CN')}`
}

const latestRetrieval = computed(() => {
  const list = data.value?.retrieval ?? []
  return list.length ? list[list.length - 1] : null
})

function pct(value) {
  if (value === undefined || value === null) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function fmtSec(sec) {
  return sec === undefined || sec === null ? '—' : `${sec}s`
}

function fmtCost(cost) {
  return cost === undefined || cost === null ? '—' : Number(cost).toFixed(2)
}

function render(key, el, option) {
  if (!el) return
  // 重渲染前先销毁旧实例：时间筛选/主题切换会反复触发，不销毁会泄漏
  instances[key]?.dispose()
  const chart = echarts.init(el, props.dark ? 'dark' : undefined)
  // 背景透明：让图表融入卡片底色，而不是 echarts 主题自带的底色
  chart.setOption({ backgroundColor: 'transparent', ...option })
  instances[key] = chart
}

function xLabels(reports) {
  // 同一天跑多次时 tag 可能重复，时间才能区分先后
  return reports.map((r) => (r.generated_at || '').slice(5, 16).replace('T', ' '))
}

function renderTrend(reports) {
  render('trend', trendChart.value, {
    tooltip: { trigger: 'axis', valueFormatter: (v) => `${(v * 100).toFixed(1)}%` },
    legend: { top: 0 },
    grid: { left: 48, right: 16, top: 32, bottom: 48 },
    xAxis: { type: 'category', data: xLabels(reports), axisLabel: { rotate: 40, fontSize: 10 } },
    yAxis: { type: 'value', min: 0, max: 1, axisLabel: { formatter: (v) => `${v * 100}%` } },
    series: [
      { name: '综合通过率', type: 'line', data: reports.map((r) => r.pass_rate), smooth: true },
      { name: '工具调用准确率', type: 'line', data: reports.map((r) => r.tool_call_accuracy), smooth: true },
      { name: '稳定通过率', type: 'line', data: reports.map((r) => r.stable_pass_rate), smooth: true },
    ],
  })
}

function renderLatency(reports) {
  render('latency', latencyChart.value, {
    tooltip: { trigger: 'axis', valueFormatter: (v) => `${v}s` },
    legend: { top: 0 },
    grid: { left: 48, right: 16, top: 32, bottom: 48 },
    xAxis: { type: 'category', data: xLabels(reports), axisLabel: { rotate: 40, fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}s' } },
    series: [
      { name: 'P50', type: 'line', data: reports.map((r) => r.p50), smooth: true },
      { name: 'P95', type: 'line', data: reports.map((r) => r.p95), smooth: true },
    ],
  })
}

function renderCategories(latest) {
  const entries = Object.entries(latest.categories ?? {})
  // 通过率放最后画会盖住前面的，按通过率升序排列更有可读性
  entries.sort((a, b) => a[1].pass_rate - b[1].pass_rate)

  render('category', categoryChart.value, {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => `${(v * 100).toFixed(1)}%` },
    grid: { left: 140, right: 32, top: 8, bottom: 32 },
    xAxis: { type: 'value', min: 0, max: 1, axisLabel: { formatter: (v) => `${v * 100}%` } },
    yAxis: {
      type: 'category',
      data: entries.map(([name]) => name),
      axisLabel: { fontSize: 11 },
    },
    series: [{
      type: 'bar',
      data: entries.map(([, v]) => v.pass_rate),
      itemStyle: {
        // 未满分的项目用警示色，让"哪里还有缺口"一眼可见
        color: (p) => (p.value >= 1 ? '#67c23a' : '#e6a23c'),
      },
      label: { show: true, position: 'right', formatter: (p) => `${(p.value * 100).toFixed(0)}%` },
    }],
  })
}

function onResize() {
  Object.values(instances).forEach((c) => c.resize())
}

function renderAll() {
  const trend = filteredTrend.value
  if (trend.length) {
    renderTrend(trend)
    renderLatency(trend)
  }
  if (data.value?.latest) renderCategories(data.value.latest)
}

// 时间筛选或主题切换都会改变图表数据/配色，统一在这里重绘
watch([filteredTrend], () => nextTick(renderAll))

onMounted(async () => {
  loading.value = true
  try {
    data.value = await fetchReports()
    await nextTick()
    renderAll()
    window.addEventListener('resize', onResize)
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      error.value = '登录已失效，请返回重新登录'
    } else {
      error.value = e.message || '读取评测报告失败'
    }
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  Object.values(instances).forEach((c) => c.dispose())
})
</script>

<style scoped>
.dashboard {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px 16px 48px;
}

.dash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.dash-header h1 {
  font-size: 20px;
  margin: 0;
}

.dash-error {
  padding: 24px;
  border: 1px dashed var(--border-1);
  border-radius: 8px;
  color: var(--text-3);
  font-size: 14px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}

.card {
  padding: 14px;
  border: 1px solid var(--border-1);
  border-radius: 10px;
  background: var(--panel-bg-2);
}

.card-num {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-1);
}

.card-num.highlight {
  color: #67c23a;
}

.card-label {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-3);
}

.dash-meta {
  margin: 10px 2px 0;
  font-size: 12px;
  color: var(--text-3);
}

.dash-meta code {
  padding: 1px 6px;
  border-radius: 4px;
  background: #f4f4f5;
  font-size: 12px;
}

.section-title {
  margin: 24px 0 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-1);
}

.trend-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.range-select {
  width: 120px;
}

/* ---------- 报告对比 ---------- */
.diff-selects {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.diff-select {
  flex: 1;
}

.diff-arrow {
  color: var(--text-3);
}

.diff-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.diff-table th,
.diff-table td {
  border: 1px solid var(--border-1);
  padding: 6px 10px;
  text-align: left;
}

.diff-table th {
  background: var(--panel-bg-2);
  color: var(--text-2);
  font-weight: 600;
}

.diff-table td.good {
  color: #16a34a;
  font-weight: 600;
}

.diff-table td.bad {
  color: #dc2626;
  font-weight: 600;
}

.diff-table td.same {
  color: var(--text-3);
}

.chart {
  width: 100%;
  height: 280px;
  border: 1px solid var(--border-1);
  border-radius: 10px;
}

.chart.tall {
  height: 340px;
}
</style>
