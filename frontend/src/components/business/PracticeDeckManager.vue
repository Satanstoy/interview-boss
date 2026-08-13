<template>
  <div data-testid="practice-deck-manager" class="relative flex h-full min-h-0 w-full overflow-hidden bg-background">
    <div class="flex min-w-0 flex-1 flex-col">
      <main class="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
        <div class="mx-auto w-full max-w-5xl px-3 pb-12 pt-4 sm:px-4 sm:pt-6 md:px-6 md:pt-8">
          <section class="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
            <div>
              <p class="text-xs font-medium uppercase tracking-[0.18em] text-primary">Study plans</p>
              <h1 class="mt-2 text-2xl font-semibold tracking-tight text-foreground md:text-3xl">题单管理</h1>
              <p class="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">把高频题库整理成自己的复习路径。每道题都会沿用同一套熟练度和间隔复习记录。</p>
            </div>
            <div class="flex items-center gap-2 text-xs text-muted-foreground">
              <Layers class="size-4 text-primary" />
              <span>{{ customDecks.length }} 个自定义题单</span>
            </div>
          </section>

          <section class="mb-7 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div class="rounded-xl border border-border bg-card px-4 py-3">
              <p class="text-xs text-muted-foreground">题单总数</p>
              <p class="mt-1 text-xl font-semibold tabular-nums text-foreground">{{ decks.length }}</p>
            </div>
            <div class="rounded-xl border border-border bg-card px-4 py-3">
              <p class="text-xs text-muted-foreground">已建立记忆</p>
              <p class="mt-1 text-xl font-semibold tabular-nums text-foreground">{{ reviewedTotal }} <span class="text-xs font-normal text-muted-foreground">道题</span></p>
            </div>
          </section>

          <section>
            <div class="mb-3 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 class="text-sm font-semibold text-foreground">我的题单</h2>
                <p class="mt-1 text-xs text-muted-foreground">系统题单只有全部题和我的收藏，其余题单由你自己组织。</p>
              </div>
              <Button data-testid="practice-deck-create" size="sm" class="h-10 w-full gap-1.5 sm:h-8 sm:w-auto" @click="openCreate"><Plus class="size-3.5" />新建题单</Button>
            </div>
            <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
              <article
                v-for="deck in decks"
                :key="deck.key"
                data-testid="practice-deck-card"
                class="group rounded-xl border border-border bg-card p-4 transition hover:border-primary/40 hover:shadow-sm"
                :class="selectedDeckKey === deck.key ? 'border-primary/50 ring-1 ring-primary/15' : ''"
              >
                <button type="button" class="w-full text-left" @click="selectDeck(deck)">
                  <div class="flex items-start gap-3">
                    <div class="flex size-10 shrink-0 items-center justify-center rounded-xl" :class="deckTone(deck)"><component :is="deckIcon(deck)" class="size-5" /></div>
                    <div class="min-w-0 flex-1">
                      <div class="flex items-center gap-2">
                        <h3 class="truncate text-sm font-semibold text-foreground">{{ deck.name }}</h3>
                        <Badge v-if="deck.kind === 'custom'" variant="secondary" class="shrink-0 text-[10px]">自定义</Badge>
                        <Badge v-else variant="outline" class="shrink-0 text-[10px]">系统</Badge>
                      </div>
                      <p class="mt-1 line-clamp-2 min-h-10 text-xs leading-5 text-muted-foreground">{{ deck.description || '暂无描述' }}</p>
                    </div>
                    <ChevronRight class="mt-1 size-4 shrink-0 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-primary" />
                  </div>
                  <div class="mt-4 flex items-center justify-between text-xs text-muted-foreground">
                    <span>{{ deck.total || 0 }} 道题 · {{ deck.reviewed || 0 }} 道已刷</span>
                    <span class="tabular-nums">{{ deck.progress || 0 }}%</span>
                  </div>
                  <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-primary transition-all" :style="{ width: `${deck.progress || 0}%` }"></div></div>
                  <div class="mt-3 flex items-center gap-1.5 text-[11px] text-muted-foreground"><span>{{ deck.kind === 'custom' ? '点击查看题目' : '点击开始复习' }}</span></div>
                </button>
                <div v-if="deck.kind === 'custom'" class="mt-3 flex justify-end gap-1 border-t border-border/70 pt-3">
                  <Button variant="ghost" size="sm" class="h-10 gap-1 text-xs text-muted-foreground sm:h-7" @click="openEdit(deck)"><Pencil class="size-3.5" />编辑</Button>
                  <Button variant="ghost" size="sm" class="h-10 gap-1 text-xs text-destructive hover:text-destructive sm:h-7" @click="emit('delete-deck', deck.key)"><Trash2 class="size-3.5" />删除</Button>
                </div>
              </article>
            </div>
            <div v-if="!decks.length && !loading" class="rounded-xl border border-dashed border-border px-6 py-12 text-center text-sm text-muted-foreground">暂无题单，先创建一个自己的八股复习路径吧。</div>
            <div v-if="loading" class="rounded-xl border border-border px-6 py-12 text-center text-sm text-muted-foreground">题单加载中...</div>
          </section>

          <section v-if="selectedCustomDeck" class="mt-8 rounded-xl border border-border bg-card">
            <div class="flex flex-col gap-3 border-b border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-between md:px-5">
              <div class="min-w-0">
                <div class="flex items-center gap-2"><List class="size-4 text-primary" /><h2 class="truncate text-sm font-semibold text-foreground">{{ selectedCustomDeck.name }} 的题目</h2></div>
                <p class="mt-1 text-xs text-muted-foreground">管理题单里的题目；题目的刷题记录不会因加入或移出题单而丢失。</p>
              </div>
              <Button size="sm" variant="outline" class="shrink-0 gap-1.5" @click="emit('start-deck', selectedCustomDeck.key)">开始刷这套题<ChevronRight class="size-3.5" /></Button>
            </div>
            <div class="border-b border-border/70 bg-muted/20 px-4 py-3 md:px-5">
              <div class="flex flex-col gap-2 sm:flex-row">
                <div class="relative min-w-0 flex-1">
                  <Search class="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                  <select v-model="questionToAdd" data-testid="practice-deck-question-select" class="h-9 w-full appearance-none rounded-md border border-input bg-background pl-8 pr-3 text-sm text-foreground outline-none focus:border-ring focus:ring-1 focus:ring-ring/20">
                    <option value="">选择一道高频题加入题单...</option>
                    <option v-for="question in addableQuestions" :key="question.id" :value="String(question.id)">{{ question.question }}</option>
                  </select>
                </div>
                    <Button size="sm" class="h-10 shrink-0 gap-1.5 sm:h-9" :disabled="!questionToAdd" @click="addQuestion"><Plus class="size-3.5" />加入题单</Button>
              </div>
              <p v-if="!availableQuestions.length" class="mt-2 text-xs text-muted-foreground">当前题库筛选下没有可加入的题目，请先回到高频题库调整筛选。</p>
            </div>
            <div class="divide-y divide-border/70">
              <div v-for="(question, index) in selectedQuestions" :key="question.id" class="flex items-start gap-3 px-4 py-3 md:px-5">
                <span class="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded bg-muted text-[11px] tabular-nums text-muted-foreground">{{ index + 1 }}</span>
                <div class="min-w-0 flex-1"><p class="text-sm leading-6 text-foreground">{{ question.question }}</p><p class="mt-1 text-[11px] text-muted-foreground">{{ question.cat1 || '未分类' }} · 熟练度 {{ question.proficiency || 0 }}/5</p></div>
                <Button variant="ghost" size="icon-sm" class="shrink-0 text-muted-foreground hover:text-destructive" :aria-label="`移出${question.question}`" @click="emit('remove-item', { deckKey: selectedCustomDeck.key, questionId: question.id })"><X class="size-4" /></Button>
              </div>
              <div v-if="!selectedQuestions.length" class="px-5 py-10 text-center text-sm text-muted-foreground">这个自定义题单还没有题目，从上方加入高频题吧。</div>
            </div>
          </section>
        </div>
      </main>
    </div>

    <AppDialog :open="editorOpen" :title="editingDeck ? '编辑题单' : '新建题单'" description="给一组需要反复背诵的八股题一个清晰的复习入口。" size="md" @update:open="editorOpen = $event">
      <div class="flex flex-col gap-4 px-6 pb-2">
        <div v-if="!editingDeck" class="rounded-lg border border-primary/15 bg-primary/5 p-3">
          <p class="text-xs font-semibold text-foreground">不知道怎么分组？可以从这些题单开始</p>
          <div class="mt-2 flex flex-wrap gap-1.5">
            <button v-for="recommendation in recommendedDecks" :key="recommendation.name" type="button" class="rounded-md border border-border bg-background px-2.5 py-1.5 text-[11px] text-muted-foreground transition hover:border-primary/40 hover:text-primary" @click="applyRecommendation(recommendation)">{{ recommendation.name }}</button>
          </div>
        </div>
        <div><label class="mb-1.5 block text-xs font-semibold text-muted-foreground">题单名称</label><input v-model="form.name" data-testid="practice-deck-name" class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none focus:border-ring focus:ring-1 focus:ring-ring/20" placeholder="例如：Java 并发八股" /></div>
        <div><label class="mb-1.5 block text-xs font-semibold text-muted-foreground">描述（可选）</label><textarea v-model="form.description" rows="3" class="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm leading-6 text-foreground outline-none focus:border-ring focus:ring-1 focus:ring-ring/20" placeholder="说明这套题单适合什么阶段或岗位" /></div>
      </div>
      <template #footer><div class="flex justify-end gap-2"><Button variant="outline" @click="editorOpen = false">取消</Button><Button data-testid="practice-deck-save" :disabled="!form.name.trim()" @click="saveDeck">{{ editingDeck ? '保存修改' : '创建题单' }}</Button></div></template>
    </AppDialog>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { BookOpen, ChevronRight, Layers, List, LockKeyhole, Pencil, Plus, Search, Trash2, X } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import AppDialog from '@/components/common/AppDialog.vue'

