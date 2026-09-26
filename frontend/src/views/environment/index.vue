<template>
  <section class="page" data-module="environment">
    <header class="page-head">
      <div>
        <h2>环境监控管理</h2>
        <p class="page-desc">维护环境记录，围绕记录编号、监控区域、温度值、湿度值做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleCreate">登记环境记录</button>
        <button class="btn" type="button" @click="exportRows">导出环境监控清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p v-if="missingAreas.length" class="notice-bar">
      今日（{{ today }}）以下监控区域暂无采集数据，已按缺测口径提示，请安排补采：{{ missingAreas.join('、') }}
    </p>

    <section v-if="showCreate" class="form-panel">
      <header class="panel-head">
        <span class="panel-title">登记环境记录</span>
        <button class="btn ghost" type="button" @click="toggleCreate">收起</button>
      </header>
      <form class="form-grid" @submit.prevent="submitCreate">
        <label v-for="field in createFields" :key="field.name" class="filter-item">
          <span>{{ field.name }}<em v-if="field.required" class="required-mark">*</em></span>
          <input
            v-model="draft[field.name]"
            :type="field.name === '采集时间' ? 'datetime-local' : 'text'"
            :placeholder="`${field.required ? '必填' : '选填'}，如 ${field.hint}`"
          />
        </label>
        <button class="btn primary" type="submit" :disabled="submitting">{{ submitting ? '提交中…' : '提交登记' }}</button>
      </form>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>记录编号</span>
        <input v-model="filters.keyword" placeholder="按记录编号检索" />
      </label>
      <label class="filter-item">
        <span>监控区域</span>
        <input v-model="filters.area" placeholder="按监控区域检索" />
      </label>
      <label class="filter-item">
        <span>监控状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="loading">
          <td :colspan="columns.length + 1" class="empty-state">环境监控数据加载中…</td>
        </tr>
        <template v-else>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">
              <span v-if="column === '监控状态'" class="tag" :class="statusClass(row[column])">{{ displayCell(row[column]) }}</span>
              <span v-else :class="{ muted: isBlank(row[column]) }">{{ displayCell(row[column]) }}</span>
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="openDetail(row)">详情</button>
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">{{ emptyHint }}</td>
          </tr>
        </template>
      </tbody>
    </table>

    <aside v-if="detail" class="form-panel">
      <header class="panel-head">
        <span class="panel-title">记录详情：{{ detail['记录编号'] }}</span>
        <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
      </header>
      <dl class="detail-grid">
        <div v-for="column in columns" :key="column">
          <dt>{{ column }}</dt>
          <dd>
            <span v-if="column === '监控状态'" class="tag" :class="statusClass(detail[column])">{{ displayCell(detail[column]) }}</span>
            <span v-else :class="{ muted: isBlank(detail[column]) }">{{ displayCell(detail[column]) }}</span>
          </dd>
        </div>
      </dl>
    </aside>

    <footer class="page-foot">
      <span>共 {{ total }} 条环境监控记录</span>
      <span v-if="noticeMessage" class="ok-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">
        {{ errorMessage }}
        <button v-if="retryHandler" class="link retry-btn" type="button" @click="retryHandler">重试</button>
      </span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatCard = { label: string; value: number }

