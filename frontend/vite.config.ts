import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // In development, the FastAPI backend runs on :8000 (uvicorn app:app). In production
  // the same FastAPI process serves this build, so /api is same-origin.
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
