#!/usr/bin/env python3
"""
Seismic Testnet Multi-Wallet Bot
================================
Automates interactions with the Seismic Testnet (Chain ID: 5124)
- Multi-wallet management (create/import/list/remove)
- Deploy Timer & Token contracts
- Check balances across all wallets
- Batch deploy to all wallets at once
- Auto-deploy mode for daily tasks
- Transaction explorer links

Seismic Testnet Info:
  Chain ID    : 5124
  RPC (HTTP)  : https://testnet-1.seismictest.net/rpc
  RPC (WS)    : wss://testnet-1.seismictest.net/ws
  Explorer    : https://seismic-testnet.socialscan.io
  Currency    : ETH (18 decimals)
  Faucet      : https://faucet-2.seismictest.net

Usage:
  pip install web3 colorama
  python seismic_testnet.py
"""

import json
import os
import sys
import time
import secrets
import signal
from datetime import datetime
from pathlib import Path

try:
    from web3 import Web3
    from eth_account import Account
    from colorama import Fore, Style, init as colorama_init
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip install web3 colorama")
    sys.exit(1)

colorama_init(autoreset=True)

# ── Seismic Testnet Configuration ──────────────────────────────────────────────
CHAIN_ID = 5124
RPC_URL = "https://testnet-1.seismictest.net/rpc"
WS_URL = "wss://testnet-1.seismictest.net/ws"
EXPLORER_URL = "https://seismic-testnet.socialscan.io"
FAUCET_URL = "https://faucet-2.seismictest.net"

WALLETS_FILE = "seismic_wallets.json"

# ── Minimal Solidity Contracts (compiled bytecode) ────────────────────────────
# Timer contract: stores block.timestamp, can be updated
TIMER_ABI = json.loads(
    '[{"inputs":[],"stateMutability":"nonpayable","type":"constructor"},'
    '{"inputs":[],"name":"lastTimestamp","outputs":[{"internalType":"uint256",'
    '"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},'
    '{"inputs":[],"name":"updateTimestamp","outputs":[],"stateMutability":"nonpayable",'
    '"type":"function"}]'
)

# Compiled Timer contract bytecode (Solidity 0.8.x):
# contract Timer {
#     uint256 public lastTimestamp;
#     constructor() { lastTimestamp = block.timestamp; }
#     function updateTimestamp() public { lastTimestamp = block.timestamp; }
# }
TIMER_BYTECODE = (
    "6080604052348015600e575f5ffd5b504260005560d3806100255f395ff3fe"
    "6080604052348015600e575f5ffd5b50600436106030575f3560e01c806336"
    "b80a57146034578063c565882714604c575b5f5ffd5b603a6054565b604051"
    "604391906079565b60405180910390f35b60526059565b005b5f5481565b42"
    "5f81905550565b5f819050919050565b607381606063565b82525050565b5f"
    "60208201905060886020830184606c565b9291505056fea264697066735822"
    "1220"
)

# Token contract: ERC20-like with name, symbol, and basic transfer
TOKEN_ABI = json.loads(
    '[{"inputs":[{"internalType":"string","name":"_name","type":"string"},'
    '{"internalType":"string","name":"_symbol","type":"string"}],'
    '"stateMutability":"nonpayable","type":"constructor"},'
    '{"inputs":[],"name":"name","outputs":[{"internalType":"string",'
    '"name":"","type":"string"}],"stateMutability":"view","type":"function"},'
    '{"inputs":[],"name":"symbol","outputs":[{"internalType":"string",'
    '"name":"","type":"string"}],"stateMutability":"view","type":"function"},'
    '{"inputs":[],"name":"totalSupply","outputs":[{"internalType":"uint256",'
    '"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},'
    '{"inputs":[{"internalType":"address","name":"","type":"address"}],'
    '"name":"balanceOf","outputs":[{"internalType":"uint256","name":"",'
    '"type":"uint256"}],"stateMutability":"view","type":"function"},'
    '{"inputs":[{"internalType":"address","name":"to","type":"address"},'
    '{"internalType":"uint256","name":"amount","type":"uint256"}],'
    '"name":"transfer","outputs":[{"internalType":"bool","name":"",'
    '"type":"bool"}],"stateMutability":"nonpayable","type":"function"},'
    '{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address",'
    '"name":"from","type":"address"},{"indexed":true,"internalType":"address",'
    '"name":"to","type":"address"},{"indexed":false,"internalType":"uint256",'
    '"name":"value","type":"uint256"}],"name":"Transfer","type":"event"}]'
)

