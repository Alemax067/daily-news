import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    server: {
        port: 4321,
        strictPort: true,
        proxy: {
            "/api": {
                target: "http://localhost:8765",
                changeOrigin: true,
                rewrite: function (p) { return p.replace(/^\/api/, ""); },
            },
        },
    },
});
