"""
Configuration management for RL Trading Bot
Centralized configuration with environment variable support
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json

@dataclass
class SMCBoostConfig:
    """SMC Hybrid Confidence Boost configuration"""
    enabled: bool = True  # ENABLED for live trading
    normal_boost: float = 0.15  # 15% boost when SMC aligns
    fvg_bonus: float = 0.20  # 20% additional bonus for FVG alignment
    max_multiplier: float = 1.5  # Cap total multiplier at 1.5x
    log_all_signals: bool = True  # Log SMC info even when boost not applied
    
    def get_params(self) -> Dict[str, float]:
        return {
            'SM_NORMAL_BOOST': self.normal_boost,
            'SM_FVG_BONUS': self.fvg_bonus,
            'MAX_POS_MULT': self.max_multiplier
        }

@dataclass
class TradingConfig:
    """Trading configuration parameters"""
    # Trading mode
    trading_mode: str = "live"  # "paper" or "live" - CHANGED TO LIVE FOR BINANCE TESTNET
    
    # Account settings
    initial_balance: float = 5928.10  # Binance testnet balance
    min_trade_amount: float = 0.002  # Minimum BTC amount for Binance
    max_position_size: float = 0.25   # Maximum position size as fraction of balance (25% = ~$2,200 per trade)
    max_daily_trades: int = 10
    max_concurrent_positions: int = 3  # Maximum concurrent positions (with cooldown system)
    
    # Risk management
    max_drawdown: float = 0.15       # Maximum allowed drawdown (15%)
    daily_risk_cap: float = 0.02     # Hard daily loss cap (2% of start-of-day equity)
    stop_loss_multiplier: float = 1.5  # ATR multiplier for stop loss
    take_profit_multiplier: float = 2.5  # Risk-reward ratio
    position_size_method: str = "r_based"  # "fixed", "kelly", "volatility", "r_based", "deterministic"
    
    # RL Model settings
    exploration_rate: float = 0.05
    learning_rate: float = 0.001
    batch_size: int = 32
    memory_size: int = 10000
    update_frequency: int = 100
    
    # Signal generation
    min_confidence_threshold: float = 0.05  # Lowered to 5% to allow more signal opportunities
    signal_cooldown_minutes: float = 2.0  # 2 minutes - prevents rapid-fire orders
    signal_check_interval_seconds: int = 60  # Check for signals every 60s (aligns with 1-5m decision frequency)
    data_refresh_minutes: int = 1  # Refresh every 1 minute (was 2)
    
    # Signal source control - TRADINGVIEW ONLY MODE
    enable_cluster_signals: bool = False  # Disable cluster-based signal generation
    enable_tradingview_signals: bool = True  # Enable TradingView webhook signals only
    
    # Staleness Thresholds - Adjusted for Google Sheets API 10-minute cache + overnight stability
    price_stale_seconds: int = 120  # 2 minutes max for price (allows websocket reconnections)
    heatmap_stale_seconds: int = 900  # 15 minutes for liquidation heatmap (accounts for Sheets cache + scraper frequency)
    oi_stale_seconds: int = 900  # 15 minutes for Open Interest (accounts for Sheets cache + scraper frequency)
    funding_stale_seconds: int = 900  # 15 minutes for Funding Rate (accounts for Sheets cache + scraper frequency)
    lsr_stale_seconds: int = 900  # 15 minutes for Long/Short Ratio (accounts for Sheets cache + scraper frequency)
    
    # Multi-Timeframe Regime Risk Budgeting (Tier 2)
    max_daily_risk_by_regime: Dict[str, float] = None  # Will be set in __post_init__
    bias_filter_enabled: bool = True  # Enable MTF trend filters
    
    # SMC Hybrid Confidence Boost (enabled for live trading)
    smc_boost: SMCBoostConfig = field(default_factory=SMCBoostConfig)
    
    def __post_init__(self):
        """Initialize regime-based risk budgets"""
        if self.max_daily_risk_by_regime is None:
            self.max_daily_risk_by_regime = {
                'TRENDING_UP': 0.02,      # Full 2% cap in uptrend
                'TRENDING_DOWN': 0.02,    # Full 2% cap in downtrend
                'RANGING': 0.015,         # Reduced 1.5% cap in chop
                'HIGH_VOL': 0.01,         # Conservative 1% cap in volatility
                'LOW_VOL': 0.02,          # Full 2% cap in calm markets
            }
    
    # Risk Management (P0 Improvement)
    daily_loss_cap_pct: float = 0.02
    risk_budget_min_pct: float = 0.0025
    risk_budget_max_pct: float = 0.0075
    
    # Liquidation analysis
    cluster_density_threshold: float = 50000  # Lowered from 150000 to allow detection with fewer data points
    cluster_width_threshold: float = 0.003
    min_cluster_points: int = 2  # Reduced from 3 to 2 to work with minimal liquidation data
    
    # Timeframes for analysis
    timeframes: List[str] = None
    
    def __post_init__(self):
        if self.timeframes is None:
            self.timeframes = ['12h', '24h', '48h', '3d', '1week']

@dataclass
class APIConfig:
    """API configuration"""
    # Google Sheets
    credentials_file: str = "credentials.json"  # This will be auto-detected
    liquidation_spreadsheet_key: str = "1ZeS5XS-SvnfTpmWQ5KNchV52b5f1X6qBqTWxnYQbBAQ"
    oi_fr_spreadsheet_key: str = "1ysGcPSyyJrlX3Wo7C4s7TCkRVF-d9YlvG7LbZeNNQ8k"
    output_sheet_key: str = "1_NVb-xkNZUp0K8aS9z6FUdD_iwEKo0W3-5Y5QtDpLaA"
    live_dashboard_key: str = "16LwZRHN0TgXOdut-RwWY805YnKsI2I8xm4AkSG2vRrU"  # Supervisor monitoring dashboard
    
    # Binance
    binance_symbol: str = "BTCUSDT"
    binance_timeframe: str = "5m"
    
    # Sheet names mapping
    sheet_names_config: Dict[str, str] = None
    lsr_sheet_name: str = "lsr"
    
    def __post_init__(self):
        if self.sheet_names_config is None:
            self.sheet_names_config = {
                '12h': '12h_data',
                '24h': '24h_data', 
                '48h': '48h_data',
                '3d': '3d_data',
                '1week': '1w_data'
            }

@dataclass
class FeatureConfig:
    """Feature engineering configuration"""
    # Technical indicators
    vwap_period: int = 20
    atr_period: int = 14
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    
    # Volume analysis
    volume_sma_period: int = 20
    cvd_period: int = 50
    
    # Market microstructure
    orderbook_depth_levels: int = 10
    tick_analysis_period: int = 100
    
    # Time-based features
    include_hourly_features: bool = True
    include_session_features: bool = True
    
    # Cross-asset features
    include_eth_correlation: bool = False
    include_dxy_correlation: bool = False

class ConfigManager:
    """Manages configuration loading and validation"""
    
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or "trading_config.json"
        self.trading_config = TradingConfig()
        self.api_config = APIConfig()
        self.feature_config = FeatureConfig()
        
        self.load_config()
        self.validate_config()
    
    def load_config(self):
        """Load configuration from file and environment variables"""
        # Load from file if exists
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config_data = json.load(f)
                    self._update_from_dict(config_data)
            except Exception as e:
                print(f"Warning: Could not load config file: {e}")
        
        # Override with environment variables
        self._load_from_env()
    
    def _update_from_dict(self, config_data: dict):
        """Update configuration from dictionary"""
        if 'trading' in config_data:
            for key, value in config_data['trading'].items():
                if hasattr(self.trading_config, key):
                    setattr(self.trading_config, key, value)
        
        if 'api' in config_data:
            for key, value in config_data['api'].items():
                if hasattr(self.api_config, key):
                    setattr(self.api_config, key, value)
        
        if 'features' in config_data:
            for key, value in config_data['features'].items():
                if hasattr(self.feature_config, key):
                    setattr(self.feature_config, key, value)
    
    def _load_from_env(self):
        """Load configuration from environment variables"""
        env_mappings = {
            'INITIAL_BALANCE': ('trading_config', 'initial_balance', float),
            'MIN_TRADE_AMOUNT': ('trading_config', 'min_trade_amount', float),
            'MAX_POSITION_SIZE': ('trading_config', 'max_position_size', float),
            'MAX_DRAWDOWN': ('trading_config', 'max_drawdown', float),
            'EXPLORATION_RATE': ('trading_config', 'exploration_rate', float),
            'LEARNING_RATE': ('trading_config', 'learning_rate', float),
            'MIN_CONFIDENCE': ('trading_config', 'min_confidence_threshold', float),
            'TRADING_MODE': ('trading_config', 'trading_mode', str),
            'LIQUIDATION_SPREADSHEET_KEY': ('api_config', 'liquidation_spreadsheet_key', str),
            'OI_FR_SPREADSHEET_KEY': ('api_config', 'oi_fr_spreadsheet_key', str),
            'OUTPUT_SHEET_KEY': ('api_config', 'output_sheet_key', str),
            'PRICE_STALE_SECONDS': ('trading_config', 'price_stale_seconds', int),
            'HEATMAP_STALE_SECONDS': ('trading_config', 'heatmap_stale_seconds', int),
            'OI_STALE_SECONDS': ('trading_config', 'oi_stale_seconds', int),
            'FUNDING_STALE_SECONDS': ('trading_config', 'funding_stale_seconds', int),
            'LSR_STALE_SECONDS': ('trading_config', 'lsr_stale_seconds', int),
            'DAILY_LOSS_CAP_PCT': ('trading_config', 'daily_loss_cap_pct', float),
        }
        
        for env_var, (config_obj, attr, type_func) in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                try:
                    converted_value = type_func(value)
                    config = getattr(self, config_obj)
                    setattr(config, attr, converted_value)
                except ValueError as e:
                    print(f"Warning: Invalid value for {env_var}: {value}")
    
    def validate_config(self):
        """Validate configuration parameters"""
        errors = []
        
        # Trading config validation
        if self.trading_config.initial_balance <= 0:
            errors.append("Initial balance must be positive")
        
        if self.trading_config.min_trade_amount <= 0:
            errors.append("Minimum trade amount must be positive")
        
        if not 0 < self.trading_config.max_position_size <= 1:
            errors.append("Max position size must be between 0 and 1")
        
        if not 0 < self.trading_config.max_drawdown < 1:
            errors.append("Max drawdown must be between 0 and 1")
        
        if not 0 < self.trading_config.exploration_rate < 1:
            errors.append("Exploration rate must be between 0 and 1")
        
        if not 0 < self.trading_config.min_confidence_threshold <= 1:
            errors.append("Min confidence threshold must be between 0 and 1")
        
        # Trading mode validation
        if self.trading_config.trading_mode not in ["paper", "live"]:
            errors.append("Trading mode must be 'paper' or 'live'")
        
        # API config validation
        if not self.api_config.liquidation_spreadsheet_key:
            errors.append("Liquidation spreadsheet key is required")
        
        if not self.api_config.oi_fr_spreadsheet_key:
            errors.append("OI/FR spreadsheet key is required")
        
        if errors:
            raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")
    
    def save_config(self):
        """Save current configuration to file"""
        config_data = {
            'trading': self.trading_config.__dict__,
            'api': self.api_config.__dict__,
            'features': self.feature_config.__dict__
        }
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config_data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save config file: {e}")
    
    def get_trading_config(self) -> TradingConfig:
        return self.trading_config
    
    def get_api_config(self) -> APIConfig:
        return self.api_config
    
    def get_feature_config(self) -> FeatureConfig:
        return self.feature_config

# Global config instance
config_manager = ConfigManager()
