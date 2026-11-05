"""Expanded public-world lifecycle and economic invariants, no external calls."""
import copy
import json
import unittest
import tempfile
from unittest.mock import patch
import numpy as np
from astrbot_plugin_sharemarket.market.causal_state import create, init_venue, extend, VERSION
from astrbot_plugin_sharemarket.market.stocks import STOCK_POOL
from astrbot_plugin_sharemarket.market.event_catalog import SPECS, CATEGORIES, CHANNELS
from astrbot_plugin_sharemarket.market.event_world import (ensure_event_schema, new_event, eligible,
    subtype_weight, choose_subtype, advance_extended, extended_payment, daily_extended_events)
from astrbot_plugin_sharemarket.market.causal_events import advance_events, cashflows, expected
from astrbot_plugin_sharemarket.market.causal_public import query_public
from astrbot_plugin_sharemarket.game.recovery import encode, decode

class ExtendedWorldTests(unittest.TestCase):
    def setUp(self):
        self.s=create(STOCK_POOL, seed=211);init_venue(self.s);ensure_event_schema(self.s)
    def event(self, subtype='large_order'):
        spec=SPECS[subtype]
        i=next(i for i,industry in enumerate(self.s['profile']['industries']) if eligible(spec,industry))
        return new_event(self.s,i,subtype)
    def resolve(self,e,truth=True,branch=.7):
        e['truth']=truth;self.s['day']=int(e['resolve'])+1
        with patch('astrbot_plugin_sharemarket.market.event_world.rand',side_effect=lambda state,identity,channel=0: .05 if channel==48 else branch):
            advance_extended(self.s,e,self.s['day'])
        self.s['tick']+=2;advance_events(self.s)
    def test_all_72_subtypes_have_public_facts_and_bounded_economics(self):
        self.assertEqual(len(SPECS),72);self.assertEqual(len(CATEGORIES),12)
        for name,spec in SPECS.items():
            e=self.event(name);row=self.s['public_news'][-1]
            self.assertEqual(row['public_detail']['subtype'],name)
            self.assertEqual(row['public_detail']['timeline'][0]['stage'],'scheduled')
            self.assertLessEqual(abs(e['win']),self.s['value'][e['i']]*.03)
            self.assertLessEqual(abs(e['lose']),self.s['value'][e['i']]*.03)
            for secret in ('"truth"','"seed"','"win"','"lose"','"actual"','"q"','"priced_value"'):
                self.assertNotIn(secret,json.dumps(row))
    def test_eligibility_and_state_weighting(self):
        for name in ('new_line','pilot_yield','equipment_accident','inventory_impairment'):
            self.assertFalse(eligible(SPECS[name],'银行'))
        self.assertFalse(eligible(SPECS['clinical_validation'],'软件'))
        self.assertTrue(eligible(SPECS['clinical_validation'],'创新药'))
        i=0;spec=SPECS['credit_renewal'];base=subtype_weight(self.s,i,spec)
        self.s['distress'][i]=1
        self.assertGreater(subtype_weight(self.s,i,spec),base)
    def test_cooldown_is_company_type_category_and_scope_specific(self):
        e=self.event('large_order');i=e['i'];code=self.s['profile']['codes'][i]
        self.assertEqual(self.s['event_cooldowns']['type:'+code+':large_order'],90)
        for day in (0,8,20):
            self.s['day']=day
            self.assertNotEqual(SPECS[choose_subtype(self.s,i)].category,'contract')
        self.event('trade_facilitation');self.assertIn('scope:全市场:macro',self.s['event_cooldowns'])
    def test_public_rows_are_immutable_and_calendar_uses_only_disclosed_plan(self):
        e=self.event();first=copy.deepcopy(self.s['public_news'][0]);e['truth']=True
        self.s['day']=1
        with patch('astrbot_plugin_sharemarket.market.event_world.rand',return_value=.4):advance_extended(self.s,e,e['next']+.01)
        self.assertEqual(first,self.s['public_news'][0])
        rows=query_public(self.s,'calendar',{},None)['data']
        planned=next(x for x in rows if x.get('event_id')==e['id'])
        self.assertEqual(planned['day'],e['public_detail']['planned_day'])
        self.assertNotIn('truth',json.dumps(rows))
    def test_delay_is_bounded_then_resolves(self):
        e=self.event()
        with patch('astrbot_plugin_sharemarket.market.event_world.rand',return_value=.05):
            for _ in range(3):
                self.s['day']=int(e['resolve'])+1;advance_extended(self.s,e,self.s['day'])
        self.assertTrue(e['resolved']);self.assertEqual(e['delays'],2)
        self.assertEqual(self.s['event_statistics']['delayed'],2)
    def test_partial_termination_and_reopening(self):
        e=self.event();self.resolve(e,True,.25);self.assertEqual(e['outcome'],'partial')
        self.assertGreater(e['actual'],0);self.assertLess(e['actual'],e['win'])
        failed=self.event('technology_license');self.resolve(failed,False,.25)
        self.assertEqual(self.s['public_news'][-1]['stage'],'terminated')
        self.assertTrue(self.s['event_followups'])
        self.s['events']=[failed];self.s['day']=self.s['event_followups'][0]['day']+2
        with patch('astrbot_plugin_sharemarket.market.event_world.uniform',return_value=np.ones(len(self.s['price']))*.999999):daily_extended_events(self.s)
        restarted=self.s['events'][-1]
        self.assertEqual(restarted['parent_event_id'],failed['id']);self.assertFalse(restarted['resolved'])
        self.assertEqual(restarted['public_detail']['timeline'][0]['stage'],'reopened')
    def test_all_channel_cashflows_are_finite_conservative_and_distinct(self):
        schedules={}
        for channel in CHANNELS:
            name=next(n for n,s in SPECS.items() if s.channel==channel);e=self.event(name)
            self.s['day']=int(e['created'])+1
            prep=extended_payment(self.s,e) or 0
            self.assertLessEqual(prep,0);self.assertEqual(extended_payment(self.s,e),None)
            self.resolve(e);initial=e['cash_paid'];payments=[]
            for _ in range(e['duration']+1):
                self.s['day']+=1;payment=extended_payment(self.s,e)
                if payment is not None:payments.append(payment)
                self.assertAlmostEqual(e['cash_paid']+expected(e),e['actual'])
            self.assertTrue(e['completed']);self.assertAlmostEqual(initial+sum(payments),e['actual'])
            self.assertAlmostEqual(e['priced_value'],0)
            schedules[channel]=payments
        self.assertNotEqual(len(schedules['investment']),len(schedules['disruption']))
        self.assertGreater(schedules['investment'][-1],schedules['investment'][0])
    def test_pending_valuation_deducts_intervening_known_cash_only_once(self):
        e=self.event();queued=self.s['pending_updates'][0]['value'];self.s['day']=1
        payment=extended_payment(self.s,e);self.s['tick']=2;advance_events(self.s)
        self.assertAlmostEqual(e['priced_value'],queued-payment)
    def test_proposals_do_not_execute_shareholder_operations(self):
        shares=self.s['shares'].copy();debt=self.s['debt'].copy();cash=self.s['cash'].copy()
        for name,spec in SPECS.items():
            if spec.category!='capital':continue
            e=self.event(name);self.resolve(e)
            self.assertEqual(e['win'],0);self.assertIn('不等于',e['public_detail']['boundary'])
        np.testing.assert_array_equal(shares,self.s['shares']);np.testing.assert_array_equal(debt,self.s['debt']);np.testing.assert_array_equal(cash,self.s['cash'])
    def test_additive_migration_preserves_legacy_financial_and_random_state(self):
        self.s.pop('event_catalog_version');self.s['profile'].pop('industries');self.s['profile'].pop('names')
        before=copy.deepcopy(self.s);ensure_event_schema(self.s)
        for key in ('price','cash','shares','public_fcf','venue_cash','value'):np.testing.assert_array_equal(before[key],self.s[key])
        self.assertEqual(before['seed'],self.s['seed']);self.assertEqual(self.s['version'],VERSION)
    def test_restart_and_ipo_preserve_public_world_and_remap_exposure(self):
        e=self.event();snapshot=decode(json.loads(json.dumps(encode(self.s))))
        self.assertEqual(json.dumps(encode(snapshot),sort_keys=True),json.dumps(encode(self.s),sort_keys=True))
        # Add an existing catalogue member to an intentionally smaller world.
        codes=list(STOCK_POOL)[:15];small=create({c:STOCK_POOL[c] for c in codes},seed=211);init_venue(small)
        event=new_event(small,0);code=small['profile']['codes'][event['i']]
        grown=extend(small,STOCK_POOL,{c:STOCK_POOL[c].initial_price for c in STOCK_POOL})
        self.assertEqual(grown['profile']['codes'][grown['events'][0]['i']],code)
        self.assertEqual(grown['events'][0]['public_detail'],event['public_detail'])
        self.assertEqual(len(grown['profile']['industries']),len(STOCK_POOL))
    def test_known_prep_cost_does_not_bypass_two_tick_information_staging(self):
        e=self.event();self.s['day']=1;e['next']=10
        self.assertEqual(e['priced_value'],0)
        payment=extended_payment(self.s,e)
        self.assertAlmostEqual(e['priced_value'],-payment)
        self.assertNotAlmostEqual(e['priced_value'],expected(e))
        self.s['tick']=2;advance_events(self.s)
        self.assertAlmostEqual(e['priced_value'],expected(e))
        self.resolve(e);self.s['day']+=1
        paid=extended_payment(self.s,e);self.assertIsNotNone(paid)
        self.assertIsNone(extended_payment(self.s,e))

    def test_legacy_checkpoint_events_use_original_finite_payment_rules(self):
        e=self.event();e.pop('catalog_version');e['type']='contract';e['duration']=2
        e['resolved']=True;e['resolution_day']=0;e['actual']=.1;e['priced_value']=.1
        self.s['pending_updates']=[];self.s['day']=1
        cashflows(self.s);self.assertAlmostEqual(e['priced_value'],.05)
        self.s['day']=2;cashflows(self.s)
        self.assertTrue(e['completed']);self.assertEqual(self.s['events'],[])
        self.assertAlmostEqual(self.s['public_event_cash'][e['i']],.1*self.s['shares'][e['i']])

    def test_broad_exposures_have_bounded_relative_size(self):
        e=self.event('trade_facilitation');anchor=self.s['value'][e['i']]
        self.assertEqual(e['scope'],'market');self.assertEqual(len(e['weights']),len(STOCK_POOL))
        for index,w in e['weights'].items():self.assertLessEqual(abs(w)*anchor/self.s['value'][int(index)],1.200001)

class DurablePublicEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_details_survive_memory_feed_eviction(self):
        from astrbot_plugin_sharemarket.runtime import MarketRuntime
        from astrbot_plugin_sharemarket.game.atomic import mutation
        with tempfile.TemporaryDirectory(prefix='fx-public-event-') as temp:
            r=MarketRuntime(temp,options={'modelVersion':'causal-v2','npcTrading':False,'rules':{'auction_enabled':False,'npc_count':0}})
            await r.start(False)
            try:
                async with mutation(r.db):e=new_event(r.engine.causal,0)
                await r.tick(now=r.clock.started+1)
                r.engine.causal['public_news']=[]
                result=await r.execute({'method':'query','params':{'action':'event','event_id':e['id']},
                    'actor':{'senderId':'700000001','accountId':'default','scope':'private','identity':'admin'},'operation_id':'archive-fixture'})
                self.assertTrue(result['ok']);self.assertEqual(result['data'][0]['event_id'],e['id'])
                self.assertEqual(result['data'][0]['public_detail']['project'],e['public_detail']['project'])
                self.assertNotIn('"truth"',json.dumps(result))
            finally:await r.close()

if __name__=='__main__':unittest.main()
