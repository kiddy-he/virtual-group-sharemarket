/** Register tools with an injected trusted context and delivery implementation. */
export function registerMarketTools(api,{adapter,getContext,deliver}){
  if(typeof getContext!=='function'||typeof deliver!=='function')throw new Error('Trusted context and delivery are required');
  for(const method of ['query','account','trade','play','admin'])api.registerTool({
    name:'sharemarket_'+method,
    description:'虚拟群股市 '+method+'；只处理当前 /fx 指令。身份与群号由宿主确定，禁止指定他人账户。',
    parameters:{type:'object',properties:{action:{type:'string'},code:{type:'string'},quantity:{type:'integer',minimum:1},price:{type:'number',exclusiveMinimum:0},keyword:{type:'string'},sector:{type:'string'},industry:{type:'string'},order_id:{type:'integer',minimum:1},amount:{type:'number'},reason:{type:'string'},limit:{type:'integer'},prop_id:{type:'string'},name:{type:'string'},question:{type:'string'},event_id:{type:'string'}},required:['action'],additionalProperties:false},
    async execute(callId,params){
      const ctx=await getContext(callId);
      if(typeof ctx?.text!=='string'||!/^\s*\/fx(?=\s|$)/u.test(ctx.text))throw new Error('/fx prefix required');
      const response=await adapter.execute({method,params},ctx);
      if(!response.result.ok)return {content:[{type:'text',text:'操作未完成，请查询原操作状态。'}],details:{ok:false}};
      const receipt=await deliver(response,await adapter.artifacts(response));
      if(!receipt)throw new Error('Delivery not confirmed; do not repeat the transaction');
      await adapter.acknowledge(response,receipt);
      // Never expose private account JSON to a group model or duplicate delivery.
      return {content:[{type:'text',text:'结果已交由宿主按权限投递，请勿重复发送或执行。'}],details:{ok:true,delivered:true}};
    }
  });
}
