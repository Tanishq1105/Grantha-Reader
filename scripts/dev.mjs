// One local command: Node runs Vite and starts the Flask API.
import {createServer} from 'vite';
import {spawn} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
process.chdir(root);
try {process.loadEnvFile('.env');} catch(e) {if(e.code!=='ENOENT')throw e;}
const python=process.env.PYTHON || (process.platform==='win32'?'python':'python3');
const server=await createServer({configFile:path.join(root,'vite.config.js')});
const backend=spawn(python,['-u','-m','backend.app'],{cwd:root,stdio:'inherit',env:process.env});
const shutdown=new AbortController();
let closing=false;
async function stop(code=0){if(closing)return;closing=true;shutdown.abort();backend.kill();await server.close();process.exitCode=code;}
backend.on('error',async e=>{console.error('Activate your Python virtual environment or set PYTHON:',e.message);await stop(1);});
backend.on('exit',async code=>{if(!closing){console.error('Flask exited. Check Python dependencies and the API port.');await stop(code || 1);}});
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>stop());

async function waitForBackend(){
  const url=`http://127.0.0.1:${Number(process.env.FLASK_PORT || 5000)}/api/health`;
  const deadline=Date.now()+120_000;
  console.log('Starting Flask and loading the book index. Waiting for the API...');
  while(!closing && Date.now()<deadline){
    try {
      const response=await fetch(url,{signal:AbortSignal.any([shutdown.signal,AbortSignal.timeout(1500)])});
      if(response.ok){
        const health=await response.json();
        if(health.status==='ok' && health.source_type==='uploaded_pdf')return !closing;
      }
    } catch {
      // Connection refusals are expected while Flask imports the book index.
    }
    if(closing)return false;
    try {await delay(250,undefined,{signal:shutdown.signal});}
    catch(e){if(closing)return false;throw e;}
  }
  if(closing)return false;
  throw new Error(`Flask did not become ready within 120 seconds. Check its output above and open ${url}.`);
}

try {
  if(await waitForBackend()){
    await server.listen();
    if(!closing){console.log('Book API ready. Open the reader:');server.printUrls();}
  }
} catch(e){if(!closing){console.error(e.message);await stop(1);}}
