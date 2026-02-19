"""
Data Sources Module
Contains clients for external data sources: Binance WebSocket and Google Sheets.
"""

print("[DATA_SOURCES] Module loading - v2025-12-15-DEBUG")

import pandas as pd
import numpy as np
import gspread
import json
import websockets
import asyncio
import threading
import time
import logging
import random
from datetime import datetime, timedelta, timezone
from google.oauth2.service_account import Credentials
try:
    from googleapiclient.errors import HttpError
except ImportError:
    # Define a fallback HttpError class if googleapiclient is not installed
    class HttpError(Exception):
        def __init__(self, resp=None, content=None, uri=None):
            self.resp = resp
            self.content = content
            self.status_code = getattr(resp, 'status', None) if resp else None
            super().__init__(str(content))
import os
from typing import Dict, List, Tuple, Optional, Callable

# Import config
try:
    from config import config_manager
except Exception as e:
    logging.getLogger(__name__).exception(f"Failed to import config_manager: {e}")
    raise

# Optional instrumentation libraries (Prometheus)
import importlib.util

PROM_AVAILABLE = False
sheets_error_counter = None

_prom_spec = importlib.util.find_spec('prometheus_client')
if _prom_spec is not None:
    try:
        prometheus_client = importlib.import_module('prometheus_client')
        Counter = prometheus_client.Counter
        # We don't initialize the counter here to avoid duplicate registration if imported multiple times
        # Instead, we'll check if it's already registered or handle it gracefully
        PROM_AVAILABLE = True
    except Exception:
        pass

logger = logging.getLogger(__name__)

