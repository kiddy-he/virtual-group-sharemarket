import {createConnection} from 'node:net';
import {lstat,realpath,open} from 'node:fs/promises';
import {resolve,relative,isAbsolute} from 'node:path';

/** Trusted local transport. No auto-retry of writes, no public network listener. */
export async function marketRpc(socketPath, request, {timeoutMs=180000,signal}={}) {
  signal?.throwIfAborted();
  const info=await lstat(socketPath);
  if(!info.isSocket() || (info.mode & 0o777)!==0o600 || info.uid!==process.getuid())
    throw new Error('Expected an owned private Unix socket');
  const payload=Buffer.from(JSON.stringify(request)+'\n');
  if(payload.length>65536) throw new Error('Request exceeds 64 KiB');
  return new Promise((done,fail)=>{
    const connection=createConnection(socketPath);let chunks=[],length=0,settled=false;
    const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);connection.destroy();error?fail(error):done(value);};
    const abort=()=>finish(new Error('Request cancelled; recover the original operation ID'));
    const timer=setTimeout(()=>finish(new Error('Request timed out; recover the original operation ID')),timeoutMs);
    signal?.addEventListener('abort',abort,{once:true});
    if(signal?.aborted){abort();return;}
    connection.on('connect',()=>connection.write(payload));
    connection.on('error',()=>finish(new Error('Market socket unavailable')));
    connection.on('end',()=>{if(!settled)finish(new Error('Incomplete response; recover the original operation ID'));});
    connection.on('data',chunk=>{
      length+=chunk.length;
      if(length>32*1024*1024){finish(new Error('Response exceeds 32 MiB'));return;}
      chunks.push(chunk);
      if(chunk.includes(10)){
        try{const result=JSON.parse(Buffer.concat(chunks).toString('utf8').split('\n',1)[0]);
          if(!result || typeof result!=='object' || Array.isArray(result))throw Error();finish(null,result);
        }catch{finish(new Error('Invalid market response'));}
      }
    });
  });
}

/** Check every returned artifact before handing it to a chat platform. */
export async function marketArtifacts(result,stateDir) {
  const root=await realpath(resolve(stateDir,'artifacts'));
  const files=result.artifacts??(result.artifact?[result.artifact]:[]);
  if(!Array.isArray(files)||files.length>64)throw new Error('Invalid artifact set');
  const checked=[];
  for(const file of files){
    const path=await realpath(file),rel=relative(root,path),info=await lstat(path);
    if(!rel||rel.startsWith('..')||isAbsolute(rel)||!info.isFile()||info.size>25*1024*1024||!path.endsWith('.png'))
      throw new Error('Artifact outside the approved market directory');
    const handle=await open(path,'r');
    try{
      const header=Buffer.alloc(8),read=await handle.read(header,0,8,0);
      if(read.bytesRead!==8||!header.equals(Buffer.from([137,80,78,71,13,10,26,10])))
        throw new Error('Artifact is not a PNG image');
    }finally{await handle.close();}
    checked.push(path);
  }
  return checked;
}
