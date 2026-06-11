# ChatView Layout Overhaul — Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform ChatView into a ChatGPT-style three-section layout (header/messages/input) with proper height constraints, state preservation across tab switches, and clean visual styling.

**Architecture:** Pure frontend changes across 3 Vue files. No API changes. `<KeepAlive>` preserves ChatView state; localStorage as fallback for activeConversationId. Height chain uses `h-screen overflow-hidden` to prevent page scroll.

**Tech Stack:** Vue 3 Composition API, Tailwind CSS, shadcn-vue

---

## File Map

| File | Responsibility | Changes |
|------|---------------|---------|
| `frontend/src/components/SiteHeader.vue` | Top navigation header | Add `noBorder` prop to conditionally remove `border-b` |
| `frontend/src/App.vue` | Root layout, tab system | Fix height chain; wrap ChatView in `<KeepAlive>`; pass `noBorder` to SiteHeader |
| `frontend/src/components/business/ChatView.vue` | Chat interface | Input area redesign; mode label cleanup; state save/restore; `onActivated` |

---

### Task 1: SiteHeader — Add `noBorder` Prop

**Files:**
- Modify: `frontend/src/components/SiteHeader.vue:5-14` (props) and `:20` (template)

- [ ] **Step 1: Add `noBorder` prop definition**

In `frontend/src/components/SiteHeader.vue`, add `noBorder` to the props object (after `activeSeason`):

```js
const props = defineProps({
  activeTabLabel: {
    type: String,
    required: true
  },
  activeSeason: {
    type: String,
    default: null
  },
  noBorder: {
    type: Boolean,
    default: false
  }
})
```

- [ ] **Step 2: Conditionally apply border class on header element**

Change line 20 from:
```html
<header class="flex h-14 shrink-0 items-center gap-4 border-b border-border bg-background/80 backdrop-blur-xl px-4 lg:px-6">
```
To:
```html
<header
  class="flex h-14 shrink-0 items-center gap-4 bg-background/80 backdrop-blur-xl px-4 lg:px-6"
  :class="{ 'border-b border-border': !noBorder }"
>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SiteHeader.vue
git commit -m "feat(frontend): add noBorder prop to SiteHeader"
```

---

### Task 2: App.vue — Height Chain + KeepAlive

**Files:**
- Modify: `frontend/src/App.vue:71` (outer wrapper), `:93-108` (main + ChatView)

- [ ] **Step 1: Fix outer wrapper height**

Change line 71 from:
```html
<div v-else class="flex min-h-screen">
```
To:
```html
<div v-else class="flex h-screen overflow-hidden">
```

- [ ] **Step 2: Pass `noBorder` prop to SiteHeader**

Find the `<SiteHeader>` usage (around line 94) and add the prop:
```html
<SiteHeader
  :active-tab-label="activeTabLabel"
  :active-season="activeSeason"
  :no-border="activeTab === 'Chat'"
  @show-settings="showSettingsPage = true"
/>
```

- [ ] **Step 3: Wrap ChatView in `<KeepAlive>`**

Change lines 102-108 from:
```html
<!-- ChatView: fills entire right side without padding -->
<ChatView
  v-if="activeTab === 'Chat'"
  :jd-list="jdData"
  :preview="isPreviewMode"
  class="flex-1 min-h-0"
/>
```
To:
```html
<!-- ChatView: fills entire right side without padding -->
<KeepAlive>
  <ChatView
    v-if="activeTab === 'Chat'"
    :jd-list="jdData"
    :preview="isPreviewMode"
    class="flex-1 min-h-0"
  />
</KeepAlive>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.vue
git commit -m "fix(frontend): fix height chain and preserve ChatView state with KeepAlive"
```

---

### Task 3: ChatView — State Preservation Logic

**Files:**
- Modify: `frontend/src/components/business/ChatView.vue:292` (imports), `:466-509` (loadConversations), `:813-819` (onMounted)

- [ ] **Step 1: Add `onActivated` to imports**

Change line 292 from:
```js
import { ref, computed, nextTick, onMounted, watch } from 'vue'
```
To:
```js
import { ref, computed, nextTick, onMounted, onActivated, watch } from 'vue'
```

- [ ] **Step 2: Add localStorage key constant**

After the refs block (after line 361), add:
```js
const STORAGE_KEY_ACTIVE_ID = 'chatview_active_conversation_id'
```

- [ ] **Step 3: Modify `loadConversations()` to preserve activeConversationId**

Replace lines 503-508 (the non-preview try/catch block) with:
```js
  try {
    const res = await chatApi.getConversations()
    conversations.value = res.data || []

    // Preserve active selection: only clear if conversation no longer exists
    if (activeConversationId.value) {
      const stillExists = conversations.value.some(c => c.id === activeConversationId.value)
      if (!stillExists) {
        activeConversationId.value = null
        messages.value = []
      }
    }
  } catch (e) {
    console.error('加载对话列表失败:', e)
  }
```

- [ ] **Step 4: Replace `onMounted` with `onMounted` + `onActivated`**

