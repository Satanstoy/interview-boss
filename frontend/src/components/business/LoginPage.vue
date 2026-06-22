<template>
  <div data-testid="login-page" class="relative h-dvh overflow-hidden bg-background">
    <a
      data-testid="login-brand"
      href="/login"
      class="absolute left-4 top-4 inline-flex items-center gap-2 text-foreground sm:left-6 sm:top-6"
    >
      <img src="/favicon-b.png" alt="InterviewBoss" class="h-8 w-8 object-contain" />
      <span class="text-base font-semibold tracking-tight">InterviewBoss</span>
    </a>

    <main class="mx-auto flex h-full min-h-0 w-full max-w-5xl flex-col items-center justify-center px-4 py-4 sm:px-6">
      <section data-testid="login-panel" class="flex w-full max-w-[400px] flex-col items-center">
        <div class="w-full rounded-xl border border-border bg-card p-5 shadow-sm sm:p-6">
          <div class="mb-5 text-center">
            <h2 class="text-lg font-semibold tracking-tight text-foreground">欢迎回来</h2>
          </div>
          <LoginModal embedded hide-header @login-success="$emit('login-success', $event)" />
        </div>

        <a
          href="/master-bank?preview=1"
          class="mt-3 inline-flex h-10 w-full items-center justify-center rounded-md border border-border bg-background text-sm font-medium text-foreground shadow-sm transition hover:bg-muted"
        >
          免登录体验
        </a>
      </section>
    </main>
  </div>
</template>

<script setup>
import LoginModal from '@/components/business/LoginModal.vue'

defineEmits(['login-success'])
</script>
