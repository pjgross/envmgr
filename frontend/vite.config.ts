import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// BACKEND_PORT can be overridden for E2E tests (default: 8000 for dev)
const backendPort = process.env.BACKEND_PORT || '8000';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Split the framework out of the entry chunk so it stays cached across
        // deploys: application code changes every release, React and MUI don't.
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom', 'react-redux', '@reduxjs/toolkit'],
          'vendor-mui': ['@mui/material', '@mui/icons-material', '@emotion/react', '@emotion/styled'],
        },
      },
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
});
