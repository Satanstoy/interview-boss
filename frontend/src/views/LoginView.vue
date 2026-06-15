<template>
  <LoginPage @login-success="onLoginSuccess" />
</template>

<script setup>
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth.js'
import LoginPage from '@/components/business/LoginPage.vue'

const router = useRouter()
const route = useRoute()
const { handleLoginSuccess } = useAuth()

const onLoginSuccess = (user) => {
  handleLoginSuccess(user)
  const redirect = route.query.redirect || '/master-bank'
  router.push(redirect)
}
</script>