# Simple ERC20 Token bytecode (constructor takes name, symbol strings)
# contract SimpleToken {
#     string public name; string public symbol;
#     uint8 public decimals = 18;
#     uint256 public totalSupply;
#     mapping(address => uint256) public balanceOf;
#     event Transfer(address indexed from, address indexed to, uint256 value);
#     constructor(string memory _name, string memory _symbol) {
#         name = _name; symbol = _symbol;
#         totalSupply = 1000000 * 1e18;
#         balanceOf[msg.sender] = totalSupply;
#         emit Transfer(address(0), msg.sender, totalSupply);
#     }
#     function transfer(address to, uint256 amount) public returns (bool) {
#         require(balanceOf[msg.sender] >= amount);
#         balanceOf[msg.sender] -= amount;
#         balanceOf[to] += amount;
#         emit Transfer(msg.sender, to, amount);
#         return true;
#     }
# }

# ── Utility Functions ─────────────────────────────────────────────────────────

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def banner():
    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════╗
║        {Fore.YELLOW}⛏  SEISMIC TESTNET MULTI-WALLET BOT  ⛏{Fore.CYAN}              ║
║                                                              ║
║  {Fore.WHITE}Chain ID  : 5124{Fore.CYAN}                                          ║
║  {Fore.WHITE}RPC       : testnet-1.seismictest.net/rpc{Fore.CYAN}                  ║
║  {Fore.WHITE}Explorer  : seismic-testnet.socialscan.io{Fore.CYAN}                  ║
║  {Fore.WHITE}Faucet    : faucet-2.seismictest.net{Fore.CYAN}                       ║
╚══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}
""")


def get_web3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print(f"{Fore.RED}[ERROR] Cannot connect to Seismic Testnet RPC: {RPC_URL}")
        print(f"{Fore.YELLOW}[TIP] Check your internet connection and try again.")
        sys.exit(1)
    return w3


def load_wallets() -> list[dict]:
    if not Path(WALLETS_FILE).exists():
        return []
    with open(WALLETS_FILE, "r") as f:
        return json.load(f)


def save_wallets(wallets: list[dict]):
    with open(WALLETS_FILE, "w") as f:
        json.dump(wallets, f, indent=2)
    print(f"{Fore.GREEN}[OK] Wallets saved to {WALLETS_FILE}")


def short_addr(addr: str) -> str:
    return f"{addr[:6]}...{addr[-4:]}"


def explorer_tx(tx_hash: str) -> str:
    return f"{EXPLORER_URL}/tx/{tx_hash}"


def explorer_addr(addr: str) -> str:
    return f"{EXPLORER_URL}/address/{addr}"


def wait_for_receipt(w3: Web3, tx_hash, timeout: int = 120):
    print(f"{Fore.YELLOW}[...] Waiting for transaction confirmation...")
    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        if receipt["status"] == 1:
            print(f"{Fore.GREEN}[OK] Transaction confirmed in block {receipt['blockNumber']}")
            print(f"     TX: {explorer_tx(tx_hash.hex())}")
        else:
            print(f"{Fore.RED}[FAIL] Transaction reverted!")
            print(f"     TX: {explorer_tx(tx_hash.hex())}")
        return receipt
    except Exception as e:
        print(f"{Fore.RED}[ERROR] Timeout or error waiting for receipt: {e}")
        return None


# ── Wallet Management ─────────────────────────────────────────────────────────

def create_wallet():
    wallets = load_wallets()
    acct = Account.create(extra_entropy=secrets.token_hex(32))
    name = input(f"{Fore.CYAN}Enter wallet name (or press Enter for auto): {Style.RESET_ALL}").strip()
    if not name:
        name = f"Wallet-{len(wallets) + 1}"

    wallet_data = {
        "name": name,
        "address": acct.address,
        "private_key": acct.key.hex(),
        "created_at": datetime.now().isoformat(),
    }
    wallets.append(wallet_data)
    save_wallets(wallets)

    print(f"\n{Fore.GREEN}[OK] New wallet created!")
    print(f"     Name       : {name}")
    print(f"     Address    : {acct.address}")
    print(f"     Private Key: {acct.key.hex()}")
    print(f"\n{Fore.RED}[!] SAVE YOUR PRIVATE KEY SECURELY! Don't share it with anyone!")
    print(f"{Fore.YELLOW}[TIP] Get testnet ETH from faucet: {FAUCET_URL}")
    return wallet_data


def import_wallet():
    wallets = load_wallets()
    pk = input(f"{Fore.CYAN}Enter private key (with or without 0x): {Style.RESET_ALL}").strip()
    if not pk.startswith("0x"):
        pk = "0x" + pk

    try:
        acct = Account.from_key(pk)
    except Exception as e:
        print(f"{Fore.RED}[ERROR] Invalid private key: {e}")
        return None

    for w in wallets:
        if w["address"].lower() == acct.address.lower():
            print(f"{Fore.YELLOW}[!] Wallet already exists: {acct.address}")
            return w

    name = input(f"{Fore.CYAN}Enter wallet name (or press Enter for auto): {Style.RESET_ALL}").strip()
    if not name:
        name = f"Wallet-{len(wallets) + 1}"

    wallet_data = {
        "name": name,
        "address": acct.address,
        "private_key": pk,
        "created_at": datetime.now().isoformat(),
    }
    wallets.append(wallet_data)
    save_wallets(wallets)

    print(f"\n{Fore.GREEN}[OK] Wallet imported!")
    print(f"     Name    : {name}")
    print(f"     Address : {acct.address}")
    return wallet_data


def list_wallets():
    wallets = load_wallets()
    if not wallets:
        print(f"{Fore.YELLOW}[!] No wallets found. Create or import one first.")
        return wallets

    w3 = get_web3()
    print(f"\n{Fore.CYAN}{'#':<4} {'Name':<15} {'Address':<44} {'Balance (ETH)':<15}")
    print(f"{Fore.CYAN}{'─' * 80}")
    for i, w in enumerate(wallets, 1):
        try:
            bal = w3.eth.get_balance(w["address"])
            bal_eth = w3.from_wei(bal, "ether")
        except Exception:
            bal_eth = "Error"
        print(f"{Fore.WHITE}{i:<4} {w['name']:<15} {w['address']:<44} {str(bal_eth):<15}")
    print()
    return wallets


def remove_wallet():
    wallets = load_wallets()
    if not wallets:
        print(f"{Fore.YELLOW}[!] No wallets to remove.")
        return
    list_wallets()
    try:
        idx = int(input(f"{Fore.CYAN}Enter wallet number to remove: {Style.RESET_ALL}")) - 1
        if 0 <= idx < len(wallets):
            removed = wallets.pop(idx)
            save_wallets(wallets)
            print(f"{Fore.GREEN}[OK] Removed wallet: {removed['name']} ({removed['address']})")
        else:
            print(f"{Fore.RED}[ERROR] Invalid wallet number.")
    except ValueError:
        print(f"{Fore.RED}[ERROR] Please enter a valid number.")


def export_wallets():
    wallets = load_wallets()
    if not wallets:
        print(f"{Fore.YELLOW}[!] No wallets to export.")
        return
    print(f"\n{Fore.RED}[!] WARNING: Private keys will be shown! Make sure no one is watching.\n")
    confirm = input(f"{Fore.YELLOW}Are you sure? (yes/no): {Style.RESET_ALL}").strip().lower()
    if confirm != "yes":
        print(f"{Fore.CYAN}[OK] Export cancelled.")
        return
    for i, w in enumerate(wallets, 1):
        print(f"{Fore.WHITE}── Wallet {i} ──")
        print(f"  Name       : {w['name']}")
        print(f"  Address    : {w['address']}")
        print(f"  Private Key: {w['private_key']}")
        print(f"  Explorer   : {explorer_addr(w['address'])}")
        print()


def select_wallet(wallets: list[dict] | None = None) -> dict | None:
    if wallets is None:
        wallets = load_wallets()
    if not wallets:
        print(f"{Fore.YELLOW}[!] No wallets found. Create or import one first.")
        return None
    if len(wallets) == 1:
        print(f"{Fore.CYAN}[AUTO] Using wallet: {wallets[0]['name']} ({short_addr(wallets[0]['address'])})")
        return wallets[0]
    list_wallets()
    try:
        idx = int(input(f"{Fore.CYAN}Select wallet number: {Style.RESET_ALL}")) - 1
        if 0 <= idx < len(wallets):
            return wallets[idx]
        print(f"{Fore.RED}[ERROR] Invalid wallet number.")
    except ValueError:
        print(f"{Fore.RED}[ERROR] Please enter a valid number.")
    return None


# ── Balance Check ─────────────────────────────────────────────────────────────

def check_balance():
    wallets = load_wallets()
    if not wallets:
        print(f"{Fore.YELLOW}[!] No wallets found.")
        return
    w3 = get_web3()
    print(f"\n{Fore.CYAN}{'#':<4} {'Name':<15} {'Address':<44} {'ETH Balance':<18}")
    print(f"{Fore.CYAN}{'─' * 83}")
    for i, w in enumerate(wallets, 1):
        try:
            bal = w3.eth.get_balance(w["address"])
            bal_eth = w3.from_wei(bal, "ether")
            color = Fore.GREEN if bal > 0 else Fore.RED
            print(f"{Fore.WHITE}{i:<4} {w['name']:<15} {w['address']:<44} {color}{str(bal_eth):<18}")
        except Exception as e:
            print(f"{Fore.WHITE}{i:<4} {w['name']:<15} {w['address']:<44} {Fore.RED}Error: {e}")
    print()


# ── Contract Deployment ───────────────────────────────────────────────────────

def compile_timer_contract():
    """Return bytecode for a minimal Timer contract using raw EVM opcodes."""
    # Minimal Timer contract assembled in raw EVM bytecode
    # Constructor: stores block.timestamp in slot 0
    # Runtime: slot 0 getter + updateTimestamp function
    source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract Timer {
    uint256 public lastTimestamp;

    constructor() {
        lastTimestamp = block.timestamp;
    }

    function updateTimestamp() public {
        lastTimestamp = block.timestamp;
    }
}
"""
    return source


