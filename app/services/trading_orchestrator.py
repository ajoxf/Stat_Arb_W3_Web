"""
Trading Orchestrator for multi-tenant trading engine management.

Manages individual trading engine instances per user with:
- User isolation
- Resource management
- State persistence
- Graceful start/stop

This fixes the order executor initialization bug by ensuring
REST adapters are initialized alongside WebSocket for order placement.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from threading import Thread, Lock

from app.database import db, User, UserExchange, UserConfig, Trade, SpreadHistory
from app.database.models import BotStatus, ExchangeType, ExchangeRole
from app.services.exchange_service import ExchangeService
from app.core.trading_engine import TradingEngine
from app.core.signals import SignalGenerator
from app.core.models import TradingConfig as CoreTradingConfig, MarketTick, Signal, Trade as CoreTrade

logger = logging.getLogger(__name__)


@dataclass
class UserTradingSession:
    """Container for a user's trading session."""
    user_id: int
    engine: TradingEngine
    loop: asyncio.AbstractEventLoop
    thread: Thread
    started_at: datetime
    is_stopping: bool = False


class TradingOrchestrator:
    """
    Orchestrates trading engines for multiple users.

    Each user gets their own isolated trading engine instance
    running in its own async event loop.

    Key features:
    - User isolation: Each user's engine is independent
    - Resource management: Proper cleanup on stop
    - State persistence: Spread history saved for recovery
    - FIX: Order executor properly initialized in WebSocket mode
    """

    def __init__(self, exchange_service: ExchangeService):
        """
        Initialize the orchestrator.

        Args:
            exchange_service: Service for handling exchange credentials
        """
        self.exchange_service = exchange_service

        # Active trading sessions by user_id
        self._sessions: Dict[int, UserTradingSession] = {}
        self._sessions_lock = Lock()

        # Callbacks for UI updates (per user)
        self._user_callbacks: Dict[int, Dict[str, Callable]] = {}

    def start_trading(
        self,
        user: User,
        on_tick: Optional[Callable] = None,
        on_signal: Optional[Callable] = None,
        on_trade: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ) -> tuple[bool, str]:
        """
        Start trading for a user.

        Creates a new trading engine instance for the user with proper
        adapter initialization (fixing the WebSocket mode bug).

        Args:
            user: The user to start trading for
            on_tick: Callback for tick updates
            on_signal: Callback for signal updates
            on_trade: Callback for trade updates
            on_error: Callback for error updates

        Returns:
            Tuple of (success, message)
        """
        with self._sessions_lock:
            # Check if already running
            if user.id in self._sessions:
                return False, "Trading already running"

        # Validate user has config
        config = UserConfig.query.filter_by(user_id=user.id).first()
        if not config:
            return False, "No trading configuration found"

        # Get active exchanges
        exchanges = UserExchange.query.filter_by(
            user_id=user.id,
            is_active=True
        ).all()

        if not exchanges:
            return False, "No active exchanges configured"

        # Find spot and futures exchanges
        spot_exchange = None
        futures_exchange = None

        for exchange in exchanges:
            if exchange.role in (ExchangeRole.SPOT, ExchangeRole.BOTH):
                spot_exchange = exchange
            if exchange.role in (ExchangeRole.FUTURES, ExchangeRole.BOTH):
                futures_exchange = exchange

        if not spot_exchange or not futures_exchange:
            return False, "Need both spot and futures exchange configured"

        try:
            # Convert DB config to core config
            core_config = self._to_core_config(config)

            # Create trading engine
            engine = TradingEngine(core_config)

            # Get decrypted credentials
            spot_creds = self.exchange_service.get_decrypted_credentials(user, spot_exchange)
            futures_creds = self.exchange_service.get_decrypted_credentials(user, futures_exchange)

            if not spot_creds or not futures_creds:
                return False, "Failed to decrypt exchange credentials"

            # Create adapters (REST for order execution)
            # FIX: Always create REST adapters for order execution,
            # even when using WebSocket for price streaming
            spot_adapter = self._create_adapter(
                spot_exchange.exchange_type,
                spot_creds,
                spot_exchange.is_testnet,
                is_futures=False
            )
            futures_adapter = self._create_adapter(
                futures_exchange.exchange_type,
                futures_creds,
                futures_exchange.is_testnet,
                is_futures=True
            )

            # Set adapters - this initializes the order executor
            engine.set_adapters(spot_adapter, futures_adapter)

            # Additionally set up WebSocket if available
            ws_manager = self._create_websocket_manager(
                spot_exchange.exchange_type,
                spot_exchange.is_testnet
            )
            if ws_manager:
                engine.set_websocket_manager(ws_manager)

            # Set callbacks
            if on_tick:
                engine.on_tick = on_tick
            if on_signal:
                engine.on_signal = on_signal
            if on_trade:
                engine.on_trade = lambda trade: self._handle_trade(user.id, trade, on_trade)
            if on_error:
                engine.on_error = on_error

            # Load spread history for recovery
            self._load_spread_history(user.id, engine, config.asset)

            # Create event loop and thread
            loop = asyncio.new_event_loop()
            thread = Thread(
                target=self._run_event_loop,
                args=(loop,),
                daemon=True,
                name=f"trading-{user.id}"
            )
            thread.start()

            # Start engine
            asyncio.run_coroutine_threadsafe(engine.start(), loop)

            # Create session
            session = UserTradingSession(
                user_id=user.id,
                engine=engine,
                loop=loop,
                thread=thread,
                started_at=datetime.now(timezone.utc),
            )

            with self._sessions_lock:
                self._sessions[user.id] = session

            # Update user status
            user.bot_status = BotStatus.RUNNING
            db.session.commit()

            logger.info("Trading started for user_id=%d", user.id)
            return True, "Trading started successfully"

        except Exception as e:
            logger.exception("Failed to start trading for user_id=%d: %s", user.id, str(e))
            return False, f"Failed to start trading: {str(e)}"

    def stop_trading(self, user: User) -> tuple[bool, str]:
        """
        Stop trading for a user.

        Gracefully stops the engine and cleans up resources.

        Args:
            user: The user to stop trading for

        Returns:
            Tuple of (success, message)
        """
        with self._sessions_lock:
            session = self._sessions.get(user.id)
            if not session:
                return False, "Trading not running"

            if session.is_stopping:
                return False, "Already stopping"

            session.is_stopping = True

        try:
            # Stop engine
            future = asyncio.run_coroutine_threadsafe(
                session.engine.stop(),
                session.loop
            )
            future.result(timeout=10)

            # Stop event loop
            session.loop.call_soon_threadsafe(session.loop.stop)

            # Wait for thread to finish
            session.thread.join(timeout=5)

            # Remove session
            with self._sessions_lock:
                del self._sessions[user.id]

            # Update user status
            user.bot_status = BotStatus.STOPPED
            db.session.commit()

            logger.info("Trading stopped for user_id=%d", user.id)
            return True, "Trading stopped successfully"

        except Exception as e:
            logger.exception("Error stopping trading for user_id=%d: %s", user.id, str(e))

            # Force cleanup
            with self._sessions_lock:
                if user.id in self._sessions:
                    del self._sessions[user.id]

            user.bot_status = BotStatus.STOPPED
            db.session.commit()

            return False, f"Error stopping trading: {str(e)}"

    def get_status(self, user: User) -> Dict[str, Any]:
        """
        Get trading status for a user.

        Args:
            user: The user

        Returns:
            Status dictionary
        """
        with self._sessions_lock:
            session = self._sessions.get(user.id)

        if not session:
            return {
                'is_running': False,
                'bot_status': user.bot_status.value,
            }

        engine_status = session.engine.get_status()
        return {
            'is_running': True,
            'bot_status': user.bot_status.value,
            'started_at': session.started_at.isoformat(),
            **engine_status,
        }

    def update_config(self, user: User, config: UserConfig) -> tuple[bool, str]:
        """
        Update trading configuration for a running engine.

        Args:
            user: The user
            config: New configuration

        Returns:
            Tuple of (success, message)
        """
        with self._sessions_lock:
            session = self._sessions.get(user.id)

        if not session:
            return True, "Configuration saved (engine not running)"

        try:
            core_config = self._to_core_config(config)
            session.engine.update_config(core_config)
            return True, "Configuration updated"
        except Exception as e:
            logger.error("Failed to update config: %s", str(e))
            return False, f"Failed to update config: {str(e)}"

    def toggle_algo(self, user: User, enabled: bool) -> tuple[bool, str]:
        """
        Toggle algorithmic trading for a user.

        Args:
            user: The user
            enabled: Whether to enable algo trading

        Returns:
            Tuple of (success, message)
        """
        with self._sessions_lock:
            session = self._sessions.get(user.id)

        if not session:
            return False, "Trading not running"

        session.engine.toggle_algo(enabled)
        return True, f"Algo trading {'enabled' if enabled else 'disabled'}"

    def _run_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Run event loop in thread."""
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _to_core_config(self, db_config: UserConfig) -> CoreTradingConfig:
        """Convert database config to core trading config."""
        return CoreTradingConfig(
            asset=db_config.asset,
            spot_symbol=db_config.spot_symbol,
            futures_symbol=db_config.futures_symbol,
            entry_threshold=db_config.entry_threshold,
            exit_threshold=db_config.exit_threshold,
            stop_loss_threshold=db_config.stop_loss_threshold,
            lookback_period=db_config.lookback_period,
            stats_update_interval=db_config.stats_update_interval,
            hurst_enabled=db_config.hurst_enabled,
            hurst_threshold=db_config.hurst_threshold,
            std_filter_enabled=db_config.std_filter_enabled,
            min_std_multiple=db_config.min_std_multiple,
            position_size_usd=db_config.position_size_usd,
            max_position_size_usd=db_config.max_position_size_usd,
            paper_trading=db_config.paper_trading,
            algo_enabled=db_config.algo_enabled,
            order_execution_mode=db_config.order_execution_mode,
            limit_order_timeout_sec=db_config.limit_order_timeout_sec,
            limit_order_price_offset_bps=db_config.limit_order_price_offset_bps,
            taker_fee_bps=db_config.taker_fee_bps,
            maker_fee_bps=db_config.maker_fee_bps,
        )

    def _create_adapter(
        self,
        exchange_type: ExchangeType,
        credentials: Dict[str, str],
        is_testnet: bool,
        is_futures: bool,
    ):
        """Create exchange adapter based on type."""
        from app.adapters import OKXAdapter, BinanceAdapter, BybitAdapter

        if exchange_type == ExchangeType.OKX:
            return OKXAdapter(
                api_key=credentials['api_key'],
                secret_key=credentials['secret_key'],
                passphrase=credentials.get('passphrase', ''),
                is_testnet=is_testnet,
            )
        elif exchange_type == ExchangeType.BINANCE:
            return BinanceAdapter(
                api_key=credentials['api_key'],
                secret_key=credentials['secret_key'],
                is_testnet=is_testnet,
                is_futures=is_futures,
            )
        elif exchange_type == ExchangeType.BYBIT:
            return BybitAdapter(
                api_key=credentials['api_key'],
                secret_key=credentials['secret_key'],
                is_testnet=is_testnet,
                is_futures=is_futures,
            )
        else:
            raise ValueError(f"Unknown exchange type: {exchange_type}")

    def _create_websocket_manager(
        self,
        exchange_type: ExchangeType,
        is_testnet: bool,
    ):
        """Create WebSocket manager if available."""
        from app.adapters import OKXWebSocketManager

        if exchange_type == ExchangeType.OKX:
            return OKXWebSocketManager(is_demo=is_testnet)

        # Other exchanges don't have WebSocket implemented yet
        return None

    def _load_spread_history(
        self,
        user_id: int,
        engine: TradingEngine,
        asset: str,
    ) -> None:
        """Load spread history from database for recovery."""
        spreads = SpreadHistory.query.filter_by(
            user_id=user_id,
            asset=asset
        ).order_by(
            SpreadHistory.timestamp.desc()
        ).limit(engine.config.lookback_period * 2).all()

        if spreads:
            # Reverse to get oldest first
            spread_values = [s.spread for s in reversed(spreads)]
            engine.signal_generator.load_spread_history(spread_values)
            logger.info(
                "Loaded %d spread values for user_id=%d",
                len(spread_values), user_id
            )

    def _handle_trade(
        self,
        user_id: int,
        core_trade: CoreTrade,
        callback: Optional[Callable],
    ) -> None:
        """Handle trade from engine and persist to database."""
        try:
            # Save to database
            db_trade = Trade(
                user_id=user_id,
                asset=core_trade.asset,
                position_type=core_trade.position_type,
                entry_time=core_trade.entry_time,
                entry_spot_price=core_trade.entry_spot_price,
                entry_futures_price=core_trade.entry_futures_price,
                entry_spread=core_trade.entry_spread,
                entry_zscore=core_trade.entry_zscore,
                exit_time=core_trade.exit_time,
                exit_spot_price=core_trade.exit_spot_price,
                exit_futures_price=core_trade.exit_futures_price,
                exit_spread=core_trade.exit_spread,
                exit_zscore=core_trade.exit_zscore,
                exit_reason=core_trade.exit_reason,
                quantity=core_trade.quantity,
                notional_usd=core_trade.notional_usd,
                pnl_usd=core_trade.pnl_usd,
                pnl_percent=core_trade.pnl_percent,
                spot_order_id=core_trade.spot_order_id,
                futures_order_id=core_trade.futures_order_id,
                is_open=core_trade.is_open,
                is_paper=core_trade.is_paper,
            )
            db.session.add(db_trade)
            db.session.commit()

            # Call user callback
            if callback:
                callback(db_trade)

        except Exception as e:
            logger.error("Failed to save trade: %s", str(e))
            db.session.rollback()

    def stop_all(self) -> None:
        """Stop all active trading sessions. Called on shutdown."""
        with self._sessions_lock:
            user_ids = list(self._sessions.keys())

        for user_id in user_ids:
            try:
                user = User.query.get(user_id)
                if user:
                    self.stop_trading(user)
            except Exception as e:
                logger.error("Error stopping trading for user_id=%d: %s", user_id, str(e))
