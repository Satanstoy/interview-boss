# ChatView Layout Overhaul — Design Spec

Date: 2026-06-11

## Problem Statement

1. Chat tab 页面可以超出视口高度，导致浏览器页面滚动
2. 输入区与消息区用 `border-t` 硬分割，不符合 ChatGPT 风格
3. SiteHeader 的 `border-b` 在 Chat 模式下形成不协调的标题区横线
4. `v-if` 导致切 tab 时 ChatView 销毁，会话状态（activeConversationId、messages）丢失
5. 重命名后 `loadConversations()` 不保留 activeConversationId

## Approach

Four targeted changes across 4 files. No API changes, no SSE rewrite.

### 1. Height Chain Fix (`App.vue`)

- Change outer wrapper from `flex min-h-screen` to `flex h-screen overflow-hidden`
- `<aside>` remains `sticky top-0` (works inside h-screen parent)
- `<main>` gets `overflow-hidden` to prevent content overflow
- ChatView receives `flex-1 min-h-0` (unchanged)

### 2. State Preservation (`App.vue` + `ChatView.vue`)

- Wrap `<ChatView>` in `<KeepAlive>` to preserve component state across tab switches
- ChatView `onMounted`: load conversations, restore activeConversationId from localStorage
- ChatView `onActivated`: refresh conversation list via `loadConversations()`, preserve current selection
- ChatView `watch(activeConversationId)`: persist to localStorage
- `loadConversations()`: preserve activeConversationId after refresh (only clear if conversation no longer exists)

### 3. Header Cleanup (`SiteHeader.vue` + `ChatView.vue`)

- SiteHeader: add `noBorder` prop, conditionally remove `border-b border-border`
- App.vue: pass `:no-border="activeTab === 'Chat'"` to SiteHeader
- ChatView mode label: change from bordered text to `bg-muted/60 rounded-full px-2 py-0.5`

### 4. Input Area GPT-ification (`ChatView.vue`)

- Remove `border-t border-border` from input wrapper
- Add gradient overlay: `absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-muted to-transparent pointer-events-none`
- Input container: `bg-muted rounded-2xl shadow-sm border border-border focus-within:ring-1 focus-within:ring-ring focus-within:border-input`
- Messages area: add `min-h-0` to `flex-1 overflow-y-auto custom-scrollbar`
- Add bottom padding (`pb-4`) to messages container for gradient breathing room

## Files to Modify

| File | Changes |
|------|---------|
| `frontend/src/App.vue` | Height chain: `h-screen overflow-hidden`; `<KeepAlive>` for ChatView; `noBorder` prop to SiteHeader |
| `frontend/src/components/business/ChatView.vue` | Input area redesign; mode label; localStorage save/restore; `onActivated`; `loadConversations` preserve active id |
| `frontend/src/components/SiteHeader.vue` | Add `noBorder` prop |

## Acceptance Criteria

- Chat tab fills right-side area exactly, no page scroll
- Messages scroll independently within their container
- Input box stays fixed at bottom
- No horizontal line between messages and input (gradient overlay instead)
- No border line below SiteHeader in Chat mode
- Rename conversation, switch tab, switch back — conversation and messages preserved
- Other tabs scroll behavior unchanged
- `npm run build` passes
