import pytest,threading,os,sys,time
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tradingview_webhook_bot.storage.signal_queue import DurableSignalQueue
from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore

class TestQueueConcurrency:
    def test_parallel_enqueue(self,tmp_path):
        q=DurableSignalQueue(str(tmp_path/'q.db'))
        errs=[]
        def enq(i):
            try:
                if not q.enqueue({'signal_id':f's{i}','payload':{'i':i}}): errs.append(i)
            except Exception as e: errs.append(str(e))
        ts=[threading.Thread(target=enq,args=(i,)) for i in range(50)]
        for t in ts: t.start()
        for t in ts: t.join()
        assert len(errs)==0
        assert q.get_stats().get('pending',0)==50

class TestIdempotencyConcurrency:
    def test_parallel_mark(self,tmp_path):
        s=IdempotencyStore(str(tmp_path/'i.db'))
        errs=[]
        def mk(i):
            try: s.mark_seen(f's{i}',f'o{i}')
            except Exception as e: errs.append(str(e))
        ts=[threading.Thread(target=mk,args=(i,)) for i in range(50)]
        for t in ts: t.start()
        for t in ts: t.join()
        assert len(errs)==0
        for i in range(50): assert s.is_seen(f's{i}')
