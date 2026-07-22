import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite 配置：开发代理将 /api 转发到后端 FastAPI（8000 端口）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/v1/ws": { // 开发环境下代理版本化后的 WebSocket 路径，避免前端一直重连
        target: "ws://127.0.0.1:8000", // WebSocket 后端目标地址
        ws: true, // 开启 WebSocket 代理支持
        changeOrigin: true, // 修改来源头以匹配后端服务
      },
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
        changeOrigin: true,
      },
      "/metrics": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          "vendor-motion": ["framer-motion"],
          "vendor-syntax": ["react-syntax-highlighter"],
        },
      },
    },
  },
});