def retry_with_exponential_backoff(max_retries=5, base_delay=1, backoff_factor=2, jitter=True):
    """Decorator for retrying API calls with exponential backoff"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # Check if it's a quota error (429) - extract status from error message
                    is_quota_error = False
                    if hasattr(e, 'status_code'):
                        is_quota_error = e.status_code == 429
                    elif str(e) and '[429]' in str(e):
                        is_quota_error = True
                    elif 'quota' in str(e).lower() and 'exceeded' in str(e).lower():
                        is_quota_error = True
                    
                    if is_quota_error:
                        # Increment quota error counters if available on client instance
                        if args and hasattr(args[0], 'quota_error_count'):
                            try:
                                args[0].quota_error_count += 1
                                logger.warning(f"Sheets quota error count: {args[0].quota_error_count}")
                                # Invoke callback to propagate to RL generator if present
                                if hasattr(args[0], 'quota_error_callback') and callable(args[0].quota_error_callback):
                                    args[0].quota_error_callback(args[0].quota_error_count)
                            except Exception as ce:
                                logger.debug(f"Quota error counter update failed: {ce}")
                        if attempt < max_retries - 1:  # Still have retries left
                            # Exponential backoff with jitter
                            delay = base_delay * (backoff_factor ** attempt)
                            if jitter:
                                delay *= (0.5 + random.random() * 0.5)  # Add random jitter
                            
                            logger.warning(f"API quota exceeded. Retrying in {delay:.1f} seconds (attempt {attempt + 1}/{max_retries})")
                            logger.warning(f"Error details: {str(e)}")
                            time.sleep(delay)
                            continue
                        else:
                            logger.error(f"Max retries ({max_retries}) exceeded for API call")
                            logger.error(f"Final error: {str(e)}")
                    else:
                        # For non-quota errors, fail immediately
                        logger.error(f"Non-quota API error: {str(e)}")
                        raise e
            
            # If we get here, all retries failed
            if last_exception is not None:
                raise last_exception
            else:
                raise RuntimeError(f"API call failed after {max_retries} retries with no exception recorded")
        return wrapper
    return decorator

class EnhancedBinanceWebSocketClient:
    """Enhanced WebSocket client with better error handling and reconnection"""
    
    def __init__(self, symbol='BTCUSDT', config=None):
        self.config = config or config_manager
        self.trading_config = self.config.get_trading_config()
        self.symbol = symbol
        self.current_price = None
        self.ltf_data = pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        self.vwap = None
        self.cumulative_volume = 0
        self.cumulative_value = 0
        self.running = False
        self.callbacks = []
        self.last_vwap_reset = datetime.now(timezone.utc).date()
        self.reconnect_attempts = 0
        self.reconnect_count = 0  # Total reconnects (for metrics)
        self.max_reconnect_attempts = 10
        self.best_bid = None
        self.best_ask = None
        
    def bootstrap_historical_ltf(self, limit: int = 300) -> bool:
        """Fetch historical 5m klines from Binance REST API to bootstrap ltf_data.
        
        This ensures signal checking can start immediately after restart
        instead of waiting 25+ minutes for 5 candles to close.
        
        Args:
            limit: Number of historical candles to fetch (default 300)
            
        Returns:
            True if successful, False otherwise
        """
        import requests
        try:
            url = f"https://fapi.binance.com/fapi/v1/klines"
            params = {
                'symbol': self.symbol,
                'interval': '5m',
                'limit': limit
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            klines = response.json()
            
            if not klines:
                logger.warning("No historical klines returned from Binance API")
                return False
                
            # Build DataFrame from klines (exclude the last one if it's not closed)
            candles = []
            for k in klines[:-1]:  # Exclude potentially incomplete last candle
                candle = {
                    'time': datetime.fromtimestamp(k[0] / 1000),
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5])
                }
                candles.append(candle)
                
            if candles:
                self.ltf_data = pd.DataFrame(candles)
                self.current_price = candles[-1]['close'] if candles else None
                logger.info(f"📊 Bootstrapped {len(candles)} historical 5m candles (current price: ${self.current_price:,.2f})")
                
                # Initialize VWAP from last candle
                if candles:
                    last_candle = candles[-1]
                    self.cumulative_volume = last_candle['volume']
                    self.cumulative_value = last_candle['close'] * last_candle['volume']
                    self.vwap = self.cumulative_value / self.cumulative_volume if self.cumulative_volume > 0 else last_candle['close']
                    
                return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to fetch historical klines: {e}")
            return False
        
    async def connect(self):
        """Connect to WebSocket with enhanced error handling"""
        self.running = True
        # Subscribe to both kline_5m and bookTicker (for BBO)
        url = f"wss://fstream.binance.com/stream?streams={self.symbol.lower()}@kline_5m/{self.symbol.lower()}@bookTicker"
        
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as websocket:
                    logger.info(f"Connected to Binance WebSocket for {self.symbol}")
                    self.reconnect_attempts = 0  # Reset on successful connection
                    
                    while self.running:
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=60)
                            data = json.loads(message)
                            # Handle combined stream format: {"stream": "...", "data": {...}}
                            if 'data' in data:
                                self.process_message(data['data'])
                            else:
                                self.process_message(data)
                        except asyncio.TimeoutError:
                            await websocket.ping()
                            continue
                        except websockets.exceptions.ConnectionClosed:
                            logger.warning("WebSocket connection closed, reconnecting...")
                            break
                        except Exception as e:
                            logger.error(f"WebSocket processing error: {e}", exc_info=True)
                            break
                            
            except Exception as e:
                self.reconnect_attempts += 1
                self.reconnect_count += 1  # Increment total reconnects for metrics
                logger.error(f"Failed to connect to WebSocket (attempt {self.reconnect_attempts}): {e}", exc_info=True)
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    await asyncio.sleep(min(10 * self.reconnect_attempts, 60))
                else:
                    logger.error("Max reconnection attempts reached. Stopping WebSocket client.")
                    self.running = False

    def process_message(self, data):
        """Process incoming WebSocket message"""
        # Handle Book Ticker (BBO)
        if 'b' in data and 'a' in data:
            try:
                self.best_bid = float(data['b'])
                self.best_ask = float(data['a'])
            except Exception:
                pass
            return

        # Handle Kline
        if 'k' in data:
            kline = data['k']
            # Always update current price freshness even if candle not closed
            try:
                self.current_price = float(kline.get('c'))
            except Exception:
                pass
            # Update last_price_update_time via callbacks to generator for stale detection
            if self.callbacks:
                # Build lightweight partial frame for in-progress candle if not closed
                if not kline['x'] and self.ltf_data.empty is False:
                    # Do not append incomplete candle, only refresh price
                    for callback in self.callbacks:
                        try:
                            callback(self.current_price, self.ltf_data, self.vwap)
                        except Exception as e:
                            logger.error(f"Callback error (partial): {e}")
                
            if kline['x']:  # Candle is closed
                candle_time = datetime.fromtimestamp(kline['t'] / 1000)
                new_candle = {
                    'time': candle_time,
                    'open': float(kline['o']),
                    'high': float(kline['h']),
                    'low': float(kline['l']),
                    'close': float(kline['c']),
                    'volume': float(kline['v'])
                }
                
                # Update VWAP
                current_date = candle_time.date()
                if current_date != self.last_vwap_reset:
                    self.cumulative_volume = 0
                    self.cumulative_value = 0
                    self.last_vwap_reset = current_date
                
                volume = float(kline['v'])
                typical_price = (float(kline['h']) + float(kline['l']) + float(kline['c'])) / 3
                self.cumulative_value += typical_price * volume
                self.cumulative_volume += volume
                self.vwap = self.cumulative_value / self.cumulative_volume if self.cumulative_volume > 0 else None
                
                # Update LTF data
                if self.ltf_data.empty:
                    self.ltf_data = pd.DataFrame([new_candle])
                else:
                    self.ltf_data = pd.concat([self.ltf_data, pd.DataFrame([new_candle])], ignore_index=True)
                self.ltf_data = self.ltf_data.tail(200)  # Keep more data for analysis
                self.current_price = float(kline['c'])
                
                # Notify callbacks
                for callback in self.callbacks:
                    try:
                        callback(self.current_price, self.ltf_data, self.vwap)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")
                    
    def start(self):
        """Start WebSocket client with historical candle bootstrap"""
        # Bootstrap historical candles so signal checks can start immediately
        self.bootstrap_historical_ltf(limit=300)
        
        def run_async_connect():
            # Set Windows-specific event loop policy if on Windows
            if hasattr(asyncio, 'WindowsSelectorEventLoopPolicy'):
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            logger.info(f"Starting WebSocket thread with {len(self.callbacks)} registered callbacks")
            asyncio.run(self.connect())
        
        self.thread = threading.Thread(target=run_async_connect, daemon=True)
        self.thread.start()
        logger.info("WebSocket thread started")
        
    def stop(self):
        """Stop WebSocket client"""
        self.running = False
        
    def register_callback(self, callback):
        """Register callback for price updates"""
        self.callbacks.append(callback)

class EnhancedGoogleSheetsClient:
    """Enhanced Google Sheets client with rotating credentials for rate limiting"""
    
    def __init__(self, credentials_files, liquidation_spreadsheet_key, oi_fr_spreadsheet_key, output_sheet_key, allow_degraded: bool = True):
        self.scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        # Store output sheet URL for reference/logging and signal rows
        self.output_sheet_key = output_sheet_key
        self.output_sheet_url = f"https://docs.google.com/spreadsheets/d/{output_sheet_key}"
        self.degraded = False
        
        # Initialize multiple clients with rotating credentials
        self.clients = []
        if credentials_files is None:
            self.credentials_files = []
        else:
            self.credentials_files = credentials_files if isinstance(credentials_files, list) else [credentials_files]
        
        for i, creds_file in enumerate(self.credentials_files):
            try:
                creds_info = None
                if isinstance(creds_file, dict):
                    creds_info = creds_file
                elif isinstance(creds_file, str):
                    if os.path.isfile(creds_file):
                        try:
                            with open(creds_file, 'r') as cf:
                                creds_info = json.load(cf)
                        except Exception as fe:
                            logger.error(f"Failed reading creds file {creds_file}: {fe}")
                    else:
                        logger.error(f"Credentials path not found: {creds_file}")
                if creds_info is None:
                    raise ValueError("Credentials info unresolved (dict or existing file path required)")
                creds = Credentials.from_service_account_info(creds_info, scopes=self.scope)
                client = gspread.authorize(creds)
                self.clients.append({
                    'client': client,
                    'liquidation_spreadsheet': client.open_by_key(liquidation_spreadsheet_key),
                    'oi_fr_spreadsheet': client.open_by_key(oi_fr_spreadsheet_key),
                    'output_spreadsheet': client.open_by_key(output_sheet_key),
                    'last_used': datetime.min,
                    'request_count': 0
                })
                logger.info(f"Initialized credentials client {i+1}/{len(self.credentials_files)}")
            except Exception as e:
                logger.error(f"Failed to initialize credentials {i+1}: {e}")
                logger.info(json.dumps({'event':'credential.error','index':i,'path':creds_file if isinstance(creds_file,str) else 'inline','error':str(e)}))
        
        if not self.clients:
            if allow_degraded:
                logger.warning("No valid credentials; entering degraded Sheets mode (all sheet ops skipped).")
                self.degraded = True
            else:
                raise Exception("No valid credentials files provided")
        
        self.current_client_index = 0
        self.last_fetch_time = {}
        logger.info(f"Rotating credentials initialized with {len(self.clients)} clients")
        logger.info(f"OI/FR Spreadsheet ID: {oi_fr_spreadsheet_key}")

        # Quota tracking
        self.quota_error_count = 0
        self.quota_error_callback: Optional[Callable] = None  # to be set by RL generator

    def _col_letter(self, n: int) -> str:
        # 1 -> A, 26 -> Z, 27 -> AA
        s = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s

    def _get_next_client(self):
        """Get next available client using round-robin rotation"""
        client_info = self.clients[self.current_client_index]
        self.current_client_index = (self.current_client_index + 1) % len(self.clients)
        client_info['last_used'] = datetime.now()
        client_info['request_count'] += 1
        logger.debug(f"Using credentials client {self.current_client_index} (used {client_info['request_count']} times)")
        return client_info

    @retry_with_exponential_backoff(max_retries=5, base_delay=5, backoff_factor=2)
    def get_data_from_sheet(self, sheet_name, spreadsheet_type='liquidation', limit_rows=5000, only_recent=True):
        """Get data from sheet using wide range fetch (A1:ZZ) to get all rows."""
        if self.degraded:
            logger.debug("Sheets degraded: returning empty dataframe for get_data_from_sheet")
            return pd.DataFrame()
        try:
            t0 = time.time()
            cache_key = f"{spreadsheet_type}_{sheet_name}"
            current_time = datetime.now()

            if (cache_key in self.last_fetch_time and 
                (current_time - self.last_fetch_time[cache_key]).seconds < 300):
                return getattr(self, f"_cached_{cache_key}", pd.DataFrame())

            client_info = self._get_next_client()
            spreadsheet = client_info['liquidation_spreadsheet'] if spreadsheet_type == 'liquidation' else client_info['oi_fr_spreadsheet']

            logger.info(f"Loading all data from {sheet_name} using wide range fetch...")

            try:
                worksheet = spreadsheet.worksheet(sheet_name)
            except Exception as e:
                logger.error(f"Could not access worksheet {sheet_name}: {e}")
                try:
                    logger.info(json.dumps({'event':'sheets.fetch','when':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'type':spreadsheet_type,'sheet':sheet_name,'status':'worksheet_error','elapsed_ms':(time.time()-t0)*1000.0}))
                except Exception:
                    pass
                return pd.DataFrame()

            # Use get_all_records() for simple, robust fetch (ignores empty rows)
            status = 'ok'
            http_status = None
            try:
                records = worksheet.get_all_records()
                df = pd.DataFrame(records)
                logger.info(f"Fetched {len(df)} rows using get_all_records()")
                
                # Log first and last rows for debugging
                if not df.empty:
                    logger.info(f"First row: {df.iloc[0].to_dict() if len(df) > 0 else 'N/A'}")
                    logger.info(f"Last row: {df.iloc[-1].to_dict() if len(df) > 0 else 'N/A'}")
                    
            except HttpError as he:
                status = 'http_error'
                http_status = getattr(he, 'status_code', None)
                logger.error(f"HttpError fetching {sheet_name}: {he}")
                df = pd.DataFrame()
            except Exception as e:
                status = 'error'
                logger.error(f"Error fetching {sheet_name}: {e}")
                df = pd.DataFrame()

            # Parse timestamps if present and apply filters
            if not df.empty:
                ts_candidates = ['Timestamp (UTC)', 'Timestamp', 'Fetch Time', 'timestamp']
                ts_header = next((h for h in df.columns if h in ts_candidates), None)
                
                if ts_header:
                    df[ts_header] = pd.to_datetime(df[ts_header], errors='coerce')
                    # Remove rows with invalid timestamps
                    df = df.dropna(subset=[ts_header])
                    
                    if not df.empty and only_recent:
                        latest_ts = df[ts_header].max()
                        df = df[df[ts_header] == latest_ts]
                        logger.info(f"Filtered to latest timestamp group: {latest_ts} ({len(df)} rows)")
                else:
                    logger.warning(f"No timestamp column found in {sheet_name} columns: {list(df.columns)}")

            setattr(self, f"_cached_{cache_key}", df)
            self.last_fetch_time[cache_key] = current_time
            logger.info(f"Data fetched successfully: {len(df)} rows from {sheet_name}")
            try:
                logger.info(json.dumps({'event':'sheets.fetch','when':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'type':spreadsheet_type,'sheet':sheet_name,'status':status if 'status' in locals() else 'ok','http_status':http_status,'elapsed_ms':(time.time()-t0)*1000.0,'rows':len(df)}))
            except Exception:
                pass
            return df

        except Exception as e:
            logger.error(f"Error fetching data from {sheet_name}: {str(e)}")
            # Metric increment commented out as we don't have global access to counter here easily without passing it in
            # if PROM_AVAILABLE:
            #     try:
            #         sheets_error_counter.inc()
            #     except Exception:
            #         pass
            return pd.DataFrame()

    @retry_with_exponential_backoff(max_retries=5, base_delay=2, backoff_factor=2)
    def get_oi_data(self, limit_rows=200):
        """Get Open Interest data using timestamp column to anchor fetch window."""
        if self.degraded:
            logger.debug("Sheets degraded: returning empty dataframe for get_oi_data")
            return pd.DataFrame()
        try:
            t0 = time.time()
            client_info = self._get_next_client()
            logger.info(f"Accessing worksheet 'oi' in spreadsheet: {client_info['oi_fr_spreadsheet'].id}")
            worksheet = client_info['oi_fr_spreadsheet'].worksheet('oi')

            headers = worksheet.row_values(1)
            if not headers:
                logger.warning("No headers found in OI sheet")
                return pd.DataFrame()

            ts_header = 'Timestamp (UTC)' if 'Timestamp (UTC)' in headers else None
            df = pd.DataFrame()
            if ts_header:
                # Use fixed bottom-anchored range to avoid col_values() caching issues
                # Scraper keeps max 100 rows (header + 99 data), so fetch last 150 for safety
                end_row = 150
                start_row = 2
                end_col_letter = self._col_letter(max(1, len(headers)))
                rng = f"A{start_row}:{end_col_letter}{end_row}"
                logger.info(f"Fetching OI range {rng}")
                raw_data = worksheet.get(rng)
                if raw_data:
                    max_cols = max(len(r) for r in raw_data)
                    df = pd.DataFrame([r + ['']*(max_cols-len(r)) for r in raw_data], columns=headers[:max_cols])
                if not df.empty:
                    df[ts_header] = pd.to_datetime(df[ts_header], errors='coerce')
                    df = df.dropna(subset=[ts_header]).sort_values(ts_header)
                    cutoff_time = df[ts_header].max() - pd.Timedelta(hours=48)
                    df = df[df[ts_header] >= cutoff_time]
            else:
                logger.warning("Timestamp column not found in OI; using bottom-anchored fetch")
                end_row = worksheet.row_count
                start_row = max(2, end_row - limit_rows + 1)
                end_col_letter = self._col_letter(max(1, len(headers)))
                raw_data = worksheet.get(f"A{start_row}:{end_col_letter}{end_row}")
                if raw_data:
                    max_cols = max(len(r) for r in raw_data)
                    df = pd.DataFrame([r + ['']*(max_cols-len(r)) for r in raw_data], columns=headers[:max_cols])

            logger.info(f"Successfully retrieved {len(df)} OI rows (timestamp-anchored)")
            try:
                logger.info(json.dumps({'event':'sheets.fetch','when':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'type':'oi','sheet':'oi','status':'ok','elapsed_ms':(time.time()-t0)*1000.0,'rows':len(df)}))
            except Exception:
                pass
            return df
        except Exception as e:
            logger.error(f"Error fetching OI data: {str(e)}")
            logger.error(json.dumps({'event':'sheets.fetch_failed','when':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'type':'oi','sheet':'oi','error':str(e),'status':'error'}))
            return pd.DataFrame()

    @retry_with_exponential_backoff(max_retries=5, base_delay=2, backoff_factor=2)
    def get_funding_rate_data(self, limit_rows=200):
        """Get funding rate data from Google Sheets (scraped by collect_oi_funding.py every minute)."""
        if self.degraded:
            logger.debug("Sheets degraded: returning empty dataframe for get_funding_rate_data")
            return pd.DataFrame()
        try:
            t0 = time.time()
            client_info = self._get_next_client()
            logger.info(f"Accessing worksheet 'fr' in spreadsheet: {client_info['oi_fr_spreadsheet'].id}")
            worksheet = client_info['oi_fr_spreadsheet'].worksheet('fr')

            headers = worksheet.row_values(1)
            if not headers:
                logger.warning("No headers found in FR sheet")
                return pd.DataFrame()

            ts_header = 'Timestamp' if 'Timestamp' in headers else None
            df = pd.DataFrame()
            if ts_header:
                # Fetch ALL rows to bypass Google Sheets caching
                all_values = worksheet.get_all_values()
                if not all_values or len(all_values) < 2:
                    logger.warning("No data rows in FR sheet")
                    return pd.DataFrame()
                
                headers = all_values[0]
                data_rows = all_values[1:]  # Skip header
                
                # Take last N rows
                recent_rows = data_rows[-min(limit_rows, len(data_rows)):]
                
                if recent_rows:
                    max_cols = max(len(r) for r in recent_rows)
                    df = pd.DataFrame([r + ['']*(max_cols-len(r)) for r in recent_rows], columns=headers[:max_cols])
                
                if not df.empty:
                    df[ts_header] = pd.to_datetime(df[ts_header], errors='coerce')
                    df = df.dropna(subset=[ts_header]).sort_values(ts_header)
                    cutoff_time = df[ts_header].max() - pd.Timedelta(hours=48)
                    df = df[df[ts_header] >= cutoff_time]
                    logger.info(f"Successfully retrieved {len(df)} funding rate rows, latest: {df[ts_header].max()}")
            else:
                logger.warning("Timestamp column not found in FR; using bottom-anchored fetch")
                end_row = worksheet.row_count
                start_row = max(2, end_row - limit_rows + 1)
                end_col_letter = self._col_letter(max(1, len(headers)))
                raw_data = worksheet.get(f"A{start_row}:{end_col_letter}{end_row}")
                if raw_data:
                    max_cols = max(len(r) for r in raw_data)
                    df = pd.DataFrame([r + ['']*(max_cols-len(r)) for r in raw_data], columns=headers[:max_cols])

            try:
                logger.info(json.dumps({'event':'sheets.fetch','when':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'type':'fr','sheet':'fr','status':'ok','elapsed_ms':(time.time()-t0)*1000.0,'rows':len(df)}))
            except Exception:
                pass
            return df
        except Exception as e:
            logger.error(f"Error fetching funding rate data: {str(e)}")
            logger.error(json.dumps({'event':'sheets.fetch_failed','when':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'type':'fr','sheet':'fr','error':str(e),'status':'error'}))
            return pd.DataFrame()

    @retry_with_exponential_backoff(max_retries=5, base_delay=2, backoff_factor=2)
    def get_lsr_data(self, limit_rows=200):
        """Get Long/Short Ratio data using timestamp column to anchor fetch window."""
        if self.degraded:
            logger.debug("Sheets degraded: returning empty dataframe for get_lsr_data")
            return pd.DataFrame()
        try:
            t0 = time.time()
            client_info = self._get_next_client()
            sheet_name = getattr(config_manager.api_config, 'lsr_sheet_name', 'lsr')
            logger.info(f"Accessing worksheet '{sheet_name}' in spreadsheet: {client_info['oi_fr_spreadsheet'].id}")
            try:
                worksheet = client_info['oi_fr_spreadsheet'].worksheet(sheet_name)
            except gspread.exceptions.WorksheetNotFound:
                logger.warning(f"LSR worksheet '{sheet_name}' not found")
                return pd.DataFrame()

            headers = worksheet.row_values(1)
            if not headers:
                logger.warning("No headers found in LSR sheet")
                return pd.DataFrame()

            ts_header = 'Timestamp' if 'Timestamp' in headers else ('Timestamp (UTC)' if 'Timestamp (UTC)' in headers else None)
            df = pd.DataFrame()
            if ts_header:
                # Get total row count to fetch from bottom
                total_rows = worksheet.row_count
                # Fetch last 250 rows (bottom-anchored) to get freshest data
                start_row = max(2, total_rows - 248)  # -248 because we skip header row
                end_row = total_rows
                end_col_letter = self._col_letter(max(1, len(headers)))
                rng = f"A{start_row}:{end_col_letter}{end_row}"
                logger.info(f"Fetching LSR range {rng} (bottom-anchored, total_rows={total_rows})")
                raw_data = worksheet.get(rng)
                if raw_data:
                    max_cols = max(len(r) for r in raw_data)
                    df = pd.DataFrame([r + ['']*(max_cols-len(r)) for r in raw_data], columns=headers[:max_cols])
                if not df.empty:
                    df[ts_header] = pd.to_datetime(df[ts_header], errors='coerce')
                    df = df.dropna(subset=[ts_header]).sort_values(ts_header)
                    cutoff_time = df[ts_header].max() - pd.Timedelta(hours=48)
                    df = df[df[ts_header] >= cutoff_time]
            else:
                logger.warning("Timestamp column not found in LSR; using bottom-anchored fetch")
                end_row = worksheet.row_count
                start_row = max(2, end_row - limit_rows + 1)
                end_col_letter = self._col_letter(max(1, len(headers)))
                raw_data = worksheet.get(f"A{start_row}:{end_col_letter}{end_row}")
                if raw_data:
                    max_cols = max(len(r) for r in raw_data)
                    df = pd.DataFrame([r + ['']*(max_cols-len(r)) for r in raw_data], columns=headers[:max_cols])

            logger.info(f"Successfully retrieved {len(df)} LSR rows (timestamp-anchored)")
            try:
                logger.info(json.dumps({'event':'sheets.fetch','when':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'type':'lsr','sheet':sheet_name,'status':'ok','elapsed_ms':(time.time()-t0)*1000.0,'rows':len(df)}))
            except Exception:
                pass
            return df
        except Exception as e:
            logger.error(f"Error fetching LSR data: {str(e)}")
            return pd.DataFrame()

    @retry_with_exponential_backoff(max_retries=5, base_delay=2, backoff_factor=2)
    def push_signal_to_sheet(self, signal, sheet_name='enhanced_signals'):
        """Push signal to Google Sheet with deterministic voting columns and retry logic"""
        if self.degraded:
            logger.debug("Sheets degraded: skipping push_signal_to_sheet")
            return
        try:
            t0 = time.time()
            client_info = self._get_next_client()
            worksheet = client_info['output_spreadsheet'].worksheet(sheet_name)

            headers = worksheet.row_values(1)
            if not headers:
                # Updated headers per spec with all required columns
                headers = [
                    'decision_id', 'ts', 'venue', 'symbol', 'price_mid', 'consensus_S',
                    'signal_dir', 'signal_strength', 'm1_proximity', 'm2_density', 'm3_sentiment',
                    'tie_break_used', 'cluster_level', 'cluster_width_pct', 'cluster_intensity_z',
                    'oi_delta_30m', 'funding', 'lsr', 'risk_R', 'sl_pct', 'tp1_pct', 'tp2_pct',
                    'tp3_mode', 'qty', 'order_type', 'limit_price', 'est_fee_bps', 'est_slip_bps', 'pretrade_checks',
                    'action', 'status', 'notes'
                ]
                worksheet.append_row(headers)

            # Normalize timestamp (accept datetime or ISO string)
            ts = signal.get('timestamp')
            try:
                if isinstance(ts, str):
                    t_str = ts.rstrip('Z')
                    try:
                        ts_dt = datetime.fromisoformat(t_str)
                    except Exception:
                        ts_dt = datetime.strptime(t_str, '%Y-%m-%dT%H:%M:%S.%f')
                elif isinstance(ts, datetime):
                    ts_dt = ts
                else:
                    ts_dt = datetime.now(timezone.utc)
            except Exception:
                ts_dt = datetime.now(timezone.utc)

            # Extract voting results if available
            votes = signal.get('votes', {})
            m1 = votes.get('m1_proximity', '')
            m2 = votes.get('m2_density', '')
            m3 = votes.get('m3_sentiment', '')
            
            # Calculate consensus score: S_long - S_short based on votes
            s_long = sum(1 for v in [m1, m2, m3] if v == 'LONG')
            s_short = sum(1 for v in [m1, m2, m3] if v == 'SHORT')
            consensus_s = s_long - s_short
            
            # Get cluster info
            cluster = signal.get('cluster', {})
            cluster_level = cluster.get('mean_price', signal.get('entry_price', ''))
            cluster_width_pct = cluster.get('width_pct', '')
            cluster_intensity_z = cluster.get('intensity_z', cluster.get('strength_score', ''))
            
            # Risk and position sizing
            entry = signal.get('entry_price', 0)
            stop = signal.get('stop_loss', 0)
            tp1 = signal.get('take_profit', 0)
            
            sl_pct = abs(entry - stop) / entry * 100 if entry > 0 and stop > 0 else ''
            tp1_pct = abs(tp1 - entry) / entry * 100 if entry > 0 and tp1 > 0 else ''
            tp2_pct = signal.get('tp2_pct', '')  # If multi-TP is supported
            tp3_mode = signal.get('tp3_mode', 'trailing')
            
            # OI, Funding, LSR
            oi_sig = signal.get('oi_signal', ('NEUTRAL', ''))
            oi_delta = oi_sig[1] if isinstance(oi_sig, (list, tuple)) and len(oi_sig) > 1 else ''
            
            funding_sig = signal.get('funding_signal', ('NEUTRAL', ''))
            funding_val = funding_sig[1] if isinstance(funding_sig, (list, tuple)) and len(funding_sig) > 1 else ''
            
            lsr = signal.get('lsr', '')  # Long/Short ratio if available
            
            # Pre-trade checks
            pretrade_checks = []
            qty = signal.get('position_size', 0)
            if qty > 0:
                pretrade_checks.append('qty_ok')
            if sl_pct != '' and float(sl_pct) < 5:
                pretrade_checks.append('sl_ok')
            pretrade_str = ','.join(pretrade_checks) if pretrade_checks else 'none'
            
            # Build the row per spec columns
            signal_row = [
                signal.get('decision_id', f"D{int(time.time()*1000)}"),  # decision_id
                ts_dt.strftime('%Y-%m-%d %H:%M:%S'),  # ts
                'binance',  # venue
                'BTCUSDT',  # symbol
                str(signal.get('current_price', entry)),  # price_mid
                str(consensus_s),  # consensus_S (S_long - S_short)
                str(signal.get('direction', '')),  # signal_dir
                str(signal.get('confidence', signal.get('combined_confidence', ''))),  # signal_strength
                str(m1),  # m1_proximity
                str(m2),  # m2_density
                str(m3),  # m3_sentiment
                str(signal.get('tie_break_used', False)),  # tie_break_used
                str(cluster_level),  # cluster_level
                str(cluster_width_pct),  # cluster_width_pct
                str(cluster_intensity_z),  # cluster_intensity_z
                str(oi_delta),  # oi_delta_30m
                str(funding_val),  # funding
                str(lsr),  # lsr
                str(signal.get('risk_R', 1)),  # risk_R
                str(sl_pct),  # sl_pct
                str(tp1_pct),  # tp1_pct
                str(tp2_pct),  # tp2_pct
                str(tp3_mode),  # tp3_mode
                str(qty),  # qty
                str(signal.get('est_fee_bps', 4)),  # est_fee_bps (default 4bps)
                str(signal.get('est_slip_bps', 2)),  # est_slip_bps (default 2bps)
                pretrade_str,  # pretrade_checks
                str(signal.get('action', 'PLACE')),  # action
                str(signal.get('status', 'pending')),  # status
                str(signal.get('bias_reason', ''))[:200]  # notes (truncated)
            ]
            status = 'ok'
            try:
                worksheet.append_row(signal_row)
            except HttpError as he:
                status = 'http_error'
                raise
            logger.info(f"Enhanced signal pushed to Google Sheet: {sheet_name}")
            logger.info(f"Signal row includes sheet link: {self.output_sheet_url}")
            try:
                logger.info(json.dumps({'event':'sheets.append','when':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'sheet':sheet_name,'status':status,'elapsed_ms':(time.time()-t0)*1000.0}))
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error pushing signal to sheet: {e}")

class ObservabilitySheets:
    """Optional creation of an observability spreadsheet for structured events."""
    def __init__(self, creds_path: str, title_prefix: str = "TradingBot_Observability"):
        self.creds_path = creds_path
        self.title = f"{title_prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        self.url = None
        self.spreadsheet = None
        self.client = None
        self.enabled = False
        try:
            if not os.path.exists(self.creds_path):
                raise FileNotFoundError(f"Observability credentials not found: {self.creds_path}")
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_file(self.creds_path, scopes=scopes)
            self.client = gspread.authorize(creds)
            self.enabled = True
        except Exception as e:
            logger.warning(f"ObservabilitySheets init failed: {e}")

    def ensure_created(self):
        if not self.enabled or self.spreadsheet is not None:
            return
        try:
            self.spreadsheet = self.client.create(self.title)
            self.url = f"https://docs.google.com/spreadsheets/d/{self.spreadsheet.id}"
            # Remove default worksheet
            try:
                default_ws = self.spreadsheet.sheet1
                self.spreadsheet.del_worksheet(default_ws)
            except Exception:
                pass
            schema = {
                'decisions': ['ts','run_id','session_id','decision_id','mode','symbol','direction','confidence','votes_oi','votes_funding','votes_clusters','multi_tf','action','reason'],
                'orders': ['ts','run_id','session_id','decision_id','order_id','side','entry','stop','tp','qty','rr','combined_conf','executed','validation'],
                'health': ['ts','run_id','session_id','price_age_s','heatmap_age_s','ws_connected','positions_open','risk_used_pct','daily_cap_hit','kill_switch','kill_reason'],
                'errors': ['ts','run_id','session_id','component','severity','message']
            }
            for title, headers in schema.items():
                ws = self.spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers)+2)
                ws.append_row(headers)
            logger.info(f"Observability spreadsheet created: {self.url}")
        except Exception as e:
            logger.error(f"Failed to create observability spreadsheet: {e}")

    def append(self, sheet_name: str, row: List):
        if not self.enabled or self.spreadsheet is None:
            return
        try:
            ws = self.spreadsheet.worksheet(sheet_name)
            ws.append_row(row)
        except Exception as e:
            logger.warning(f"Observability append failed ({sheet_name}): {e}")

class CandleAggregator:
    """
    Aggregates 5m candles into higher timeframes (15m, 1h, 4h, 1d).
    Maintains rolling buffers for each timeframe.
    """
    def __init__(self, max_candles: int = 200):
        self.max_candles = max_candles
        self.timeframes = ['15m', '1h', '4h', '1d']
        self.aggregated_data = {tf: pd.DataFrame() for tf in self.timeframes}
        
    def process_5m_data(self, ltf_data: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """
        Process 5m data and update higher timeframes.
        
        Args:
            ltf_data: DataFrame containing 5m candles with 'time', 'open', 'high', 'low', 'close', 'volume'
            
        Returns:
            Dictionary of DataFrames for each timeframe
        """
        if ltf_data.empty:
            return self.aggregated_data
            
        # Ensure time is datetime and set as index for resampling
        df = ltf_data.copy()
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'])
            df.set_index('time', inplace=True)
            
        # Resample logic
        # 15m
        self.aggregated_data['15m'] = self._resample(df, '15min')
        
        # 1h
        self.aggregated_data['1h'] = self._resample(df, '1h')
        
        # 4h
        self.aggregated_data['4h'] = self._resample(df, '4h')
        
        # 1d
        self.aggregated_data['1d'] = self._resample(df, '1D')
        
        return self.aggregated_data
        
    def _resample(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        """Resample OHLCV data"""
        try:
            resampled = df.resample(rule).agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            # Keep only last N candles
            if len(resampled) > self.max_candles:
                resampled = resampled.iloc[-self.max_candles:]
                
            # Reset index to keep 'time' as column to match ltf_data format
            resampled = resampled.reset_index()
            return resampled
        except Exception as e:
            logger.error(f"Error resampling {rule}: {e}")
            return pd.DataFrame()
