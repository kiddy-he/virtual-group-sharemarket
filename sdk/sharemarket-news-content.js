import {buildPublicEventReport} from './sharemarket-news-events.js';
const missingModel = async () => { throw new Error('No news model configured'); };
export const NEWS_STYLE_VERSION=5;
export const FICTION_LABEL='虚拟市场快讯';
export const NEWS_STAGES={scheduled:'计划／结果未定',progress:'进展／未确认',uncertain:'不确定／待核实',confirmed:'已确认',release:'报告发布',revision:'数据修订',unexpected:'突发事件',implementation:'执行阶段',realized:'兑现完成',review:'复核／未确认',delayed:'延期／未确认',reopened:'重启／未确认',partial:'部分目标达成',terminated:'终止推进'};
export function selectPublicNews(items,maxItems=30){
    const latest=new Map();
    for(const row of items){
        const key=row.event_id??('legacy-'+(row.seq??row.news_id)),prior=latest.get(key);
        // RPC queries arrive newest first; ingestion and other callers may use ascending order.
        const chosen=!prior||(row.seq??row.news_id)>(prior.seq??prior.news_id)?row:prior;
        latest.set(key,{...chosen,severity:Math.max(row.severity??0,prior?.severity??0)});
    }
    return [...latest.values()].sort((a,b)=>b.severity-a.severity||(b.seq??b.news_id)-(a.seq??a.news_id)).slice(0,maxItems).sort((a,b)=>(a.seq??a.news_id)-(b.seq??b.news_id));
}
const clean=value=>String(value??'').replace(/[「」\r\n\u0000-\u001f\u007f]/gu,' ').slice(0,1000);
export function sanitizeMarketCopy(value){ return String(value??''); }
export function publicNewsFact(row){
    const facts=Object.entries(row.facts??{}).map(([k,v])=>`${clean(k)}：${clean(v)}`).join('；');
    return `#${row.seq??row.news_id} · ${row.day===undefined?'旧版公告':'第'+row.day+'日'} · ${NEWS_STAGES[row.stage]??'公开更新'} · ${clean(row.event_id??row.kind)}：${sanitizeMarketCopy(clean(row.headline))}${facts?'；'+facts:''}`;
}
/** Reader-facing lead; audit IDs remain in the source record, never in the article. */
export function publicNewsLead(row,subjects=[]){
    let headline=clean(row.event_report?.lead??row.headline);
    for(const subject of subjects)headline=headline.replace(new RegExp('(?:虚拟)?企业\\s*'+subject.code+'\\s*','gu'),`${subject.name}（${subject.code}）`);
    headline=sanitizeMarketCopy(headline).replace(/[。；;]+$/gu,'');
    const day=Number.isInteger(row.day)?`第${row.day}个交易日，`:'';
    const facts=Object.entries(row.facts??{}).map(([key,value])=>`${clean(key)}为${clean(value)}`).join('；');
    const boundary=row.public_detail?.category==='capital'?row.event_report?.boundary??'':'';
    return `${day}${headline}。${facts?'披露数据：'+facts+'。':''}${boundary}`;
}
function reportSubjects(row,catalogue){
    return (catalogue?.stocks??[]).filter(stock=>row.targets?.includes(stock.code)).map(({code,name,sector,industry})=>({code,name,sector,industry}));
}
const metaReport=/本条公开信息未列明|本次(?:公开信息|披露)确认(?:了|公司|相关|该)|相关披露确认/u;
const chatStyle=/[♪♫～]|嗨[，,！!~～]|你看[，,]|不妨|别担心|小插曲|一串脚印|风声轻拂|微风轻|泛起涟漪|迷雾散去|静静等待|保持.{0,6}(?:从容|优雅|平静)|最(?:美妙|迷人)/u;
const fakeAttribution=/据(?:新华社|路透|彭博|央视)|记者获悉|知情人士|内部人士|消息人士|分析师(?:表示|指出)|负责人(?:表示|透露)/u;
const forbidden=/\[CQ:|MEDIA:|<|SOUL\.md|OpenClaw|\/(?:root|etc|tmp)\/|(?:sk|rk)-[A-Za-z0-9_-]{12,}|https?:\/\/|⟦(?!NEWS_FACT_\d+⟧)|保证收益|稳赚|包赚|必然涨|肯定涨/u;
export const NEWS_WRITING_RULES=`你是当前角色担任的财经新闻播报员，报道本市场中已经公开的事件。SOUL只提供克制、自然的播报气质，新闻正文必须是专业事件报道，不能写成陪聊、抒情散文或投资劝慰。宿主已标注“市场快讯”，正文不要反复自称市场，也不能冒充现实市场公告。不要面向读者劝慰或安排关注行动，不要反复用“后续需关注/跟踪/观察”收尾。
采用事件报道结构：标题明确公司/行业主体、发生什么、当前进展，避免“新风向、小波澜、引发关注、如期揭晓”等没有具体信息的标题。stock作用域只有一家主体时标题必须使用subjects中准确的公司名称。正文第一句必须是对应fact_token，宿主会将其还原为包含主体、交易日、事件及已披露数据的新闻导语。后续段落说明这次披露实际确认了什么、本条公开信息尚未提供什么。提供length_hint时按其篇幅组织，否则公开事实少时整篇五十至一百二十字，资料丰富时一百至二百二十字；宁可写简短快讯，也不要推测或重复后续关注点凑字。
只使用public_fact、report_lead、subjects和event_report中的已公开信息。event_report是宿主为这个市场事件登记的具体情节，属于本轮事件素材，可以作为事实报道，并非让你另编的新事件。存在event_report时，标题写具体事件动作，尽量控制在十五至三十五字；标题可简写项目术语，完整project名称留在正文，避免把长项目名全部塞进标题。正文把background、development及必要的next自然组织为新闻：什么项目、为何启动、本轮具体发生什么、下一步是什么；标题或正文中必须原样出现project名称。不要复述“本次披露确认了某情况”，不要写“本条公开信息未列明”或逐项列缺失资料，不用编造的采访引语，不抄技术字段名，也不要在正文里解释宿主内部规则。source只说明该事件在本市场内的公告类别，可自然表述为“公司公告称”，不得冒充现实公告。不同阶段可能出现具体中间步骤，但必须保留最终结果未确认；不能将中间验证升级为最终中标、量产、交割或审批结果。如需解释采购、交付、融资、财报口径等普通行业背景，必须用“一般而言”“通常”等措辞明确这是通用背景；不得将行业常识或公司名称暗示的业务写成本次事件具体涉及的项目、环节或措施。不得以“本次重点围绕”“该项目关乎”等措辞新增输入未提供的事件内容。没有event_report且素材确实不足时可以简短说明已知边界，但不列缺项清单，也不能推断该公司从未公开过。不得杜撰订单、客户、工厂地点、会议、负责人原话、新闻来源、具体政策或事件原因；不得声称市场已经热议、资金流入或股价反应，除非输入明确披露；不得预设经营复苏、效率改善、降本增效或业务调整已经发生。尤其禁止由竞标/研发未达标推出“销售排期将调整”“产品上线将放缓”“交付将推迟”等未披露的具体后果，不得用“意味着”“预计会”等句式把猜测包装成确定的未来经营变化。不得把盈利预期变化说成已实现利润变化，不得把计划/传闻/进展写成已经落实，不得推测隐藏事件结果或未来价格，不得保证收益。
禁止“嗨、你看、不妨、微风、涟漪、旅途、保持从容、请大家理性”等陪聊、诗意比喻或安抚语，禁止语气符号♪、～，不要称呼用户，不写导语以外的内部编号、event/public标识或技术字段名。未确认阶段在创作部分明确写“尚未确认”“待核实”或“结果未定”，不能宣布完成；“尚未确定”“仍未确认”等等义表述也可使用。
若event_report.extended=true，使用已持久化的project、reason、evidence、region、counterparty、timeline、development、next和boundary写出具体事件经过，区分背景、最新进展和后续边界。timeline只包含已公开历史，不把计划核验日写成结果必然公布日，不把模型中的关联敞口写成已签约客户。可以引用已提供的区域和合作方称谓，不编造实名。部分达成必须说明范围有限；终止不代表公司破产；重启不代表原失败结果被撤销。capital类仅报道方案审议与筹备。boundary会随fact_token还原的导语逐字呈现，无需在后续正文重复，不能声称股份、现金分红、回购或融资已经执行。正文长度参照length_hint，避免每条都套同一开场及收尾；不能为了凑字数补造事实。数字信息均由fact_token还原的导语完整呈现。\n每个输入id按顺序恰好返回一篇严格JSON：{"articles":[{"id":"指定id","title":"主体明确的事件标题","body":"⟦NEWS_FACT_对应序号⟧\\n\\n报道的后续正文"}]}。对应fact_token必须在正文开头出现一次，不得删改、重复或引用其他token。除fact_token外不要写阿拉伯数字或价格百分比，数值由导语准确呈现。只输出JSON。`;
export function validateNewsArticles(raw,items,{catalogue}={}){
    const parsed=JSON.parse(String(raw).trim().replace(/^```(?:json)?\s*|\s*```$/gu,''));
    if(Object.keys(parsed).some(k=>k!=='articles')||!Array.isArray(parsed.articles)||parsed.articles.length!==items.length)throw new Error('invalid news batch');
    return parsed.articles.map((article,i)=>{
        const row=items[i],id=String(row.seq??row.news_id),token=`⟦NEWS_FACT_${i}⟧`;
        if(!article||Object.keys(article).some(k=>!['id','title','body'].includes(k))||article.id!==id
            ||typeof article.title!=='string'||!article.title.trim()||article.title.length>80
            ||typeof article.body!=='string'||article.body.length>1600||article.body.length<20)throw new Error('invalid news article');
        const prose=article.title+'\n'+article.body.replace(token,'');
        const tokens=article.body.match(/⟦NEWS_FACT_\d+⟧/gu)??[];
        if(!article.body.trimStart().startsWith(token)||chatStyle.test(prose)||fakeAttribution.test(prose))throw new Error('news is not event reporting');
        const subjects=reportSubjects(row,catalogue);
        if(row.scope==='stock'&&subjects.length===1&&!article.title.includes(subjects[0].name))throw new Error('news subject missing');
        if(row.event_report&&(metaReport.test(prose)||!prose.includes(row.event_report.project)))throw new Error('news lacks concrete event');
        if(tokens.length!==1||tokens[0]!==token||forbidden.test(prose)||/\d|⟦|⟧/u.test(prose))throw new Error('news changed public facts');
        if(['scheduled','progress','uncertain','review','delayed','reopened'].includes(row.stage)&&(!/(?:尚|仍|还)?未(?:确认|确定|证实)|待(?:核实|确认)|结果未定/u.test(prose)||/已经?(?:落实|落地|兑现|完成)|已确认/u.test(prose)))throw new Error('news changed uncertainty');
        if(row.public_detail?.category==='capital'){
            // The immutable public boundary travels with the fact token; the LLM
            // need not duplicate it verbatim and cannot convert a proposal into execution.
            const capitalProse=prose.replace(row.event_report.boundary,'');
            if(/(?:已(?:经)?(?:完成(?:了)?|实施(?:了)?|实际)?|完成了|实施了)(?:实际)?(?:股份|股票|现金)?(?:回购|派息|分红|增发|配股|股东交易)|(?:回购|分红|增发|配股)(?:计划)?已(?:经)?(?:执行|完成|实施)/u.test(capitalProse))throw new Error('capital proposal reported as executed');
        }
        return {title:article.title.trim(),text:article.body.trim().replace(token,publicNewsLead(row,subjects))};
    });
}
export function newsForwardNodes(articles,{scope='全市场',omitted=0,empty=false}={}){
    return [{title:FICTION_LABEL,text:`以下为本市场公开信息。查询范围：${scope}。${empty?'当前暂无关联公开事件，不编造公告。':''}${omitted?'部分同一事件的旧进展已合并。':''}`},
        ...articles.map(a=>({title:`${FICTION_LABEL}｜${a.title}`,text:a.text}))];
}
export function newsVisibleText(nodes){return nodes.map(n=>`【${n.title}】\n${n.text}`).join('\n\n');}
export async function generateMarketNews(items,context,{signal,request=missingModel,roleConfig,workspaceConfig,maxItems=30,scope='全市场',budgetMs=60000,attemptMs=25000,preserveItems=false,catalogue}={}){
    const selected=preserveItems?items.slice(0,maxItems):selectPublicNews(items,maxItems),omitted=items.length-selected.length;
    const chosen=selected.map(row=>({...row,event_report:buildPublicEventReport(row,catalogue)??row.event_report}));
    if(!chosen.length){const nodes=newsForwardNodes([],{scope,empty:true});return {nodes,text:newsVisibleText(nodes),status:'empty'};}
    const persona={personaName:context.personaName??'市场播报员',persona:context.persona??''};
    const bounded=signal?AbortSignal.any([signal,AbortSignal.timeout(budgetMs)]):AbortSignal.timeout(budgetMs);
    try{
        const input=chosen.map((row,i)=>({id:String(row.seq??row.news_id),stage:NEWS_STAGES[row.stage]??'公开更新',public_fact:publicNewsFact(row),fact_token:`⟦NEWS_FACT_${i}⟧`,report_lead:publicNewsLead(row,reportSubjects(row,catalogue)),subjects:reportSubjects(row,catalogue),event_report:row.event_report}));
        const output=await request(JSON.stringify(input),{...persona,signal:bounded,timeoutMs:attemptMs,outputFormat:'json',
            maxOutputTokens:Math.min(14000,Math.max(4096,chosen.length*1500+2000)),guestAddress:'你',
            instruction:NEWS_WRITING_RULES,validate:raw=>validateNewsArticles(raw,chosen,{catalogue})});
        const articles=validateNewsArticles(typeof output==='string'?output:output.text,chosen,{catalogue});
        const nodes=newsForwardNodes(articles,{scope,omitted});
        return {...persona,articles,nodes,text:newsVisibleText(nodes),status:'generated',styleVersion:NEWS_STYLE_VERSION,model:output.model};
    }catch{
        signal?.throwIfAborted();
        // Keep public information deliverable; never claim a failed LLM generation succeeded.
        const nodes=newsForwardNodes(chosen.map(row=>({title:'公开事件简报（创作暂不可用）',text:publicNewsFact(row)})),{scope,omitted});
        return {...persona,nodes,text:newsVisibleText(nodes),status:'facts-only'};
    }
}
