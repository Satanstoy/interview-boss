import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  build: {
    rollupOptions: {
      output: {
        // vite 8 (rolldown) 仅支持函数形式；对象形式已移除
        manualChunks(id) {
          if (/[\\/]node_modules[\\/](echarts|zrender)[\\/]/.test(id)) {
            return 'vendor-echarts'
          }
          if (/[\\/]node_modules[\\/](vue|@vue|@vueuse)[\\/]/.test(id)) {
            return 'vendor-vue'
          }
          return undefined
        }
      }
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    headers: {
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'Referrer-Policy': 'strict-origin-when-cross-origin',
      'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    }
  }
})
