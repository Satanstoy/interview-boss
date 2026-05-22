import { get, del, upload } from './http.js'

// ── 简历管理 ──
export const uploadResume = (formData) => upload('/api/profile/resume', formData)
export const getResume = () => get('/api/profile/resume', { noCache: true })
export const deleteResume = () => del('/api/profile/resume')
