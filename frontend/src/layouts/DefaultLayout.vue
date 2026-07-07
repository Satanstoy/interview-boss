<script setup>
// DefaultLayout is a simple wrapper — the actual two-column layout
// is now handled directly in App.vue with <aside> + <main>.
</script>

<template>
  <div class="flex min-h-screen">
    <slot name="sidebar" />
    <main class="flex-1 min-w-0 flex flex-col">
      <slot name="header" />
      <div class="flex-1 overflow-auto">
        <slot />
      </div>
    </main>
  </div>
</template>
