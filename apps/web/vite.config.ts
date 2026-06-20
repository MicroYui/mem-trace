import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

const proxyTarget = process.env.MEMTRACE_DEV_API_PROXY_TARGET ?? "http://localhost:8000";
const cacheDir = process.env.MEMTRACE_WEB_VITE_CACHE_DIR ?? resolve(tmpdir(), "memtrace-vite-cache", "apps-web");

export default defineConfig({
  cacheDir,
  plugins: [react()],
  server: {
    proxy: {
      "/v1": {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
});
