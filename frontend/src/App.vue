<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api, type Domain, type Job, type JobEvent, type KnowledgeDocument } from './api'
import UiIcon from './components/UiIcon.vue'

const jobs = ref<Job[]>([])
const domains = ref<Domain[]>([])
const selected = ref<Job | null>(null)
const documents = ref<KnowledgeDocument[]>([])
const showCreate = ref(false)
const showSettings = ref(false)
const showCategories = ref(false)
const pendingDelete = ref<Job | null>(null)
const deleting = ref(false)
const newCategoryName = ref('')
const editingCategoryId = ref<string | null>(null)
const editingCategoryName = ref('')
const searchTerm = ref('')
const statusFilter = ref<'all' | 'active' | 'review' | 'completed' | 'other'>('all')
const busy = ref(false)
const notice = ref('')
const error = ref('')
const inputMode = ref<'path' | 'upload'>('path')
const uploads = ref<File[]>([])
const form = reactive({ name: '', source_path: '', mode: 'export', fixed_domain: '' })
const dify = reactive({
  dify_base_url: '', dify_api_key: '', dify_api_key_configured: false,
  embedding_provider: '', embedding_model: '', dataset_prefix: 'pdf2dify-',
  dataset_ids: {} as Record<string, string>,
})
let timer: number | undefined
let stream: EventSource | null = null
let streamJobId: string | null = null
let selectionVersion = 0
let detailVersion = 0
let stopped = false

const isActive = (job: Job) => ['preparing', 'queued', 'running'].includes(job.status)
const canDelete = (job: Job) => !['preparing', 'running'].includes(job.status)
const activeCount = computed(() => jobs.value.filter(isActive).length)
const reviewCount = computed(() => jobs.value.filter(j => j.status === 'needs_review').length)
const completedCount = computed(() => jobs.value.filter(j => j.status === 'completed').length)
const otherCount = computed(() => jobs.value.length - activeCount.value - reviewCount.value - completedCount.value)
const filteredJobs = computed(() => jobs.value.filter(job => {
  const matchesStatus = statusFilter.value === 'all'
    || (statusFilter.value === 'active' && isActive(job))
    || (statusFilter.value === 'review' && job.status === 'needs_review')
    || (statusFilter.value === 'completed' && job.status === 'completed')
    || (statusFilter.value === 'other' && !isActive(job) && !['needs_review', 'completed'].includes(job.status))
  return matchesStatus && job.name.toLocaleLowerCase().includes(searchTerm.value.trim().toLocaleLowerCase())
}))

const labels: Record<string, string> = {
  preparing: '接收文件', queued: '排队中', running: '处理中', needs_review: '待分类', paused: '已暂停',
  completed: '已完成', failed: '失败', cancelled: '已取消',
}

function flash(message: string, isError = false) {
  if (isError) error.value = message
  else notice.value = message
  window.setTimeout(() => { notice.value = ''; error.value = '' }, 4000)
}

function closeStream() {
  stream?.close()
  stream = null
  streamJobId = null
}

function closeJob() {
  selectionVersion++
  closeStream()
  selected.value = null
  documents.value = []
}

function watchJob(job: Job) {
  if (!isActive(job)) { closeStream(); return }
  if (stream && streamJobId === job.id) return
  closeStream()
  const lastEvent = job.events?.at(-1)?.id || 0
  const source = new EventSource(`/api/jobs/${job.id}/events?after=${lastEvent}`)
  stream = source
  streamJobId = job.id
  source.addEventListener('log', (event) => {
    const current = selected.value
    if (!current || current.id !== job.id) return
    const entry = JSON.parse((event as MessageEvent).data) as JobEvent
    if (current.events?.some(item => item.id === entry.id)) return
    selected.value = { ...current, events: [...(current.events || []), entry].slice(-200) }
  })
  source.addEventListener('status', (event) => {
    const current = selected.value
    if (!current || current.id !== job.id) return
    const update = JSON.parse((event as MessageEvent).data) as Job
    const changed = update.stage !== current.stage || update.status !== current.status
    selected.value = { ...current, ...update }
    jobs.value = jobs.value.map(item => item.id === update.id ? update : item)
    if (changed) void loadSelected(update.id, selectionVersion).catch(e => flash((e as Error).message, true))
    if (!isActive(update)) closeStream()
  })
}

