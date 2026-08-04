<!-- frontend/src/App.vue — thin router shell -->
<script setup>
import { Toaster } from 'vue-sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
</script>

<template>
  <TooltipProvider :delay-duration="120" :skip-delay-duration="80">
    <router-view v-slot="{ Component }">
      <Transition name="app-route" mode="out-in">
        <component :is="Component" />
      </Transition>
    </router-view>
    <Toaster position="top-right" richColors closeButton />
  </TooltipProvider>
</template>
