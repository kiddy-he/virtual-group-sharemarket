/** Public fictional event scenes. Inputs are disclosed rows + public catalogue only.
 * Adds reporting detail, never financial shocks, private evidence or price targets.
 * Identity is stable across stages, roles and restarts; no world seed is consulted.
 */
import {createHash} from 'node:crypto';
export const EVENT_REPORT_VERSION=2;
const business=(product,project,resources,asset,site)=>({product,project,resources,asset,site});
const B={
    banking:business('企业资金管理服务','企业结算服务采购项目','支付清算及数据服务资源','区域金融服务业务资产','营业与清算服务场所'),
    securities:business('机构交易服务系统','机构交易服务采购项目','行情数据与交易系统服务','区域机构客户服务业务资产','交易及数据服务场所'),
    insurance:business('企业保险服务','团体保险服务采购项目','理赔审核与客户服务资源','区域保险服务业务资产','客户与理赔服务场所'),
    software:business('企业协同平台','企业数字化平台采购项目','云服务容量及关键软件组件','企业软件服务团队与技术资产','数据与运维服务中心'),
    hardware:business('高可靠电子模块','工业电子模块集采项目','关键电子元件及封装材料','电子模块设计与测试业务资产','电子产品测试与生产场所'),
    chip:business('新一代控制芯片','控制芯片配套采购项目','晶圆代工及封装测试资源','芯片设计与验证业务资产','芯片封装与测试场所'),
    air:business('航空运维调度系统','货运运力包销项目','航材及发动机维修备件','区域地面保障业务资产','机场地面保障作业区'),
    shipping:business('货运调度服务','航运运力年度采购项目','船舶维修及港口配套服务','区域航运代理业务资产','港口与船舶保障作业区'),
    logistics:business('仓配调度系统','区域仓配服务采购项目','运输运力及仓储配套服务','区域仓储配送业务资产','仓储配送作业区'),
    power:business('电力运行监测系统','园区能源服务采购项目','电网设备及运维备件','区域能源服务业务资产','能源设备运行场所'),
    battery:business('高循环寿命储能模块','储能模块配套采购项目','电芯及关键电池材料','储能模组技术与生产业务资产','电池测试与生产场所'),
    solar:business('高效率光电转换模块','光伏配套设备采购项目','光伏组件材料及功率器件','光伏配套技术与生产业务资产','光伏设备测试与生产场所'),
    machine:business('工业自动化控制模块','生产线配套设备采购项目','核心控制器及机械零部件','工业设备技术与服务业务资产','设备装配与测试场所'),
    car:business('新一代车用配套模块','汽车配套产品采购项目','车规级零部件及配套材料','汽车配套技术与服务业务资产','汽车配套产品测试与生产场所'),
    pharma:business('候选医药产品','医药产品配送采购项目','医药原辅料及合规检验服务','医药技术与质量检验业务资产','医药研发与储运场所'),
    medical:business('医疗服务支持系统','医疗服务配套采购项目','医疗耗材及检验服务','区域医疗服务配套业务资产','医疗服务与检验场所'),
    food:business('新配方食品产品','连锁渠道年度供货项目','食品原料及包装材料','区域食品加工与渠道业务资产','食品加工与冷链仓储场所'),
    feed:business('高转化率饲料配方','养殖企业饲料集采项目','饲料原料及营养添加剂','区域饲料加工与配送业务资产','饲料加工与原料仓储场所'),
    farming:business('农业生产配套产品','农业生产资料采购项目','种苗及农业生产配套物资','区域农业技术与服务业务资产','农业生产与储运场所'),
    retail:business('零售供应管理系统','连锁零售渠道供货项目','品牌货源及配送服务','区域零售门店与渠道业务资产','零售仓储与配送场所'),
    education:business('职业培训课程产品','职业培训服务采购项目','课程内容及教学服务资源','区域培训服务业务资产','教学与课程制作场所'),
    media:business('数字内容服务产品','数字内容服务采购项目','内容授权及制作服务资源','区域内容制作与发行业务资产','内容制作与数据服务场所'),
    property:business('工程运行管理系统','园区工程服务采购项目','工程材料及专业施工服务','区域工程管理与服务业务资产','工程建设与运维场所'),
    materials:business('高稳定性工业材料','工业材料年度供货项目','原材料及关键工艺配套资源','工业材料技术与生产业务资产','材料生产与仓储场所'),
    generic:business('核心业务配套产品','企业配套服务采购项目','关键物资及配套服务','相关技术与服务业务资产','主要业务运行场所')
};
const groups=[
    ['banking',['银行']],['securities',['证券']],['insurance',['保险']],
    ['software',['软件','云计算','信息技术','网络安全']],['hardware',['电子','通信']],['chip',['半导体','汽车芯片','汽车电子']],
    ['air',['航空']],['shipping',['航运','船舶','港口']],['logistics',['物流','交通运输','高速公路']],
    ['power',['电力','公用事业','风电','氢能']],['battery',['锂电','储能','锂电设备']],['solar',['光伏','光伏逆变器','新能源']],
    ['machine',['自动化','工程机械','专用设备','家电','军工']],['car',['汽车','新能源车']],
    ['pharma',['医药','创新药','中药','生物制品','疫苗']],['medical',['医疗服务','医疗器械']],
    ['food',['食品','食品加工','食品饮料','乳品','调味品','白酒','饮料']],['feed',['饲料']],['farming',['农业','养殖','种业']],
    ['retail',['零售','珠宝','纺织']],['media',['传媒']],['property',['房地产','建筑','建材']],
    ['materials',['有色','钢铁','新材料','化工','煤炭','石油化工','石油石化']]
];
const industries=new Map(groups.flatMap(([group,names])=>names.map(name=>[name,group])));
const pick=(identity,values)=>values[createHash('sha256').update(identity).digest().readUInt32BE()%values.length];
const eventKinds=new Set(['contract','research','acquisition','governance','refinancing','supply','cyber','weather']);
/** Sole outcome input is an already-disclosed result; never an unresolved event's truth. */
function publicOutcome(row){
    if(row.stage!=='confirmed')return undefined;
    if(/未达原定目标/u.test(row.headline))return 'negative';
    if(/进展达成/u.test(row.headline))return 'positive';
    return undefined;
}
function marketReport(row){
    const known={
        policy_calendar:['货币政策例会','政策日程公告','货币政策例会将按公开日程审议利率安排。','例会列入近期议程','政策例会将在三个交易日后举行，利率决定尚未公布。','利率决定尚未确认，待例会结束后公布。'],
        policy:['货币政策例会','政策决定公告','本市场的融资条件与估值测算采用公开政策利率作为基准。','公布本次利率决定','本次例会公布政策利率决定，具体利率见披露数据。','本次公布不包含未来会议的利率承诺。'],
        index_rebalance:['指数季度成分调整','指数调整公告','指数按季度检查成分配置，被动资金按调整安排分批衔接。','进入调仓执行窗口','季度成分调整进入执行期，相关被动资金按安排分批调仓。','本次执行不保证任一个股的价格方向。'],
        macro:['经济运行数据发布','经济运行数据公报','需求与融资等公开经济指标按周期更新。','发布本期经济运行指标','本期公开指标已发布，具体数值以披露数据为准。','指标反映本期测量，不构成后续增长承诺。'],
        data_revision:['历史经济数据修订','经济数据修订公报','历史测量数据按后续核验记录进行修订。','公布历史指标修订','已披露历史指标的本次修订幅度见数据导语。','修订只适用于已明确披露的统计口径。'],
        earnings_calendar:['近期经营报告披露安排','报告披露日程公告','企业按既定报告周期发布经营测算。','公布近期报告披露日程','未来三个交易日有企业计划披露经营报告。','报告内容及盈利预期变化尚未确认，待报告正式发布。']
    };
    const data=known[row.kind];if(row.scope!=='market'||!data)return undefined;
    const [project,source,background,action,development,next]=data;
    return {version:EVENT_REPORT_VERSION,project,source,background,action,development,next,stage:row.stage,lead:`${project}：${action}`};
}
const extendedCategories=new Set(['macro','industry','contract','supply','research','capacity','earnings_event','refinancing','capital','acquisition','governance','incident']);
const publicStages=new Set(['scheduled','progress','uncertain','review','delayed','reopened','confirmed','partial','terminated','unexpected','realized']);
/** New events carry persistent public-world detail. Never accept a private event object. */
function extendedReport(row,catalogue){
    const detail=row.public_detail;
    if(detail?.version!==1||!extendedCategories.has(detail.category)||!publicStages.has(row.stage))return undefined;
    const text=(value,max=700)=>typeof value==='string'&&value.length<=max&&!/[\u0000-\u001f]|(?:sk|rk)-[A-Za-z0-9_-]{12,}|(?:SOUL\.md|\/root\/)/u.test(value)?value:undefined;
    const required=['title','project','source','background','reason','evidence','action','development','next','boundary'];
    if(required.some(key=>!text(detail[key])))return undefined;
    const subjects=(catalogue?.stocks??[]).filter(stock=>row.targets?.includes(stock.code));
    if(row.scope==='stock'&&(subjects.length!==1||row.targets.length!==1))return undefined;
    const subject=subjects.length===1?{code:subjects[0].code,name:subjects[0].name,industry:subjects[0].industry,sector:subjects[0].sector}:undefined;
    const timeline=Array.isArray(detail.timeline)?detail.timeline.slice(-8).flatMap(item=>
        Number.isInteger(item.day)&&publicStages.has(item.stage)&&text(item.action,160)?[{day:item.day,stage:item.stage,action:item.action}]:[]):[];
    const level=row.severity>=3?'detailed':(['confirmed','partial','terminated','realized'].includes(row.stage)||timeline.length>=3)?'standard':'brief';
    const report={version:EVENT_REPORT_VERSION,extended:true,category:detail.category,category_label:text(detail.category_label,40),
        subtype:text(detail.subtype,80),subject,project:detail.project,source:detail.source,background:detail.background,
        reason:detail.reason,evidence:detail.evidence,action:detail.action,development:detail.development,next:detail.next,
        boundary:detail.boundary,region:text(detail.region,100),counterparty:text(detail.counterparty,100),
        channel_label:text(detail.channel_label,100),timeline,reporting_level:level,
        length_hint:level==='detailed'?'正文约220至380字，分两至三段':level==='standard'?'正文约140至260字，分两段':'正文约80至160字，简短快讯',
        stage:row.stage,lead:`${subject?`${subject.name}（${subject.code}）`:text(detail.subject,100)??'本市场'}：${detail.title}，${detail.action}`};
    // Only a published outcome can appear, never a live event's truth/payoff/probability.
    if(['confirmed','partial','terminated','unexpected','realized'].includes(row.stage)&&['positive','negative','partial'].includes(detail.outcome))report.outcome=detail.outcome;
    if(text(detail.parent_event_id,100))report.related_public_event=detail.parent_event_id;
    return report;
}
export function buildPublicEventReport(row,catalogue){
    if(row.public_detail)return extendedReport(row,catalogue);
    if(row.scope==='market')return marketReport(row);
    if(row.scope!=='stock'||!Array.isArray(row.targets)||row.targets.length!==1)return undefined;
    const subject=catalogue?.stocks?.find(stock=>stock.code===row.targets[0]);if(!subject)return undefined;
    const {code,name,industry,sector}=subject;
    const b=B[name.includes('教育')?'education':industries.get(industry)??'generic'];
    const identity=[row.event_id??row.news_id??row.seq,code,industry,row.kind].join('|');
    const outcome=publicOutcome(row),stage=row.stage;
    let scene;
    if(eventKinds.has(row.kind)){
        // No future conditions, hidden outcomes, model parameters, prices or amounts here.
        const scenes={
            contract:()=>({
                project:pick(identity,[b.project,b.project.replace(/项目$/u,'框架项目')]),
                source:'公司项目进度公告',background:`公司拟通过公开采购程序拓展${b.product}相关业务合作。`,
                scheduled:['提交投标资格审查材料','公司已递交资格审查材料，采购方将按流程核验履约能力及服务方案。','资格评审后再开展正式评标，是否中标尚未确定。'],
                progress:['投标方案通过本轮技术评审','采购方接受本轮技术方案，报价及履约条款仍在评审范围内。','仍需完成商务评标，中标结果尚未确认。'],
                uncertain:['投标文件进入补充核验','采购方要求补充履约材料，本轮评审尚未形成最终中标结论。','补充材料核验后再确定评审安排，最终结果待核实。'],
                positive:['获得中标确认','采购方公布中标结果，公司取得本次项目的中标资格。','后续进入合同条款衔接与履约准备。'],
                negative:['未获中标','采购方公布评标结果，公司未获得本次项目的中标资格。','本次招投标程序结束。']
            }),
            research:()=>({
                project:pick(identity,[`${b.product}升级验证项目`,`${b.product}适配研发项目`]),
                source:'公司研发项目公告',background:`公司围绕${b.product}的适配需求开展研发验证，本项目以阶段验收作为研发目标。`,
                scheduled:['启动研发验证','研发团队启动方案验证与测试准备，最终验收尚未开展。','下一步开展样本测试，最终研发结果尚未确认。'],
                progress:['通过本轮方案验证','本轮测试达到本阶段验证要求，项目进入扩大测试环节。','仍需完成阶段验收，最终研发结果尚未确认。'],
                uncertain:['部分测试项目需补充验证','本轮测试出现一致性偏差，团队正在复核测试条件与适配方案。','补充测试结束后再组织阶段验收，最终结果待核实。'],
                positive:['通过阶段验收','项目通过本次阶段验收，达到预先设定的研发验证目标。','后续进入产品适配与应用准备。'],
                negative:['未通过阶段验收','本次验收未达到预设验证要求，项目未能实现原定研发目标。','本轮验收结束，后续补测安排需另行公告。']
            }),
            acquisition:()=>({
                project:pick(identity,[`${b.asset}收购项目`,`${b.asset}整合项目`]),
                source:'公司交易事项公告',background:`公司拟通过${b.asset}整合补充现有业务能力，交易须经过尽职调查与内部审议。`,
                scheduled:['启动标的尽职调查','公司与交易对方就尽调范围达成安排，资料核验开始。','尽调与内部审议尚未结束，交易结果尚未确定。'],
                progress:['标的核心资料通过初步核验','核心资产资料进入初步核验后的条款磋商阶段，交易条件仍在讨论。','仍需完成内部审议及交割条件核验，最终结果尚未确认。'],
                uncertain:['标的权属资料需补充核验','部分资产权属资料存在待补充事项，交易各方正在核对交割条件。','尽调结论及交易去向尚未确定。'],
                positive:['交易审议通过，进入交割准备','尽调及内部审议通过，交易各方确认本阶段条件达成。','下一步按约定推进交割准备。'],
                negative:['因交割条件未达成终止推进','交易各方未就本阶段交割条件达成一致，本轮交易停止推进。','本次交易程序终止。']
            }),
            supply:()=>({
                project:pick(identity,[`${b.resources}备用渠道验证项目`,`${b.resources}采购衔接项目`]),
                source:'公司采购保障公告',background:`公司为降低${b.resources}单一来源采购风险，对备用渠道及交付衔接方案进行验证。`,
                scheduled:['启动备用渠道评审','采购团队启动备用渠道资质评审，准备开展交付适配核验。','下一步验证交付能力，整体调整结果尚未确定。'],
                progress:['备用渠道通过本轮适配核验','备用渠道的本轮资质与适配核验通过，交付衔接测试继续推进。','最终切换方案仍需验收，整体调整结果尚未确认。'],
                uncertain:['交付衔接测试出现待核验事项','备用渠道测试中出现交付适配问题，采购团队要求补充验证。','后续需复核衔接方案，最终结果待核实。'],
                positive:['切换方案通过验证','备用渠道及交付衔接方案通过本阶段验证，达到采购保障目标。','后续依照验证方案衔接采购与交付。'],
                negative:['切换方案未通过验收','备用渠道的交付衔接未达到验收要求，本轮切换方案未获通过。','本轮替代方案未获采用，采购保障需另作安排。']
            }),
            governance:()=>({
                project:pick(identity,['关联交易审批专项核查','采购授权与合同审批专项核查']),
                source:'公司内部控制核查公告',background:'公司按内控程序核验审批记录与授权链条，本轮核查不预设存在违规。',
                scheduled:['启动审批记录抽查','核查组开始抽查授权记录、审批文件与执行凭证。','资料核验后形成核查结论，最终结果尚未确认。'],
                progress:['本轮审批资料核验通过','本轮抽查资料满足核验要求，其余执行凭证仍在复核。','核查结论尚未确认，仍需完成剩余资料复核。'],
                uncertain:['部分审批留痕需补充核验','部分执行凭证与授权记录需进一步核对，相关部门正在补充材料。','最终核查结论尚未确认，不能据此提前认定违规。'],
                positive:['核查结束，未发现重大审批缺陷','本轮核查结束，抽查范围内未发现需进一步处理的重大审批缺陷。','专项核查结束并归档本轮核查记录。'],
                negative:['发现审批留痕缺陷并下发整改清单','核查发现审批留痕不完整，相关部门收到整改要求。','相关部门按整改清单补齐审批留痕。']
            }),
            refinancing:()=>({
                project:pick(identity,['存量流动资金借款续作项目','到期授信置换申请项目']),
                source:'公司融资进度公告',background:'公司为衔接存量债务到期安排，向授信机构提交融资续作申请。',
                scheduled:['提交授信续作申请','授信机构接收续作申请，开始审核经营与偿债资料。','授信评审尚未结束，续作结果尚未确认。'],
                progress:['续作材料通过本轮审核','授信机构接受本轮申报资料，额度及执行条件仍在评审。','仍需最终授信审批，续作结果尚未确认。'],
                uncertain:['授信评审要求补充担保资料','评审环节要求补充担保及偿债安排材料，续作条件仍在核对。','补充核验后再作审批，最终结果尚未确定。'],
                positive:['续作方案获授信审批','授信机构通过本阶段续作方案，后续提款与衔接按约定推进。','后续按授信条件安排提款及到期衔接。'],
                negative:['续作申请未获通过','授信机构未通过本次续作申请，原定融资衔接目标未能达成。','相关融资安排需另行协商。']
            }),
            cyber:()=>({
                project:pick(identity,['核心业务系统故障处置','业务数据访问异常排查']),
                source:'公司运行事件通报',background:`公司围绕${b.product}相关业务平台的运行异常启动排查。`,
                scheduled:['启动异常访问排查','运维团队启动日志核验与备用资源检查，尚未形成最终结论。','排查结果尚未确认，下一步核验受影响范围。'],
                progress:['备用资源切换测试通过','运维团队验证了备用服务路径，异常排查仍在推进。','整体处置结果尚未确认，仍需核验业务恢复情况。'],
                uncertain:['异常范围仍需进一步核验','排查发现部分访问记录需补充核对，运维团队扩大核验范围。','受影响范围及最终处置结果尚未确认。'],
                positive:['异常排查完成，服务路径恢复','本阶段排查及恢复验证通过，达到本轮运行保障目标。','业务团队按恢复方案核验后续运行情况。'],
                negative:['系统异常影响业务处理，启动恢复处置','本轮系统异常影响部分业务处理，运维团队启动备用路径与恢复处置。','运维团队继续核验服务恢复情况。']
            }),
            weather:()=>({
                project:pick(identity,[`${b.site}强降雨应对`,`${b.site}高温运行保障`]),
                source:'公司业务保障通报',background:`公司围绕${b.site}的天气风险启动业务保障安排。`,
                scheduled:['启动天气风险排查','保障人员检查重点作业环节与备用资源，准备应对天气影响。','实际影响尚未确认，下一步核验保障安排。'],
                progress:['备用保障方案通过本轮检验','保障团队的备用方案通过本轮检查，重点作业环节继续排查。','整体应对效果尚未确认，仍需后续核验。'],
                uncertain:['部分业务保障环节仍待核验','排查中有配套资源需进一步确认，保障团队正在补充检查。','最终应对效果尚未确定。'],
                positive:['业务保障安排通过验证','本阶段保障方案通过验证，达到天气风险应对目标。','保障团队转入后续运行巡检。'],
                negative:['天气影响部分作业，启动应急保障','相关场所受天气影响，部分作业受到干扰，保障团队启动应急衔接。','保障团队继续核验作业恢复情况。']
            })
        };
        scene=scenes[row.kind]();
     }else if(['debt_calendar','debt_maturity','unlock_calendar','unlock','risk_warning','liquidation'].includes(row.kind)){
        const data={
            debt_calendar:['本期到期债务衔接','公司债务日程公告','公司按债务到期日程筹备资金衔接。','启动到期融资衔接准备','本期债务将在五个交易日后进入到期窗口。','最终衔接结果尚未确认，待到期安排披露。'],
            debt_maturity:['本期到期债务衔接','公司债务安排公告','本期融资按到期日程进入偿付及续作安排。',/出现缺口/u.test(row.headline)?'到期融资出现衔接缺口':'完成到期债务衔接',/出现缺口/u.test(row.headline)?'本期到期融资未能完成全部衔接，偿债压力上升。':'本期到期债务安排完成。','不将融资缺口自行解释为破产或监管处罚。'],
            unlock_calendar:['本期限售股份解禁','公司股份流通日程公告','限售股按公开解禁日程办理后续流通安排。','公布近期解禁日程','部分限售股份计划在三个交易日后解禁。','实际执行结果尚未确认，解禁不等同于股东已减持。'],
            unlock:['本期限售股份解禁','公司股份流通公告','限售股份按已公告日程进入可流通安排。','已公告限售股份进入流通','本期限售股份按已公告安排进入流通。','股份解禁不等同于股东已卖出股份。'],
            risk_warning:['股票风险警示安排','公司风险警示公告','风险警示按本市场已披露的经营与财务条件执行。',/解除风险警示/u.test(row.headline)?'解除风险警示':'实施风险警示',/解除风险警示/u.test(row.headline)?'已披露的经营与财务条件改善，本轮解除风险警示。':'已披露的财务条件触及风险警示标准，本轮实施风险警示。','风险警示安排不代表对后续股价作出判断。'],
            liquidation:/准备期/u.test(row.headline)?['清算准备安排','公司清算准备公告','公司按已披露条件启动清算准备。','进入清算准备期','公司进入已公告的清算准备窗口，实际清算尚未完成。','后续回收金额与终止交易以完成公告为准。']:['本期清算及终止交易安排','公司清算公告','清算按本市场已确认的处置安排执行。','清算完成并终止股票交易','本期清算完成，股票终止交易；回收金额以披露数据为准。','本次清算结束，不延伸推断其他公司的风险。']
        };
        const [project,source,background,action,development,next]=data[row.kind];
        scene={project,source,background,[stage]:[action,development,next]};
    }else if(row.kind==='earnings'){
        const change=String(row.facts?.['相对原盈利预期变化']??'');
        const value=Number(change.replace(/%$/u,'')),direction=value<0?'下调':value>0?'上调':'更新';
        scene={project:'本期经营测算报告',source:'公司经营报告',background:'公司以本期经营测算为依据调整未来盈利预期，调整对象为预期而非已实现利润。',release:[`${direction}盈利预期并发布经营测算报告`,'本期报告更新了未来盈利测算基准，具体变动幅度见披露数据。','本次预期变动不等同于已实现利润变化。']};
    }else return undefined;
    const step=stage==='realized'?['本阶段经营影响计入结束','本事件对应的阶段性经营影响计入结束。','本轮事项的阶段性兑现结束。']:
        stage==='unexpected'?scene.negative:(scene[outcome??stage]??scene[stage]);
    if(!step)return undefined;
    return {version:EVENT_REPORT_VERSION,subject:{code,name,industry,sector},project:scene.project,source:scene.source,
        background:scene.background,action:step[0],development:step[1],next:step[2],stage,
        lead:`${name}（${code}）${step[0]}`};
}
