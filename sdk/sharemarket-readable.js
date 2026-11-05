/** Last boundary before persona generation: structured transport data is not chat copy. */
export const RETIRED_MARKET_ACTIONS=Object.freeze({
    tasks:'每日任务功能已下线，交易进度尚未接通全部成交路径。当前不再记录任务或发放任务奖励。',
    season:'赛季功能已下线，积分统计尚未接通全部成交路径。历史积分与领奖记录保留。',
    claim_season:'赛季功能已下线，当前不再发放赛季奖励。历史积分与领奖记录保留。',
});
const unavailable='这次操作的结果已记录，但暂时无法整理成可读说明。请查询对应功能的当前状态；不要重复提交买卖、购买或领取操作。';
export function readableMarketDraft(value){
    const text=String(value??'').trim();
    const unfenced=text.replace(/^```(?:json)?\s*/u,'').replace(/\s*```$/u,'').trim();
    const embedded=unfenced.search(/[\[{]\s*(?:"[A-Za-z_][A-Za-z_0-9]*"\s*:|\{)/u);
    const candidate=(embedded>=0?unfenced.slice(embedded):unfenced).trim();
    if(!/^[\[{]/u.test(candidate))return {text,projected:false};
    try{
        const data=JSON.parse(candidate);
        if(data&&typeof data==='object'){
            if(data.quest_info||data.daily_tasks)return {text:RETIRED_MARKET_ACTIONS.tasks,projected:true};
            if(data.season_id!==undefined||data.season_name!==undefined)return {text:RETIRED_MARKET_ACTIONS.season,projected:true};
        }
    }catch{/* A partial structured response is equally unsuitable for direct delivery. */}
    return {text:unavailable,projected:true};
}
export function marketRewriteFailure(error){
    if(['AbortError','TimeoutError'].includes(error?.name)||/超时|timed?\s*out/iu.test(String(error?.message??'')))return 'timeout';
    const http=/HTTP\s+(\d{3})/u.exec(String(error?.code??error?.message??''));if(http)return 'http_'+http[1];
    return typeof error?.message==='string'&&/^market_[a-z_]{1,64}$/u.test(error.message)?error.message:'rewrite_unavailable_or_invalid';
}