def compile_token_contract():
    """Return source for a minimal ERC20-like Token contract."""
    source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract SimpleToken {
    string public name;
    string public symbol;
    uint8 public constant decimals = 18;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;

    event Transfer(address indexed from, address indexed to, uint256 value);

    constructor(string memory _name, string memory _symbol) {
        name = _name;
        symbol = _symbol;
        totalSupply = 1000000 * 10 ** 18;
        balanceOf[msg.sender] = totalSupply;
        emit Transfer(address(0), msg.sender, totalSupply);
    }

    function transfer(address to, uint256 amount) public returns (bool) {
        require(balanceOf[msg.sender] >= amount, "Insufficient balance");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        emit Transfer(msg.sender, to, amount);
        return true;
    }
}
"""
    return source


def compile_solidity(source: str, contract_name: str):
    """Compile Solidity source using py-solc-x. Installs solc if needed."""
    try:
        import solcx
    except ImportError:
        print(f"{Fore.RED}[ERROR] py-solc-x not installed. Run: pip install py-solc-x")
        return None, None

    installed = solcx.get_installed_solc_versions()
    target_version = "0.8.19"
    if not any(str(v).startswith("0.8") for v in installed):
        print(f"{Fore.YELLOW}[...] Installing Solidity compiler v{target_version}...")
        solcx.install_solc(target_version)

    solcx.set_solc_version(target_version)
    print(f"{Fore.YELLOW}[...] Compiling {contract_name}...")
    compiled = solcx.compile_source(
        source,
        output_values=["abi", "bin"],
        solc_version=target_version,
    )
    contract_key = f"<stdin>:{contract_name}"
    if contract_key not in compiled:
        for key in compiled:
            if contract_name in key:
                contract_key = key
                break
    abi = compiled[contract_key]["abi"]
    bytecode = compiled[contract_key]["bin"]
    return abi, bytecode


def deploy_timer(wallet: dict):
    """Deploy a Timer contract from the given wallet."""
    w3 = get_web3()
    print(f"\n{Fore.CYAN}[DEPLOY] Timer Contract")
    print(f"  Wallet: {wallet['name']} ({short_addr(wallet['address'])})")

    source = compile_timer_contract()
    abi, bytecode = compile_solidity(source, "Timer")
    if not bytecode:
        print(f"{Fore.RED}[ERROR] Compilation failed.")
        return None

    acct = Account.from_key(wallet["private_key"])
    nonce = w3.eth.get_transaction_count(acct.address)
    balance = w3.eth.get_balance(acct.address)
    if balance == 0:
        print(f"{Fore.RED}[ERROR] Wallet has 0 ETH. Get testnet ETH from faucet first!")
        print(f"  Faucet: {FAUCET_URL}")
        return None

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    try:
        gas_price = w3.eth.gas_price
    except Exception:
        gas_price = w3.to_wei("1", "gwei")

    tx = contract.constructor().build_transaction({
        "chainId": CHAIN_ID,
        "from": acct.address,
        "nonce": nonce,
        "gasPrice": gas_price,
    })

    try:
        tx["gas"] = w3.eth.estimate_gas(tx)
    except Exception:
        tx["gas"] = 500000

    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"{Fore.GREEN}[OK] Timer deploy TX sent: {tx_hash.hex()}")

    receipt = wait_for_receipt(w3, tx_hash)
    if receipt and receipt["status"] == 1:
        contract_addr = receipt["contractAddress"]
        print(f"{Fore.GREEN}[OK] Timer contract deployed at: {contract_addr}")
        print(f"     Explorer: {EXPLORER_URL}/address/{contract_addr}")
        return contract_addr
    return None


def deploy_token(wallet: dict, token_name: str = None, token_symbol: str = None):
    """Deploy a Token contract from the given wallet."""
    w3 = get_web3()

    if not token_name:
        token_name = input(f"{Fore.CYAN}Enter token name: {Style.RESET_ALL}").strip()
        if not token_name:
            token_name = "SeismicToken"
    if not token_symbol:
        token_symbol = input(f"{Fore.CYAN}Enter token symbol: {Style.RESET_ALL}").strip()
        if not token_symbol:
            token_symbol = "SEIS"

    print(f"\n{Fore.CYAN}[DEPLOY] Token Contract")
    print(f"  Wallet: {wallet['name']} ({short_addr(wallet['address'])})")
    print(f"  Name  : {token_name}")
    print(f"  Symbol: {token_symbol}")

    source = compile_token_contract()
    abi, bytecode = compile_solidity(source, "SimpleToken")
    if not bytecode:
        print(f"{Fore.RED}[ERROR] Compilation failed.")
        return None

    acct = Account.from_key(wallet["private_key"])
    nonce = w3.eth.get_transaction_count(acct.address)
    balance = w3.eth.get_balance(acct.address)
    if balance == 0:
        print(f"{Fore.RED}[ERROR] Wallet has 0 ETH. Get testnet ETH from faucet first!")
        print(f"  Faucet: {FAUCET_URL}")
        return None

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    try:
        gas_price = w3.eth.gas_price
    except Exception:
        gas_price = w3.to_wei("1", "gwei")

    tx = contract.constructor(token_name, token_symbol).build_transaction({
        "chainId": CHAIN_ID,
        "from": acct.address,
        "nonce": nonce,
        "gasPrice": gas_price,
    })

    try:
        tx["gas"] = w3.eth.estimate_gas(tx)
    except Exception:
        tx["gas"] = 1500000

    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"{Fore.GREEN}[OK] Token deploy TX sent: {tx_hash.hex()}")

    receipt = wait_for_receipt(w3, tx_hash)
    if receipt and receipt["status"] == 1:
        contract_addr = receipt["contractAddress"]
        print(f"{Fore.GREEN}[OK] Token '{token_name}' ({token_symbol}) deployed at: {contract_addr}")
        print(f"     Explorer: {EXPLORER_URL}/address/{contract_addr}")
        return contract_addr
    return None


# ── Batch Deploy (All Wallets) ────────────────────────────────────────────────

def batch_deploy_timer():
    """Deploy Timer contract from all wallets."""
    wallets = load_wallets()
    if not wallets:
        print(f"{Fore.YELLOW}[!] No wallets found.")
        return

    print(f"\n{Fore.CYAN}[BATCH] Deploying Timer contract from {len(wallets)} wallet(s)...\n")
    results = []
    for i, w in enumerate(wallets, 1):
        print(f"{Fore.CYAN}── Wallet {i}/{len(wallets)}: {w['name']} ({short_addr(w['address'])}) ──")
        addr = deploy_timer(w)
        results.append({"wallet": w["name"], "address": w["address"], "contract": addr})
        if i < len(wallets):
            time.sleep(2)

    print(f"\n{Fore.CYAN}{'─' * 60}")
    print(f"{Fore.CYAN}[BATCH RESULTS] Timer Deployments:")
    for r in results:
        status = f"{Fore.GREEN}OK: {r['contract']}" if r["contract"] else f"{Fore.RED}FAILED"
        print(f"  {r['wallet']}: {status}")
    print()


def batch_deploy_token():
    """Deploy Token contract from all wallets."""
    wallets = load_wallets()
    if not wallets:
        print(f"{Fore.YELLOW}[!] No wallets found.")
        return

    token_name = input(f"{Fore.CYAN}Enter token name for all wallets: {Style.RESET_ALL}").strip()
    if not token_name:
        token_name = "SeismicToken"
    token_symbol = input(f"{Fore.CYAN}Enter token symbol for all wallets: {Style.RESET_ALL}").strip()
    if not token_symbol:
        token_symbol = "SEIS"

    print(f"\n{Fore.CYAN}[BATCH] Deploying Token '{token_name}' ({token_symbol}) from {len(wallets)} wallet(s)...\n")
    results = []
    for i, w in enumerate(wallets, 1):
        print(f"{Fore.CYAN}── Wallet {i}/{len(wallets)}: {w['name']} ({short_addr(w['address'])}) ──")
        addr = deploy_token(w, token_name, token_symbol)
        results.append({"wallet": w["name"], "address": w["address"], "contract": addr})
        if i < len(wallets):
            time.sleep(2)

    print(f"\n{Fore.CYAN}{'─' * 60}")
    print(f"{Fore.CYAN}[BATCH RESULTS] Token Deployments:")
    for r in results:
        status = f"{Fore.GREEN}OK: {r['contract']}" if r["contract"] else f"{Fore.RED}FAILED"
        print(f"  {r['wallet']}: {status}")
    print()


# ── Auto Deploy Mode ──────────────────────────────────────────────────────────

def auto_deploy_mode():
    """Automated deployment loop for all wallets."""
    wallets = load_wallets()
    if not wallets:
        print(f"{Fore.YELLOW}[!] No wallets found. Add wallets first.")
        return

    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════╗
║              AUTO DEPLOY MODE                            ║
║                                                          ║
║  This will automatically:                                ║
║  • Deploy Timer contract from all wallets (daily)        ║
║  • Deploy Token contract from all wallets (every cycle)  ║
║                                                          ║
║  Press Ctrl+C to stop                                    ║
╚══════════════════════════════════════════════════════════╝
""")

    interval_hours = input(f"{Fore.CYAN}Deploy interval in hours (default 24): {Style.RESET_ALL}").strip()
    try:
        interval = int(interval_hours) * 3600 if interval_hours else 86400
    except ValueError:
        interval = 86400

    token_name = input(f"{Fore.CYAN}Token name (default: SeismicToken): {Style.RESET_ALL}").strip() or "SeismicToken"
    token_symbol = input(f"{Fore.CYAN}Token symbol (default: SEIS): {Style.RESET_ALL}").strip() or "SEIS"

    cycle = 0
    running = True

    def stop_handler(sig, frame):
        nonlocal running
        running = False
        print(f"\n{Fore.YELLOW}[!] Stopping auto-deploy mode...")

    signal.signal(signal.SIGINT, stop_handler)

    while running:
        cycle += 1
        print(f"\n{Fore.CYAN}{'═' * 60}")
        print(f"{Fore.CYAN}  AUTO DEPLOY - Cycle {cycle} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{Fore.CYAN}{'═' * 60}\n")

        wallets = load_wallets()

        # Deploy Timer from all wallets
        print(f"{Fore.YELLOW}[TIMER] Deploying Timer contracts...")
        for i, w in enumerate(wallets, 1):
            if not running:
                break
            print(f"\n{Fore.CYAN}── [{i}/{len(wallets)}] {w['name']} ──")
            deploy_timer(w)
            time.sleep(2)

        if not running:
            break

        # Deploy Token from all wallets
        print(f"\n{Fore.YELLOW}[TOKEN] Deploying Token contracts...")
        for i, w in enumerate(wallets, 1):
            if not running:
                break
            print(f"\n{Fore.CYAN}── [{i}/{len(wallets)}] {w['name']} ──")
            deploy_token(w, f"{token_name}_{cycle}", token_symbol)
            time.sleep(2)

        if not running:
            break

        next_run = datetime.fromtimestamp(time.time() + interval)
        print(f"\n{Fore.GREEN}[OK] Cycle {cycle} complete!")
        print(f"{Fore.CYAN}[NEXT] Next cycle at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{Fore.YELLOW}[TIP] Press Ctrl+C to stop\n")

        # Sleep in small chunks so Ctrl+C is responsive
        elapsed = 0
        while elapsed < interval and running:
            time.sleep(min(30, interval - elapsed))
            elapsed += 30

    print(f"{Fore.GREEN}[OK] Auto-deploy mode stopped. Total cycles: {cycle}")


