/**
 * HTTP 客户端 re-export
 *
 * 实际实现已移至 services/http.js，此文件保留以兼容现有 import 路径。
 * 新代码建议直接从 services/http.js 导入。
 */
export {
  get,
  post,
  put,
  del,
  upload,
  uploadSSE,
  postSSE,
  getSSE,
  fetchWithCredentials,
  cancelAllRequests,
  invalidateCache,
  setAuthToken,
  getAuthToken,
  refreshAuthToken,
  setUnauthorizedHandler,
  getFriendlyError,
} from '../services/http.js'
