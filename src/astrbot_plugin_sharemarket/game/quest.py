"""Natural-day quests; progress, claim markers and reward credit are atomic."""
import json
import time
from .atomic import atomic
from .clock import day_key
CHECKIN_BASE_REWARD=100

class QuestService:
    def __init__(self,db):self.db=db
    async def ensure_schema(self):
        await self.db.conn.execute("CREATE TABLE IF NOT EXISTS user_quests(user_id TEXT PRIMARY KEY,checkin_streak INTEGER NOT NULL DEFAULT 0,last_checkin_ts INTEGER NOT NULL DEFAULT 0,daily_task_progress TEXT NOT NULL DEFAULT '{}')")
        await self.db.conn.execute('CREATE TABLE IF NOT EXISTS quest_days(user_id TEXT PRIMARY KEY,day_ts INTEGER NOT NULL)')
    @atomic
    async def enable(self,user_id):
        if not await self.db.get_account(user_id):raise ValueError('请先开户。')
        await self.db.conn.execute("INSERT OR IGNORE INTO user_quests(user_id) VALUES(?)",(user_id,))
        await self.settle_day(user_id)
        return {'ok':True,'msg':'quest enabled'}
    @atomic
    async def settle_day(self,user_id):
        today=day_key()
        old=await (await self.db.conn.execute('SELECT day_ts FROM quest_days WHERE user_id=?',(user_id,))).fetchone()
        if old and old['day_ts']==today:return {'ok':True,'already_settled':True}
        await self.db.conn.execute("UPDATE user_quests SET daily_task_progress='{}' WHERE user_id=?",(user_id,))
        await self.db.conn.execute('INSERT INTO quest_days VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET day_ts=excluded.day_ts',(user_id,today))
        return {'ok':True,'reset':True}
    async def status(self,user_id):
        row=await (await self.db.conn.execute('SELECT * FROM user_quests WHERE user_id=?',(user_id,))).fetchone()
        return {'ok':True,**dict(row)} if row else {'ok':False,'error':'请先开户并签到。'}
    @atomic
    async def handle_checkin(self,user_id):
        await self.enable(user_id);status=await self.status(user_id);now=int(time.time());today=day_key(now)
        if status['last_checkin_ts']>=today:return {'ok':False,'reward':0,'error':'今日已签到。','reason':'already_checkined_today'}
        streak=status['checkin_streak']+1 if status['last_checkin_ts']>=today-86400 else 1
        reward=100+(streak-1)*50 if streak<=10 else 800
        await self.db.conn.execute('UPDATE user_quests SET checkin_streak=?,last_checkin_ts=? WHERE user_id=?',(streak,now,user_id))
        await self.db.grant_cash(user_id,reward,'checkin')
        return {'ok':True,'reward':reward,'new_streak':streak,'credited':True,'msg':f'签到成功，获得{reward}金币，连续{streak}天'}
    @atomic
    async def get_daily_tasks(self,user_id):
        await self.enable(user_id)
        progress=json.loads((await self.status(user_id))['daily_task_progress'])
        definitions=[('trade_count','完成交易',3,'笔',50),('position_count','同时持有不同股票',2,'只',100),('use_prop','使用道具',1,'次',50),('view_leaderboard','查看榜单',1,'次',50)]
        return [{'task_id':key,'title':title,'description':title,'target':target,'unit':unit,'reward':reward,'progress':min(target,progress.get(key,0)),'completed':progress.get(key,0)>=target,'claimed':bool(progress.get(key+'_claimed'))} for key,title,target,unit,reward in definitions]
    @atomic
    async def submit_task(self,user_id,task_id,proof=None):
        await self.enable(user_id)
        tasks={t['task_id']:t for t in await self.get_daily_tasks(user_id)}
        if task_id not in tasks:return {'ok':False,'reward':0,'error':'未知任务。'}
        task=tasks[task_id];progress=json.loads((await self.status(user_id))['daily_task_progress']);proof=proof or {}
        if task_id=='position_count':
            # Actual holdings are the authority; visiting a page never increases them.
            actual=len(await self.db.get_positions(user_id));value=max(progress.get(task_id,0),actual)
        elif task_id=='trade_count':value=progress.get(task_id,0)+max(0,min(1,int(proof.get('trade_count',0))))
        elif task_id=='use_prop':value=progress.get(task_id,0)+max(0,min(1,int(proof.get('use_count',0))))
        else:value=1
        progress[task_id]=min(value,task['target'])
        reward=task['reward'] if value>=task['target'] and not progress.get(task_id+'_claimed') else 0
        if reward:
            progress[task_id+'_claimed']=True
            await self.db.grant_cash(user_id,reward,'quest')
        await self.db.conn.execute('UPDATE user_quests SET daily_task_progress=? WHERE user_id=?',(json.dumps(progress),user_id))
        return {'ok':True,'reward':reward,'credited':True,'progress':progress[task_id],'target':task['target'],'completed':value>=task['target'],'claimed':bool(progress.get(task_id+'_claimed'))}
    @atomic
    async def claim_task_reward(self,user_id,task_id):
        tasks={t['task_id']:t for t in await self.get_daily_tasks(user_id)}
        task=tasks.get(task_id)
        if not task or not task['completed']:return {'ok':False,'reward':0,'error':'任务未完成。'}
        if task['claimed']:return {'ok':False,'reward':0,'error':'奖励已到账。'}
        return await self.submit_task(user_id,task_id,{})
    async def get_user_quest_info(self,user_id):
        tasks=await self.get_daily_tasks(user_id)
        return {'ok':True,'quest_info':await self.status(user_id),'daily_tasks':tasks}