# ── Network Info ──────────────────────────────────────────────────────────────

def show_network_info():
    w3 = get_web3()
    try:
        block = w3.eth.block_number
        chain_id = w3.eth.chain_id
        gas_price = w3.eth.gas_price
    except Exception as e:
        print(f"{Fore.RED}[ERROR] Cannot fetch network info: {e}")
        return

    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════╗
║               SEISMIC TESTNET INFO                       ║
╠══════════════════════════════════════════════════════════╣
║  {Fore.WHITE}Network      : Seismic Testnet{Fore.CYAN}                          ║
║  {Fore.WHITE}Chain ID     : {chain_id}{Fore.CYAN}                                    ║
║  {Fore.WHITE}RPC (HTTP)   : {RPC_URL}{Fore.CYAN}  ║
║  {Fore.WHITE}RPC (WS)     : {WS_URL}{Fore.CYAN}   ║
║  {Fore.WHITE}Explorer     : {EXPLORER_URL}{Fore.CYAN}       ║
║  {Fore.WHITE}Faucet       : {FAUCET_URL}{Fore.CYAN}           ║
║  {Fore.WHITE}Currency     : ETH (18 decimals){Fore.CYAN}                        ║
║  {Fore.WHITE}Current Block: {block}{Fore.CYAN}{' ' * (40 - len(str(block)))}║
║  {Fore.WHITE}Gas Price    : {w3.from_wei(gas_price, 'gwei')} gwei{Fore.CYAN}{' ' * max(0, 34 - len(str(w3.from_wei(gas_price, 'gwei'))))}║
╚══════════════════════════════════════════════════════════╝
""")
    print(f"{Fore.YELLOW}[MetaMask Setup]")
    print(f"  Network Name : Seismic Testnet")
    print(f"  RPC URL      : {RPC_URL}")
    print(f"  Chain ID     : {CHAIN_ID}")
    print(f"  Symbol       : ETH")
    print(f"  Explorer     : {EXPLORER_URL}")
    print()


# ── Transaction Explorer ──────────────────────────────────────────────────────

def check_transactions():
    wallet = select_wallet()
    if not wallet:
        return
    print(f"\n{Fore.CYAN}[EXPLORER] View transactions for {wallet['name']}:")
    print(f"  {explorer_addr(wallet['address'])}")
    print(f"\n{Fore.YELLOW}[TIP] Open the link above in your browser to view all transactions.")
    print()


# ── Main Menu ─────────────────────────────────────────────────────────────────

def wallet_menu():
    while True:
        print(f"""
{Fore.CYAN}── WALLET MANAGEMENT ──────────────────
{Fore.WHITE}  1. Create New Wallet
  2. Import Wallet (Private Key)
  3. List All Wallets
  4. Remove Wallet
  5. Export Wallets (Show Keys)
  0. Back to Main Menu
