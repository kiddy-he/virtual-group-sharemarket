import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:net';
import {mkdtemp,chmod,mkdir,writeFile,symlink,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {marketRpc,marketArtifacts} from '../sdk/rpc.mjs';

test('RPC only uses an owned 0600 socket and handles partial JSON frames',async()=>{
  const dir=await mkdtemp(join(tmpdir(),'vm-rpc-')),path=join(dir,'rpc.sock');
  const server=createServer(c=>c.once('data',()=>{c.write('{"ok":');setImmediate(()=>c.end('true}\n'));}));
  try{
    await new Promise((ok,fail)=>{server.once('error',fail);server.listen(path,ok);});
    await chmod(path,0o600);assert.deepEqual(await marketRpc(path,{method:'health'}),{ok:true});
    await chmod(path,0o666);await assert.rejects(marketRpc(path,{method:'health'}),/private Unix socket/);
    await chmod(path,0o600);const alias=join(dir,'alias');await symlink(path,alias);await assert.rejects(marketRpc(alias,{method:'health'}));
    await assert.rejects(marketRpc(path,{content:'x'.repeat(66000)}),/64 KiB/);
  }finally{await new Promise(ok=>server.close(ok));await rm(dir,{recursive:true,force:true});}
});

test('all artifact pages must stay inside the exact market directory',async()=>{
  const dir=await mkdtemp(join(tmpdir(),'vm-images-'));
  try{
    await mkdir(join(dir,'artifacts'));const p=join(dir,'artifacts','1.png'),q=join(dir,'artifacts','2.png');
    const png=Buffer.from([137,80,78,71,13,10,26,10]);await writeFile(p,png);await writeFile(q,png);
    assert.deepEqual(await marketArtifacts({artifacts:[p,q]},dir),[p,q]);
    const outside=join(dir,'outside.png');await writeFile(outside,'private-test-fixture');
    await assert.rejects(marketArtifacts({artifacts:[p,outside]},dir));
    const alias=join(dir,'artifacts','link.png');await symlink(outside,alias);await assert.rejects(marketArtifacts({artifact:alias},dir));
    await assert.rejects(marketArtifacts({artifacts:Array(65).fill(p)},dir));
    await writeFile(q,'not-png');await assert.rejects(marketArtifacts({artifact:q},dir),/not a PNG/);
  }finally{await rm(dir,{recursive:true,force:true});}
});
