# Seismic Testnet Multi-Wallet Bot

Automated script for interacting with the **Seismic Testnet** (Chain ID: 5124) with multi-wallet support.

## Features

- **Multi-Wallet Management** — Create, import, list, remove, and export wallets
- **Balance Checking** — Check ETH balances across all wallets at once
- **Contract Deployment** — Deploy Timer and ERC20 Token contracts
- **Batch Deploy** — Deploy contracts from all wallets in one go
- **Auto Deploy Mode** — Automated deployment loop with configurable intervals
- **Transaction Explorer** — Quick links to view transactions on Seismic Explorer
- **Network Info** — View Seismic Testnet details and MetaMask setup instructions

## Seismic Testnet Info

| Property | Value |
|----------|-------|
| Chain ID | `5124` |
| RPC (HTTP) | `https://testnet-1.seismictest.net/rpc` |
| RPC (WS) | `wss://testnet-1.seismictest.net/ws` |
| Explorer | `https://seismic-testnet.socialscan.io` |
| Currency | ETH (18 decimals) |
| Faucet | `https://faucet-2.seismictest.net` |

## Setup

```bash
# Install dependencies
pip install -r requirements.txt
```

### Option 1: CLI Script (Terminal)
```bash
python seismic_testnet.py
```

### Option 2: Telegram Bot
```bash
# 1. Create a bot via @BotFather on Telegram and get the token
# 2. Set your token
export TELEGRAM_BOT_TOKEN="your-token-here"

# 3. Run the bot
python seismic_tg_bot.py
```
Then open your bot on Telegram and send `/start`.

## Usage

### Main Menu
```
1. Wallet Management     — Create/Import/List/Remove/Export wallets
2. Check Balances        — View ETH balance for all wallets
3. Deploy Contracts      — Deploy Timer/Token contracts (single or batch)
4. View Transactions     — Explorer links for wallet transactions
5. Network Info          — Seismic Testnet details & MetaMask setup
6. Faucet Link           — Get testnet ETH & USDC
0. Exit
```

### Quick Start
1. Run the script: `python seismic_testnet.py`
2. Go to **Wallet Management** → Create or Import a wallet
3. Get testnet ETH from the faucet (need 10 GitHub followers)
4. Go to **Deploy Contracts** → Deploy Timer or Token contracts
5. Use **Auto Deploy Mode** for automated daily deployments

### Multi-Wallet Workflow
1. Create/import multiple wallets
2. Fund all wallets from the faucet
3. Use **Batch Deploy** to deploy contracts from all wallets at once
4. Use **Auto Deploy Mode** to automate recurring deployments

## Faucet Instructions
1. Go to faucet: `https://faucet-2.seismictest.net`
2. Connect with GitHub (need 10 followers)
3. Paste your wallet address
4. Claim ETH & USDC every 24 hours

## Add Seismic Testnet to MetaMask
1. Open MetaMask → Settings → Networks → Add Network
2. Enter:
   - Network Name: `Seismic Testnet`
   - RPC URL: `https://testnet-1.seismictest.net/rpc`
   - Chain ID: `5124`
   - Currency Symbol: `ETH`
   - Explorer: `https://seismic-testnet.socialscan.io`

## Files
- `seismic_testnet.py` — Main bot script
- `requirements.txt` — Python dependencies
- `seismic_wallets.json` — Wallet storage (created on first use, **keep private!**)

## Security
- Private keys are stored locally in `seismic_wallets.json`
- **Never share your `seismic_wallets.json` file**
- Add `seismic_wallets.json` to `.gitignore`
