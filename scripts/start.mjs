// Convenience launcher. Production Docker uses Gunicorn directly.
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
process.chdir(root);
try{process.loadEnvFile('.env');}catch(e){if(e.code!=='ENOENT')throw e;}
const python=process.env.PYTHON||(process.platform==='win32'?'python':'python3');
const proc=spawn(python,['-m','backend.app'],{cwd:root,stdio:'inherit',env:process.env});
proc.on('error',e=>{console.error(e.message);process.exitCode=1;});
proc.on('exit',code=>{process.exitCode=code||0;});
for(const s of ['SIGINT','SIGTERM'])process.on(s,()=>proc.kill(s));
