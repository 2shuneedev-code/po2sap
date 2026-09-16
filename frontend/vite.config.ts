import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// /api 는 백엔드로 넘긴다 — 프론트에 절대주소를 박지 않는다.
// 사내 이관 시 VITE_API_TARGET 만 바꾸면 된다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
