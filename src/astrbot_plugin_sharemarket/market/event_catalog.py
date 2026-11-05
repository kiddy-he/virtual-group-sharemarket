"""Versioned public event vocabulary and economic channels; no outcomes or world state.

Six subtypes in each of twelve families. Projects, evidence and disclosed stages
are market-world facts, not claims about real issuers. Capital proposals only
model their preparation costs; actual shares/dividends remain corporate actions.
"""
from dataclasses import dataclass

CATALOG_VERSION = 1
@dataclass(frozen=True)
class EventSpec:
    id: str
    category: str
    title: str
    project: str
    evidence: str
    positive: str
    negative: str
    channel: str
    industries: tuple = ()

CATEGORIES = {
 'macro':('宏观与政策','市场政策安排公告','公开政策安排的适用范围与执行条件','需求与融资条件'),
 'industry':('行业周期','行业运行调查公报','行业订单、库存与产销衔接','行业需求与竞争'),
 'contract':('订单与客户','公司业务进展公告','客户需求及履约能力匹配','收入与履约成本'),
 'supply':('供应链与成本','公司采购保障公告','原料、服务和交付资源的稳定性','采购成本与交付'),
 'research':('研发与产品','公司研发项目公告','技术验证与产品适配需求','研发支出与产品收益'),
 'capacity':('产能与投资','公司投资进展公告','既有设施和新增业务需求的衔接','投资支出与产能收益'),
 'earnings_event':('财报与经营','公司经营事项公告','经营质量与资产回收情况','经营利润与资产损失'),
 'refinancing':('融资与信用','公司融资进度公告','到期资金安排与授信条件','融资费用与信用风险'),
 'capital':('股权与资本运作','公司资本安排公告','资本方案的审议和可行性核验','方案筹备费用'),
 'acquisition':('并购与战略','公司交易事项公告','业务边界调整及合作条件','交易费用与整合收益'),
 'governance':('治理与法律','公司治理事项公告','授权、合规与交易凭证的核验','整改及法律成本'),
 'incident':('安全与外部冲击','公司运行保障通报','异常影响范围及业务连续性','停工损失与恢复费用'),
}
SPECS = {}
def group(category, rows):
    for row in rows:
        identity,title,project,evidence,positive,negative,channel,*tags=row
        SPECS[identity]=EventSpec(identity,category,title,project,evidence,positive,negative,channel,tuple(tags))

