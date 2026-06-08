import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // Never ship sourcemaps to production — they expose original source,
    // module structure, and comments. (Vite's default is already false;
    // this makes the intent explicit and pins it against future changes.)
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Group heavy third-party libs into their own chunks so:
        //  - Pages that don't use them don't pay for them on first paint.
        //  - When a chart-bearing page lazy-loads, it pulls in the
        //    already-cached recharts chunk rather than re-downloading
        //    chart code each route.
        // Keep the chunk list small — manualChunks too granular hurts
        // (each chunk adds an HTTP request + a few KB of overhead).
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('node_modules/recharts')) return 'recharts'
          if (id.includes('node_modules/d3-')) return 'recharts'
          if (id.includes('node_modules/internmap')) return 'recharts'
          if (id.includes('node_modules/victory-vendor')) return 'recharts'
          if (id.includes('node_modules/react-icons')) return 'icons'
          // lucide-react stays in the main bundle: it's already
          // tree-shaken per-icon import so it ships only the ~87 icons
          // we actually use, and routing those through a separate chunk
          // would add request overhead without size savings.
          return undefined
        },
      },
    },
  },
  define: {
    'import.meta.env.VITE_APP_NAME': '"Eidolum"',
  },
})
