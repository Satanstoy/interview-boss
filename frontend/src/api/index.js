/**
 * API 统一入口 — 从 services/ 领域模块 re-export 所有函数
 *
 * 所有现有 import 路径保持不变：
 *   import { xxx } from '@/api/index.js'
 *   import * as api from '@/api/index.js'
 *
 * 新代码建议直接从 services/ 按领域导入：
 *   import { authLogin } from '@/services/authApi.js'
 */

// ── Auth ──
export {
  authRegister,
  authLogin,
  authMe,
  authUpdateShareDefault,
  authRefresh,
  authLogout,
  resetPassword,
  changePassword,
  sendVerifyCode,
  authRegisterWithEmail,
  authLoginWithEmail,
  getMyEmail,
  sendBindCode,
  bindEmail,
  bindEmailWithToken,
} from '../services/authApi.js'

// ── Data ──
export {
  fetchJdData,
  fetchInterviewData,
  fetchMasterBank,
  submitData,
  submitDataSSE,
  createSubmitJob,
  fetchActiveSubmitJobs,
  deleteRecord,
  updateRecord,
  restoreRecord,
  fetchTrash,
  batchDeleteData,
} from '../services/dataApi.js'

// ── Master Bank ──
export {
  buildMasterBank,
  buildMasterBankSSE,
  streamJobProgress,
  buildPersonalBankSSE,
  retagQuestion,
  generateAnswer,
  saveUserAnswer,
  generateRecitation,
  toggleStar,
  deleteMasterQuestion,
  updateQuestion,
  splitQuestion,
  deleteOriginalQuestion,
  mergeQuestion,
  searchMasterBank,
  getAnalysisStatus,
  uploadToBank,
  fetchPendingQuestions,
  approveQuestion,
  rejectQuestion,
  batchDeleteMasterBank,
  batchGenerateAnswers,
  fetchMasterBankTrash,
  restoreQuestion,
  batchRestoreMasterBank,
} from '../services/masterBankApi.js'

// ── Interview ──
export {
  reprocessInterview,
  reprocessInterviewSSE,
} from '../services/interviewApi.js'

// ── Analytics ──
export {
  fetchAnalytics,
  fetchPracticeStats,
  fetchKnowledgeGraph,
} from '../services/analyticsApi.js'

// ── Insights ──
export { fetchInsights, fetchPracticeActivity } from '../services/insightsApi.js'

// ── Profile ──
export {
  fetchProfile,
  fetchPublicProfile,
  updateProfile,
  switchPosition,
  switchPositionById,
  switchMyPosition,
  fetchPositions,
  deletePosition,
  createPosition,
  generateTaxonomy,
  confirmTaxonomy,
  savePersonalTaxonomy,
  shareTaxonomy,
  fetchPublicTaxonomies,
  deletePublicTaxonomy,
  fetchMyLLMConfig,
  updateMyLLMConfig,
  deleteMyLLMConfig,
  fetchLLMStatus,
} from '../services/profileApi.js'

// ── Practice ──
export {
  fetchPracticeHistory,
  evaluateAnswer,
  fetchPracticeDecks,
  fetchPracticeDeckQuestions,
  submitPracticeReview,
  createPracticeDeck,
  updatePracticeDeck,
  deletePracticeDeck,
  addPracticeDeckItem,
  removePracticeDeckItem,
} from '../services/practiceApi.js'

// ── Chat ──
export {
  createConversation,
  getConversations,
  getConversation,
  updateTitle,
  archiveConversation,
  deleteConversation,
  getMessages,
  sendMessage,
  getMemories,
  deleteMemory,
} from '../services/chatApi.js'

export {
  getDistributionDefault,
  getDistributionPreference,
  saveDistributionPreference,
} from '../services/interviewDistributionApi.js'

// ── Resume ──
export {
  uploadResume,
  getResume,
  deleteResume,
} from '../services/resumeApi.js'

// ── Cache Management (re-export from http service) ──
export { invalidateCache } from '../services/http.js'

// ── Coding ──
export {
  fetchCodingProblems,
  fetchCodingProblem,
  submitCodingCode,
  fetchCodingSubmissions,
  fetchCodingSubmission,
  fetchCodingErrorStats,
} from '../services/codingApi.js'
