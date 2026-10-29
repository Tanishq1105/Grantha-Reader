import {defineConfig, loadEnv} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('.',import.meta.url));

export default defineConfig(({mode})=>{
  // Never prefix API secrets with VITE_: those variables are exposed to clients.
  const env={...loadEnv(mode,root,''),...process.env};
  return {
    root:'frontend', envDir:root, plugins:[react()],
    server:{host:'127.0.0.1',port:Number(env.VITE_PORT || 3000),strictPort:true,proxy:{'/api':`http://127.0.0.1:${Number(env.FLASK_PORT || 5000)}`}},
    build:{outDir:'../dist',emptyOutDir:true},
    test:{environment:'jsdom',include:['../tests/**/*.test.jsx'],setupFiles:['../tests/react.setup.js'],restoreMocks:true},
  };
});
