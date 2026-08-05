import { get, del, upload, postSSE } from './http.js'

// ── 简历管理 ──
export const uploadResume = (formData) => upload('/api/profile/resume', formData)
export const getResume = () => get('/api/profile/resume', { noCache: true })
export const deleteResume = () => del('/api/profile/resume')

// ── 简历原文与优化 ──
export const getResumeText = () => get('/api/profile/resume/text', { noCache: true })
export const getResumeOptimization = () => get('/api/profile/resume/optimization', { noCache: true })
export const optimizeResume = (position, onEvent, options = {}) =>
  postSSE('/api/profile/resume/optimize', { position }, onEvent, options)
