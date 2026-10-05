import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/HT-AIMC/', // Replace with your EXACT repository name
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  }
})