const ENDPOINT = '/api/environment'
const columns = ["记录编号", "监控区域", "温度值", "湿度值", "压差值", "采集时间", "记录人员", "监控状态"]
const actions = ["确认采集", "登记缺测", "提交校准"]
const statuses = ["正常采集", "数据缺测", "超限报警", "已校准"]
const createFields = [
  { name: '记录编号', required: true, hint: 'ENVI-0004' },
  { name: '监控区域', required: true, hint: '培养室A' },
  { name: '温度值', required: true, hint: '22.5℃' },
  { name: '湿度值', required: false, hint: '55%' },
  { name: '压差值', required: false, hint: '8Pa' },
  { name: '采集时间', required: true, hint: '2026-09-26 09:00' },
  { name: '记录人员', required: false, hint: '张工' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatCard[]>([
  { label: '在监区域', value: 0 },
  { label: '超限次数', value: 0 },
  { label: '缺测记录数', value: 0 },
])
const missingAreas = ref<string[]>([])
const today = ref('')
const detail = ref<Row | null>(null)
const showCreate = ref(false)
const submitting = ref(false)
const loading = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')
const retryHandler = ref<(() => void) | null>(null)
const filters = ref({ keyword: '', area: '', status: '' })
const draft = ref<Record<string, string>>({})

const hasFilters = computed(() => Boolean(filters.value.keyword || filters.value.area || filters.value.status))
const emptyHint = computed(() => {
  if (!hasFilters.value) {
    return '暂无环境监控数据，可先登记环境记录'
  }
  if (filters.value.area) {
    return `监控区域「${filters.value.area}」暂无采集数据，若今日应采集请按缺测处理并安排补采`
  }
  return '没有符合筛选条件的环境记录，可重置条件后再试'
})

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || String(value).trim() === ''
}

function displayCell(value: unknown): string {
  // 压差值等选填字段缺失时不能留白，要给出明确提示
  return isBlank(value) ? '未采集' : String(value)
}

function statusClass(value: unknown): string {
  const status = String(value ?? '')
  if (status === '超限报警') return 'tag-danger'
  if (status === '数据缺测') return 'tag-warn'
  if (status === '已校准') return 'tag-done'
  return 'tag-ok'
}

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    if (payload && typeof payload.detail === 'string' && payload.detail) {
      return payload.detail
    }
  } catch {
    // 响应体不是 JSON 时使用兜底文案
  }
  return `${fallback}（接口返回 ${response.status}）`
}

function reportError(error: unknown, retry: (() => void) | null) {
  errorMessage.value = error instanceof Error ? error.message : '环境监控操作失败，请稍后重试'
  retryHandler.value = retry
}

async function reload() {
  loading.value = true
  errorMessage.value = ''
  retryHandler.value = null
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters.value)) {
    if (value) {
      query.set(key, value)
    }
  }
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/stats`),
    ])
    if (!listResponse.ok) {
      throw new Error(await readError(listResponse, '环境记录列表读取失败'))
    }
    if (!statsResponse.ok) {
      throw new Error(await readError(statsResponse, '环境监控统计读取失败'))
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const statPayload = await statsResponse.json()
    stats.value = [
      { label: '在监区域', value: statPayload.areas ?? 0 },
      { label: '超限次数', value: statPayload.over_limit ?? 0 },
      { label: '缺测记录数', value: statPayload.missing ?? 0 },
    ]
    missingAreas.value = statPayload.missing_areas ?? []
    today.value = statPayload.today ?? ''
  } catch (error) {
    reportError(error, () => void reload())
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.value = { keyword: '', area: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function toggleCreate() {
  showCreate.value = !showCreate.value
  if (showCreate.value) {
    draft.value = Object.fromEntries(createFields.map((field) => [field.name, '']))
  }
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  retryHandler.value = null
  const missing = createFields
    .filter((field) => field.required && !String(draft.value[field.name] ?? '').trim())
    .map((field) => field.name)
  if (missing.length) {
    errorMessage.value = `缺少必填字段：${missing.join('、')}`
    retryHandler.value = () => void submitCreate()
    return
  }
  submitting.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...draft.value } }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '环境记录登记失败'))
    }
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '环境记录登记失败')
    }
    noticeMessage.value = payload.message || '环境记录已登记'
    draft.value = Object.fromEntries(createFields.map((field) => [field.name, '']))
    showCreate.value = false
    await reload()
  } catch (error) {
    // 超时重试也安全：后端按记录编号幂等处理，不会重复写入或覆盖缺测标记
    reportError(error, () => void submitCreate())
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  retryHandler.value = null
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, `环境记录「${action}」未生效`))
    }
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || `环境记录「${action}」未生效`)
    }
    noticeMessage.value = payload.message || `环境记录已${action}`
    if (detail.value && payload.entry && detail.value.id === row.id) {
      // 详情面板打开着同一条记录时同步刷新，保证列表、详情、统计状态一致
      detail.value = payload.entry
    }
    await reload()
  } catch (error) {
    reportError(error, () => void runAction(action, row))
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  retryHandler.value = null
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error(await readError(response, '环境记录详情读取失败'))
    }
    detail.value = await response.json()
  } catch (error) {
    reportError(error, () => void openDetail(row))
  }
}

function closeDetail() {
  detail.value = null
}

onMounted(reload)
</script>
