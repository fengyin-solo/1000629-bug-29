<template>
  <section class="page" data-module="environment">
    <header class="page-head">
      <div>
        <h2>环境监控管理</h2>
        <p class="page-desc">围绕监控区域、温度值（18~26℃）、湿度值（30~70%RH）做登记、超限判定与缺测补录，列表、详情与统计口径一致。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记环境记录</button>
        <button class="btn" type="button" @click="exportRows">导出环境监控清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="cardClass(item.status)">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ statsLoading ? '…' : statsError ? '—' : item.value }}</strong>
      </article>
    </div>

    <div v-if="statsError" class="inline-error">
      <span>统计卡片读取失败：{{ statsError }}</span>
      <button class="link" type="button" @click="loadStats">重试</button>
    </div>

    <table v-if="!statsLoading && !statsError" class="data-table area-table">
      <thead>
        <tr><th>监控区域</th><th>监控状态</th><th>温度状态</th><th>湿度状态</th><th>最近采集时间</th><th>说明</th></tr>
      </thead>
      <tbody>
        <tr v-for="area in areaSummary" :key="area.监控区域">
          <td>{{ area.监控区域 }}</td>
          <td><span class="tag" :class="statusClass(area.status)">{{ area.status }}</span></td>
          <td><span class="tag" :class="measureClass(area.温度状态)">{{ area.温度状态 }}</span></td>
          <td><span class="tag" :class="measureClass(area.湿度状态)">{{ area.湿度状态 }}</span></td>
          <td>{{ area.采集时间 || '—' }}</td>
          <td>{{ area.说明 || (area.missing_today ? '当日缺测' : '—') }}</td>
        </tr>
      </tbody>
    </table>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>记录编号</span>
        <input v-model="keyword" placeholder="按记录编号检索" />
      </label>
      <label class="filter-item">
        <span>监控状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="listError" class="error-banner">
      <span>{{ listError }}</span>
      <button class="btn primary" type="button" @click="loadList">重试</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>说明</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="listLoading">
          <td :colspan="columns.length + 2" class="loading-state">环境监控数据加载中，若服务长时间未响应会提示超时…</td>
        </tr>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-missing': row.missing_today }">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '温度值'">
              <span class="measure" :class="measureClass(row.温度状态)">{{ formatMeasure(row.温度值, '℃') }}</span>
            </template>
            <template v-else-if="column === '湿度值'">
              <span class="measure" :class="measureClass(row.湿度状态)">{{ formatMeasure(row.湿度值, '%RH') }}</span>
            </template>
            <template v-else-if="column === '压差值'">
              <span class="measure" :class="measureClass(row.压差状态)">{{ formatPressure(row.压差值) }}</span>
            </template>
            <template v-else-if="column === '监控状态'">
              <span class="tag" :class="statusClass(row.status)">{{ row.status }}</span>
            </template>
            <template v-else>{{ displayText(row[column], column) }}</template>
          </td>
          <td class="note-cell">{{ row.说明 || '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <template v-if="!row.missing_today">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                :disabled="busyIds.has(String(row.id))"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="hint-text">缺测行，请补录后再操作</span>
          </td>
        </tr>
        <tr v-if="!listLoading && !listError && !rows.length">
          <td :colspan="columns.length + 2" class="empty-state">
            没有符合条件的环境监控记录；监控区域当天无采集数据时会自动标记为「数据缺测」
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条环境监控记录（含当日缺测补录提示）</span>
      <span v-if="actionError" class="error-text">
        {{ actionError }}
        <button v-if="lastFailed" class="link" type="button" @click="retryLastAction">重试该动作</button>
      </span>
    </footer>

    <!-- 详情弹窗：字段级状态与列表、统计同源 -->
    <div v-if="detailVisible" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card">
        <header class="modal-head">
          <h3>环境记录详情</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>
        <div v-if="detailLoading" class="modal-state">明细加载中…</div>
        <div v-else-if="detailError" class="modal-state error-text">
          <p>{{ detailError }}</p>
          <button class="btn primary" type="button" @click="reloadDetail">重试</button>
        </div>
        <dl v-else-if="detail" class="detail-grid">
          <template v-for="item in detailItems" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd v-html="item.html"></dd>
          </template>
        </dl>
      </div>
    </div>

    <!-- 登记弹窗 -->
    <div v-if="createVisible" class="modal-mask" @click.self="closeCreate">
      <div class="modal-card">
        <header class="modal-head">
          <h3>登记环境记录</h3>
          <button class="link" type="button" @click="closeCreate">关闭</button>
        </header>
        <form class="create-form" @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field.key" class="create-item">
            <span>{{ field.label }}<em v-if="field.required">*</em></span>
            <input
              v-model="form[field.key]"
              :type="field.type"
              :placeholder="field.placeholder"
              :disabled="creating"
            />
          </label>
          <p v-if="createError" class="error-text">{{ createError }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" :disabled="creating" @click="closeCreate">取消</button>
            <button class="btn primary" type="submit" :disabled="creating">{{ creating ? '提交中…' : '提交登记' }}</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { RequestError, request } from '@/api/client'

type MeasureState = '正常' | '超限' | '缺测' | '缺失'
type MonitorStatus = '正常采集' | '数据缺测' | '超限报警' | '已校准'

interface EnvRow {
  id: number | string
  记录编号: string | null
  监控区域: string | null
  温度值: number | null
  湿度值: number | null
  压差值: number | null
  采集时间: string | null
  记录人员: string | null
  status: MonitorStatus
  abnormal: boolean
  pending: boolean
  温度状态?: MeasureState
  湿度状态?: MeasureState
  压差状态?: MeasureState
  说明?: string
  missing_today?: boolean
  [key: string]: string | number | boolean | null | MeasureState | MonitorStatus | undefined
}

interface StatCard {
  label: string
  value: number
  status: MonitorStatus | '正常'
}

interface AreaSummary {
  监控区域: string
  status: MonitorStatus
  温度状态: MeasureState
  湿度状态: MeasureState
  采集时间: string | null
  说明: string
  missing_today: boolean
}

interface PagePayload {
  items: EnvRow[]
  total: number
}

interface StatsPayload {
  cards: StatCard[]
  areas: AreaSummary[]
}

const ENDPOINT = '/api/environment'
const columns = ["记录编号", "监控区域", "温度值", "湿度值", "压差值", "采集时间", "记录人员", "监控状态"]
const actions = ["确认采集", "登记缺测", "提交校准"]
const statuses: MonitorStatus[] = ["正常采集", "数据缺测", "超限报警", "已校准"]
const DEFAULT_STATS: StatCard[] = [
  { label: '在监区域', value: 0, status: '正常' },
  { label: '超限次数', value: 0, status: '正常' },
  { label: '缺测记录数', value: 0, status: '正常' },
]

const rows = ref<EnvRow[]>([])
const total = ref(0)
const listLoading = ref(false)
const listError = ref('')
const stats = ref<StatCard[]>(DEFAULT_STATS)
const areaSummary = ref<AreaSummary[]>([])
const statsLoading = ref(false)
const statsError = ref('')

const keyword = ref('')
const statusFilter = ref('')

const actionError = ref('')
const lastFailed = ref<{ action: string; row: EnvRow } | null>(null)
const busyIds = reactive(new Set<string>())

// -- 展示辅助 -------------------------------------------------------------

function statusClass(status: string): string {
  if (status === '超限报警') return 'tag-over'
  if (status === '数据缺测') return 'tag-missing'
  if (status === '已校准') return 'tag-calibrated'
  return 'tag-normal'
}

function measureClass(state?: string): string {
  if (state === '超限') return 'tag-over'
  if (state === '缺测' || state === '缺失') return 'tag-missing'
  return 'tag-normal'
}

function cardClass(status: string): string {
  return status === '超限报警' || status === '超限'
    ? 'card-over'
    : status === '数据缺测' || status === '缺测'
      ? 'card-missing'
      : ''
}

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || String(value).trim() === ''
}

function formatMeasure(value: number | null, unit: string): string {
  return isBlank(value) ? '缺测' : `${value}${unit}`
}

function formatPressure(value: number | null): string {
  return isBlank(value) ? '缺失·待补录' : `${value}Pa`
}

function displayText(value: unknown, column: string): string {
  if (value === null || value === undefined || String(value).trim() === '') {
    return column === '记录编号' ? '待补录' : '—'
  }
  return String(value)
}

// -- 列表与统计 -----------------------------------------------------------

async function loadList() {
  listLoading.value = true
  listError.value = ''
  try {
    const params = new URLSearchParams()
    if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
    if (statusFilter.value) params.set('status', statusFilter.value)
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    const payload = (await response.json()) as PagePayload
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    rows.value = []
    total.value = 0
    listError.value = error instanceof Error ? error.message : '环境记录列表读取失败，请稍后重试'
  } finally {
    listLoading.value = false
  }
}

async function loadStats() {
  statsLoading.value = true
  statsError.value = ''
  try {
    const response = await request(`${ENDPOINT}/stats`)
    const payload = (await response.json()) as StatsPayload
    stats.value = payload.cards?.length ? payload.cards : DEFAULT_STATS
    areaSummary.value = payload.areas ?? []
  } catch (error) {
    statsError.value = error instanceof Error ? error.message : '统计数据读取失败'
  } finally {
    statsLoading.value = false
  }
}

function reload() {
  void loadList()
  void loadStats()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void loadList()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

// -- 动作（防重复提交 + 失败重试） -----------------------------------------

async function runAction(action: string, row: EnvRow) {
  actionError.value = ''
  lastFailed.value = null
  const key = String(row.id)
  if (busyIds.has(key)) return // 同一条记录的动作串行，避免重复提交
  busyIds.add(key)
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as { ok: boolean; message: string }
    if (!payload.ok) throw new RequestError(payload.message || '环境监控动作未生效，请稍后重试')
    reload()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '环境监控操作失败，请稍后重试'
    lastFailed.value = { action, row }
  } finally {
    busyIds.delete(key)
  }
}

function retryLastAction() {
  if (!lastFailed.value) return
  void runAction(lastFailed.value.action, lastFailed.value.row)
}

// -- 详情弹窗 -------------------------------------------------------------

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref<EnvRow | null>(null)
const detailTarget = ref<EnvRow | null>(null)

function statusTag(status: string): string {
  return `<span class="tag ${statusClass(status)}">${status}</span>`
}

function measureTag(value: number | null, state: MeasureState | undefined, unit: string): string {
  const text = value === null || value === undefined ? '缺测' : `${value}${unit}`
  return `<span class="tag ${measureClass(state)}">${text}（${state ?? '—'}）</span>`
}

const detailItems = computed(() => {
  const row = detail.value
  if (!row) return []
  return [
    { label: '记录编号', html: displayText(row.记录编号, '记录编号') },
    { label: '监控区域', html: displayText(row.监控区域, '监控区域') },
    { label: '温度值', html: `${measureTag(row.温度值, row.温度状态, '℃')}` },
    { label: '湿度值', html: `${measureTag(row.湿度值, row.湿度状态, '%RH')}` },
    {
      label: '压差值',
      html: isBlank(row.压差值)
        ? '<span class="tag tag-missing">缺失·请及时补录</span>'
        : `<span class="tag ${measureClass(row.压差状态)}">${row.压差值}Pa（${row.压差状态 ?? '正常'}）</span>`,
    },
    { label: '采集时间', html: displayText(row.采集时间, '采集时间') },
    { label: '记录人员', html: displayText(row.记录人员, '记录人员') },
    { label: '监控状态', html: statusTag(row.status) },
    { label: '说明', html: row.说明 || (row.missing_today ? '当日无采集数据，按缺测处理' : '—') },
  ]
})

async function fetchDetail(row: EnvRow) {
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  try {
    const response = await request(`${ENDPOINT}/${String(row.id)}`)
    detail.value = (await response.json()) as EnvRow
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '明细读取失败，请稍后重试'
  } finally {
    detailLoading.value = false
  }
}

function openDetail(row: EnvRow) {
  detailVisible.value = true
  detailTarget.value = row
  if (row.missing_today) {
    // 当日缺测行由列表口径直接生成，不再请求
    detail.value = row
    detailError.value = ''
    detailLoading.value = false
  } else {
    void fetchDetail(row)
  }
}

function reloadDetail() {
  if (detailTarget.value) void fetchDetail(detailTarget.value)
}

function closeDetail() {
  detailVisible.value = false
  detail.value = null
  detailTarget.value = null
  detailError.value = ''
}

// -- 登记弹窗 -------------------------------------------------------------

const createVisible = ref(false)
const creating = ref(false)
const createError = ref('')

const createFields = [
  { key: '记录编号', label: '记录编号', type: 'text', placeholder: '如 ENVI-0006', required: true },
  { key: '监控区域', label: '监控区域', type: 'text', placeholder: '如 理化检测一区', required: true },
  { key: '温度值', label: '温度值（℃，18~26）', type: 'text', placeholder: '如 23.5', required: true },
  { key: '湿度值', label: '湿度值（%RH，30~70）', type: 'text', placeholder: '如 55', required: true },
  { key: '压差值', label: '压差值（Pa，可空）', type: 'text', placeholder: '留空将在列表提示缺失', required: false },
  { key: '采集时间', label: '采集时间', type: 'date', placeholder: '', required: true },
  { key: '记录人员', label: '记录人员', type: 'text', placeholder: '可空', required: false },
] as const

const today = new Date().toISOString().slice(0, 10)
const form = reactive<Record<string, string>>({ 采集时间: today })

function openCreate() {
  for (const field of createFields) form[field.key] = field.key === '采集时间' ? today : ''
  createVisible.value = true
  createError.value = ''
}

function closeCreate() {
  createVisible.value = false
  createError.value = ''
}

async function submitCreate() {
  createError.value = ''
  const values: Record<string, string> = {}
  for (const field of createFields) {
    const raw = (form[field.key] ?? '').trim()
    if (field.required && !raw) {
      createError.value = `缺少必填字段：${field.label.replace(/（.*?）/, '')}，请补全后再提交`
      return
    }
    values[field.key] = raw
  }
  creating.value = true
  try {
    await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    createVisible.value = false
    reload()
  } catch (error) {
    // 后端的可读说明（缺字段/数值非法/重复编号）直接展示，弹窗保留供修改后再次提交
    createError.value = error instanceof Error ? error.message : '环境记录登记失败，请稍后重试'
  } finally {
    creating.value = false
  }
}

onMounted(reload)
</script>
