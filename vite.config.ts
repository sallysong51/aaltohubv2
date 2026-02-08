import { jsxLocPlugin } from "@builder.io/vite-plugin-jsx-loc";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss(), jsxLocPlugin()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "client", "src"),
      "@shared": path.resolve(import.meta.dirname, "shared"),
      "@assets": path.resolve(import.meta.dirname, "attached_assets"),
    },
  },
  envDir: path.resolve(import.meta.dirname, "client"),
  root: path.resolve(import.meta.dirname, "client"),
  build: {
    outDir: path.resolve(import.meta.dirname, "dist"),
    emptyOutDir: true,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
          router: ["wouter"],
          ui: ["sonner"],
          icons: ["lucide-react"],
        },
      },
    },
  },
  server: {
    port: 3000,
    strictPort: false,
    host: true,
    allowedHosts: [
      "localhost",
      "127.0.0.1",
    ],
    proxy: {
      // Note: This handler only fires for connection-level errors (ECONNREFUSED, ETIMEDOUT).
      // HTTP-level errors (500, 503) from the backend are proxied through to the client.
      // The client handles those via api.ts getApiErrorMessage().
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("error", (_err, _req, res) => {
            if ("writeHead" in res && typeof res.writeHead === "function") {
              res.writeHead(502, { "Content-Type": "application/json" });
              res.end(
                JSON.stringify({
                  detail:
                    "Backend server is not running. Start it with: pnpm run dev:backend",
                }),
              );
            }
          });
        },
      },
    },
    fs: {
      strict: true,
      deny: ["**/.*"],
    },
    middlewareMode: false,
    middleware: (req, res, next) => {
      // Set CSP headers with frame-ancestors (HTTP header only)
      res.setHeader(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' https: data:; connect-src 'self' http://localhost:8000 https://*.supabase.co wss://*.supabase.co https://fonts.googleapis.com https://*.sentry.io; frame-ancestors 'none';"
      );
      next();
    },
  },
});
