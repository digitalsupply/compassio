<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

if (auth.isAdmin) router.replace('/admin/notifications')
else if (auth.isTeacher) router.replace('/teacher')
else if (auth.isStudent) router.replace('/student')
else router.replace('/login')
</script>

<template>
  <div class="redirecting">正在跳转…</div>
</template>

<style scoped>
.redirecting {
  text-align: center;
  padding: 40px;
  color: #666;
}
</style>
