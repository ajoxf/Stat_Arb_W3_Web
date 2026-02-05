"""
Core data models for the trading engine.

These are the runtime models used by the trading engine,
separate from the database models.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime


class SignalType(Enum):
    """Trading signal types."""
    NONE = "NONE"
    LONG = "LONG"
    SHORT = "SHORT"
    EXIT = "EXIT"
    STOP_LOSS = "STOP_LOSS"


class PositionType(Enum):
    """Position types."""
    NONE = "NONE"
    LONG = "LONG"
    SHORT = "SHORT"


class OrderSide(Enum):
    """Order side."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """Order type."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class TradingConfig:
    """Trading configuration settings."""
    asset: str = "BTC"
    spot_symbol: str = "BTC-USDT"
    futures_symbol: str = "BTC-USDT-SWAP"

    # Z-score thresholds
    entry_threshold: float = 2.0
    exit_threshold: float = 0.5
    stop_loss_threshold: float = 4.0

    # Rolling window settings
    lookback_period: int = 100
    stats_update_interval: int = 300

    # Filters
    hurst_enabled: bool = True
    hurst_threshold: float = 0.5
    std_filter_enabled: bool = True
    min_std_multiple: float = 1.5

    # Position sizing
    position_size_usd: float = 1000.0
    max_position_size_usd: float = 10000.0

    # Trading mode
    paper_trading: bool = True
    algo_enabled: bool = False

    # Order execution
    order_execution_mode: str = "MARKET"
    limit_order_timeout_sec: int = 30
    limit_order_price_offset_bps: float = 1.0

    # Fees
    taker_fee_bps: float = 5.0
    maker_fee_bps: float = 2.0
    estimated_costs_bps: float = 10.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'asset': self.asset,
            'spot_symbol': self.spot_symbol,
            'futures_symbol': self.futures_symbol,
            'entry_threshold': self.entry_threshold,
            'exit_threshold': self.exit_threshold,
            'stop_loss_threshold': self.stop_loss_threshold,
            'lookback_period': self.lookback_period,
            'stats_update_interval': self.stats_update_interval,
            'hurst_enabled': self.hurst_enabled,
            'hurst_threshold': self.hurst_threshold,
            'std_filter_enabled': self.std_filter_enabled,
            'min_std_multiple': self.min_std_multiple,
            'position_size_usd': self.position_size_usd,
            'max_position_size_usd': self.max_position_size_usd,
            'paper_trading': self.paper_trading,
            'algo_enabled': self.algo_enabled,
            'order_execution_mode': self.order_execution_mode,
            'limit_order_timeout_sec': self.limit_order_timeout_sec,
            'limit_order_price_offset_bps': self.limit_order_price_offset_bps,
            'taker_fee_bps': self.taker_fee_bps,
            'maker_fee_bps': self.maker_fee_bps,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TradingConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Trade:
    """Trade record."""
    id: Optional[int] = None
    asset: str = ""
    position_type: str = "LONG"

    entry_time: Optional[datetime] = None
    entry_spot_price: float = 0.0
    entry_futures_price: float = 0.0
    entry_spread: float = 0.0
    entry_zscore: float = 0.0

    exit_time: Optional[datetime] = None
    exit_spot_price: float = 0.0
    exit_futures_price: float = 0.0
    exit_spread: float = 0.0
    exit_zscore: float = 0.0
    exit_reason: str = ""

    quantity: float = 0.0
    notional_usd: float = 0.0
    pnl_usd: float = 0.0
    pnl_percent: float = 0.0

    spot_order_id: str = ""
    futures_order_id: str = ""

    is_open: bool = True
    is_paper: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'asset': self.asset,
            'position_type': self.position_type,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'entry_spot_price': self.entry_spot_price,
            'entry_futures_price': self.entry_futures_price,
            'entry_spread': self.entry_spread,
            'entry_zscore': self.entry_zscore,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'exit_spot_price': self.exit_spot_price,
            'exit_futures_price': self.exit_futures_price,
            'exit_spread': self.exit_spread,
            'exit_zscore': self.exit_zscore,
            'exit_reason': self.exit_reason,
            'quantity': self.quantity,
            'notional_usd': self.notional_usd,
            'pnl_usd': self.pnl_usd,
            'pnl_percent': self.pnl_percent,
            'is_open': self.is_open,
            'is_paper': self.is_paper,
        }


@dataclass
class MarketTick:
    """Market tick data."""
    symbol: str = ""
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume_24h: float = 0.0
    timestamp: Optional[datetime] = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2 if self.bid and self.ask else self.last

    @property
    def spread_bps(self) -> float:
        if self.mid > 0:
            return ((self.ask - self.bid) / self.mid) * 10000
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'bid': self.bid,
            'ask': self.ask,
            'last': self.last,
            'mid': self.mid,
            'volume_24h': self.volume_24h,
            'spread_bps': self.spread_bps,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class Signal:
    """Trading signal."""
    signal_type: str = "NONE"
    zscore: float = 0.0
    spread: float = 0.0
    spread_mean: float = 0.0
    spread_std: float = 0.0
    hurst: float = 0.5
    hurst_ok: Optional[bool] = True
    std_filter_ok: Optional[bool] = True
    regime: str = "UNKNOWN"
    timestamp: Optional[datetime] = None
    current_position: str = "NONE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            'signal_type': self.signal_type,
            'zscore': self.zscore,
            'spread': self.spread,
            'spread_mean': self.spread_mean,
            'spread_std': self.spread_std,
            'hurst': self.hurst,
            'hurst_ok': self.hurst_ok,
            'std_filter_ok': self.std_filter_ok,
            'regime': self.regime,
            'current_position': self.current_position,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class OrderResult:
    """Order execution result."""
    success: bool = False
    order_id: str = ""
    filled_qty: float = 0.0
    filled_price: float = 0.0
    commission: float = 0.0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'order_id': self.order_id,
            'filled_qty': self.filled_qty,
            'filled_price': self.filled_price,
            'commission': self.commission,
            'error': self.error,
        }


