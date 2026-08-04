import { get, put } from './http.js'

const API = '/api'

export const getDistributionDefault = (jobPosition) => {
  const query = jobPosition ? `?job_position=${encodeURIComponent(jobPosition)}` : ''
  return get(`${API}/interview/distribution/default${query}`, { noCache: true })
}

export const getDistributionPreference = (jobPosition) => {
  const query = jobPosition ? `?job_position=${encodeURIComponent(jobPosition)}` : ''
  return get(`${API}/profile/interview-distribution-preference${query}`, { noCache: true })
}

export const saveDistributionPreference = (jobPosition, payload) => {
  const query = jobPosition ? `?job_position=${encodeURIComponent(jobPosition)}` : ''
  return put(`${API}/profile/interview-distribution-preference${query}`, payload)
}
