export type JobStatus = 'preparing' | 'queued' | 'running' | 'needs_review' | 'paused' | 'completed' | 'failed' | 'cancelled'

export interface JobFile {
  id: string
  source_id: string
  name: string
  relative_path: string
  pages: number
  domain: string | null
  classification_status: string
}

export interface JobEvent {
  id: number
  level: string
  message: string
  created_at: string
}

export interface Job {
  id: string
  name: string
  source_type: string
  source_path: string
  mode: 'export' | 'sync'
  fixed_domain: string | null
  status: JobStatus
  stage: string
  progress: number
  message: string
  total_files: number
  total_pages: number
  processed_files: number
  processed_pages: number
  output_dir: string | null
  error: string | null
  created_at: string
  updated_at: string
  files?: JobFile[]
  events?: JobEvent[]
}

export interface Domain { id: string; name: string; custom: boolean }

export interface KnowledgeDocument {
  key: string
  domain: string
  source_name: string
  title: string
  pages: number[]
  image_count: number
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || `请求失败：${response.status}`)
  return body as T
}

export const api = {
  jobs: () => request<Job[]>('/api/jobs'),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  deleteJob: (id: string) => request<{deleted: string; cleanup_failed?: string[]}>(`/api/jobs/${id}`, { method: 'DELETE' }),
  documents: (id: string) => request<KnowledgeDocument[]>(`/api/jobs/${id}/documents`),
  domains: () => request<Domain[]>('/api/domains'),
  createDomain: (name: string) => request<Domain>('/api/domains', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  }),
  renameDomain: (id: string, name: string) => request<Domain>(`/api/domains/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  }),
  createPath: (payload: object) => request<Job>('/api/jobs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  createUpload: (form: FormData) => request<Job>('/api/jobs/upload', { method: 'POST', body: form }),
  action: (id: string, action: string) => request<Job>(`/api/jobs/${id}/${action}`, { method: 'POST' }),
  classify: (jobId: string, fileId: string, domain: string) => request<JobFile>(`/api/jobs/${jobId}/files/${fileId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ domain }),
  }),
  settings: () => request<any>('/api/settings/dify'),
  saveSettings: (payload: object) => request<any>('/api/settings/dify', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  testDify: () => request<{ok: boolean; message: string}>('/api/settings/dify/test', { method: 'POST' }),
}
