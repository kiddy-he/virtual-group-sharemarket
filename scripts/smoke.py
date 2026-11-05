#!/usr/bin/env python3
"""Isolated two-process acceptance test. No production data or chat connection."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from astrbot_plugin_sharemarket.client import request

ACTOR={'senderId':'700000001','accountId':'bot','scope':'private','identity':'admin','nickname':'示例玩家'}

def main():
    children=[]
    with tempfile.TemporaryDirectory(prefix='virtual-market-smoke-') as tmp:
        root=Path(tmp);config=root/'market.json'
        config.write_text(json.dumps({'modelVersion':'causal-v2','modelSeed':181,'npcTrading':False,'rules':{'market_mode':'247','tick_seconds':3,'day_seconds':1200,'market_paused':True,'auction_enabled':False,'npc_count':0,'trade_cooldown_seconds':0}}))
        def start(name):
            log=(root/f'{name}.log').open('ab')
            process=subprocess.Popen([sys.executable,'-m','astrbot_plugin_sharemarket.runtime','serve','--state-dir',str(root/name),'--market-id',name,'--config',str(config)],stdout=log,stderr=log)
            log.close();children.append(process)
            until=time.monotonic()+30
            while time.monotonic()<until:
                if process.poll() is not None:raise AssertionError('Temporary market exited before readiness')
                try:
                    if request(str(root/name/'runtime.sock'),{'method':'health'},timeout=1)['ok']:return process
                except (OSError,ValueError,RuntimeError,TimeoutError):pass
                time.sleep(.05)
            raise AssertionError('Temporary market did not become ready')
        def call(name,method,params=None,op=None,**extra):
            body={'method':method,**extra}
            if params is not None:body.update(params=params,actor=ACTOR,operation_id=op)
            result=request(str(root/name/'runtime.sock'),body)
            assert result.get('ok'),f'{method} failed in temporary market'
            return result
        def stop(p):
            if p.poll() is None:p.terminate()
            try:p.wait(timeout=35)
            except subprocess.TimeoutExpired:p.kill();p.wait();raise
            assert p.returncode==0,'Unclean temporary market shutdown'
        try:
            a=start('alpha');start('beta')
            assert call('alpha','health')['pid']!=call('beta','health')['pid']
            call('alpha','account',{'action':'open'},'open-alpha')
            call('beta','account',{'action':'open'},'open-beta')
            original=call('alpha','trade',{'action':'buy','code':'600003','quantity':100},'trade-alpha')
            assert original==call('alpha','trade',{'action':'buy','code':'600003','quantity':100},'trade-alpha')
            alpha=call('alpha','account',{'action':'funds'},'funds-alpha')
            beta=call('beta','account',{'action':'funds'},'funds-beta')
            assert alpha['private'] and alpha['data']['cash_available']<beta['data']['cash_available']
            chart=call('alpha','query',{'action':'overview'},'chart-alpha')
            files=chart.get('artifacts') or [chart.get('artifact')]
            assert len(files)>1 and all(p and Path(p).is_file() and Path(p).read_bytes().startswith(b'\x89PNG\r\n\x1a\n') for p in files)
            help_card=call('alpha','query',{'action':'help'},'help-alpha')
            assert Path(help_card['artifact']).is_file()
            recovered=call('alpha','result',id='trade-alpha',actor=ACTOR)
            assert recovered==original
            mismatch=request(str(root/'alpha/runtime.sock'),{'method':'result','id':'trade-alpha','actor':{**ACTOR,'senderId':'700000002'}})
            assert mismatch['ok'] is False
            call('alpha','ack',id='trade-alpha',actor=ACTOR,receipt={'message_id':'synthetic-receipt'})
            stop(a);start('alpha')
            assert call('alpha','trade',{'action':'buy','code':'600003','quantity':100},'trade-alpha')==original
            after=call('alpha','account',{'action':'funds'},'funds-after-restart')
            assert after['data']['cash_available']==alpha['data']['cash_available']
            audit=call('alpha','admin',{'action':'audit'},'audit-alpha')
            assert audit['data']['ok']
            print(json.dumps({'status':'passed','markets':2,'chart_pages':len(files),'checks':['owned sockets','separate processes','idempotent buy','private funds','market isolation','all chart pages','generic help','actor-bound recovery','delivery ACK','restart recovery','ledger audit']},ensure_ascii=False))
        finally:
            for p in children:
                if p.poll() is None:stop(p)

if __name__=='__main__':main()
