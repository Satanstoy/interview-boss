import { ref } from 'vue'
import { fetchInsights } from '@/services/insightsApi.js'

export function useInsightsData() {
  const snapshot = ref(null)
  const isLoading = ref(false)
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

  return { snapshot, isLoading, error, loadInsights }
}
