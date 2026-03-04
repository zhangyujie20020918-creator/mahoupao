import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // 设置代理超时时间为2小时（SSE流式下载可能需要很长时间）
        timeout: 7200000,
        // 配置WebSocket/SSE相关
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            // 对于SSE请求，设置更长的超时
            proxyReq.setSocketKeepAlive(true)
          })
        },
      },
    },
  },
})
