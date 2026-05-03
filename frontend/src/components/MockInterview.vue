<template>
  <div class="space-y-6">
    <div class="flex flex-wrap justify-between items-center mb-4 gap-2">
      <h2 class="text-lg lg:text-xl font-bold flex items-center gap-2">模拟面试</h2>
      <button @click="loadQuestions" class="text-sm bg-orange-600 text-white font-bold px-4 py-2 rounded hover:bg-orange-700 transition">
        换一批题目
      </button>
    </div>

    <div v-if="mockQuestions.length === 0" class="text-center py-10 text-gray-400 border-2 border-dashed border-gray-200 rounded-xl">
      <p class="mb-2 text-lg">正在加载模拟面试题目...</p>
      <p class="text-sm">如果没有题目，请先录入面经数据。</p>
    </div>

    <div v-for="(q, qIdx) in mockQuestions" :key="q.id" class="border border-orange-200 rounded-xl overflow-hidden bg-white shadow-sm">
      <div class="p-5 bg-gradient-to-r from-orange-50 to-amber-50">
        <div class="flex items-start gap-4">
          <div class="flex flex-col items-center justify-center bg-orange-100 text-orange-700 font-bold rounded-lg p-3 min-w-[50px] border border-orange-200">
            <span class="text-xs font-normal text-orange-400">第</span>
            <span class="text-xl leading-none">{{ qIdx + 1 }}</span>
            <span class="text-xs font-normal text-orange-400">题</span>
          </div>
          <div class="flex-1">
            <div class="flex gap-2 mb-2 items-center flex-wrap">
              <span class="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded font-semibold">{{ q.cat1 || '未分类' }}</span>
              <span class="text-xs font-medium px-2 py-0.5 rounded" :class="String(q.difficulty).includes('L3') ? 'bg-red-50 text-red-600' : String(q.difficulty).includes('L2') ? 'bg-yellow-50 text-yellow-600' : 'bg-green-50 text-green-600'">
                {{ q.difficulty || '-' }}
              </span>
              <span class="text-xs text-gray-400 ml-auto">考频 {{ q.frequency }}</span>
            </div>
            <h3 class="text-lg font-bold text-gray-800 leading-snug">{{ q.question }}</h3>
          </div>
        </div>
      </div>
      <div class="border-t border-orange-100">
        <button
          @click="q._showAnswer = !q._showAnswer"
          class="w-full py-3 text-sm font-medium text-orange-600 hover:bg-orange-50 transition flex items-center justify-center gap-2"
        >
          {{ q._showAnswer ? '收起参考答案' : '查看参考答案（先自己想想！）' }}
        </button>
        <div v-if="q._showAnswer" class="p-6 bg-slate-50 border-t border-orange-100">
          <div v-if="q.ai_answer" class="text-gray-700 text-sm leading-relaxed answer-content" v-html="renderMarkdown(q.ai_answer)"></div>
          <div v-else class="text-center py-4">
            <p class="text-gray-400 mb-3 text-sm">该题目暂无 AI 生成的参考答案。</p>
            <button @click="handleGenerate(q)" class="bg-blue-100 text-blue-700 font-bold px-6 py-2 rounded-lg hover:bg-blue-200 transition text-sm">
              召唤 AI 生成参考答案
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { marked } from 'marked'
import { fetchRandomQuestions, generateAnswer as apiGenerateAnswer } from '../api/index.js'

const props = defineProps({
  filterDifficulty: { type: String, default: '' }
})

const mockQuestions = ref([])

const loadQuestions = async () => {
  try {
    const data = await fetchRandomQuestions(5, props.filterDifficulty)
    mockQuestions.value = data.map(q => ({ ...q, _showAnswer: false }))
  } catch (e) {
    console.error('获取模拟面试题目失败', e)
    mockQuestions.value = []
  }
}

const handleGenerate = async (q) => {
  q._isLoadingAnswer = true
  try {
    const data = await apiGenerateAnswer(q.id)
    q.ai_answer = data.answer
  } catch (e) {
    alert(`生成解答失败: ${e.message}`)
  } finally {
    q._isLoadingAnswer = false
  }
}

const renderMarkdown = (text) => text ? marked.parse(text) : ''

// Load questions on mount
loadQuestions()

defineExpose({ loadQuestions })
</script>
