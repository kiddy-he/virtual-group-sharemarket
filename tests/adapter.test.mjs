import test from 'node:test';
import assert from 'node:assert/strict';
import {createMarketAdapter,exactPlan,parseMarketCommand,validatePlan} from '../sdk/adapter.mjs';
import {registerMarketTools} from '../sdk/tools.mjs';
const config={enabled:true,privateQueries:true,privateMarket:'a',adminIds:['700000001'],groups:{'700000101':'a','700000102':'b'},markets:{a:{enabled:true,stateDir:'state/a'},b:{enabled:true,stateDir:'state/b'}}};
const ctx={senderId:'700000002',accountId:'bot',scope:'group',groupId:'700000101',messageId:'m1',text:'/fx 开户'};
test('prefix and incomplete trades cannot accidentally mutate a market',()=>{
  for(const value of ['聊聊/fx','/fxfoo','买入 600003 100','引用 /fx 开户'])assert.equal(parseMarketCommand(value),null);
  assert.equal(exactPlan('买一点'),null);assert.equal(exactPlan('买入 600003 100股').params.quantity,100);
  assert.throws(()=>validatePlan({method:'trade',params:{action:'buy',senderId:'700000001'}}));
});
test('groups route independently, actor ignores untrusted identity and receipt uses same operation',async()=>{
  const calls=[];const a=createMarketAdapter(config,{rpc:async(socket,r)=>{calls.push({socket,r});return {ok:true,text:'开户完成'};}});
  const x=await a.handle({...ctx,identity:'admin'});await a.handle({...ctx,groupId:'700000102'});
  assert.notEqual(calls[0].socket,calls[1].socket);assert.equal(calls[0].r.actor.identity,'guest');
  const replay=await a.handle(ctx);assert.equal(x.operationId,replay.operationId);
  await a.acknowledge(x,{message_id:'example-receipt'});assert.equal(calls.at(-1).r.id,x.operationId);
});
test('authorization happens before semantic classification and admin requires private context',async()=>{
  let calls=0;const a=createMarketAdapter(config,{resolveIntent:()=>{calls++;},rpc:async()=>({ok:true})});
  await assert.rejects(a.handle({...ctx,groupId:'700000103',text:'/fx 随便看看'}));assert.equal(calls,0);
  await assert.rejects(a.execute({method:'admin',params:{action:'pause'}},ctx));
  await assert.rejects(a.execute({method:'admin',params:{action:'pause'}},{...ctx,senderId:'700000001'}));
});
test('personal account data receives a DM destination',async()=>{
  const a=createMarketAdapter(config,{rpc:async()=>({ok:true,private:true,text:'持仓'})});
  const d=await a.handle({...ctx,text:'/fx 持仓'});assert.deepEqual(d.destination,{scope:'private',id:ctx.senderId});
});
test('registered tools never return personal JSON into the group model',async()=>{
  const tools=[];const a=createMarketAdapter(config,{rpc:async()=>({ok:true,private:true,text:'private',data:{cash:123}})});
  registerMarketTools({registerTool:t=>tools.push(t)},{adapter:a,getContext:async()=>({...ctx,text:'/fx 持仓'}),deliver:async d=>{assert.equal(d.destination.scope,'private');return {message_id:'receipt'};}});
  const result=await tools.find(t=>t.name==='sharemarket_account').execute('call',{action:'portfolio'});
  assert.ok(!JSON.stringify(result).includes('123'));assert.equal(result.details.delivered,true);
});
