# Chat Frontend UX 优化报告

**日期:** 2026-05-22

## 研究来源

搜索了 15+ 个开源 chatbot 前端项目，包括：
- kernelift-labs/ai-chat (Vue 3 + TypeScript)
- nuxt-ui-templates/chat-vue (Nuxt UI)
- CommentOut64/simple-ai-chat (Vue 3 + 解耦架构)
- keepingFE/VantChatUI (Vue 3 + 移动端)
- opentiny/tiny-robot (Vue 3 企业级)
- assistant-ui/assistant-ui (React，最流行)
- ZenMux/zenmux-chat (React + 插件架构)
- chatgpt-vue3-light-mvp (Vue 3 MVP)

## 提炼的最佳实践

| 特性 | 实现方式 | 来源项目 |
|------|---------|---------|
| 打字指示器 | 三点跳动动画 + "正在思考..." 文字 | VantChatUI, tiny-robot, streaming-ui-primitives |
| 代码高亮 | highlight.js 核心 + 按需加载语言 | simple-ai-chat, chatgpt-vue3-light-mvp |
| 消息复制 | hover 显示复制按钮，点击反馈 | assistant-ui, zenmux-chat |
| 停止生成 | 红色方形按钮，保留已生成内容 | GhazelleChat, zenmux-chat |
| 输入框 | textarea 自适应高度，Enter 发送/Shift+Enter 换行 | ai-chat, simple-ai-chat |
| 智能滚动 | 用户上滚时暂停自动滚动 | ai-chat (useAutoScroll) |
| 暗色代码块 | github-dark 主题 + 圆角 | chatgpt-vue3-light-mvp |

## 实现的改进

### 1. 打字指示器 (ChatView.vue)
- AI 正在思考时显示三点跳动动画 + "正在思考..."
- 第一个 chunk 到达后自动切换为流式内容
- 参考: VantChatUI 的 `Typing` 组件

### 2. 代码语法高亮 (ChatMessage.vue)
- highlight.js 核心 + 按需注册 14 种常用语言
- github-dark 暗色主题
- 包大小: 963KB → 89KB (tree-shaking)
- 支持: JavaScript, Python, Java, SQL, Bash, JSON, CSS, HTML, TypeScript

### 3. 消息复制按钮 (ChatMessage.vue)
- hover AI 消息时显示复制按钮
- 点击后显示绿色勾号反馈 (2秒)
- 参考: assistant-ui 的 message actions

### 4. 停止生成按钮 (ChatView.vue)
- 流式输出时显示红色方形停止按钮
- 保留已生成内容 + "[已停止生成]" 标记
- 使用 `cancelAllRequests()` 取消 SSE 连接
- 参考: GhazelleChat, zenmux-chat

### 5. 输入框升级 (ChatView.vue)
- `<input>` → `<textarea>` 自适应高度 (42px-160px)
- Enter 发送，Shift+Enter 换行
- 底部提示文字
- 参考: ai-chat 的智能输入

### 6. 智能自动滚动 (ChatView.vue)
- 用户上滚 >100px 时暂停自动滚动
- 切换对话时重置为自动滚动
- 参考: ai-chat 的 useAutoScroll

## 构建结果

```
ChatView: 89KB JS + 3KB CSS (gzip: 30KB + 1KB)
highlight.js: 14 种语言，tree-shaken
构建时间: 16s
```