const props = defineProps({
  decks: { type: Array, default: () => [] },
  availableQuestions: { type: Array, default: () => [] },
  selectedQuestions: { type: Array, default: () => [] },
  selectedDeckKey: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['select-deck', 'start-deck', 'create-deck', 'update-deck', 'delete-deck', 'add-item', 'remove-item'])
const editorOpen = ref(false)
const editingDeck = ref(null)
const questionToAdd = ref('')
const form = ref({ name: '', description: '', visibility: 'private' })

const customDecks = computed(() => props.decks.filter(deck => deck.kind === 'custom'))
const selectedCustomDeck = computed(() => customDecks.value.find(deck => deck.key === props.selectedDeckKey) || null)
const addableQuestions = computed(() => {
  const selected = new Set(props.selectedQuestions.map(question => Number(question.id)))
  return props.availableQuestions.filter(question => !selected.has(Number(question.id)))
})
const reviewedTotal = computed(() => props.decks.reduce((sum, deck) => sum + Number(deck.reviewed || 0), 0))
const recommendedDecks = [
  { name: 'Java 并发八股', description: '线程、锁、JMM、并发容器和线程池' },
  { name: '项目复盘表达', description: '项目难点、性能优化、故障复盘和结果指标' },
  { name: '前端原理冲刺', description: '浏览器、JavaScript、框架原理和工程化' },
]

function deckIcon(deck) {
  if (deck.kind === 'custom') return LockKeyhole
  return deck.key === 'all' ? BookOpen : Layers
}
function deckTone(deck) {
  if (deck.kind === 'custom') return 'bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-300'
  return 'bg-primary/10 text-primary'
}
function selectDeck(deck) {
  if (deck.kind === 'custom') emit('select-deck', deck.key)
  else emit('start-deck', deck.key)
}
function openCreate() {
  editingDeck.value = null
  form.value = { name: '', description: '', visibility: 'private' }
  editorOpen.value = true
}
function openEdit(deck) {
  editingDeck.value = deck
  form.value = { name: deck.name || '', description: deck.description || '', visibility: deck.visibility || 'private' }
  editorOpen.value = true
}
function applyRecommendation(recommendation) {
  form.value = { name: recommendation.name, description: recommendation.description, visibility: 'private' }
}
function saveDeck() {
  if (!form.value.name.trim()) return
  if (editingDeck.value) emit('update-deck', { deckKey: editingDeck.value.key, payload: { ...form.value } })
  else emit('create-deck', { ...form.value })
  editorOpen.value = false
}
function addQuestion() {
  if (!questionToAdd.value || !selectedCustomDeck.value) return
  emit('add-item', { deckKey: selectedCustomDeck.value.key, questionId: Number(questionToAdd.value) })
  questionToAdd.value = ''
}
</script>