@dataclass
class Position:
    """Current position."""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    leverage: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'side': self.side,
            'quantity': self.quantity,
            'entry_price': self.entry_price,
            'unrealized_pnl': self.unrealized_pnl,
            'leverage': self.leverage,
        }


@dataclass
class AccountInfo:
    """Account information."""
    exchange: str = ""
    balance_usd: float = 0.0
    available_balance_usd: float = 0.0
    margin_used: float = 0.0
    unrealized_pnl: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'exchange': self.exchange,
            'balance_usd': self.balance_usd,
            'available_balance_usd': self.available_balance_usd,
            'margin_used': self.margin_used,
            'unrealized_pnl': self.unrealized_pnl,
        }


@dataclass
class SDTouchEvent:
    """Standard deviation touch event."""
    id: Optional[int] = None
    asset: str = ""
    timestamp: Optional[datetime] = None
    sd_level: float = 0.0
    direction: str = ""
    spread: float = 0.0
    zscore: float = 0.0
    spot_price: float = 0.0
    futures_price: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'asset': self.asset,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'sd_level': self.sd_level,
            'direction': self.direction,
            'spread': self.spread,
            'zscore': self.zscore,
            'spot_price': self.spot_price,
            'futures_price': self.futures_price,
        }


# Crypto asset configurations
CRYPTO_ASSETS: Dict[str, Dict[str, str]] = {
    'BTC': {
        'name': 'Bitcoin',
        'okx_spot': 'BTC-USDT',
        'okx_futures': 'BTC-USDT-SWAP',
        'binance_spot': 'BTCUSDT',
        'binance_futures': 'BTCUSDT',
        'bybit_spot': 'BTCUSDT',
        'bybit_futures': 'BTCUSDT',
    },
    'ETH': {
        'name': 'Ethereum',
        'okx_spot': 'ETH-USDT',
        'okx_futures': 'ETH-USDT-SWAP',
        'binance_spot': 'ETHUSDT',
        'binance_futures': 'ETHUSDT',
        'bybit_spot': 'ETHUSDT',
        'bybit_futures': 'ETHUSDT',
    },
    'SOL': {
        'name': 'Solana',
        'okx_spot': 'SOL-USDT',
        'okx_futures': 'SOL-USDT-SWAP',
        'binance_spot': 'SOLUSDT',
        'binance_futures': 'SOLUSDT',
        'bybit_spot': 'SOLUSDT',
        'bybit_futures': 'SOLUSDT',
    },
    'XRP': {
        'name': 'Ripple',
        'okx_spot': 'XRP-USDT',
        'okx_futures': 'XRP-USDT-SWAP',
        'binance_spot': 'XRPUSDT',
        'binance_futures': 'XRPUSDT',
        'bybit_spot': 'XRPUSDT',
        'bybit_futures': 'XRPUSDT',
    },
    'DOGE': {
        'name': 'Dogecoin',
        'okx_spot': 'DOGE-USDT',
        'okx_futures': 'DOGE-USDT-SWAP',
        'binance_spot': 'DOGEUSDT',
        'binance_futures': 'DOGEUSDT',
        'bybit_spot': 'DOGEUSDT',
        'bybit_futures': 'DOGEUSDT',
    },
    'AVAX': {
        'name': 'Avalanche',
        'okx_spot': 'AVAX-USDT',
        'okx_futures': 'AVAX-USDT-SWAP',
        'binance_spot': 'AVAXUSDT',
        'binance_futures': 'AVAXUSDT',
        'bybit_spot': 'AVAXUSDT',
        'bybit_futures': 'AVAXUSDT',
    },
    'LINK': {
        'name': 'Chainlink',
        'okx_spot': 'LINK-USDT',
        'okx_futures': 'LINK-USDT-SWAP',
        'binance_spot': 'LINKUSDT',
        'binance_futures': 'LINKUSDT',
        'bybit_spot': 'LINKUSDT',
        'bybit_futures': 'LINKUSDT',
    },
}


def get_symbols_for_asset(asset: str, exchange_type: str) -> tuple:
    """Get spot and futures symbols for an asset on a specific exchange."""
    if asset not in CRYPTO_ASSETS:
        raise ValueError(f"Unknown asset: {asset}")

    config = CRYPTO_ASSETS[asset]
    exchange_type = exchange_type.lower()

    spot_key = f"{exchange_type}_spot"
    futures_key = f"{exchange_type}_futures"

    if spot_key not in config or futures_key not in config:
        raise ValueError(f"Unknown exchange type: {exchange_type}")

    return config[spot_key], config[futures_key]
