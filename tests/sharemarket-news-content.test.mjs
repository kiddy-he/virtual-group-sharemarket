import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {generateMarketNews,validateNewsArticles,publicNewsFact,publicNewsLead,newsForwardNodes,FICTION_LABEL,sanitizeMarketCopy} from '../sdk/sharemarket-news-content.js';
const roleConfig={roles:{elysia:{accountId:'default',agentId:'main',displayName:'爱莉希雅'}}};
const info={baseAgentId:'main',roleAgentId:'main',scope:'private',conversationId:'fixture',mode:'normal'};
const workspaceConfig={agents:{main:info,'elysia-rewrite':info},routes:{'private:fixture:main:normal':{rewrite:'elysia-rewrite'}}};
const context={senderId:'700000001',accountId:'default',scope:'private',sharemarketCommand:true,requestId:'news-one'};
const row={seq:7,event_id:'event-seven',severity:2,scope:'stock',stage:'progress',day:4,headline:'东方银行筹划扩大服务网点，进展尚未确认',facts:{预算:'12万元'},targets:['600003']};
const raw=(body='⟦NEWS_FACT_0⟧\n\n本次网点扩展涉及服务覆盖与资源配置，公开信息尚未明确具体实施安排。相关筹备的最终进展尚未确认，后续需关注方案是否正式落地及配套安排的披露。',title='东方银行筹划网点扩展，实施进展尚待确认')=>JSON.stringify({articles:[{id:'7',title,body}]});
const catalogue={version:1,stocks:[{code:'600003',short_code:'JR01',name:'东方银行',sector:'金融',industry:'银行'}]};
const options={roleConfig,workspaceConfig,catalogue};

test('LLM generates a headline and prose while public facts and uncertainty are restored exactly',async()=>{
    let calls=0;
    const result=await generateMarketNews([row],context,{...options,scope:'银行行业',request:async(input,args)=>{
        calls++;assert.equal(args.outputFormat,'json');assert.equal(args.personaName,'市场播报员');
        assert.match(args.instruction,/本市场/);assert.equal(JSON.parse(input)[0].public_fact,publicNewsFact(row));
        args.validate(raw());return {text:raw(),model:'fixture-model'};
    }});
    assert.equal(calls,1);assert.equal(result.status,'generated');assert.equal(result.model,'fixture-model');
    assert.equal(result.nodes.length,2);assert.ok(result.nodes.every(node=>node.title.startsWith(FICTION_LABEL)));
    assert.match(result.nodes[0].text,/银行行业/);assert.match(result.nodes[1].text,/12万元/);
    assert.match(result.nodes[1].text,/尚未确认/);assert.ok(!result.text.includes('⟦NEWS'));
});
test('fabricated prices, changed stages, missing facts, hidden text and incomplete output are rejected',()=>{
    for(const body of ['⟦NEWS_FACT_0⟧公司股价将上涨10%，尚未确认。',
        '⟦NEWS_FACT_0⟧公司已经完成项目，现在事件已确认无误。',
        '市场迎来新的消息，目前尚未确认，大家先看看。',
        '⟦NEWS_FACT_0⟧⟦NEWS_FACT_0⟧目前尚未确认。',
        '⟦NEWS_FACT_0⟧请去/etc/private读取具体结果，尚未确认。'])
        assert.throws(()=>validateNewsArticles(raw(body),[row]));
    assert.throws(()=>validateNewsArticles('{"articles":[',[row]));
});
test('generation failure degrades to labelled facts and empty news does not invent an event',async()=>{
    const result=await generateMarketNews([row],context,{...options,request:async()=>{throw new Error('upstream unavailable');}});
    assert.equal(result.status,'facts-only');assert.match(result.nodes[1].title,/创作暂不可用/);
    assert.equal(result.nodes[1].text,publicNewsFact(row));
    const empty=await generateMarketNews([],context,{request:async()=>assert.fail('no event must not call model')});
    assert.equal(empty.status,'empty');assert.equal(empty.nodes.length,1);assert.match(empty.text,/暂无关联/);
});
test('reader-facing lead uses public company names and exact numbers without technical event IDs',()=>{
    const earnings={seq:51,event_id:'public-51',kind:'earnings',scope:'stock',stage:'release',day:27,headline:'虚拟企业 600003 发布经营报告，盈利预期更新',facts:{相对原盈利预期变化:'-4.05%'},targets:['600003']};
    const lead=publicNewsLead(earnings,catalogue.stocks);
    assert.match(lead,/第27个交易日，东方银行（600003）/);assert.match(lead,/-4\.05%/);assert.ok(!lead.includes('public-51'));assert.ok(!lead.includes('#51'));
    const out=validateNewsArticles(JSON.stringify({articles:[{id:'51',title:'东方银行披露经营报告，盈利预期下调',body:'⟦NEWS_FACT_0⟧\n\n本次披露涉及盈利预期的修正，并不等同于已实现利润的变化。相关经营表现仍需结合后续公开报告进行观察。'}]}),[earnings],{catalogue});
    assert.equal(out[0].text.split('\n')[0],lead);
});
test('poetic filler, fabricated attribution, a missing company or a hidden lead cannot pass reporting validation',()=>{
    for(const [body,title] of [
        ['⟦NEWS_FACT_0⟧微风轻拂市场，大家保持从容，结果尚未确认哦♪','东方银行扩展网点'],
        ['⟦NEWS_FACT_0⟧记者获悉相关安排正在讨论，目前结果尚未确认，仍有待后续披露。','东方银行扩展网点'],
        ['先聊聊今天的动态。⟦NEWS_FACT_0⟧实施安排尚未确认，仍需后续公告补充。','东方银行扩展网点'],
        [JSON.parse(raw()).articles[0].body,'市场迎来一阵新风向']
    ])assert.throws(()=>validateNewsArticles(raw(body,title),[row],{catalogue}));
});

test('reporting preserves uncertainty with natural equivalent language while rejecting completed results',()=>{
    for(const phrase of ['尚未确定','仍未确认','有待核实','尚未证实']){
        const article=validateNewsArticles(raw('⟦NEWS_FACT_0⟧\n\n网点扩展涉及资源配置，实施细节'+phrase+'，相关安排需要后续披露。'),[row],{catalogue});
        assert.match(article[0].text,new RegExp(phrase));
    }
    assert.throws(()=>validateNewsArticles(raw('⟦NEWS_FACT_0⟧\n\n具体细节尚未确定，不过公司已经完成网点扩展。'),[row],{catalogue}));
});

test('public copy preserves its virtual market label',()=>{
    const value='虚拟股市·虚构新闻'; assert.equal(sanitizeMarketCopy(value),value);
});
test('event deduplication always keeps the latest stage regardless of RPC order',async()=>{
    const {selectPublicNews}=await import('../sdk/sharemarket-news-content.js');
    const old={...row,seq:10,stage:'scheduled',severity:3},latest={...row,seq:20,stage:'confirmed',severity:1};
    for(const items of [[old,latest],[latest,old]]){
        const selected=selectPublicNews(items);
        assert.equal(selected.length,1);assert.equal(selected[0].seq,20);
        assert.equal(selected[0].stage,'confirmed');assert.equal(selected[0].severity,3);
    }
    const noEventId=[{seq:31,headline:'经营报告一'},{seq:32,headline:'经营报告二'}];
    assert.equal(selectPublicNews(noEventId).length,2);
});