async function loadSelected(jobId: string, version: number) {
  const requestVersion = ++detailVersion
  const [job, output] = await Promise.all([api.job(jobId), api.documents(jobId)])
  if (version !== selectionVersion || requestVersion !== detailVersion) return
  const liveEvents = selected.value?.id === jobId ? selected.value.events || [] : []
  const events = [...(job.events || []), ...liveEvents]
    .filter((item, index, all) => all.findIndex(other => other.id === item.id) === index)
    .sort((left, right) => left.id - right.id).slice(-200)
  selected.value = { ...job, events }
  documents.value = output
  watchJob(selected.value)
}

function scheduleRefresh() {
  if (stopped) return
  if (timer) window.clearTimeout(timer)
  timer = window.setTimeout(() => { void refresh() }, jobs.value.some(isActive) ? 5000 : 15000)
}

async function refresh() {
  try {
    jobs.value = await api.jobs()
    const current = selected.value
    if (stream?.readyState === EventSource.CLOSED) closeStream()
    if (current && (!stream || stream.readyState !== EventSource.OPEN)) {
      const latest = jobs.value.find(job => job.id === current.id)
      if (latest && latest.updated_at !== current.updated_at) {
        await loadSelected(latest.id, selectionVersion)
      } else if (isActive(current) && !stream) {
        watchJob(current)
      }
    }
  }
  catch (e) { flash((e as Error).message, true) }
  finally { scheduleRefresh() }
}

async function openJob(job: Job) {
  const version = ++selectionVersion
  closeStream()
  try { await loadSelected(job.id, version) }
  catch (e) { flash((e as Error).message, true) }
}

async function createJob() {
  busy.value = true
  try {
    let job: Job
    if (inputMode.value === 'path') {
      job = await api.createPath({ ...form, fixed_domain: form.fixed_domain || null })
    } else {
      const body = new FormData()
      body.append('name', form.name)
      body.append('mode', form.mode)
      if (form.fixed_domain) body.append('fixed_domain', form.fixed_domain)
      uploads.value.forEach(file => body.append('files', file, file.webkitRelativePath || file.name))
      job = await api.createUpload(body)
    }
    showCreate.value = false
    form.name = ''; form.source_path = ''; form.fixed_domain = ''; uploads.value = []
    flash('任务已创建，Worker 将自动开始处理')
    await refresh(); await openJob(job)
  } catch (e) { flash((e as Error).message, true) }
  finally { busy.value = false }
}

async function jobAction(action: string) {
  if (!selected.value) return
  try {
    const job = await api.action(selected.value.id, action)
    flash(action === 'resume' ? '任务已继续' : action === 'pause'
      ? (job.status === 'paused' ? '任务已暂停' : '已请求暂停')
      : (job.status === 'cancelled' ? '任务已取消' : '已请求取消'))
    await loadSelected(job.id, selectionVersion)
    await refresh()
  } catch (e) { flash((e as Error).message, true) }
}

async function deleteJob() {
  const job = pendingDelete.value
  if (!job || deleting.value) return
  deleting.value = true
  try {
    const result = await api.deleteJob(job.id)
    if (selected.value?.id === job.id) closeJob()
    pendingDelete.value = null
    jobs.value = jobs.value.filter(item => item.id !== job.id)
    flash(result.cleanup_failed?.length
      ? '任务记录已删除，但部分本地文件未能清理，请检查 data 目录'
      : '任务已删除')
    await refresh()
  } catch (e) { flash((e as Error).message, true) }
  finally { deleting.value = false }
}

async function setDomain(fileId: string, domain: string) {
  if (!selected.value) return
  try {
    await api.classify(selected.value.id, fileId, domain)
    await loadSelected(selected.value.id, selectionVersion)
  } catch (e) { flash((e as Error).message, true) }
}

