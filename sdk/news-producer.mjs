/** Fetch public event feed and prepare durable articles without sending chat messages. */
import {resolve} from 'node:path';
import {marketRpc} from './rpc.mjs';
import {NewsPublicationStore,publicationPath,prepareMarketNews} from './sharemarket-news-cache.js';
export async function produceNews(config,{request,rpc=marketRpc,signal,store}={}) {
  if(!config.enabled||!config.news?.enabled)return [];
  const own=!store;store??=new NewsPublicationStore(publicationPath(config));const results=[];
  try{
    for(const [id,market] of Object.entries(config.markets??{})){
      if(!market.enabled)continue;
      const socket=resolve(market.stateDir,'runtime.sock');
      const catalogue=await rpc(socket,{method:'catalogue'},{signal});if(!catalogue.ok)throw Error('Catalogue unavailable');
      const accountId=config.news.accountId??'bot';let after=store.cursor(id,accountId);
      for(let page=0;page<3;page++){
        const feed=await rpc(socket,{method:'news_feed',after,limit:200},{signal});if(!feed.ok)throw Error('Public feed unavailable');
        store.ingest(id,accountId,feed.items);if(!feed.items.length)break;after=feed.items.at(-1).seq;if(feed.items.length<200)break;
      }
      const context={accountId,scope:'private',actorType:'service',personaName:config.news.personaName??'市场播报员'};
      const generate=async(items,ctx,options)=>{
        const {generateMarketNews}=await import('./sharemarket-news-content.js');return generateMarketNews(items,ctx,{...options,request});
      };
      results.push({marketId:id,...await prepareMarketNews(id,context,{store,items:[],generate,signal,catalogue})});
    }
    return results;
  }finally{if(own)store.close();}
}
