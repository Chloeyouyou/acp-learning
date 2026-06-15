import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,            // 监听 0.0.0.0，局域网/隧道可达
    allowedHosts: true,    // 允许 *.trycloudflare.com 等外部 Host（隧道访问必须）
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
