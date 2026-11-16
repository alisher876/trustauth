import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Inside Docker the backend is reachable as http://backend:8000; outside Docker, on localhost.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // listen on all interfaces so the container port can be reached
    port: 5173,
    // The browser calls /api/...; Vite forwards it to the backend. Same origin, so no CORS setup needed.
    proxy: {
      "/api": {
        target: backendUrl,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
    // File-change events do not reach containers from a Windows folder, so check for changes by polling.
    watch: { usePolling: true },
  },
});