""")
        choice = input(f"{Fore.CYAN}Select option: {Style.RESET_ALL}").strip()
        if choice == "1":
            create_wallet()
        elif choice == "2":
            import_wallet()
        elif choice == "3":
            list_wallets()
        elif choice == "4":
            remove_wallet()
        elif choice == "5":
            export_wallets()
        elif choice == "0":
            break
        else:
            print(f"{Fore.RED}Invalid option.")
        input(f"\n{Fore.CYAN}Press Enter to continue...{Style.RESET_ALL}")


def deploy_menu():
    while True:
        print(f"""
{Fore.CYAN}── CONTRACT DEPLOYMENT ────────────────
{Fore.WHITE}  1. Deploy Timer (Single Wallet)
  2. Deploy Token (Single Wallet)
  3. Deploy Timer (ALL Wallets)
  4. Deploy Token (ALL Wallets)
  5. Auto Deploy Mode (Loop)
  0. Back to Main Menu
""")
        choice = input(f"{Fore.CYAN}Select option: {Style.RESET_ALL}").strip()
        if choice == "1":
            w = select_wallet()
            if w:
                deploy_timer(w)
        elif choice == "2":
            w = select_wallet()
            if w:
                deploy_token(w)
        elif choice == "3":
            batch_deploy_timer()
        elif choice == "4":
            batch_deploy_token()
        elif choice == "5":
            auto_deploy_mode()
        elif choice == "0":
            break
        else:
            print(f"{Fore.RED}Invalid option.")
        input(f"\n{Fore.CYAN}Press Enter to continue...{Style.RESET_ALL}")


def main():
    clear_screen()
    banner()

    while True:
        print(f"""
{Fore.CYAN}── MAIN MENU ─────────────────────────
{Fore.WHITE}  1. Wallet Management
  2. Check Balances (All Wallets)
  3. Deploy Contracts
  4. View Transactions (Explorer)
  5. Network Info
  6. Faucet Link
  0. Exit
