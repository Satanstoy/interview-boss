<template>
  <div data-testid="login-page" class="h-dvh overflow-hidden bg-background">
    <main class="mx-auto flex h-full min-h-0 w-full max-w-5xl flex-col items-center justify-center px-4 py-4 sm:px-6">
      <section data-testid="login-panel" class="flex w-full max-w-[400px] flex-col items-center">
        <div class="mb-5 flex flex-col items-center text-center">
          <img src="/favicon-b.png" alt="InterviewBoss" class="h-12 w-12 object-contain" />
          <h1 class="mt-3 text-2xl font-semibold tracking-tight text-foreground">InterviewBoss</h1>
          <p class="mt-1 text-sm text-muted-foreground">JD / 面经 / 模拟面试，一处管理</p>
        </div>

        <div class="w-full rounded-xl border border-border bg-card p-5 shadow-sm sm:p-6">
          <div class="mb-5 text-center">
            <h2 class="text-lg font-semibold tracking-tight text-foreground">登录你的面试工作台</h2>
            <p class="mt-1 text-sm text-muted-foreground">继续查看题库、面经和模拟面试记录</p>
          </div>
          <LoginModal embedded hide-header @login-success="$emit('login-success', $event)" />
        </div>

        <a
          href="/master-bank?preview=1"
          class="mt-3 inline-flex h-10 w-full items-center justify-center rounded-md border border-border bg-background text-sm font-medium text-foreground shadow-sm transition hover:bg-muted"
        >
          无需登录，先体验工作台
        </a>

        <div class="mt-4 grid w-full grid-cols-3 gap-2 text-center text-[11px] text-muted-foreground">
          <span class="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">高频题库</span>
          <span class="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">模拟面试</span>
          <span class="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">复盘进度</span>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
import LoginModal from '@/components/business/LoginModal.vue'

defineEmits(['login-success'])
</script>
