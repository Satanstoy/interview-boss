<template>
  <div class="min-h-[calc(100vh-56px)] bg-background">
    <div class="mx-auto grid min-h-[calc(100vh-56px)] max-w-6xl gap-8 px-4 py-8 lg:grid-cols-[minmax(0,1fr)_420px] lg:items-center lg:px-8">
      <!-- Left side: marketing content -->
      <section class="hidden lg:block">
        <div class="max-w-xl">
          <div class="mb-6 inline-flex items-center rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-muted-foreground shadow-sm">
            shadcn-vue workspace preview
          </div>
          <h2 class="text-3xl font-semibold tracking-tight text-foreground">
            把面试准备变成一个清晰的学习工作台
          </h2>
          <p class="mt-3 max-w-lg text-sm leading-6 text-muted-foreground">
            InterviewBoss 会把 JD、面经和高频题组织成可筛选、可练习、可复盘的数据界面。新版视觉更接近 shadcn-vue 的 dashboard、table、charts 和 AI chat 组件。
          </p>

          <!-- Stats cards -->
          <div class="mt-8 grid gap-3 md:grid-cols-3">
            <div class="rounded-xl border border-border bg-card p-4 shadow-sm">
              <p class="text-xs font-medium text-muted-foreground">题库规模</p>
              <p class="mt-3 text-2xl font-semibold tracking-tight text-foreground">1,248</p>
              <div class="mt-4 h-2 rounded-full bg-muted">
                <div class="h-2 w-[72%] rounded-full bg-primary"></div>
              </div>
            </div>
            <div class="rounded-xl border border-border bg-card p-4 shadow-sm">
              <p class="text-xs font-medium text-muted-foreground">本周练习</p>
              <p class="mt-3 text-2xl font-semibold tracking-tight text-foreground">42</p>
              <svg viewBox="0 0 160 46" class="mt-3 h-12 w-full text-chart-3">
                <path d="M0 38 C20 30 28 16 48 21 C72 27 69 7 92 13 C116 19 118 35 138 24 C150 18 154 12 160 10" fill="none" stroke="currentColor" stroke-width="2.5" />
              </svg>
            </div>
            <div class="rounded-xl border border-border bg-card p-4 shadow-sm">
              <p class="text-xs font-medium text-muted-foreground">模拟面试</p>
              <p class="mt-3 text-2xl font-semibold tracking-tight text-foreground">82</p>
              <div class="mt-4 grid grid-cols-3 gap-1.5 text-center text-[10px] text-muted-foreground">
                <span class="rounded-md bg-muted py-1">表达</span>
                <span class="rounded-md bg-muted py-1">结构</span>
                <span class="rounded-md bg-muted py-1">深度</span>
              </div>
            </div>
          </div>

          <!-- AI Copilot preview -->
          <div class="mt-4 rounded-xl border border-border bg-card shadow-sm">
            <div class="flex items-center justify-between border-b border-border/50 px-4 py-3">
              <div>
                <p class="text-sm font-semibold text-foreground">AI Interview Copilot</p>
                <p class="text-xs text-muted-foreground">检索题库、评估回答、生成追问</p>
              </div>
              <span class="rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary">Live</span>
            </div>
            <div class="space-y-3 p-4">
              <div class="max-w-[78%] rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground">
                先介绍最近一个项目，以及你承担的核心职责。
              </div>
              <div class="ml-auto max-w-[78%] rounded-xl bg-primary px-3 py-2 text-sm text-primary-foreground">
                我负责题库导入解析、AI 生成答案和模拟面试链路...
              </div>
              <div class="rounded-lg border border-border bg-card p-3 text-xs">
                <div class="flex items-center justify-between">
                  <span class="font-medium text-foreground">AI Thinking</span>
                  <span class="text-muted-foreground">3 sources</span>
                </div>
                <div class="mt-2 space-y-1.5 text-muted-foreground">
                  <p>检索项目复盘题目：完成</p>
                  <p>分析回答结构：完成</p>
                  <p>生成追问：进行中</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Right side: login form -->
      <section class="mx-auto w-full max-w-sm lg:mx-0">
        <div class="mb-6 text-center lg:text-left">
          <div class="mx-auto mb-4 grid h-11 w-11 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground lg:mx-0">
            IB
          </div>
          <h1 class="text-xl font-semibold tracking-tight text-foreground">登录 InterviewBoss</h1>
          <p class="mt-1 text-sm text-muted-foreground">访问你的题库、面经和模拟面试记录</p>
        </div>

        <!-- Login form card -->
        <div class="rounded-xl border border-border bg-card p-6 shadow-sm">
          <LoginModal embedded @login-success="$emit('login-success', $event)" />
        </div>

        <!-- Preview link -->
        <a
          href="?preview=1"
          class="mt-3 inline-flex h-10 w-full items-center justify-center rounded-md border border-border bg-card text-sm font-medium text-foreground shadow-sm transition hover:bg-muted"
        >
          预览新版工作台
        </a>
      </section>
    </div>
  </div>
</template>

<script setup>
import LoginModal from '@/components/business/LoginModal.vue'

defineEmits(['login-success'])
</script>
