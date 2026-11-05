#!/usr/bin/env python3
"""Small deterministic numeric check, not a full ledger or calibration study."""
import argparse
import json
import numpy as np
from astrbot_plugin_sharemarket.market.causal_engine import CausalPriceEngine

def run(days,seeds):
    summaries=[]
    for seed in range(1,seeds+1):
        engine=CausalPriceEngine(seed=seed,tick_seconds=30,day_seconds=1200)
        state=engine.causal;prices=[state['price'].copy()]
        for _ in range(days):
            for _ in range(40):engine.tick()
            engine.day_close()
            prices.append(state['price'].copy())
        p=np.asarray(prices);ret=p[1:]/p[:-1]-1
        assert np.isfinite(p).all() and (p>0).all()
        issued=state['venue_inventory'].sum(axis=0)+state['house_inventory']+state['lending_inventory']+state['locked_inventory']
        assert np.array_equal(issued,state['shares'])
        drawdown=1-p/np.maximum.accumulate(p,axis=0)
        summaries.append({'test_seed':seed,'days':days,'companies':p.shape[1],
                          'median_daily_vol_pct':round(float(np.median(np.std(ret,axis=0)))*100,3),
                          'median_max_drawdown_pct':round(float(np.median(drawdown.max(axis=0)))*100,3),
                          'finite_positive_prices':True,'share_conservation':True})
    return {'mode':'numeric-only; no SQL ledger, platform sends or empirical calibration','runs':summaries}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--days',type=int,default=252);parser.add_argument('--seeds',type=int,default=3)
    args=parser.parse_args()
    if not 1<=args.days<=10000 or not 1<=args.seeds<=100:parser.error('days 1..10000 and seeds 1..100 required')
    print(json.dumps(run(args.days,args.seeds),indent=2))
