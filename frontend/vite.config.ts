import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
  server: {
    // 5173 — порт, который ui/web_window.py открывает как dev-фолбэк, поэтому он
    // остаётся значением по умолчанию. Но strictPort с жёстким числом означал, что
    // при занятом порте `npm run dev` просто падает; PORT позволяет запустить второй
    // экземпляр или обойти конфликт, не трогая конфиг.
    port: Number(process.env.PORT) || 5173,
    strictPort: !process.env.PORT,
  },
})