async function openDifySettings() {
  const current = await api.settings()
  Object.assign(dify, current, { dify_api_key: '' })
  showSettings.value = true
}

async function saveDify(test = false) {
  busy.value = true
  try {
    await api.saveSettings(dify)
    if (test) {
      const result = await api.testDify()
      flash(result.message)
    } else flash('Dify 配置已保存')
    showSettings.value = false
  } catch (e) { flash((e as Error).message, true) }
  finally { busy.value = false }
}

function pickFiles(event: Event) {
  uploads.value = Array.from((event.target as HTMLInputElement).files || [])
    .filter(file => file.name.toLowerCase().endsWith('.pdf'))
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function domainName(id: string | null) { return domains.value.find(d => d.id === id)?.name || '未分类' }

async function createCategory() {
  if (!newCategoryName.value.trim()) return
  busy.value = true
  try {
    const category = await api.createDomain(newCategoryName.value)
    domains.value = await api.domains()
    newCategoryName.value = ''
    flash(`已创建分类：${category.name}`)
  } catch (e) { flash((e as Error).message, true) }
  finally { busy.value = false }
}

function beginRenameCategory(category: Domain) {
  editingCategoryId.value = category.id
  editingCategoryName.value = category.name
}

async function renameCategory(category: Domain) {
  const name = editingCategoryName.value.trim()
  if (!name || name === category.name) { editingCategoryId.value = null; return }
  busy.value = true
  try {
    await api.renameDomain(category.id, name)
    domains.value = await api.domains()
    editingCategoryId.value = null
    flash('分类名称已更新')
  } catch (e) { flash((e as Error).message, true) }
  finally { busy.value = false }
}

onMounted(async () => {
  try { domains.value = await api.domains() }
  catch (e) { flash((e as Error).message, true) }
  await refresh()
})
onUnmounted(() => {
  stopped = true
  if (timer) window.clearTimeout(timer)
  closeJob()
})
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="mark"><UiIcon name="file" :size="21" /></div>
        <div><strong>pdf2dify</strong><span>文档处理工作台</span></div>
      </div>
      <div class="top-actions">
        <button class="ghost" @click="showCategories = true"><UiIcon name="folder" />分类管理</button>
        <button class="ghost" @click="openDifySettings"><UiIcon name="link" />Dify 连接</button>
        <button class="primary" @click="showCreate = true"><UiIcon name="add" />新建任务</button>
      </div>
    </header>

    <main>
      <section class="page-intro">
        <div><p class="eyebrow">工作台 / 任务</p><h1>处理任务</h1><p>管理 PDF 解析、交付文件与 Dify 同步</p></div>
      </section>

      <section class="summary-grid" aria-label="任务概览">
        <button class="metric" :class="{ active: statusFilter === 'all' }" @click="statusFilter = 'all'"><span class="metric-icon"><UiIcon name="grid" /></span><span class="metric-content"><span>全部任务</span><b>{{ jobs.length }}</b></span><UiIcon name="chevron" :size="16" /></button>
        <button class="metric" :class="{ active: statusFilter === 'active' }" @click="statusFilter = 'active'"><span class="metric-icon blue"><UiIcon name="clock" /></span><span class="metric-content"><span>进行中</span><b>{{ activeCount }}</b></span><UiIcon name="chevron" :size="16" /></button>
        <button class="metric" :class="{ active: statusFilter === 'review' }" @click="statusFilter = 'review'"><span class="metric-icon amber"><UiIcon name="folder" /></span><span class="metric-content"><span>待分类</span><b>{{ reviewCount }}</b></span><UiIcon name="chevron" :size="16" /></button>
        <button class="metric" :class="{ active: statusFilter === 'completed' }" @click="statusFilter = 'completed'"><span class="metric-icon green"><UiIcon name="check" /></span><span class="metric-content"><span>已完成</span><b>{{ completedCount }}</b></span><UiIcon name="chevron" :size="16" /></button>
      </section>

      <section class="workspace">
        <div class="section-heading">
          <div><h2>任务列表</h2><p>查看进度，处理异常并获取交付文件</p></div>
          <button class="ghost refresh-button" @click="refresh"><UiIcon name="refresh" :size="16" />刷新</button>
        </div>

        <div class="list-tools">
          <div class="filter-tabs" aria-label="筛选任务">
            <button :class="{ active: statusFilter === 'all' }" @click="statusFilter = 'all'">全部 <span>{{ jobs.length }}</span></button>
            <button :class="{ active: statusFilter === 'active' }" @click="statusFilter = 'active'">进行中 <span>{{ activeCount }}</span></button>
            <button :class="{ active: statusFilter === 'review' }" @click="statusFilter = 'review'">待分类 <span>{{ reviewCount }}</span></button>
            <button :class="{ active: statusFilter === 'completed' }" @click="statusFilter = 'completed'">已完成 <span>{{ completedCount }}</span></button>
            <button v-if="otherCount" :class="{ active: statusFilter === 'other' }" @click="statusFilter = 'other'">其他 <span>{{ otherCount }}</span></button>
          </div>
          <label class="search-box"><UiIcon name="search" :size="17" /><input v-model="searchTerm" aria-label="搜索任务名称" placeholder="搜索任务名称" /></label>
        </div>

        <div v-if="!jobs.length" class="empty">
          <div class="empty-icon"><UiIcon name="file" :size="28" /></div>
          <h3>还没有处理任务</h3>
          <p>新建任务后，处理进度、分类问题和 Dify 索引状态都会显示在这里。</p>
          <button class="primary" @click="showCreate = true"><UiIcon name="add" />创建第一个任务</button>
        </div>

        <div v-else-if="!filteredJobs.length" class="empty filtered-empty">
          <div class="empty-icon"><UiIcon name="search" :size="26" /></div>
          <h3>没有找到任务</h3><p>试试其他状态，或修改搜索关键词。</p>
          <button class="ghost" @click="statusFilter = 'all'; searchTerm = ''">清除筛选</button>
        </div>

        <div v-else class="job-list">
          <div v-for="job in filteredJobs" :key="job.id" class="job-row">
            <div class="file-badge"><UiIcon name="file" :size="23" /><span>PDF</span></div>
            <div class="job-main">
              <div class="job-title"><strong>{{ job.name }}</strong><span :class="['status', job.status]">{{ labels[job.status] }}</span></div>
              <p>{{ job.message || job.stage }}</p>
              <div class="job-stats"><span>{{ job.total_files || '—' }} 个文件</span><span>{{ job.total_pages || '—' }} 页</span><span>更新于 {{ formatTime(job.updated_at) }}</span></div>
              <div class="progress"><i :style="{ width: `${job.progress}%` }"></i></div>
            </div>
            <div class="job-side"><b>{{ Math.round(job.progress) }}%</b><div class="job-actions"><button class="outline-action" :aria-label="`查看任务：${job.name}`" @click="openJob(job)"><UiIcon name="eye" :size="16" />查看详情</button><button v-if="canDelete(job)" class="icon-action destructive" :aria-label="`删除任务：${job.name}`" title="删除任务" @click="pendingDelete = job"><UiIcon name="trash" :size="17" /></button></div></div>
          </div>
        </div>
      </section>
    </main>

    <aside v-if="selected" class="drawer">
      <button class="close" aria-label="关闭任务详情" @click="closeJob"><UiIcon name="close" /></button>
      <p class="eyebrow">任务详情</p>
      <h2>{{ selected.name }}</h2>
      <div class="detail-status"><span :class="['status', selected.status]">{{ labels[selected.status] }}</span><b>{{ Math.round(selected.progress) }}%</b></div>
      <div class="progress large"><i :style="{ width: `${selected.progress}%` }"></i></div>
      <p class="detail-message">{{ selected.message }}</p>
      <div class="facts">
        <div><span>当前阶段</span><b>{{ selected.stage }}</b></div>
        <div><span>PDF</span><b>{{ selected.total_files }}</b></div>
        <div><span>总页数</span><b>{{ selected.total_pages }}</b></div>
        <div><span>模式</span><b>{{ selected.mode === 'sync' ? '处理并同步' : '仅生成文件' }}</b></div>
      </div>

      <div v-if="selected.status === 'needs_review'" class="review-box">
        <h3>需要选择业务分类</h3>
        <p>未分类文件不会继续入库，其他处理结果已保留。</p>
        <button class="ghost small-button" @click="showCategories = true"><UiIcon name="add" :size="15" />新增分类</button>
        <div v-for="file in selected.files?.filter(f => !f.domain)" :key="file.id" class="file-review">
          <span :title="file.relative_path">{{ file.name }}</span>
          <select @change="setDomain(file.id, ($event.target as HTMLSelectElement).value)">
            <option value="">选择分类</option>
            <option v-for="domain in domains" :key="domain.id" :value="domain.id">{{ domain.name }}</option>
          </select>
        </div>
        <button class="primary wide" @click="jobAction('resume')"><UiIcon name="play" :size="16" />保存分类并继续</button>
      </div>

      <div v-if="selected.error" class="error-card"><b>失败原因</b><p>{{ selected.error }}</p></div>

      <div class="action-row">
        <button v-if="selected.status === 'running' || selected.status === 'queued'" class="ghost" @click="jobAction('pause')"><UiIcon name="pause" :size="16" />暂停处理</button>
        <button v-if="selected.status === 'paused' || selected.status === 'failed'" class="primary" @click="jobAction('resume')"><UiIcon name="play" :size="16" />继续 / 重试</button>
        <button v-if="!['completed','failed','cancelled'].includes(selected.status)" class="danger" @click="jobAction('cancel')"><UiIcon name="close" :size="16" />取消任务</button>
        <button v-if="canDelete(selected)" class="ghost delete-action" @click="pendingDelete = selected"><UiIcon name="trash" :size="16" />删除任务</button>
      </div>

      <div v-if="selected.status === 'completed'" class="artifacts">
        <div class="block-heading"><h3>交付产物</h3><span>处理完成后可下载</span></div>
        <a class="artifact-main" :href="`/api/jobs/${selected.id}/artifacts/dify-ready.zip`"><span class="artifact-icon"><UiIcon name="database" :size="22" /></span><span><b>Dify 入库包</b><small>包含可导入的知识文档与资源</small></span><UiIcon name="download" :size="18" /></a>
        <div class="artifact-grid">
          <a :href="`/api/jobs/${selected.id}/artifacts/manifest.xlsx`"><UiIcon name="file" /><span>Excel 入库清单</span><UiIcon name="download" :size="16" /></a>
          <a target="_blank" rel="noopener" :href="`/api/jobs/${selected.id}/artifacts/quality-report.html`"><UiIcon name="eye" /><span>HTML 质量报告</span><UiIcon name="arrow" :size="16" /></a>
          <a :href="`/api/jobs/${selected.id}/artifacts/manifest.json`"><UiIcon name="file" /><span>导出清单 JSON</span><UiIcon name="download" :size="16" /></a>
          <a :href="`/api/jobs/${selected.id}/artifacts/verification.json`"><UiIcon name="file" /><span>质量数据 JSON</span><UiIcon name="download" :size="16" /></a>
        </div>
      </div>

      <div class="files" v-if="selected.files?.length">
        <div class="block-heading"><h3>来源文件</h3><span>{{ selected.files.length }} 个</span></div>
        <div v-for="file in selected.files" :key="file.id" class="mini-file">
          <span class="mini-file-icon"><UiIcon name="file" :size="18" /></span><span class="mini-file-info"><b :title="file.name">{{ file.name }}</b><small>{{ file.pages }} 页 · {{ domainName(file.domain) }}</small></span><a class="outline-action" target="_blank" rel="noopener" :href="`/api/jobs/${selected.id}/files/${file.id}/preview`"><UiIcon name="eye" :size="15" />预览</a>
        </div>
      </div>

      <div v-if="documents.length" class="files">
        <div class="block-heading"><h3>生成的知识文档</h3><span>{{ documents.length }} 个</span></div>
        <div v-for="document in documents.slice(0, 120)" :key="document.key" class="mini-file">
          <span class="mini-file-icon"><UiIcon name="file" :size="18" /></span><span class="mini-file-info"><b :title="document.title || document.source_name">{{ document.title || document.source_name }}</b><small>第 {{ document.pages.join('、') }} 页 · {{ document.image_count }} 图 · {{ domainName(document.domain) === '未分类' ? '资料导航' : domainName(document.domain) }}</small></span><a class="outline-action" :href="`/api/jobs/${selected.id}/documents/${document.key}`"><UiIcon name="download" :size="15" />下载</a>
        </div>
        <p v-if="documents.length > 120" class="hint">仅展示前 120 条，完整清单见 Excel 文件。</p>
      </div>

      <div class="timeline">
        <h3>运行日志</h3>
        <div v-for="event in selected.events?.slice().reverse().slice(0, 80)" :key="event.id" :class="['event', event.level]">
          <time>{{ formatTime(event.created_at) }}</time><p>{{ event.message }}</p>
        </div>
      </div>
    </aside>
    <div v-if="selected" class="scrim" @click="closeJob"></div>

    <div v-if="showCreate" class="modal-wrap">
      <div class="modal">
        <button class="close" aria-label="关闭创建任务" @click="showCreate = false"><UiIcon name="close" /></button>
        <p class="eyebrow">创建任务</p><h2>新建处理任务</h2>
        <label>任务名称<input v-model="form.name" placeholder="例如：9 月新增财务手册" /></label>
        <div class="tabs"><button :class="{active: inputMode === 'path'}" @click="inputMode = 'path'"><UiIcon name="folder" :size="16" />指定服务器路径</button><button :class="{active: inputMode === 'upload'}" @click="inputMode = 'upload'"><UiIcon name="upload" :size="16" />上传 PDF</button></div>
        <label v-if="inputMode === 'path'">PDF 文件或目录<input v-model="form.source_path" placeholder="例如：/home/user/pdfs 或 C:\资料\手册.pdf" /></label>
        <div v-else class="upload-choices">
          <label class="dropzone"><UiIcon name="file" :size="25" />选择 PDF 文件
            <input type="file" accept="application/pdf,.pdf" multiple @change="pickFiles" />
            <span>多选文件</span>
          </label>
          <label class="dropzone"><UiIcon name="folder" :size="25" />选择整个文件夹
            <input type="file" webkitdirectory multiple @change="pickFiles" />
            <span>保留文件夹内的分类路径</span>
          </label>
          <p class="hint">{{ uploads.length ? `已选择 ${uploads.length} 个 PDF` : '支持单个、多选和文件夹上传' }}</p>
        </div>
        <div class="form-grid">
          <label>业务分类<select v-model="form.fixed_domain"><option value="">自动识别</option><option v-for="domain in domains" :key="domain.id" :value="domain.id">{{ domain.name }}</option></select><button class="ghost small-button inline-button" type="button" @click="showCategories = true"><UiIcon name="add" :size="15" />新增分类</button></label>
          <label>完成动作<select v-model="form.mode"><option value="export">只生成入库包</option><option value="sync">生成并同步 Dify</option></select></label>
        </div>
        <p class="hint">自动识别不了的文件会暂停在“待分类”，已完成的解析不会丢失。</p>
        <button class="primary wide" :disabled="busy || !form.name || (inputMode === 'path' ? !form.source_path : !uploads.length)" @click="createJob"><UiIcon name="play" :size="17" />{{ busy ? '正在创建…' : '开始处理' }}</button>
      </div>
    </div>

    <div v-if="showSettings" class="modal-wrap">
      <div class="modal compact">
        <button class="close" aria-label="关闭连接设置" @click="showSettings = false"><UiIcon name="close" /></button>
        <p class="eyebrow">连接设置</p><h2>Dify 连接</h2>
        <label>API Base URL<input v-model="dify.dify_base_url" placeholder="http://192.168.24.133:8811/v1" /></label>
        <label>知识库 API Key<input v-model="dify.dify_api_key" type="password" :placeholder="dify.dify_api_key_configured ? '已配置；留空保持不变' : 'dataset-...'" /></label>
        <label>Embedding Provider<input v-model="dify.embedding_provider" /></label>
        <label>Embedding Model<input v-model="dify.embedding_model" /></label>
        <label>新建知识库名称前缀<input v-model="dify.dataset_prefix" placeholder="pdf2dify-" /></label>
        <details class="dataset-mapping">
          <summary>映射已有知识库 ID（可选）</summary>
          <p class="hint">填写 ID 的分类会写入该库；留空的分类按名称前缀自动创建或复用。</p>
          <label v-for="domain in [...domains, { id: 'process_navigation', name: '资料导航', custom: false }]" :key="domain.id">
            {{ domain.name }}<input v-model="dify.dataset_ids[domain.id]" placeholder="留空则自动创建" />
          </label>
        </details>
        <p class="hint">密钥只保存在本机后端的 data 目录，不会写入浏览器构建文件。</p>
        <div class="action-row"><button class="ghost" :disabled="busy" @click="saveDify(false)"><UiIcon name="check" :size="16" />保存</button><button class="primary" :disabled="busy" @click="saveDify(true)"><UiIcon name="link" :size="16" />保存并测试连接</button></div>
      </div>
    </div>

    <div v-if="showCategories" class="modal-wrap">
      <div class="modal compact">
        <button class="close" aria-label="关闭分类管理" @click="showCategories = false"><UiIcon name="close" /></button>
        <p class="eyebrow">分类设置</p><h2>分类管理</h2>
        <p class="hint">新增分类会出现在任务、人工归类及 Dify 知识库映射中。预置分类保留；自定义分类可以改名。</p>
        <div class="category-create">
          <input v-model="newCategoryName" maxlength="50" placeholder="例如：供应链合规" @keyup.enter="createCategory" />
          <button class="primary" :disabled="busy || !newCategoryName.trim()" @click="createCategory"><UiIcon name="add" :size="16" />新增分类</button>
        </div>
        <div class="category-list">
          <div v-for="category in domains" :key="category.id" class="category-row">
            <span class="category-symbol"><UiIcon name="folder" :size="17" /></span>
            <template v-if="editingCategoryId === category.id">
              <input v-model="editingCategoryName" maxlength="50" aria-label="分类名称" @keyup.enter="renameCategory(category)" @keyup.esc="editingCategoryId = null" />
              <button class="primary small-button" :disabled="busy || !editingCategoryName.trim()" @click="renameCategory(category)">保存</button>
              <button class="ghost small-button" @click="editingCategoryId = null">取消</button>
            </template>
            <template v-else>
              <span class="category-name">{{ category.name }}</span><small>{{ category.custom ? '自定义' : '预置' }}</small>
              <button v-if="category.custom" class="outline-action" @click="beginRenameCategory(category)"><UiIcon name="edit" :size="15" />改名</button>
            </template>
          </div>
        </div>
      </div>
    </div>

    <div v-if="pendingDelete" class="modal-wrap confirm-wrap">
      <div class="modal confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <h2 id="delete-title">删除任务？</h2>
        <p>“{{ pendingDelete.name }}”的任务记录、上传副本和生成文件将被删除。原始来源文件会保留。<template v-if="pendingDelete.mode === 'sync'">已同步到 Dify 的内容不会删除。</template></p>
        <div class="confirm-actions">
          <button class="ghost" :disabled="deleting" @click="pendingDelete = null">保留任务</button>
          <button class="danger-solid" :disabled="deleting" @click="deleteJob"><UiIcon name="trash" :size="16" />{{ deleting ? '正在删除…' : '确认删除' }}</button>
        </div>
      </div>
    </div>

    <div v-if="notice" class="toast success">{{ notice }}</div>
    <div v-if="error" class="toast fail">{{ error }}</div>
  </div>
</template>
