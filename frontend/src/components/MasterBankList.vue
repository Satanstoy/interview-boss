<template>
  <div class="space-y-4">
    <!-- Batch action bar -->
    <div class="flex flex-wrap justify-end items-center bg-white p-4 rounded-lg border border-gray-200 shadow-sm gap-4">
      <div class="flex items-center gap-2">
        <button @click="$emit('toggle-select-all')" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">全选/取消全选</button>
        <button @click="$emit('invert-selection')" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">反选</button>
        <div class="w-px h-5 bg-gray-300 mx-1"></div>
        <button @click="$emit('batch-generate')" :disabled="selectedCount === 0" class="text-sm bg-blue-100 text-blue-700 px-3 py-1.5 rounded hover:bg-blue-200 transition font-medium flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed">
          批量生成答案 ({{ selectedCount }})
        </button>
        <button @click="$emit('batch-delete')" :disabled="selectedCount === 0" class="text-sm bg-red-100 text-red-700 px-3 py-1.5 rounded hover:bg-red-200 transition font-medium flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed">
          批量删除 ({{ selectedCount }})
        </button>
      </div>
    </div>

    <div v-if="items.length === 0" class="text-center py-10 text-gray-400 border-2 border-dashed border-gray-200 rounded-xl">
      <p class="mb-2">暂无符合条件的精炼真题。</p>
      <p class="text-sm">你可以点击左侧"全部高频真题"查看所有，或者录入更多面经自动扩充。</p>
    </div>

    <div v-for="q in items" :key="q.id" class="border border-gray-200 rounded-lg overflow-hidden bg-white hover:border-blue-300 transition shadow-sm" :class="isSelected(q.id) ? 'border-blue-400 ring-1 ring-blue-400' : ''">
      <!-- Card header -->
      <div class="p-5 flex gap-4 items-start cursor-pointer hover:bg-slate-50 transition" @click="q._showAnswer = !q._showAnswer">
        <div class="flex items-center h-full pt-3" @click.stop>
          <input type="checkbox" :checked="isSelected(q.id)" @change="$emit('toggle-item', q.id)" class="w-5 h-5 text-blue-600 rounded border-gray-300 focus:ring-blue-500 cursor-pointer">
        </div>
        <div class="flex flex-col items-center justify-center bg-red-50 text-red-600 font-bold rounded-lg p-3 min-w-[60px] border border-red-100 shadow-inner">
          <span class="text-xs font-normal text-red-400 mb-0.5">考频</span>
          <span class="text-xl leading-none">{{ q.frequency }}</span>
        </div>

        <div class="flex-1">
          <div class="flex gap-2 mb-2 items-center flex-wrap">
            <span class="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded font-semibold">{{ q.cat1 || '未分类' }}</span>
            <span v-for="tag in (q.tags ? q.tags.split(',') : [])" :key="tag" class="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded border border-gray-200">
              {{ tag }}
            </span>
            <span class="text-xs ml-auto font-medium px-2 py-0.5 rounded" :class="String(q.difficulty).includes('困难') || String(q.difficulty).includes('L3') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'">
              难度: {{ q.difficulty || '-' }}
            </span>
            <button @click.stop="$emit('toggle-star', q)" class="text-lg ml-1 transition-transform hover:scale-125" :title="q.is_starred ? '取消收藏' : '收藏'">
              {{ q.is_starred ? '★' : '☆' }}
            </button>
            <button @click.stop="$emit('retag', q)" :disabled="q._isRetagging" class="text-xs bg-yellow-50 text-yellow-700 px-2 py-0.5 rounded border border-yellow-200 hover:bg-yellow-100 transition disabled:opacity-50 ml-2">
              <svg v-if="q._isRetagging" class="animate-spin inline-block w-3 h-3 mr-1" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
              {{ q._isRetagging ? '打标中...' : '重新打标' }}
            </button>
          </div>
          <h3 class="text-lg font-bold text-gray-800 leading-snug">{{ q.question }}</h3>
        </div>

        <div class="text-gray-400 mt-2">
          <svg class="w-6 h-6 transform transition-transform" :class="q._showAnswer ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
        </div>
      </div>

      <!-- Expandable answer section -->
      <div v-if="q._showAnswer" class="border-t border-gray-100 bg-slate-50 p-6 relative group">
        <!-- Source tracing -->
        <div v-if="q.sources && q.sources.length > 0" class="mb-4 bg-indigo-50/50 border border-indigo-100 rounded-lg p-3">
          <h4 class="text-sm font-bold text-indigo-800 mb-2 flex items-center gap-1">
            追溯面经源头 (共 {{ q.sources.length }} 次出现)
          </h4>
          <div class="flex flex-wrap gap-2 text-xs">
            <span v-for="(src, idx) in q.sources" :key="idx" class="bg-white border border-indigo-200 text-indigo-700 px-2.5 py-1 rounded-md inline-flex items-center shadow-sm">
              {{ src.company === '未提供' ? '未知公司' : src.company }}
              <span class="text-indigo-400 mx-1">|</span>
              {{ src.round === '未提供' ? '未知轮次' : src.round }}
              <a v-if="src.url && src.url !== '未提供链接'" :href="src.url" target="_blank" class="ml-2 text-blue-500 hover:text-blue-700 font-bold transition-colors" title="访问原帖">
                [原帖链接]
              </a>
            </span>
          </div>
        </div>

        <!-- Edit answer mode -->
        <div v-if="q._isEditingAnswer" class="flex flex-col gap-3">
          <label class="font-bold text-gray-700">编辑答案</label>
          <textarea v-model="q._editAnswer" rows="8" class="w-full border border-blue-300 rounded p-4 text-sm focus:ring-blue-500 focus:border-blue-500 shadow-inner font-mono"></textarea>
          <div class="flex gap-2 justify-end mt-2">
            <button @click="q._isEditingAnswer = false" class="px-5 py-2 bg-gray-200 rounded-lg text-gray-700 text-sm hover:bg-gray-300 transition">取消</button>
            <button @click="$emit('save-field', { tableName: 'master_question_bank', recordId: q.id, dbColumn: 'ai_answer', newValue: q._editAnswer, rowObj: q, editStateKey: '_isEditingAnswer', frontendKey: 'ai_answer' })" class="px-5 py-2 bg-blue-600 text-white font-bold rounded-lg text-sm hover:bg-blue-700 transition shadow">保存修改</button>
          </div>
        </div>

        <!-- View answer mode -->
        <div v-else>
          <button v-if="q.ai_answer" @click="q._isEditingAnswer = true; q._editAnswer = q.ai_answer" class="absolute top-4 right-4 bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 px-3 py-1 rounded text-xs transition opacity-0 group-hover:opacity-100 shadow-sm z-10">
            修改答案
          </button>

          <div v-if="q.ai_answer && !isFailedAnswer(q.ai_answer)" class="text-gray-700 text-sm leading-relaxed max-w-none answer-content" v-html="renderMarkdown(q.ai_answer)"></div>

          <div v-else-if="q._isLoadingAnswer" class="flex flex-col items-center justify-center py-6 text-blue-600 gap-3">
            <svg class="animate-spin h-8 w-8" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
            <span class="font-medium">大模型正在为您生成高质量解答，请稍候...</span>
          </div>

          <div v-else class="text-center py-4">
            <p v-if="isFailedAnswer(q.ai_answer)" class="text-red-500 mb-3 text-sm">上次自动生成失败，请手动重试。</p>
            <p v-else class="text-gray-500 mb-3 text-sm">该题目是由系统后台刚刚抽取出的新考点，尚未生成解答。</p>
            <button @click.stop="$emit('generate-answer', q)" class="bg-blue-100 text-blue-700 font-bold px-6 py-2.5 rounded-lg hover:bg-blue-200 transition shadow-sm border border-blue-200">
              召唤 AI 生成满分回答
            </button>
            <button @click="q._isEditingAnswer = true; q._editAnswer = ''" class="ml-3 bg-gray-100 text-gray-600 font-bold px-6 py-2.5 rounded-lg hover:bg-gray-200 transition shadow-sm border border-gray-200">
              手动编写答案
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { marked } from 'marked'

defineProps({
  items: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
  isSelected: { type: Function, default: () => false }
})

defineEmits(['toggle-select-all', 'invert-selection', 'batch-generate', 'batch-delete', 'toggle-star', 'retag', 'generate-answer', 'save-field', 'toggle-item'])

const isFailedAnswer = (answer) => answer && answer.includes('生成失败')
const renderMarkdown = (text) => text ? marked.parse(text) : ''
</script>