group('macro', [
 ('fiscal_project','公共投资安排','区域公共服务采购配套方案','执行预算与采购适用范围','配套采购条件通过核验','配套采购安排缩减实施范围','demand'),
 ('consumer_support','消费支持安排','终端服务消费支持衔接方案','渠道适用范围与服务核销条件','服务衔接方案通过执行评审','核销条件未完成衔接','demand'),
 ('trade_facilitation','跨境通关安排','跨境业务便利化试点方案','通关材料与服务流程','试点服务流程通过核验','试点材料仍未满足执行条件','trade'),
 ('credit_program','专项融资安排','专项经营融资支持衔接方案','适用主体与授信核验条件','融资服务衔接条件核验通过','融资支持衔接条件未获确认','credit'),
 ('energy_transition','能源改造安排','节能改造配套服务方案','改造范围与设备适配记录','设备适配与服务条件审核通过','改造服务安排未通过适配评审','cost'),
 ('data_infrastructure','公共数据设施安排','数据基础设施服务衔接方案','接口规范与运行保障条件','服务接口通过联合验证','接口衔接未达到本轮验证要求','investment'),
])
group('industry', [
 ('inventory_cycle','行业库存周期','行业库存周转调查','库存消化与渠道补货记录','渠道去库存取得阶段进展','库存消化慢于本轮调查预期','demand'),
 ('price_competition','行业价格竞争','行业产品定价协调评估','终端报价与成交条款记录','产品定价与服务差异化方案通过评估','同业竞价压缩原有服务空间','cost'),
 ('capacity_exit','行业产能调整','低效产能整合观察','行业供给与设备使用记录','低效供给退出获得阶段确认','原定供给调整未完成落实','capacity'),
 ('demand_recovery','行业需求变化','重点渠道需求回访','渠道询单与需求复核记录','渠道新增需求通过订单核验','渠道需求回访未形成有效补单','demand'),
 ('standards_change','行业标准更新','行业服务标准切换','标准条款及适配检验记录','标准适配获得阶段认可','部分服务未达到新适配要求','compliance'),
 ('channel_shift','行业渠道迁移','渠道结构与交付方式调整','线上线下渠道及履约适配记录','新渠道交付方式通过验证','渠道切换出现服务衔接缺口','trade'),
])
group('contract', [
 ('large_order','重点项目竞标','{business}重点采购竞标项目','技术评标材料与履约资质','获得本项目中标确认','未获得本项目中标资格','order'),
 ('customer_renewal','客户续约','{business}存量客户续约项目','服务验收与续约条款','存量客户确认续约条件','客户未接受本轮续约方案','order'),
 ('order_cancellation','订单变更磋商','{business}订单变更协商项目','变更请求及双方履约责任','双方确认继续按修订条款履约','客户确认取消本轮订单安排','order'),
 ('delivery_acceptance','交付验收','{business}交付验收项目','交付清单与验收测试记录','本轮交付通过客户验收','交付未达到约定验收条件','order'),
 ('new_channel','新增销售渠道','{business}新渠道准入项目','渠道准入与售后服务方案','取得新渠道准入确认','渠道合作未通过本轮准入审核','trade'),
 ('payment_collection','客户回款','{business}客户账款核对项目','结算凭证及争议账款清单','客户确认本轮结算与付款安排','部分争议账款未完成回收安排','receivables'),
])
group('supply', [
 ('alternate_supplier','备用供应商','{resource}备用渠道验证项目','供应商资质及交付样本','备用渠道通过最终切换验收','替代渠道未达到本轮交付要求','cost'),
 ('raw_material_price','原料采购议价','{resource}采购议价项目','报价单与年度采购条款','本轮议价形成可执行采购条件','本轮采购条件未能维持原定成本目标','cost'),
 ('supply_interruption','供应恢复','{resource}供给恢复项目','供给中断记录与恢复计划','受影响供给通过恢复验证','原定恢复计划未完成执行','disruption'),
 ('logistics_route','物流路线调整','{resource}运输路线衔接项目','路线运力与交付时效记录','替代运输路线通过交付验证','替代路线未达到交付时效要求','logistics'),
 ('energy_procurement','能源采购','{resource}能源配套采购项目','能源服务合同与保障安排','能源服务条件完成衔接','能源服务安排未完成保障核验','cost'),
 ('local_substitution','本地替代适配','{resource}本地采购适配项目','适配样本及质量一致性检验','本地替代方案通过适配验收','替代样本未达到一致性要求','investment'),
])
group('research', [
 ('prototype_validation','样机验证','{product}样机验证项目','样机性能及测试条件记录','样机通过阶段验证','样机未达到本轮性能目标','research'),
 ('pilot_yield','试生产良率','{product}试生产一致性项目','试生产批次及质量检验记录','试生产一致性达到验收标准','试生产一致性未达到验收标准','research','manufacturing'),
 ('product_launch','新品上市准备','{product}上市适配项目','产品合规与渠道适配资料','完成本阶段上市适配准备','上市适配未完成本轮准备目标','research'),
 ('technology_license','技术授权','{product}技术授权核验项目','授权边界及知识产权凭证','技术授权条款核验通过','授权边界未能完成核验','research'),
 ('clinical_validation','医药阶段验证','{product}研究方案阶段核验','合规审查与阶段研究记录','本阶段研究核验目标达成','本阶段研究未达到既定核验目标','research','pharma'),
 ('software_release','软件版本验证','{product}新版本适配项目','接口回归及试用服务记录','新版本通过本轮适配验收','新版本未达到稳定性要求','research','digital'),
])
group('capacity', [
 ('new_line','新增产线','{product}配套产线建设项目','施工计划与设备交付清单','本阶段设施验收通过','设施验收未达到阶段建设要求','investment','manufacturing'),
 ('facility_upgrade','设施升级','{business}服务设施升级项目','设施改造与连续服务方案','服务设施完成升级验收','改造未达到连续服务要求','investment'),
 ('maintenance','设备检修','{product}设备检修项目','检修清单与复机检验记录','重点设备通过复机检验','部分设备未能按计划复机','disruption','manufacturing'),
 ('automation','流程自动化','{business}自动化流程改造项目','流程测试与岗位衔接记录','自动化流程通过运行验收','自动化流程未满足适配要求','investment'),
 ('investment_overrun','投资预算复核','{business}投资预算复核项目','工程变更与采购预算记录','修订预算与交付安排通过审核','追加预算未通过本轮审议','investment'),
 ('capacity_lease','产能租赁','{business}配套服务租赁项目','租赁期限与可用服务能力','租赁安排完成能力核验','租赁资源未达到可用能力要求','capacity'),
])
group('earnings_event', [
 ('earnings_guidance','经营预告复核','本期经营预告口径复核','合同确认及预告测算底稿','经营测算支持本轮预告口径','部分测算未能支持原预告口径','order'),
 ('margin_review','成本利润复核','{business}成本与利润率复核','收入成本匹配与费用归集资料','成本归集复核达到预设改进目标','成本压力未能完成原定消化目标','cost'),
 ('inventory_impairment','存货减值核验','{resource}库存可回收性核验','库存账龄及可回收金额评估','存货处置方案通过核验','部分存货需确认回收损失','impairment','manufacturing'),
 ('receivable_risk','应收账款核验','{business}应收款可回收性核验','账款确认函及结算争议记录','重点应收款核验及回收安排达成','部分账款未达到可回收性要求','receivables'),
 ('asset_disposal','资产处置','{business}非核心资产处置评估','资产权属及转让评估材料','非核心资产处置条件确认','本轮资产处置条件未能达成','impairment'),
 ('business_restructuring','业务结构调整','{business}经营结构调整项目','业务成本与服务能力评估','本阶段业务衔接目标达成','业务衔接未实现阶段调整目标','capacity'),
])
group('refinancing', [
 ('credit_renewal','授信续作','存量经营授信续作项目','偿债资料与授信续作条件','本阶段授信续作审批通过','授信续作申请未获通过','credit'),
 ('bond_preparation','发债准备','经营债务工具申报准备','偿债能力及发行申报资料','本轮申报准备审议通过','本轮申报准备未通过审核','credit'),
 ('debt_extension','债务展期','到期债务展期协商项目','展期期限及偿付安排','债权方确认本轮展期条款','本轮债务展期未达成一致','credit'),
 ('guarantee_review','担保风险复核','关联担保责任核验项目','担保合同及被担保方偿付凭证','核验确认本轮担保责任已妥善衔接','核验发现待履行担保责任','credit'),
 ('credit_restructuring','信用重组','经营债务重组方案核验','债权清单及重组协议条件','本阶段重组条件获债权方确认','重组安排未获本轮债权方确认','credit'),
 ('default_remediation','逾期偿付处置','逾期经营债务处置协商','逾期凭证及补充偿付安排','补充偿付方案完成本阶段核验','逾期资金缺口未完成衔接','credit'),
])
group('capital', [
 ('buyback_proposal','回购方案审议','股份回购方案可行性审议','资金来源与方案授权条件','本轮方案可行性审议通过','方案未通过本轮可行性审议','proposal'),
 ('dividend_proposal','分红方案论证','利润分配方案前期论证','可分配利润与偿债约束口径','本轮分配方案论证完成','本轮分配方案未形成审议结论','proposal'),
 ('placement_proposal','融资方案筹备','股权融资方案前期筹备','用途论证与股东授权条件','本阶段方案筹备审议通过','方案筹备未通过本轮审议','proposal'),
 ('shareholder_plan','股东持股安排','股东持股安排披露核验','披露文件及适用交易约束','持股安排披露核验通过','持股安排需重新补充披露','proposal'),
 ('control_review','控制权方案核验','控制权安排可行性核验','协议条件及治理衔接资料','本阶段控制权方案核验通过','本轮控制权方案未完成核验','proposal'),
 ('lockup_extension','限售承诺核验','股东限售承诺核验','限售期限与承诺文件','本轮限售承诺完成核验','限售承诺文件未完成核验','proposal'),
])
group('acquisition', [
 ('business_acquisition','业务收购','{business}业务收购项目','尽调材料与资产交割条件','交易条件获本阶段审议确认','交割条件未达成并终止推进','integration'),
 ('business_sale','业务出售','{business}非核心业务出售项目','权属资料与业务交接安排','业务出售条件获本阶段确认','业务出售条件未能达成一致','integration'),
 ('joint_venture','合资合作','{business}合资服务项目','出资约定与合作治理安排','合资合作条件获本阶段确认','合作方未就本阶段条件达成一致','integration'),
 ('integration_review','整合进度复核','{business}业务整合验收项目','系统迁移与客户服务衔接记录','本阶段业务整合验收通过','业务整合未达到服务衔接目标','integration'),
 ('strategic_partner','战略合作','{business}战略合作衔接项目','合作范围与履约责任边界','本阶段合作衔接条件确认','合作衔接条件未能完成确认','order'),
 ('market_exit','区域业务调整','{business}区域服务调整项目','客户迁移与资产处置安排','区域业务调整完成阶段衔接','区域业务调整出现衔接缺口','integration'),
])
group('governance', [
 ('audit_review','审计事项核验','年度审计证据补充核验','审计凭证及管理层补充说明','本轮证据核验未发现重大缺陷','本轮核验发现需整改的证据缺陷','compliance'),
 ('regulatory_inquiry','问询事项回复','经营事项问询回复核验','问询清单与对应事实依据','本轮回复材料核验通过','问询回复需补充关键证据','compliance'),
 ('litigation','合同争议处置','{business}合同争议处置项目','合同履约凭证及争议请求','本阶段争议处置条件达成','本阶段争议处理产生不利确认','legal'),
 ('compliance_rectification','合规整改','{business}合规执行整改项目','整改清单与复核证据','整改通过本阶段复核','整改未达到本轮复核要求','compliance'),
 ('management_change','管理职责交接','经营管理职责交接核验','授权文件及岗位衔接清单','经营管理职责完成交接核验','部分管理职责未完成交接','compliance'),
 ('related_party_review','关联交易核验','关联交易授权专项核验','定价依据与交易审批凭证','抽查范围内未发现重大授权缺陷','抽查发现授权或定价凭证缺陷','legal'),
])
group('incident', [
 ('extreme_weather','极端天气保障','{business}天气风险保障项目','天气影响与备用保障记录','本阶段天气影响处置完成核验','天气影响导致部分业务恢复未达目标','disruption'),
 ('equipment_accident','设备异常处置','{product}设备异常恢复项目','故障检验与复机测试记录','异常设备完成本轮恢复检验','异常设备未能通过本轮复机检验','disruption','manufacturing'),
 ('network_outage','网络故障恢复','{business}业务系统恢复项目','运行日志及备用路径测试记录','业务系统恢复路径通过检验','系统恢复未达到服务连续性要求','disruption','digital'),
 ('data_security','数据访问核验','{business}异常访问处置项目','访问日志与受影响范围核验','异常访问处置通过本轮验证','异常访问影响范围仍有待处置事项','legal'),
 ('public_health','服务连续性保障','{business}人员与服务连续性项目','岗位保障与备用服务安排','服务连续性通过本阶段检验','部分服务未能完成连续性衔接','disruption'),
 ('transport_disruption','运输中断应对','{resource}运输中断恢复项目','受阻运输与替代运力记录','替代运力通过本轮交付验证','替代运力未达到本轮交付需求','logistics'),
])
assert len(SPECS) == 72 and all(sum(s.category == c for s in SPECS.values()) == 6 for c in CATEGORIES)

# Budget is a fraction of public annual FCF, not an arbitrary fraction of price.
# benefit/cost are finite net incremental cash-flow magnitudes relative to that budget.
CHANNELS = {
 'demand':(.10,.45,.35,45,100), 'trade':(.08,.40,.35,35,90),
 'order':(.12,.42,.32,25,80), 'cost':(.08,.38,.42,25,75),
 'logistics':(.07,.25,.50,12,45), 'research':(.16,.55,.50,45,120),
 'investment':(.20,.45,.45,60,150), 'capacity':(.12,.40,.40,35,100),
 'receivables':(.08,.25,.65,20,80), 'impairment':(.10,.15,.70,20,65),
 'credit':(.09,.25,.65,25,90), 'proposal':(.025,0.,.20,8,25),
 'integration':(.16,.40,.50,50,130), 'compliance':(.045,.10,.50,15,50),
 'legal':(.075,.10,.70,20,75), 'disruption':(.065,.10,.80,8,40),
}
ALIASES = {'contract':'large_order','research':'prototype_validation','acquisition':'business_acquisition',
 'governance':'related_party_review','refinancing':'credit_renewal','supply':'alternate_supplier',
 'cyber':'network_outage','weather':'extreme_weather','unlock':'lockup_extension'}
