import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {marketRpc,marketArtifacts} from './rpc.mjs';

export function parseMarketCommand(text) {
  if(typeof text!=='string'||!/^\/fx(?=\s|$)/u.test(text.trim()))return null;
  const body=text.trim().slice(3).trim();return {body,help:!body||['帮助','help','?','？'].includes(body)};
}
const numeric=value=>typeof value==='string'&&/^\d{5,20}$/u.test(value);
const operationId=ctx=>'chat:'+createHash('sha256').update(JSON.stringify([ctx.accountId,ctx.scope,ctx.groupId??null,ctx.senderId,ctx.messageId])).digest('hex');
const ACTIONS={query:new Set(['help','overview','analyze','search','stock','book','chart','rank','history','news','calendar','event','sector']),account:new Set(['open','rebirth','funds','portfolio','orders','trades','watchlist','watch_add','watch_remove']),trade:new Set(['buy','sell','cancel']),play:new Set(['checkin','achievements','props','buy_prop','sell_prop','use_prop','ipo','subscribe','issue','margin_status','borrow_cash','repay_cash','borrow_stock','cover']),admin:new Set(['health','audit','pause','resume','settle','compensate','backup'])};
const FIELDS=new Set(['action','code','quantity','price','order_id','keyword','sector','industry','limit','local','days','question','event_id','prop_id','name','amount','reason','token']);

export function validatePlan(plan) {
  if(!plan||typeof plan!=='object'||!ACTIONS[plan.method]?.has(plan.params?.action))throw new Error('Unsupported market action');
  if(Object.keys(plan).some(k=>!['method','params'].includes(k))||Object.keys(plan.params).some(k=>!FIELDS.has(k)))throw new Error('Identity and destinations cannot come from a plan');
  if(Buffer.byteLength(JSON.stringify(plan))>16000)throw new Error('Plan too large');
  return plan;
}

export function exactPlan(body) {
  const basic={'帮助':['query','help'],'开户':['account','open'],'行情':['query','overview'],'新闻':['query','news'],'资金':['account','funds'],'持仓':['account','portfolio'],'委托':['account','orders'],'成交':['account','trades'],'自选':['account','watchlist'],'排行':['query','rank'],'签到':['play','checkin'],'成就':['play','achievements'],'道具':['play','props'],'商店':['play','props']};
  if(basic[body])return {method:basic[body][0],params:{action:basic[body][1]}};
  let m=/^(行情|新闻|搜索|个股|盘口|K线)\s+(.+)$/iu.exec(body);
  if(m){const action={'行情':'overview','新闻':'news','搜索':'search','个股':'stock','盘口':'book','k线':'chart'}[m[1].toLowerCase()]??{'K线':'chart'}[m[1]];
    return {method:'query',params:{action,...(['stock','book','chart'].includes(action)?{code:m[2]}:{keyword:m[2]})}};}
  m=/^(买入|卖出)\s+(\S+)\s+(\d+)(?:股)?(?:\s+限价\s*(\d+(?:\.\d+)?))?$/u.exec(body);
  if(m)return {method:'trade',params:{action:m[1]==='买入'?'buy':'sell',code:m[2],quantity:Number(m[3]),...(m[4]?{price:Number(m[4])}:{})}};
  m=/^撤单\s+(\d+)$/u.exec(body);if(m)return {method:'trade',params:{action:'cancel',order_id:Number(m[1])}};
  return null;
}

/** All ctx fields must be verified host event data, never LLM/tool/user JSON. */
export function createMarketAdapter(config,{rpc=marketRpc,resolveIntent}={}) {
  async function authorize(ctx,method){
    if(!config.enabled||ctx.internal||!numeric(ctx.senderId)||!ctx.accountId||!ctx.messageId)throw new Error('Trusted inbound context required');
    let id;
    if(ctx.scope==='group'){
      if(!numeric(ctx.groupId))throw new Error('Trusted group ID required');
      id=config.groups?.[ctx.groupId];if(!id)throw new Error('Group market not enabled');
    }else if(ctx.scope==='private'&&config.privateQueries)id=config.privateMarket;
    else throw new Error('Chat scope not enabled');
    const market=config.markets?.[id];if(!market?.enabled)throw new Error('Market disabled');
    const admin=(config.adminIds??[]).includes(ctx.senderId);
    if(method==='admin'&&(!admin||ctx.scope!=='private'))throw new Error('Admin private chat required');
    return {id,market,actor:{senderId:ctx.senderId,accountId:ctx.accountId,scope:ctx.scope,...(ctx.scope==='group'?{groupId:ctx.groupId}:{}),identity:admin?'admin':'guest',nickname:String(ctx.nickname??'玩家').replace(/[\r\n\x00-\x1f]/gu,' ').slice(0,80)}};
  }
  async function execute(plan,ctx,{signal}={}){
    validatePlan(plan);const auth=await authorize(ctx,plan.method);
    const path=resolve(auth.market.stateDir,'runtime.sock');
    const result=await rpc(path,{...plan,actor:auth.actor,operation_id:operationId(ctx)},{signal});
    // A private account response must be delivered in DM by the host, never in its group.
    return {result,marketId:auth.id,stateDir:resolve(auth.market.stateDir),actor:auth.actor,operationId:operationId(ctx),destination:result.private?{scope:'private',id:ctx.senderId}:{scope:ctx.scope,id:ctx.scope==='group'?ctx.groupId:ctx.senderId}};
  }
  return {execute,
    async handle(ctx,options={}){
      const command=parseMarketCommand(ctx.text);if(!command)return null;
      // Check authorization before model invocation, avoiding unauthorized API spend.
      await authorize(ctx,'query');
      const plan=command.help?{method:'query',params:{action:'help'}}:exactPlan(command.body)??await resolveIntent?.(command.body,{signal:options.signal});
      if(!plan)return {needsClarification:true,text:'请使用 /fx 帮助 查看指令，或补充股票、数量等信息。'};
      return execute(plan,ctx,options);
    },
    async artifacts(delivery){return delivery.result.artifact||delivery.result.artifacts?marketArtifacts(delivery.result,delivery.stateDir):[];},
    async acknowledge(delivery,receipt,{signal}={}){
      if(!receipt || delivery.result.ok!==true)throw new Error('A successful delivery receipt is required');
      return rpc(resolve(delivery.stateDir,'runtime.sock'),{method:'ack',actor:delivery.actor,id:delivery.operationId,receipt},{signal});
    }
  };
}
