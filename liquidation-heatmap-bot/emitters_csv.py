import os
import csv
import threading
from datetime import datetime, timezone
from typing import Dict

class CSVEmitter:
    """Simple CSV emitter that creates files on first write and appends rows.
    Provides insert_decision/insert_order/insert_fill/insert_health/insert_error methods.
    """
    def __init__(self, out_dir: str = None):
        self.out_dir = out_dir or os.path.join(os.getcwd(), 'events_csv')
        os.makedirs(self.out_dir, exist_ok=True)
        self.files = {}
        self.locks = {}

    def _open_file(self, name: str, headers: list):
        path = os.path.join(self.out_dir, f"{name}.csv")
        first = not os.path.exists(path)
        lock = self.locks.setdefault(name, threading.Lock())
        fh = open(path, 'a', newline='', encoding='utf-8')
        writer = csv.DictWriter(fh, fieldnames=headers)
        if first:
            writer.writeheader()
            fh.flush()
        self.files[name] = (fh, writer)
        return fh, writer, lock

    def _write(self, name: str, row: Dict, headers: list):
        try:
            if name not in self.files:
                fh, writer, lock = self._open_file(name, headers)
            else:
                fh, writer = self.files[name]
                lock = self.locks.get(name)
            with lock:
                writer.writerow({k: row.get(k) for k in headers})
                fh.flush()
            return True
        except Exception:
            return False

    def insert_decision(self, payload: Dict):
        headers = [
            'ts','run_id','session_id','decision_id','signal_dir','signal_strength',
            'S_long','S_short','votes','tie_break_used','cluster_timeframe','cluster_target_level',
            'cluster_target_width_pct','intensity_z','distance_bps','oi_delta_30m_bps','funding_pct',
            'lsr','post_shock_flag','funding_window_block','spread_bps','est_slip_bps','edge_bps','edge_ok',
            'risk_R_pct','sl_pct','qty','step_ok','tick_ok','minQty_ok','minNotional_ok','action','no_trade_reason'
        ]
        # Flatten payload into row
        row = {
            'ts': payload.get('ts') or payload.get('timestamp'),
            'run_id': payload.get('run_id'),
            'session_id': payload.get('session_id'),
            'decision_id': payload.get('decision_id'),
            'signal_dir': payload.get('signal_dir'),
            'signal_strength': payload.get('signal_strength'),
            'S_long': payload.get('S_long'),
            'S_short': payload.get('S_short'),
            'votes': payload.get('votes'),
            'tie_break_used': payload.get('tie_break_used'),
            'cluster_timeframe': (payload.get('cluster') or {}).get('timeframe'),
            'cluster_target_level': (payload.get('cluster') or {}).get('target_level'),
            'cluster_target_width_pct': (payload.get('cluster') or {}).get('target_width_pct'),
            'intensity_z': (payload.get('cluster') or {}).get('intensity_z'),
            'distance_bps': (payload.get('cluster') or {}).get('distance_bps'),
            'oi_delta_30m_bps': (payload.get('context') or {}).get('oi_delta_30m_bps'),
            'funding_pct': (payload.get('context') or {}).get('funding_pct'),
            'lsr': (payload.get('context') or {}).get('lsr'),
            'post_shock_flag': (payload.get('context') or {}).get('post_shock_flag'),
            'funding_window_block': (payload.get('context') or {}).get('funding_window_block'),
            'spread_bps': (payload.get('costs') or {}).get('spread_bps'),
            'est_slip_bps': (payload.get('costs') or {}).get('est_slip_bps'),
            'edge_bps': (payload.get('costs') or {}).get('edge_bps'),
            'edge_ok': (payload.get('costs') or {}).get('edge_ok'),
            'risk_R_pct': (payload.get('risk') or {}).get('risk_R_pct'),
            'sl_pct': (payload.get('risk') or {}).get('sl_pct'),
            'qty': (payload.get('orderability') or {}).get('qty'),
            'step_ok': (payload.get('orderability') or {}).get('step_ok'),
            'tick_ok': (payload.get('orderability') or {}).get('tick_ok'),
            'minQty_ok': (payload.get('orderability') or {}).get('minQty_ok'),
            'minNotional_ok': (payload.get('orderability') or {}).get('minNotional_ok'),
            'action': payload.get('action'),
            'no_trade_reason': payload.get('no_trade_reason')
        }
        return self._write('decisions', row, headers)

    def insert_order(self, payload: Dict):
        headers = ['ts','run_id','session_id','order_id','decision_id','side','type','px','qty','status','latency_ms','reduce_only','time_in_force']
        row = {
            'ts': payload.get('timestamp') or payload.get('ts'),
            'run_id': payload.get('run_id'),
            'session_id': payload.get('session_id'),
            'order_id': payload.get('order_id'),
            'decision_id': payload.get('decision_id'),
            'side': payload.get('side'),
            'type': payload.get('type'),
            'px': payload.get('px') or payload.get('entry'),
            'qty': payload.get('qty') or payload.get('size'),
            'status': payload.get('status') or payload.get('executed'),
            'latency_ms': payload.get('latency_ms'),
            'reduce_only': payload.get('reduce_only'),
            'time_in_force': payload.get('time_in_force')
        }
        return self._write('orders', row, headers)

    def insert_fill(self, payload: Dict):
        headers = ['ts','run_id','session_id','fill_id','order_id','px','qty','fee','pnl_open','pnl_close']
        row = {
            'ts': payload.get('timestamp') or payload.get('ts'),
            'run_id': payload.get('run_id'),
            'session_id': payload.get('session_id'),
            'fill_id': payload.get('fill_id'),
            'order_id': payload.get('order_id'),
            'px': payload.get('px'),
            'qty': payload.get('qty'),
            'fee': payload.get('fee'),
            'pnl_open': payload.get('pnl_open'),
            'pnl_close': payload.get('pnl_close')
        }
        return self._write('fills', row, headers)

    def insert_health(self, payload: Dict):
        headers = ['ts','run_id','session_id','price_age_s','heatmap_age_s','ws_connected','coinglass_ok','positions_open','risk_used_pct','daily_cap_hit']
        row = {
            'ts': payload.get('timestamp') or payload.get('ts'),
            'run_id': payload.get('run_id'),
            'session_id': payload.get('session_id'),
            'price_age_s': payload.get('price_age_s'),
            'heatmap_age_s': payload.get('heatmap_age_s'),
            'ws_connected': payload.get('ws_connected'),
            'coinglass_ok': payload.get('coinglass_ok'),
            'positions_open': payload.get('positions_open'),
            'risk_used_pct': payload.get('risk_used_pct'),
            'daily_cap_hit': payload.get('daily_cap_hit')
        }
        return self._write('health', row, headers)

    def insert_error(self, payload: Dict):
        headers = ['ts','run_id','session_id','severity','component','message','exc_type','exc_msg','stack','linked_ids']
        row = {
            'ts': payload.get('timestamp') or payload.get('ts'),
            'run_id': payload.get('run_id'),
            'session_id': payload.get('session_id'),
            'severity': payload.get('severity'),
            'component': payload.get('component'),
            'message': payload.get('message'),
            'exc_type': payload.get('exc_type'),
            'exc_msg': payload.get('exc_msg'),
            'stack': payload.get('stack'),
            'linked_ids': payload.get('linked_ids')
        }
        return self._write('errors', row, headers)
