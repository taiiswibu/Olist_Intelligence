// Adapt preview server flags to the local Python API. No frontend build step.
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import path from 'node:path';
const root=process.cwd(),args=process.argv.slice(2);
const option=(name,fallback)=>{const i=args.indexOf(name);return i>=0?args[i+1]:fallback;};
const host=option('--host','127.0.0.1'),port=option('--port',process.env.PORT||'3000');
const candidates=process.platform==='win32'?[path.join(root,'.venv/Scripts/python.exe')]:[path.join(root,'.venv/bin/python'),path.join(root,'../.venv/bin/python')];
const python=candidates.find(existsSync)||'python3';
const child=spawn(python,['-m','uvicorn','olist.api:app','--host',host,'--port',port],{stdio:'inherit',env:process.env});
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>child.kill(signal));
child.on('exit',code=>process.exit(code??0));
