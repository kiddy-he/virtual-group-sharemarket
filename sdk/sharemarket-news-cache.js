/** Durable pre-publication cache. Query path is read-only and never invokes an LLM. */
import {buildPublicEventReport} from './sharemarket-news-events.js';
import {DatabaseSync} from 'node:sqlite';
import {mkdirSync,chmodSync} from 'node:fs';
import {dirname,join,resolve} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {NEWS_STYLE_VERSION,generateMarketNews,selectPublicNews,publicNewsFact,newsForwardNodes,newsVisibleText,sanitizeMarketCopy} from './sharemarket-news-content.js';

// Bump this version whenever the canonical public-fact representation changes.
export const NEWS_FINGERPRINT_VERSION=2;
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
const fingerprint=row=>createHash('sha256').update(publicNewsFact(row)+(row.public_detail?'\n'+JSON.stringify(canonical(row.public_detail)):'')).digest('hex');
export const publicationPath=config=>join(resolve(config.stateRoot??'state'),'news-publications.sqlite');
export class NewsPublicationStore {
    constructor(path){
        mkdirSync(dirname(path),{recursive:true,mode:0o700});this.db=new DatabaseSync(path);chmodSync(path,0o600);
        this.db.exec(`PRAGMA busy_timeout=3000; PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS publications(market TEXT NOT NULL,account TEXT NOT NULL,seq INTEGER NOT NULL,fingerprint TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',article TEXT,persona TEXT,attempts INTEGER NOT NULL DEFAULT 0,retry_at INTEGER NOT NULL DEFAULT 0,lease TEXT,lease_until INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(market,account,seq));
            CREATE TABLE IF NOT EXISTS publication_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS publication_cursors(market TEXT NOT NULL,account TEXT NOT NULL,seq INTEGER NOT NULL,PRIMARY KEY(market,account));`);
        this.db.exec('BEGIN IMMEDIATE');
        try{
            if(!this.db.prepare('PRAGMA table_info(publications)').all().some(column=>column.name==='style_version'))this.db.exec('ALTER TABLE publications ADD COLUMN style_version INTEGER NOT NULL DEFAULT 0');
            const version=Number(this.db.prepare("SELECT value FROM publication_metadata WHERE key='fingerprint_version'").get()?.value??0);
            if(version<NEWS_FINGERPRINT_VERSION){
                // Upgrade only from each stored, trusted payload. Never accept a changed query
                // merely because its sequence matches, and preserve articles and active leases.
                const update=this.db.prepare('UPDATE publications SET fingerprint=? WHERE market=? AND account=? AND seq=?');
                for(const row of this.db.prepare('SELECT market,account,seq,fingerprint,payload FROM publications').all()){
                    const current=fingerprint(JSON.parse(row.payload));
                    if(current!==row.fingerprint)update.run(current,row.market,row.account,row.seq);
                }
                this.db.prepare("INSERT INTO publication_metadata VALUES('fingerprint_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").run(String(NEWS_FINGERPRINT_VERSION));
            }
            this.db.exec('COMMIT');
        }
        catch(error){this.db.exec('ROLLBACK');throw error;}
    }
    close(){this.db.close();}
    cursor(market,account){return this.db.prepare('SELECT seq FROM publication_cursors WHERE market=? AND account=?').get(market,account)?.seq??0;}
    ingest(market,account,items){
        this.db.exec('BEGIN IMMEDIATE');try{
            const insert=this.db.prepare('INSERT OR IGNORE INTO publications(market,account,seq,fingerprint,payload) VALUES(?,?,?,?,?)');
            for(const row of items)insert.run(market,account,row.seq,fingerprint(row),JSON.stringify(row));
            if(items.length)this.db.prepare('INSERT INTO publication_cursors VALUES(?,?,?) ON CONFLICT(market,account) DO UPDATE SET seq=MAX(seq,excluded.seq)').run(market,account,Math.max(...items.map(x=>x.seq)));
            this.db.exec('COMMIT');
        }catch(error){this.db.exec('ROLLBACK');throw error;}
    }
    claim(market,account,{now=Date.now(),limit=4,leaseMs=240000}={}){
        const lease=randomUUID();this.db.exec('BEGIN IMMEDIATE');try{
            // Recent articles first during initial backfill; every disclosed stage retains its own row.
            const rows=this.db.prepare("SELECT * FROM publications WHERE market=? AND account=? AND (status!='ready' OR style_version<CASE WHEN json_extract(payload,'$.public_detail.version')=1 THEN ? ELSE 4 END) AND retry_at<=? AND lease_until<=? ORDER BY seq DESC LIMIT ?").all(market,account,NEWS_STYLE_VERSION,now,now,limit);
            const update=this.db.prepare('UPDATE publications SET lease=?,lease_until=? WHERE market=? AND account=? AND seq=?');
            for(const row of rows)update.run(lease,now+leaseMs,market,account,row.seq);
            this.db.exec('COMMIT');return {lease,items:rows.map(row=>JSON.parse(row.payload))};
        }catch(error){this.db.exec('ROLLBACK');throw error;}
    }
    recordReports(market,account,claim){
        // Annotation of the same public event; original facts and delivery identity stay unchanged.
        this.db.exec('BEGIN IMMEDIATE');try{
            const update=this.db.prepare('UPDATE publications SET payload=? WHERE market=? AND account=? AND seq=? AND lease=? AND fingerprint=?');
            for(const row of claim.items)if(row.event_report)update.run(JSON.stringify(row),market,account,row.seq,claim.lease,fingerprint(row));
            this.db.exec('COMMIT');
        }catch(error){this.db.exec('ROLLBACK');throw error;}
    }
    finish(market,account,claim,result,{now=Date.now()}={}){
        const ready=result?.status==='generated'&&result.articles?.length===claim.items.length;
        const persona=JSON.stringify({personaName:result?.personaName,model:result?.model});
        this.db.exec('BEGIN IMMEDIATE');try{
            for(let i=0;i<claim.items.length;i++){
                const row=claim.items[i];
                if(ready)this.db.prepare("UPDATE publications SET status='ready',style_version=?,article=?,persona=?,lease=NULL,lease_until=0,attempts=attempts+1,retry_at=0 WHERE market=? AND account=? AND seq=? AND lease=? AND fingerprint=?").run(NEWS_STYLE_VERSION,JSON.stringify(result.articles[i]),persona,market,account,row.seq,claim.lease,fingerprint(row));
                else this.db.prepare("UPDATE publications SET status=CASE WHEN article IS NULL THEN 'pending' ELSE 'ready' END,lease=NULL,lease_until=0,attempts=attempts+1,retry_at=?+MIN(900000,30000*(1<<MIN(attempts,5))) WHERE market=? AND account=? AND seq=? AND lease=?").run(now,market,account,row.seq,claim.lease);
            }
            this.db.exec('COMMIT');
        }catch(error){this.db.exec('ROLLBACK');throw error;}
        return ready;
    }
    article(market,account,row){
        const value=this.db.prepare("SELECT article,persona FROM publications WHERE market=? AND account=? AND seq=? AND fingerprint=? AND status='ready'").get(market,account,row.seq,fingerprint(row));
        if(!value)return null;
        const article=JSON.parse(value.article);
        if(article&&typeof article==='object'){
            if(typeof article.title==='string')article.title=sanitizeMarketCopy(article.title);
            if(typeof article.text==='string')article.text=sanitizeMarketCopy(article.text);
        }
        return {article,...JSON.parse(value.persona)};
    }
}
export async function prepareMarketNews(market,context,{store,items,generate=generateMarketNews,signal,now=Date.now(),batchSize=4,catalogue}={}){
    store.ingest(market,context.accountId,items);
    const claim=store.claim(market,context.accountId,{now,limit:batchSize});if(!claim.items.length)return {state:'idle',count:0};
    claim.items=claim.items.map(row=>({...row,event_report:buildPublicEventReport(row,catalogue)??row.event_report}));
    store.recordReports(market,context.accountId,claim);
    let result;
    try{result=await generate(claim.items,context,{signal,preserveItems:true,maxItems:batchSize,budgetMs:180000,attemptMs:60000,catalogue});}
    catch(error){store.finish(market,context.accountId,claim,null,{now});throw error;}
    const ready=store.finish(market,context.accountId,claim,result,{now});
    return {state:ready?'prepared':'retry_pending',count:claim.items.length,model:result.model};
}
export async function readPreparedMarketNews(items,context,{config,marketId,store,scope='全市场',maxItems=30}={}){
    const own=!store;store??=new NewsPublicationStore(publicationPath(config));
    try{
        const chosen=selectPublicNews(items,maxItems),found=chosen.map(row=>store.article(marketId,context.accountId,row));
        const ready=found.filter(Boolean),pending=found.length-ready.length;
        const nodes=newsForwardNodes(ready.map(x=>x.article),{scope,empty:chosen.length===0,omitted:items.length-chosen.length});
        if(pending)nodes[0].text+=`另有${pending}条公开事件正在后台撰写新闻，请稍后查询；本次未临时调用模型。`;
        return {nodes,text:newsVisibleText(nodes),status:pending?'preparing':ready.length?'generated':'empty',pending,
            personaName:ready[0]?.personaName,model:ready[0]?.model,workspaceAgentId:context.workspaceAgentId};
    }finally{if(own)store.close();}
}
