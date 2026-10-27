import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    css: false,
  },
  server: {
    proxy: {
      "/api": {
        target: process.env.SEARCHING_API || "http://127.0.0.1:5000",
        changeOrigin: true,
      }
    }
  }
});
