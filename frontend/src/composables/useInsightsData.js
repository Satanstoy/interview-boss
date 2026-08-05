import { ref } from 'vue'
import { fetchInsights, fetchPracticeActivity } from '@/services/insightsApi.js'

export function useInsightsData() {
  const snapshot = ref(null)
  const practiceActivity = ref(null)
  const isLoading = ref(false)
  const practiceLoading = ref(false)
  const error = ref(null)

  async function loadInsights() {
    isLoading.value = true
    error.value = null
    try {
      snapshot.value = await fetchInsights({ noCache: true })
    } catch (err) {
      error.value = err
    } finally {
      isLoading.value = false
    }
  }

  async function loadPracticeActivity() {
    practiceLoading.value = true
    try {
      practiceActivity.value = await fetchPracticeActivity({ noCache: true })
    } catch {
      practiceActivity.value = null
    } finally {
      practiceLoading.value = false
    }
  }

  return {
    snapshot,
    practiceActivity,
    isLoading,
    practiceLoading,
    error,
    loadInsights,
    loadPracticeActivity,
  }
}
