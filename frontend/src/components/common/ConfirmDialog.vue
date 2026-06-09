<template>
  <AlertDialog :open="confirmState.show" @update:open="handleCancel">
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>{{ confirmState.title }}</AlertDialogTitle>
        <AlertDialogDescription class="whitespace-pre-line">
          {{ confirmState.message }}
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel @click="handleCancel">
          {{ confirmState.cancelLabel || '取消' }}
        </AlertDialogCancel>
        <AlertDialogAction :class="confirmBtnClass" @click="handleConfirm">
          {{ confirmState.confirmLabel || '确定' }}
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>

<script setup>
import { computed } from 'vue'
import { useConfirm } from '@/composables/useNotification.js'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

const { confirmState, handleConfirm, handleCancel } = useConfirm()

const variant = computed(() => confirmState.value.variant || 'warning')

const confirmBtnClass = computed(() => ({
  danger: 'bg-destructive text-white hover:bg-destructive/90',
  warning: '',
  info: 'bg-blue-600 text-white hover:bg-blue-700',
}[variant.value]))
</script>