""")
        choice = input(f"{Fore.CYAN}Select option: {Style.RESET_ALL}").strip()

        if choice == "1":
            wallet_menu()
        elif choice == "2":
            check_balance()
            input(f"\n{Fore.CYAN}Press Enter to continue...{Style.RESET_ALL}")
        elif choice == "3":
            deploy_menu()
        elif choice == "4":
            check_transactions()
            input(f"\n{Fore.CYAN}Press Enter to continue...{Style.RESET_ALL}")
        elif choice == "5":
            show_network_info()
            input(f"\n{Fore.CYAN}Press Enter to continue...{Style.RESET_ALL}")
        elif choice == "6":
            print(f"\n{Fore.GREEN}[FAUCET] Get testnet ETH & USDC:")
            print(f"  {FAUCET_URL}")
            print(f"\n{Fore.YELLOW}[NOTE] You need 10 GitHub followers to use the faucet.")
            print(f"  1. Connect with GitHub")
            print(f"  2. Paste your wallet address")
            print(f"  3. Claim ETH & USDC every 24 hours")
            input(f"\n{Fore.CYAN}Press Enter to continue...{Style.RESET_ALL}")
        elif choice == "0":
            print(f"\n{Fore.GREEN}Goodbye! Happy testing on Seismic Testnet!")
            sys.exit(0)
        else:
            print(f"{Fore.RED}Invalid option. Try again.")


if __name__ == "__main__":
    main()
