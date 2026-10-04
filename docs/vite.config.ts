import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/AnalogIOC/', // Replace with your EXACT repository name
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  }
})