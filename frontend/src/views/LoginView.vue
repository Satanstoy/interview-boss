<template>
  <LoginPage @login-success="onLoginSuccess" />
</template>

<script setup>
import { inject } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import LoginPage from '@/components/business/LoginPage.vue'

const router = useRouter()
const route = useRoute()
const { handleLoginSuccess: layoutHandleLoginSuccess } = inject('appData')

const onLoginSuccess = (user) => {
  layoutHandleLoginSuccess(user)
  const redirect = route.query.redirect || '/master-bank'
  router.push(redirect)
}
</script>