Replace lines 813-819 with:
```js
// Restore active conversation from localStorage
const savedId = localStorage.getItem(STORAGE_KEY_ACTIVE_ID)
if (savedId) {
  activeConversationId.value = savedId
}

// Load conversations on mount
onMounted(async () => {
  await loadConversations()

  // If we have a saved ID and it exists in the list, load its messages
  if (activeConversationId.value) {
    const exists = conversations.value.some(c => c.id === activeConversationId.value)
    if (exists) {
      try {
        const res = await chatApi.getMessages(activeConversationId.value)
        messages.value = res.data || []
        await scrollToBottom(true)
      } catch (e) {
        console.error('加载消息失败:', e)
      }
    } else {
      activeConversationId.value = null
    }
  }

  watch(activeConversationId, (id) => {
    autoScrollEnabled.value = true
    if (id) {
      localStorage.setItem(STORAGE_KEY_ACTIVE_ID, id)
    } else {
      localStorage.removeItem(STORAGE_KEY_ACTIVE_ID)
    }
  })
})

// Refresh conversations when returning to this tab (KeepAlive)
onActivated(async () => {
  await loadConversations()
})
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/business/ChatView.vue
git commit -m "fix(frontend): preserve active conversation across tab switches"
```

---

### Task 4: ChatView — Template Redesign

**Files:**
- Modify: `frontend/src/components/business/ChatView.vue:114-143` (header), `:146` (messages), `:214-276` (input area)

- [ ] **Step 1: Clean up chat header — remove mode label border**

Change line 141 from:
```html
<p class="px-1 text-xs text-muted-foreground">{{ activeConversationMode }}</p>
```
To:
```html
<span class="inline-block bg-muted/60 rounded-full px-2 py-0.5 text-[11px] text-muted-foreground">{{ activeConversationMode }}</span>
```

- [ ] **Step 2: Add `min-h-0` to messages container**

Change line 146 from:
```html
<div ref="messagesContainer" @scroll="onMessagesScroll" class="flex-1 overflow-y-auto custom-scrollbar">
```
To:
```html
<div ref="messagesContainer" @scroll="onMessagesScroll" class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
```

- [ ] **Step 3: Add bottom padding to messages inner container**

Change line 147 from:
```html
<div class="max-w-3xl mx-auto px-6 py-8">
```
To:
```html
<div class="max-w-3xl mx-auto px-6 pt-8 pb-28">
```

(`pb-28` = 7rem bottom padding so the gradient overlay can cover the last messages without hiding content)

- [ ] **Step 4: Replace input area border with gradient overlay**

Replace lines 214-276 (the entire input area `<div class="shrink-0 border-t ...">` through its closing `</div>`) with:

```html
      <!-- Input area -->
      <div class="shrink-0 relative">
        <!-- Gradient overlay: fades messages into input area -->
        <div class="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-muted to-transparent pointer-events-none"></div>
        <div class="relative max-w-3xl mx-auto px-6 pb-4">
          <form @submit.prevent="handleSend">
            <div class="flex flex-col gap-2 p-2 bg-muted border border-border rounded-2xl focus-within:ring-1 focus-within:ring-ring focus-within:border-input transition-all shadow-sm">
              <!-- Textarea -->
              <textarea
                ref="inputRef"
                v-model="inputText"
                :placeholder="inputPlaceholder"
                :disabled="isSending"
                @keydown="onInputKeydown"
                @input="autoResize"
                rows="1"
                class="w-full px-3 py-2 text-sm bg-transparent focus:outline-none disabled:opacity-50 resize-none overflow-hidden"
                style="min-height: 32px; max-height: 120px;"
              ></textarea>

              <!-- Action buttons -->
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-1">
                  <!-- Attachment button -->
                  <button
                    type="button"
                    class="flex items-center justify-center size-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-background transition-colors"
                    title="上传文件"
                  >
                    <Paperclip :size="16" />
                  </button>
                  <!-- Model selector -->
                  <ModelSelector
                    :current-model="selectedModel"
                    @select="handleModelSelect"
                  />
                </div>
                <!-- Send button -->
                <Button
                  v-if="isSending"
                  type="button"
                  @click="handleStop"
                  variant="destructive"
                  size="icon"
                  class="rounded-lg size-8 shrink-0"
                >
                  <Square :size="14" />
                </Button>
                <Button
                  v-else
                  type="submit"
                  :disabled="!inputText.trim()"
                  size="icon"
                  class="rounded-lg size-8 shrink-0"
                >
                  <ArrowUp :size="16" />
                </Button>
              </div>
            </div>
            <div class="mt-2 flex items-center justify-between px-1">
              <span class="text-[11px] text-muted-foreground">按 Enter 发送，Shift+Enter 换行</span>
              <span class="text-[11px] text-muted-foreground">基于题库和 JD 上下文追问</span>
            </div>
          </form>
        </div>
      </div>
```

Key changes from original:
- Outer wrapper: `shrink-0 relative` (was `shrink-0 border-t border-border bg-background`)
- Added gradient overlay div: `absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-muted to-transparent pointer-events-none`
- Inner container: `relative` (z-index above gradient), `pb-4` (was `py-4`)
- Input box: `bg-muted` (was `bg-background`), removed `relative` and `shadow-sm`
- Attachment button hover: `hover:bg-background` (was `hover:bg-muted`) for contrast on muted bg

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/business/ChatView.vue
git commit -m "feat(frontend): ChatGPT-style input area with gradient overlay"
```

---

### Task 5: Build Verification + Deploy

- [ ] **Step 1: Run frontend build**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build
```

Expected: Build succeeds with no errors.

- [ ] **Step 2: Deploy**

```bash
cd /home/ubuntu/sj/interview-boss && ./deploy/docker-deploy.sh update
```

Expected: All containers healthy.

- [ ] **Step 3: Verify in browser**

Check:
1. Chat tab fills right side exactly — no page scroll
2. Messages scroll independently
3. Input box stays at bottom with gradient fade
4. No horizontal line between messages and input
5. No border line below SiteHeader in Chat mode
6. Rename conversation → switch tab → switch back → conversation and messages preserved
7. Other tabs scroll normally
8. Mobile: input box visible, messages scroll
