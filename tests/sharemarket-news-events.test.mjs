import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {buildPublicEventReport} from '../sdk/sharemarket-news-events.js';
import {publicNewsFact,publicNewsLead,validateNewsArticles,generateMarketNews} from '../sdk/sharemarket-news-content.js';
import {NewsPublicationStore,prepareMarketNews} from '../sdk/sharemarket-news-cache.js';
const catalogue={version:1,stocks:[{code:'600003',short_code:'JR01',name:'东方银行',sector:'金融',industry:'银行'}]};
const row=(kind='supply',stage='scheduled')=>({seq:21,event_id:'same-scene',scope:'stock',targets:['600003'],kind,stage,day:7,headline:stage==='confirmed'?'虚拟企业 600003 的相关事项结果确认：未达原定目标，后续影响将逐步兑现':'虚拟企业 600003 的相关事项进入观察期，结果尚未确定',facts:{}});
test('event scenes keep the same project across disclosure stages and never depend on hidden truth',()=>{
    const source=row();const before=structuredClone(source);
    const initial=buildPublicEventReport(source,catalogue);
    for(const stage of ['scheduled','progress','uncertain','confirmed','realized']){
        const r=row('supply',stage),a=buildPublicEventReport({...r,truth:true,seed:'private-A'},catalogue),b=buildPublicEventReport({...r,truth:false,seed:'private-B'},catalogue);
        assert.deepEqual(a,b);assert.equal(a.project,initial.project);
        assert.ok(!JSON.stringify(a).includes('private-'));
        if(['scheduled','progress','uncertain'].includes(stage))assert.match(a.next,/未确认|未确定|待核实/);
    }
    assert.deepEqual(source,before);
});
test('all event categories report concrete actions matching the publicly disclosed outcome',()=>{
    for(const kind of ['contract','research','acquisition','governance','refinancing','supply','cyber','weather']){
        for(const stage of ['scheduled','progress','uncertain','confirmed','realized','unexpected']){
            const r=row(kind,stage),report=buildPublicEventReport(r,catalogue);
            assert.ok(report.project);assert.ok(report.development);assert.ok(report.action);assert.equal(report.stage,stage);
            if(stage==='confirmed'){
                const good=buildPublicEventReport({...r,headline:'虚拟企业 600003 的相关事项结果确认：进展达成，需结合实际条件评估'},catalogue);
                assert.notEqual(good.action,report.action);assert.equal(good.project,report.project);
                assert.equal(buildPublicEventReport({...r,headline:'未提供已披露结果'},catalogue),undefined);
            }
        }
    }
});
test('business scenes distinguish aviation, banking and education; unavailable scopes receive no invented project',()=>{
    const aviation=buildPublicEventReport(row(),{stocks:[{...catalogue.stocks[0],industry:'航空'}]});
    const education=buildPublicEventReport(row('research'),{stocks:[{...catalogue.stocks[0],name:'中公教育',industry:'传媒'}]});
    assert.match(aviation.project,/航材|发动机/);assert.match(education.project,/课程/);
    for(const r of [{...row(),targets:['unlisted']},{...row(),targets:['600003','600004']},{...row(),scope:'market'},row('unknown')])assert.equal(buildPublicEventReport(r,catalogue),undefined);
});
test('event leads and articles retain original financial facts and reject the former status-report style',()=>{
    const r=row('earnings','release');r.facts={'相对原盈利预期变化':'-4.05%'};
    const audit=publicNewsFact(r),event_report=buildPublicEventReport(r,catalogue),enriched={...r,event_report};
    assert.match(event_report.action,/下调/);assert.equal(publicNewsFact(enriched),audit);
    assert.match(publicNewsLead(enriched),/-4\.05%/);
    const raw=body=>JSON.stringify({articles:[{id:'21',title:'东方银行更新本期经营测算报告',body}]});
    assert.throws(()=>validateNewsArticles(raw('⟦NEWS_FACT_0⟧\n本次披露确认了公司盈利预期变化，本条公开信息未列明业务明细。'),[enriched],{catalogue}));
    const out=validateNewsArticles(raw('⟦NEWS_FACT_0⟧\n\n本期经营测算报告调整未来盈利测算基准，本次预期变动不等同于已实现利润变化。'),[enriched],{catalogue});
    assert.match(out[0].text,/-4\.05%/);
});
test('public event scenes persist before generation, survive failed writes and remain available to later retries',async()=>{
    const dir=await mkdtemp(join(tmpdir(),'event-scene-')),store=new NewsPublicationStore(join(dir,'news.sqlite'));
    try{
        const source=row();const context={accountId:'default',scope:'private'};let observed;
        const a=await prepareMarketNews('m',context,{store,items:[source],catalogue,now:100,generate:async items=>{
            observed=items[0].event_report;
            const saved=JSON.parse(store.db.prepare('SELECT payload FROM publications').get().payload);
            assert.deepEqual(saved.event_report,observed);
            return {status:'facts-only'};
        }});
        assert.equal(a.state,'retry_pending');
        await prepareMarketNews('m',context,{store,items:[source],now:30101,generate:async items=>{
            assert.deepEqual(items[0].event_report,observed);
            return {status:'generated',articles:[{title:'东方银行备用渠道启动评审',text:'具体事件报道'}]};
        }});
        assert.ok(store.article('m','default',source));assert.equal(store.cursor('m','default'),21);
    }finally{store.close();await rm(dir,{recursive:true,force:true});}
});
test('news generation receives concrete public scenes and returns a complete forward without mutating the event',async()=>{
    const roleConfig={roles:{elysia:{accountId:'default',agentId:'main',displayName:'爱莉希雅'}}};
    const info={baseAgentId:'main',roleAgentId:'main',scope:'private',conversationId:'fixture',mode:'normal'};
    const workspaceConfig={agents:{main:info,'elysia-rewrite':info},routes:{'private:fixture:main:normal':{rewrite:'elysia-rewrite'}}};
    const source=row('supply','progress'),copy=structuredClone(source);
    const result=await generateMarketNews([source],{accountId:'default',scope:'private'},{catalogue,roleConfig,workspaceConfig,request:async(input,opts)=>{
        const payload=JSON.parse(input)[0];assert.match(payload.event_report.project,/支付清算/);assert.match(payload.report_lead,/备用渠道通过/);
        const text=JSON.stringify({articles:[{id:'21',title:'东方银行备用渠道通过首轮适配核验',body:`⟦NEWS_FACT_0⟧\n\n公司公告称，${payload.event_report.project}旨在降低单一来源采购风险。备用渠道完成本轮资质与适配核验，下一步继续交付衔接测试，最终结果尚未确认。`}]});
        opts.validate(text);return {text,model:'fixture'};
    }});
    assert.equal(result.status,'generated');assert.equal(result.styleVersion,5);assert.equal(result.nodes.length,2);assert.match(result.text,/交付衔接测试/);assert.deepEqual(source,copy);
});
test('policy and market calendars use disclosed decisions without inventing rate changes or report results',()=>{
    for(const [kind,stage] of [['policy_calendar','scheduled'],['policy','confirmed'],['index_rebalance','implementation'],['earnings_calendar','scheduled']]){
        const r={...row(kind,stage),scope:'market',targets:[],facts:kind==='policy'?{'政策利率':'4.20%'}:{}};
        const report=buildPublicEventReport(r,catalogue);assert.ok(report.project);assert.ok(report.development);
        assert.ok(!/降息|加息|上调利率|下调利率/u.test(report.lead));
        if(stage==='scheduled')assert.match(report.next,/未确认/);
        assert.equal(publicNewsFact({...r,event_report:report}),publicNewsFact(r));
    }
    for(const kind of ['debt_calendar','debt_maturity','unlock_calendar','unlock','risk_warning','liquidation']){
        const r=row(kind,kind.endsWith('calendar')?'scheduled':'confirmed');
        const report=buildPublicEventReport(r,catalogue);assert.ok(report.project);assert.ok(report.development);
    }
});
