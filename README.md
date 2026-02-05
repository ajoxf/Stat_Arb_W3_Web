# Crypto Statistical Arbitrage SaaS Platform

A professional multi-tenant SaaS platform for crypto spot-futures statistical arbitrage trading.

## Features

### Trading Engine
- **Z-Score Mean Reversion**: Trades spread between spot and futures markets using Z-score signals
- **Hurst Exponent Filter**: Detects mean-reverting vs trending regimes
- **STD Filter**: Ensures volatility covers trading costs
- **Order Execution**: Supports both Market and Pegged Limit orders
- **Paper Trading**: Test strategies without risking capital

### Multi-Tenant Architecture
- **User Isolation**: Each user has isolated trading engine instances
- **Secure API Key Storage**: AES-256-GCM encryption with per-user derived keys
- **Subscription Tiers**: Free, Pro, and Enterprise with different limits

### Security
- **Password Hashing**: Argon2id (winner of Password Hashing Competition)
- **API Key Encryption**: AES-256-GCM with unique IV per encryption
- **JWT Authentication**: Secure stateless API authentication
- **CSRF Protection**: Token-based CSRF protection
- **Rate Limiting**: Prevents API abuse

### Supported Exchanges
- OKX
- Binance
- Bybit

## Quick Start

### Development with Docker

```bash
# Clone repository
git clone https://github.com/ajoxf/Stat_Arb_W3_Web.git
cd Stat_Arb_W3_Web

# Copy environment file
cp .env.example .env

# Start services
docker-compose up -d

# Application available at http://localhost:5000
```

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your settings

# Initialize database (PostgreSQL required)
flask db upgrade

# Run application
python run.py
```

## Configuration

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask secret key |
| `DATABASE_URL` | PostgreSQL connection string |
| `MASTER_ENCRYPTION_KEY` | Key for API key encryption (min 32 chars) |
| `JWT_SECRET_KEY` | JWT signing key |

### Optional Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `STRIPE_API_KEY` | Stripe secret key | - |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook secret | - |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `LOG_LEVEL` | Logging level | `INFO` |

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login and get tokens
- `POST /api/auth/logout` - Logout
- `POST /api/auth/refresh` - Refresh access token
- `GET /api/auth/me` - Get current user

### Trading
- `GET /api/trading/status` - Get engine status
- `POST /api/trading/start` - Start trading
- `POST /api/trading/stop` - Stop trading
- `POST /api/trading/toggle-algo` - Toggle algo trading

### Exchanges
- `GET /api/exchanges` - List exchanges
- `POST /api/exchanges` - Add exchange
- `PUT /api/exchanges/:id` - Update exchange
- `DELETE /api/exchanges/:id` - Delete exchange
- `POST /api/exchanges/:id/test` - Test connection

### User
- `GET /api/user/config` - Get trading config
- `PUT /api/user/config` - Update trading config
- `GET /api/user/trades` - Get trade history
- `GET /api/user/statistics` - Get statistics

## Architecture

```
app/
├── api/                  # API routes
│   ├── auth_routes.py
│   ├── trading_routes.py
│   ├── exchange_routes.py
│   └── subscription_routes.py
├── auth/                 # Authentication
│   ├── service.py
│   ├── jwt_handler.py
│   └── decorators.py
├── core/                 # Trading engine
│   ├── trading_engine.py
│   ├── signals.py
│   ├── order_executor.py
│   └── models.py
├── database/             # Database models
│   └── models.py
├── security/             # Encryption & security
│   ├── encryption.py
│   └── password.py
├── services/             # Business logic
│   ├── exchange_service.py
│   ├── trading_orchestrator.py
│   └── subscription_service.py
├── adapters/             # Exchange adapters
│   ├── okx_adapter.py
│   ├── binance_adapter.py
│   └── bybit_adapter.py
└── templates/            # HTML templates
```

## Bug Fixes

### Order Executor Initialization (WebSocket Mode)
The original codebase had a bug where the order executor wasn't initialized when using WebSocket mode for price streaming. This has been fixed by ensuring REST adapters are always set up for order execution, regardless of the data streaming method.

**Fix location**: `app/core/trading_engine.py` and `app/services/trading_orchestrator.py`

```python
# Always set adapters first (initializes order executor)
engine.set_adapters(spot_adapter, futures_adapter)

# Then optionally add WebSocket for real-time streaming
ws_manager = create_websocket_manager(exchange_type, is_testnet)
if ws_manager:
    engine.set_websocket_manager(ws_manager)
```

## Security Considerations

### API Key Storage
- Keys are encrypted using AES-256-GCM before storage
- Each user has a unique encryption salt
- Master key is derived from environment variable
- Keys are never logged or exposed in error messages

### Password Storage
- Passwords hashed with Argon2id
- Memory-hard to prevent GPU attacks
- Automatic rehashing on parameter updates

### Session Security
- Secure, HttpOnly, SameSite cookies
- JWT tokens for API authentication
- Token refresh mechanism
- Session timeout and revocation

## License

Proprietary - All rights reserved.

## Support

For issues and feature requests, please contact support.
