<template>
  <AlertDialog :open="dialogState.show" @update:open="handleDialogClose">
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle class="flex items-center gap-2">
          <AlertTriangle class="size-4 text-amber-500 shrink-0" />
          {{ dialogState.title }}
        </AlertDialogTitle>
        <AlertDialogDescription class="whitespace-pre-line">
          {{ dialogState.message }}
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel @click="handleDialogClose">取消</AlertDialogCancel>
        <Button @click="handleGoSettings">
          <Settings2 class="size-4" />
          去配置
        </Button>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>

<script setup>
import { AlertTriangle, Settings2 } from '@lucide/vue'
import { useModelGuard } from '@/composables/useModelGuard.js'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

const {
  dialogState,
  handleDialogClose,
  handleGoSettings,
} = useModelGuard()
</script>
