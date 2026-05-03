<template>
  <div class="space-y-6">
    <!-- Config panel -->
    <div v-if="!quizStarted" class="bg-white rounded-xl border border-orange-200 p-6 space-y-6">
      <h2 class="text-lg font-bold text-gray-800">配置抽测</h2>

      <!-- Category selection -->
      <div>
        <label class="text-sm font-semibold text-gray-600 mb-2 block">选择领域</label>
        <div class="flex flex-wrap gap-2">
          <button
            @click="selectedCat = ''"
            class="text-xs px-3 py-1.5 rounded-full border transition-colors"
            :class="selectedCat === '' ? 'bg-orange-100 text-orange-700 border-orange-300 font-semibold' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'"
          >全部领域</button>
          <button
            v-for="(cnt, cat) in popularTags" :key="cat"
            @click="selectedCat = cat"
            class="text-xs px-3 py-1.5 rounded-full border transition-colors"
            :class="selectedCat === cat ? 'bg-orange-100 text-orange-700 border-orange-300 font-semibold' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'"
          >{{ cat }} <span class="opacity-50 ml-0.5">{{ cnt }}</span></button>
        </div>
      </div>

      <!-- Difficulty selection -->
      <div>
        <label class="text-sm font-semibold text-gray-600 mb-2 block">难度</label>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="opt in difficultyOptions" :key="opt.value"
            @click="selectedDifficulty = opt.value"
            class="text-xs px-3 py-1.5 rounded-full border transition-colors"
            :class="selectedDifficulty === opt.value ? 'bg-orange-100 text-orange-700 border-orange-300 font-semibold' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'"
          >{{ opt.label }}</button>
        </div>
      </div>

      <!-- Count -->
      <div>
        <label class="text-sm font-semibold text-gray-600 mb-2 block">题目数量</label>
        <div class="flex items-center gap-3">
          <button @click="questionCount = Math.max(1, questionCount - 1)" class="w-9 h-9 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 flex items-center justify-center text-lg font-bold transition">-</button>
          <input v-model.number="questionCount" type="number" min="1" max="50" class="w-20 text-center border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:ring-orange-500 focus:border-orange-500" />
          <button @click="questionCount = Math.min(50, questionCount + 1)" class="w-9 h-9 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 flex items-center justify-center text-lg font-bold transition">+</button>
        </div>
      </div>

      <!-- Start button -->
      <button @click="startQuiz" class="w-full bg-orange-600 text-white font-bold py-3 rounded-lg hover:bg-orange-700 transition text-base shadow-sm">
        开始抽测
      </button>
    </div>

    <!-- Quiz mode -->
    <div v-else>
      <!-- Summary bar -->
      <div class="flex flex-wrap items-center justify-between gap-3 mb-4 bg-orange-50 border border-orange-200 rounded-lg px-4 py-3">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="text-gray-500">当前：</span>
          <span class="bg-orange-100 text-orange-700 px-2 py-0.5 rounded text-xs font-semibold">{{ selectedCat || '全部领域' }}</span>
          <span class="bg-orange-100 text-orange-700 px-2 py-0.5 rounded text-xs font-semibold">{{ selectedDifficultyLabel }}</span>
          <span class="text-gray-400">|</span>
          <span class="text-gray-600">共 {{ mockQuestions.length }} 题</span>
        </div>
        <div class="flex gap-2">
          <button @click="loadQuestions" class="text-sm bg-orange-600 text-white font-semibold px-4 py-1.5 rounded-lg hover:bg-orange-700 transition">换一批</button>
          <button @click="quizStarted = false" class="text-sm bg-white text-gray-600 border border-gray-200 px-4 py-1.5 rounded-lg hover:bg-gray-50 transition">重新配置</button>
        </div>
      </div>

      <!-- Loading -->
      <div v-if="isLoading" class="text-center py-10 text-gray-400 border-2 border-dashed border-gray-200 rounded-xl">
        <svg class="animate-spin h-8 w-8 text-orange-400 mx-auto mb-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
        <p class="text-lg">正在加载题目...</p>
      </div>

      <!-- Empty -->
      <div v-else-if="mockQuestions.length === 0" class="text-center py-10 text-gray-400 border-2 border-dashed border-gray-200 rounded-xl">
        <p class="mb-2 text-lg">暂无符合条件的题目</p>
        <p class="text-sm">请调整筛选条件或录入更多面经数据。</p>
        <button @click="quizStarted = false" class="mt-4 text-sm bg-orange-100 text-orange-700 px-4 py-2 rounded-lg hover:bg-orange-200 transition">返回配置</button>
      </div>

      <!-- Questions -->
      <div v-for="(q, qIdx) in mockQuestions" :key="q.id" class="border border-orange-200 rounded-xl overflow-hidden bg-white shadow-sm">
        <div class="p-5 bg-gradient-to-r from-orange-50 to-amber-50">
          <div class="flex items-start gap-4">
            <div class="flex flex-col items-center justify-center bg-orange-100 text-orange-700 font-bold rounded-lg p-3 min-w-[56px] border border-orange-200">
              <span class="text-xs font-normal text-orange-400">第</span>
              <span class="text-xl leading-none">{{ qIdx + 1 }}</span>
              <span class="text-xs font-normal text-orange-400">题</span>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex gap-2 mb-2 items-center flex-wrap">
                <span class="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded font-semibold">{{ q.cat1 || '未分类' }}</span>
                <span class="text-xs font-medium px-2 py-0.5 rounded" :class="String(q.difficulty).includes('L3') ? 'bg-red-50 text-red-600' : String(q.difficulty).includes('L2') ? 'bg-yellow-50 text-yellow-600' : 'bg-green-50 text-green-600'">
                  {{ q.difficulty || '-' }}
                </span>
                <span class="text-xs text-gray-400 ml-auto">频率 {{ q.frequency }}</span>
              </div>
              <h3 class="text-base lg:text-lg font-bold text-gray-800 leading-snug">{{ q.question }}</h3>
            </div>
          </div>
        </div>
        <div class="border-t border-orange-100">
          <button
            @click="q._showAnswer = !q._showAnswer"
            class="w-full py-3 text-sm font-medium text-orange-600 hover:bg-orange-50 transition flex items-center justify-center gap-2"
          >
            {{ q._showAnswer ? '收起答案' : '查看答案' }}
          </button>
          <div v-if="q._showAnswer" class="p-6 bg-slate-50 border-t border-orange-100">
            <div v-if="q.ai_answer" class="text-gray-700 text-sm leading-relaxed answer-content" v-html="renderMarkdown(q.ai_answer)"></div>
            <div v-else class="text-center py-4">
              <p class="text-gray-400 mb-3 text-sm">暂无 AI 答案。</p>
              <button @click="handleGenerate(q)" :disabled="q._isLoadingAnswer" class="bg-blue-100 text-blue-700 font-bold px-6 py-2 rounded-lg hover:bg-blue-200 transition text-sm disabled:opacity-50">
                {{ q._isLoadingAnswer ? '生成中...' : 'AI 生成答案' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { marked } from 'marked'
import { fetchRandomQuestions, generateAnswer as apiGenerateAnswer } from '../api/index.js'
import { useToast } from '../composables/useNotification.js'

const toast = useToast()

const props = defineProps({
  popularTags: { type: Object, default: () => ({}) }
})

const difficultyOptions = [
  { value: '', label: '随机' },
  { value: 'L1', label: 'L1-基础' },
  { value: 'L2', label: 'L2-中等' },
  { value: 'L3', label: 'L3-困难' }
]

// Config state
const selectedCat = ref('')
const selectedDifficulty = ref('')
const questionCount = ref(10)

// Quiz state
const quizStarted = ref(false)
const isLoading = ref(false)
const mockQuestions = ref([])

const selectedDifficultyLabel = computed(() =>
  difficultyOptions.find(o => o.value === selectedDifficulty.value)?.label || '随机'
)

const startQuiz = () => {
  quizStarted.value = true
  loadQuestions()
}

const loadQuestions = async () => {
  isLoading.value = true
  try {
    const data = await fetchRandomQuestions({
      count: questionCount.value,
      cat1: selectedCat.value || undefined,
      difficulty: selectedDifficulty.value || undefined
    })
    mockQuestions.value = data.map(q => ({ ...q, _showAnswer: false, _isLoadingAnswer: false }))
  } catch (e) {
    console.error('获取题目失败', e)
    mockQuestions.value = []
  } finally {
    isLoading.value = false
  }
}

const handleGenerate = async (q) => {
  q._isLoadingAnswer = true
  try {
    const data = await apiGenerateAnswer(q.id)
    q.ai_answer = data.answer
    toast.success('答案已生成')
  } catch (e) {
    toast.error(`生成失败: ${e.message}`)
  } finally {
    q._isLoadingAnswer = false
  }
}

const renderMarkdown = (text) => text ? marked.parse(text) : ''
</script>
