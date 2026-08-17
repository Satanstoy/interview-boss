<script setup>
import { useRouter } from 'vue-router'
import AppPageHeader from '@/components/common/AppPageHeader.vue'
import EvaluationFlowNav from './EvaluationFlowNav.vue'

defineProps({
  title: { type: String, required: true },
  description: { type: String, required: true },
  activeKey: { type: String, default: '' },
  showFlow: { type: Boolean, default: true },
})

const router = useRouter()

function navigate(crumb) {
  if (crumb.to) router.push(crumb.to)
}
</script>

<template>
  <div class="space-y-5">
    <AppPageHeader
      :title="title"
      :description="description"
      :breadcrumbs="[{ label: '评测中心', to: '/admin/evals/overview' }, { label: title }]"
      @navigate="navigate"
    >
      <template v-if="$slots.actions" #actions>
        <slot name="actions" />
      </template>
    </AppPageHeader>
    <EvaluationFlowNav v-if="showFlow" :active-key="activeKey" />
  </div>
</template>
