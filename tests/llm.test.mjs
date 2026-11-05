import test from 'node:test';
import assert from 'node:assert/strict';
import {createJsonModel} from '../sdk/llm.mjs';
const cfg={enabled:true,api:'chat-completions',baseUrl:'https://example.invalid/v1',apiKeyEnv:'EXAMPLE_KEY',model:'example-text-model'};
test('model URL, model name and credential come exclusively from injected configuration',async()=>{
  const request=createJsonModel(cfg,{env:{EXAMPLE_KEY:'placeholder'},fetchImpl:async(url,o)=>{
    assert.equal(url,'https://example.invalid/v1/chat/completions');assert.equal(JSON.parse(o.body).model,cfg.model);assert.equal(o.headers.Authorization,'Bearer placeholder');
    return {ok:true,json:async()=>({choices:[{finish_reason:'stop',message:{content:'{"ok":true}'}}]})};}});
  assert.equal((await request('public events')).model,cfg.model);
});
test('disabled model makes zero requests and incomplete output is rejected',async()=>{
  await assert.rejects(createJsonModel({enabled:false},{fetchImpl:()=>assert.fail('network')})('test'));
  const invoke=createJsonModel(cfg,{env:{EXAMPLE_KEY:'placeholder'},fetchImpl:async()=>({ok:true,json:async()=>({choices:[{finish_reason:'length',message:{content:'{"ok":'}}]})})});
  await assert.rejects(invoke('test'));
});
