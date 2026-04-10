import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => ({
    plugins: [react()],
    base: mode === 'production' ? '/admin/' : '/',
    server: {
        port: 5173,
        proxy: {
            '/api': 'http://localhost:8002',
        },
    },
}))
