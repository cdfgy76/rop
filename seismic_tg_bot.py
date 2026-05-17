#!/usr/bin/env python3
"""
Seismic Testnet Telegram Bot
=============================
Telegram bot for interacting with the Seismic Testnet (Chain ID: 5124)
- Multi-wallet management (create/import/list/remove/export)
- Deploy Timer & Token contracts (single or all wallets)
- Check balances across all wallets
- Auto-deploy mode
- Transaction explorer links
- Network info & faucet link

Usage:
  1. Create a Telegram bot via @BotFather and get the token
  2. Set your token: export TELEGRAM_BOT_TOKEN="your-token-here"
  3. pip install -r requirements.txt
  4. python seismic_tg_bot.py
"""

import json
import logging
import os
import sys
import secrets
import asyncio
from datetime import datetime
from pathlib import Path

try:
    from web3 import Web3
    from eth_account import Account
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application,
        CommandHandler,
        CallbackQueryHandler,
        ConversationHandler,
        MessageHandler,
        filters,
        ContextTypes,
    )
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip install web3 python-telegram-bot py-solc-x")
    sys.exit(1)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Seismic Testnet Configuration ─────────────────────────────────────────────
CHAIN_ID = 5124
RPC_URL = "https://testnet-1.seismictest.net/rpc"
WS_URL = "wss://testnet-1.seismictest.net/ws"
EXPLORER_URL = "https://seismic-testnet.socialscan.io"
FAUCET_URL = "https://faucet-2.seismictest.net"
WALLETS_FILE = "seismic_wallets.json"

# ── Conversation states ───────────────────────────────────────────────────────
(
    IMPORT_KEY,
    IMPORT_NAME,
    CREATE_NAME,
    REMOVE_SELECT,
    DEPLOY_TIMER_SELECT,
    DEPLOY_TOKEN_SELECT,
    TOKEN_NAME,
    TOKEN_SYMBOL,
    AUTO_INTERVAL,
    AUTO_TOKEN_NAME,
    AUTO_TOKEN_SYMBOL,
) = range(11)

# ── Web3 Helper ───────────────────────────────────────────────────────────────

def get_web3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    return w3


def load_wallets() -> list:
    if not Path(WALLETS_FILE).exists():
        return []
    with open(WALLETS_FILE, "r") as f:
        return json.load(f)


def save_wallets(wallets: list):
    with open(WALLETS_FILE, "w") as f:
        json.dump(wallets, f, indent=2)


def short_addr(addr: str) -> str:
    return f"{addr[:6]}...{addr[-4:]}"


def explorer_tx(tx_hash: str) -> str:
    return f"{EXPLORER_URL}/tx/{tx_hash}"


def explorer_addr(addr: str) -> str:
    return f"{EXPLORER_URL}/address/{addr}"


# ── Solidity Compilation ─────────────────────────────────────────────────────

def compile_solidity(source: str, contract_name: str):
    try:
        import solcx
    except ImportError:
        return None, None

    installed = solcx.get_installed_solc_versions()
    target_version = "0.8.19"
    if not any(str(v).startswith("0.8") for v in installed):
        solcx.install_solc(target_version)

    solcx.set_solc_version(target_version)
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


TIMER_SOURCE = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;
contract Timer {
    uint256 public lastTimestamp;
    constructor() { lastTimestamp = block.timestamp; }
    function updateTimestamp() public { lastTimestamp = block.timestamp; }
}
"""

TOKEN_SOURCE = """
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


def deploy_contract_from_wallet(wallet: dict, contract_type: str,
                                 token_name: str = "", token_symbol: str = ""):
    """Deploy a contract and return (success, message, contract_address)."""
    w3 = get_web3()
    if not w3.is_connected():
        return False, "Cannot connect to Seismic RPC", None

    acct = Account.from_key(wallet["private_key"])
    balance = w3.eth.get_balance(acct.address)
    if balance == 0:
        return False, f"Wallet has 0 ETH. Get testnet ETH from faucet first!\n{FAUCET_URL}", None

    if contract_type == "timer":
        abi, bytecode = compile_solidity(TIMER_SOURCE, "Timer")
    else:
        abi, bytecode = compile_solidity(TOKEN_SOURCE, "SimpleToken")

    if not bytecode:
        return False, "Solidity compilation failed. Make sure py-solc-x is installed.", None

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    nonce = w3.eth.get_transaction_count(acct.address)

    try:
        gas_price = w3.eth.gas_price
    except Exception:
        gas_price = w3.to_wei("1", "gwei")

    if contract_type == "timer":
        tx = contract.constructor().build_transaction({
            "chainId": CHAIN_ID,
            "from": acct.address,
            "nonce": nonce,
            "gasPrice": gas_price,
        })
    else:
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

    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt["status"] == 1:
            contract_addr = receipt["contractAddress"]
            msg = (
                f"Contract deployed!\n"
                f"Address: `{contract_addr}`\n"
                f"TX: [View on Explorer]({explorer_tx(tx_hash.hex())})\n"
                f"Contract: [View on Explorer]({explorer_addr(contract_addr)})"
            )
            return True, msg, contract_addr
        else:
            return False, f"Transaction reverted!\nTX: {explorer_tx(tx_hash.hex())}", None
    except Exception as e:
        return False, f"Error waiting for receipt: {e}", None


# ── Telegram Bot Handlers ─────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💰 Wallet Management", callback_data="wallet_menu")],
        [InlineKeyboardButton("📊 Check Balances", callback_data="check_balance")],
        [InlineKeyboardButton("📜 Deploy Contracts", callback_data="deploy_menu")],
        [InlineKeyboardButton("🔍 View Transactions", callback_data="view_tx")],
        [InlineKeyboardButton("🌐 Network Info", callback_data="network_info")],
        [InlineKeyboardButton("🚰 Faucet Link", callback_data="faucet")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        "⛏ *SEISMIC TESTNET BOT* ⛏\n\n"
        "Chain ID: `5124`\n"
        "RPC: `testnet-1.seismictest.net/rpc`\n"
        "Explorer: seismic-testnet.socialscan.io\n\n"
        "Select an option:"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=reply_markup, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=text, reply_markup=reply_markup, parse_mode="Markdown"
        )


# ── Wallet Menu ───────────────────────────────────────────────────────────────

async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ Create New Wallet", callback_data="create_wallet")],
        [InlineKeyboardButton("📥 Import Wallet (Private Key)", callback_data="import_wallet")],
        [InlineKeyboardButton("📋 List All Wallets", callback_data="list_wallets")],
        [InlineKeyboardButton("❌ Remove Wallet", callback_data="remove_wallet")],
        [InlineKeyboardButton("🔑 Export Wallets (Show Keys)", callback_data="export_wallets")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text="*WALLET MANAGEMENT*\n\nSelect an option:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def create_wallet_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Enter a name for the new wallet (or send /skip for auto-name):"
    )
    return CREATE_NAME


async def create_wallet_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = load_wallets()
    name = update.message.text.strip()
    if name == "/skip":
        name = f"Wallet-{len(wallets) + 1}"

    acct = Account.create(extra_entropy=secrets.token_hex(32))
    wallet_data = {
        "name": name,
        "address": acct.address,
        "private_key": acct.key.hex(),
        "created_at": datetime.now().isoformat(),
    }
    wallets.append(wallet_data)
    save_wallets(wallets)

    text = (
        f"✅ *New Wallet Created!*\n\n"
        f"Name: `{name}`\n"
        f"Address: `{acct.address}`\n"
        f"Private Key: `{acct.key.hex()}`\n\n"
        f"⚠️ *SAVE YOUR PRIVATE KEY SECURELY!*\n"
        f"Get testnet ETH: {FAUCET_URL}"
    )

    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    await update.message.reply_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def import_wallet_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Send your private key (with or without 0x prefix):")
    return IMPORT_KEY


async def import_wallet_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pk = update.message.text.strip()
    if not pk.startswith("0x"):
        pk = "0x" + pk

    try:
        acct = Account.from_key(pk)
    except Exception as e:
        await update.message.reply_text(f"Invalid private key: {e}\n\nTry again or /cancel")
        return IMPORT_KEY

    wallets = load_wallets()
    for w in wallets:
        if w["address"].lower() == acct.address.lower():
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
            await update.message.reply_text(
                f"Wallet already exists: `{acct.address}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return ConversationHandler.END

    context.user_data["import_pk"] = pk
    context.user_data["import_address"] = acct.address
    await update.message.reply_text(
        f"Address: `{acct.address}`\n\nEnter a name for this wallet (or /skip for auto):",
        parse_mode="Markdown",
    )
    return IMPORT_NAME


async def import_wallet_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = load_wallets()
    name = update.message.text.strip()
    if name == "/skip":
        name = f"Wallet-{len(wallets) + 1}"

    wallet_data = {
        "name": name,
        "address": context.user_data["import_address"],
        "private_key": context.user_data["import_pk"],
        "created_at": datetime.now().isoformat(),
    }
    wallets.append(wallet_data)
    save_wallets(wallets)

    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    await update.message.reply_text(
        f"✅ *Wallet Imported!*\n\nName: `{name}`\nAddress: `{wallet_data['address']}`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def list_wallets_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    if not wallets:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "No wallets found. Create or import one first.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    w3 = get_web3()
    text = "*YOUR WALLETS*\n\n"
    for i, w in enumerate(wallets, 1):
        try:
            bal = w3.eth.get_balance(w["address"])
            bal_eth = w3.from_wei(bal, "ether")
        except Exception:
            bal_eth = "Error"
        text += (
            f"*{i}. {w['name']}*\n"
            f"  `{w['address']}`\n"
            f"  Balance: {bal_eth} ETH\n\n"
        )

    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def remove_wallet_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    if not wallets:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "No wallets to remove.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    keyboard = []
    for i, w in enumerate(wallets):
        keyboard.append([
            InlineKeyboardButton(
                f"{w['name']} ({short_addr(w['address'])})",
                callback_data=f"remove_{i}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")])

    await query.edit_message_text(
        "Select wallet to remove:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return REMOVE_SELECT


async def remove_wallet_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    wallets = load_wallets()
    if 0 <= idx < len(wallets):
        removed = wallets.pop(idx)
        save_wallets(wallets)
        text = f"✅ Removed: {removed['name']} (`{removed['address']}`)"
    else:
        text = "Invalid selection."

    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def export_wallets_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    if not wallets:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "No wallets to export.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    text = "🔑 *WALLET EXPORT*\n⚠️ Keep your private keys safe!\n\n"
    for i, w in enumerate(wallets, 1):
        text += (
            f"*{i}. {w['name']}*\n"
            f"Address: `{w['address']}`\n"
            f"Key: `{w['private_key']}`\n"
            f"[Explorer]({explorer_addr(w['address'])})\n\n"
        )

    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


# ── Balance Check ─────────────────────────────────────────────────────────────

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    if not wallets:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "No wallets found.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    w3 = get_web3()
    text = "📊 *WALLET BALANCES*\n\n"
    total = 0
    for i, w in enumerate(wallets, 1):
        try:
            bal = w3.eth.get_balance(w["address"])
            bal_eth = float(w3.from_wei(bal, "ether"))
            total += bal_eth
            emoji = "🟢" if bal > 0 else "🔴"
        except Exception:
            bal_eth = 0
            emoji = "⚠️"
        text += f"{emoji} *{w['name']}*: {bal_eth:.6f} ETH\n  `{short_addr(w['address'])}`\n\n"

    text += f"💰 *Total: {total:.6f} ETH*"

    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# ── Deploy Menu ───────────────────────────────────────────────────────────────

async def deploy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("⏱ Deploy Timer (Single)", callback_data="deploy_timer_single")],
        [InlineKeyboardButton("🪙 Deploy Token (Single)", callback_data="deploy_token_single")],
        [InlineKeyboardButton("⏱ Deploy Timer (ALL Wallets)", callback_data="deploy_timer_all")],
        [InlineKeyboardButton("🪙 Deploy Token (ALL Wallets)", callback_data="deploy_token_all")],
        [InlineKeyboardButton("🔄 Auto Deploy Mode", callback_data="auto_deploy")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text="*CONTRACT DEPLOYMENT*\n\nSelect an option:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def deploy_timer_single_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    if not wallets:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "No wallets found. Create one first.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    keyboard = []
    for i, w in enumerate(wallets):
        keyboard.append([
            InlineKeyboardButton(
                f"{w['name']} ({short_addr(w['address'])})",
                callback_data=f"timer_{i}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")])

    await query.edit_message_text(
        "Select wallet to deploy Timer contract:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DEPLOY_TIMER_SELECT


async def deploy_timer_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    wallets = load_wallets()
    if idx >= len(wallets):
        await query.edit_message_text("Invalid wallet.")
        return ConversationHandler.END

    wallet = wallets[idx]
    await query.edit_message_text(
        f"⏳ Deploying Timer from {wallet['name']}...\nPlease wait..."
    )

    success, msg, addr = deploy_contract_from_wallet(wallet, "timer")
    keyboard = [
        [InlineKeyboardButton("📜 Deploy More", callback_data="deploy_menu")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")],
    ]
    prefix = "✅" if success else "❌"
    await query.edit_message_text(
        text=f"{prefix} *Timer Deploy*\nWallet: {wallet['name']}\n\n{msg}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


async def deploy_token_single_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    if not wallets:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "No wallets found.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    keyboard = []
    for i, w in enumerate(wallets):
        keyboard.append([
            InlineKeyboardButton(
                f"{w['name']} ({short_addr(w['address'])})",
                callback_data=f"tkwallet_{i}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")])

    await query.edit_message_text(
        "Select wallet to deploy Token contract:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DEPLOY_TOKEN_SELECT


async def deploy_token_wallet_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    context.user_data["token_wallet_idx"] = idx
    await query.edit_message_text("Enter token name (e.g. SeismicToken):")
    return TOKEN_NAME


async def deploy_token_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["token_name"] = update.message.text.strip() or "SeismicToken"
    await update.message.reply_text("Enter token symbol (e.g. SEIS):")
    return TOKEN_SYMBOL


async def deploy_token_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token_symbol = update.message.text.strip() or "SEIS"
    token_name = context.user_data["token_name"]
    idx = context.user_data["token_wallet_idx"]
    wallets = load_wallets()

    if idx >= len(wallets):
        await update.message.reply_text("Invalid wallet.")
        return ConversationHandler.END

    wallet = wallets[idx]
    await update.message.reply_text(
        f"⏳ Deploying Token '{token_name}' ({token_symbol}) from {wallet['name']}...\nPlease wait..."
    )

    success, msg, addr = deploy_contract_from_wallet(wallet, "token", token_name, token_symbol)
    keyboard = [
        [InlineKeyboardButton("📜 Deploy More", callback_data="deploy_menu")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")],
    ]
    prefix = "✅" if success else "❌"
    await update.message.reply_text(
        text=f"{prefix} *Token Deploy*\nWallet: {wallet['name']}\nToken: {token_name} ({token_symbol})\n\n{msg}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


# ── Batch Deploy ──────────────────────────────────────────────────────────────

async def deploy_timer_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    if not wallets:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "No wallets found.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    await query.edit_message_text(
        f"⏳ Deploying Timer from {len(wallets)} wallet(s)...\nThis may take a while..."
    )

    results = []
    for i, w in enumerate(wallets):
        success, msg, addr = deploy_contract_from_wallet(w, "timer")
        status = f"✅ {addr}" if success else f"❌ Failed"
        results.append(f"{w['name']}: {status}")

    text = "*BATCH TIMER DEPLOY RESULTS*\n\n" + "\n".join(results)
    keyboard = [
        [InlineKeyboardButton("📜 Deploy More", callback_data="deploy_menu")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def deploy_token_all_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    if not wallets:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "No wallets found.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    context.user_data["batch_token"] = True
    await query.edit_message_text("Enter token name for all wallets (e.g. SeismicToken):")
    return TOKEN_NAME


async def batch_token_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["batch_token_name"] = update.message.text.strip() or "SeismicToken"
    await update.message.reply_text("Enter token symbol (e.g. SEIS):")
    return TOKEN_SYMBOL


async def batch_token_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token_symbol = update.message.text.strip() or "SEIS"
    token_name = context.user_data.get("batch_token_name", "SeismicToken")
    wallets = load_wallets()

    await update.message.reply_text(
        f"⏳ Deploying Token '{token_name}' ({token_symbol}) from {len(wallets)} wallet(s)...\nPlease wait..."
    )

    results = []
    for w in wallets:
        success, msg, addr = deploy_contract_from_wallet(w, "token", token_name, token_symbol)
        status = f"✅ `{addr}`" if success else "❌ Failed"
        results.append(f"{w['name']}: {status}")

    text = f"*BATCH TOKEN DEPLOY*\nToken: {token_name} ({token_symbol})\n\n" + "\n".join(results)
    keyboard = [
        [InlineKeyboardButton("📜 Deploy More", callback_data="deploy_menu")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")],
    ]
    await update.message.reply_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    context.user_data.pop("batch_token", None)
    context.user_data.pop("batch_token_name", None)
    return ConversationHandler.END


# ── Auto Deploy ───────────────────────────────────────────────────────────────

async def auto_deploy_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    if not wallets:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "No wallets found. Add wallets first.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "🔄 *AUTO DEPLOY MODE*\n\n"
        "This will deploy Timer + Token contracts from all wallets on a loop.\n\n"
        "Enter interval in hours (e.g. 24):",
        parse_mode="Markdown",
    )
    return AUTO_INTERVAL


async def auto_deploy_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        hours = int(update.message.text.strip())
    except ValueError:
        hours = 24
    context.user_data["auto_interval"] = hours * 3600
    await update.message.reply_text("Enter token name (e.g. SeismicToken):")
    return AUTO_TOKEN_NAME


async def auto_deploy_token_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["auto_token_name"] = update.message.text.strip() or "SeismicToken"
    await update.message.reply_text("Enter token symbol (e.g. SEIS):")
    return AUTO_TOKEN_SYMBOL


async def auto_deploy_token_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token_symbol = update.message.text.strip() or "SEIS"
    token_name = context.user_data["auto_token_name"]
    interval = context.user_data["auto_interval"]
    hours = interval // 3600

    # Store auto-deploy config
    context.user_data["auto_running"] = True
    context.user_data["auto_token_symbol"] = token_symbol
    context.user_data["auto_cycle"] = 0

    await update.message.reply_text(
        f"🔄 *Auto Deploy Started!*\n\n"
        f"Token: {token_name} ({token_symbol})\n"
        f"Interval: {hours}h\n"
        f"Wallets: {len(load_wallets())}\n\n"
        f"Send /stop\\_auto to stop.",
        parse_mode="Markdown",
    )

    # Run first cycle immediately, then schedule
    asyncio.create_task(
        run_auto_deploy_cycle(update, context, token_name, token_symbol, interval)
    )
    return ConversationHandler.END


async def run_auto_deploy_cycle(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 token_name: str, token_symbol: str, interval: int):
    chat_id = update.effective_chat.id
    cycle = 0
    while context.user_data.get("auto_running", False):
        cycle += 1
        wallets = load_wallets()
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔄 *Auto Deploy Cycle {cycle}*\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="Markdown",
        )

        # Deploy timers
        timer_results = []
        for w in wallets:
            success, msg, addr = deploy_contract_from_wallet(w, "timer")
            status = "✅" if success else "❌"
            timer_results.append(f"{status} {w['name']}")

        # Deploy tokens
        token_results = []
        for w in wallets:
            success, msg, addr = deploy_contract_from_wallet(
                w, "token", f"{token_name}_{cycle}", token_symbol
            )
            status = "✅" if success else "❌"
            token_results.append(f"{status} {w['name']}")

        text = (
            f"📊 *Cycle {cycle} Results*\n\n"
            f"*Timer:*\n" + "\n".join(timer_results) + "\n\n"
            f"*Token:*\n" + "\n".join(token_results) + "\n\n"
            f"Next cycle in {interval // 3600}h\n"
            f"Send /stop\\_auto to stop."
        )
        await context.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="Markdown"
        )

        # Wait for interval
        for _ in range(interval // 10):
            if not context.user_data.get("auto_running", False):
                break
            await asyncio.sleep(10)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🛑 Auto deploy stopped after {cycle} cycle(s).",
    )


async def stop_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["auto_running"] = False
    await update.message.reply_text("🛑 Stopping auto-deploy mode...")


# ── View Transactions ─────────────────────────────────────────────────────────

async def view_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wallets = load_wallets()
    if not wallets:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "No wallets found.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    text = "🔍 *TRANSACTION EXPLORER*\n\nClick to view transactions:\n\n"
    for i, w in enumerate(wallets, 1):
        text += f"{i}. [{w['name']}]({explorer_addr(w['address'])})\n"

    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


# ── Network Info ──────────────────────────────────────────────────────────────

async def network_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    w3 = get_web3()
    try:
        block = w3.eth.block_number
        chain_id = w3.eth.chain_id
        gas_price = w3.from_wei(w3.eth.gas_price, "gwei")
    except Exception:
        block = "N/A"
        chain_id = CHAIN_ID
        gas_price = "N/A"

    text = (
        "🌐 *SEISMIC TESTNET INFO*\n\n"
        f"Network: Seismic Testnet\n"
        f"Chain ID: `{chain_id}`\n"
        f"RPC: `{RPC_URL}`\n"
        f"WS: `{WS_URL}`\n"
        f"Explorer: {EXPLORER_URL}\n"
        f"Faucet: {FAUCET_URL}\n"
        f"Currency: ETH (18 decimals)\n"
        f"Block: {block}\n"
        f"Gas: {gas_price} gwei\n\n"
        "*MetaMask Setup:*\n"
        f"Network: `Seismic Testnet`\n"
        f"RPC: `{RPC_URL}`\n"
        f"Chain ID: `{CHAIN_ID}`\n"
        f"Symbol: `ETH`\n"
        f"Explorer: `{EXPLORER_URL}`"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


# ── Faucet ────────────────────────────────────────────────────────────────────

async def faucet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "🚰 *SEISMIC FAUCET*\n\n"
        f"Link: {FAUCET_URL}\n\n"
        "*Steps:*\n"
        "1. Connect with GitHub\n"
        "2. Paste your wallet address\n"
        "3. Claim ETH & USDC every 24h\n\n"
        "⚠️ Need 10 GitHub followers to use faucet"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


# ── Cancel / Help ─────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
    await update.message.reply_text(
        "Cancelled.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*SEISMIC TESTNET BOT - HELP*\n\n"
        "*Commands:*\n"
        "/start - Main menu\n"
        "/help - This help message\n"
        "/stop\\_auto - Stop auto-deploy\n"
        "/cancel - Cancel current operation\n\n"
        "*Features:*\n"
        "• Multi-wallet management\n"
        "• Deploy Timer & Token contracts\n"
        "• Batch deploy to all wallets\n"
        "• Auto deploy mode\n"
        "• Balance checking\n"
        "• Transaction explorer\n"
        "• Network info & faucet"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERROR: Set TELEGRAM_BOT_TOKEN environment variable!")
        print("  1. Create a bot via @BotFather on Telegram")
        print("  2. export TELEGRAM_BOT_TOKEN='your-token-here'")
        print("  3. python seismic_tg_bot.py")
        sys.exit(1)

    app = Application.builder().token(token).build()

    # Conversation handlers
    create_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_wallet_start, pattern="^create_wallet$")],
        states={CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_wallet_name)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    import_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(import_wallet_start, pattern="^import_wallet$")],
        states={
            IMPORT_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, import_wallet_key)],
            IMPORT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, import_wallet_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    remove_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_wallet_start, pattern="^remove_wallet$")],
        states={
            REMOVE_SELECT: [CallbackQueryHandler(remove_wallet_confirm, pattern="^remove_\\d+$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    deploy_timer_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(deploy_timer_single_start, pattern="^deploy_timer_single$")
        ],
        states={
            DEPLOY_TIMER_SELECT: [
                CallbackQueryHandler(deploy_timer_execute, pattern="^timer_\\d+$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    deploy_token_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(deploy_token_single_start, pattern="^deploy_token_single$")
        ],
        states={
            DEPLOY_TOKEN_SELECT: [
                CallbackQueryHandler(deploy_token_wallet_selected, pattern="^tkwallet_\\d+$")
            ],
            TOKEN_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, deploy_token_name)],
            TOKEN_SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, deploy_token_symbol)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    batch_token_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(deploy_token_all_start, pattern="^deploy_token_all$")
        ],
        states={
            TOKEN_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, batch_token_name)],
            TOKEN_SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, batch_token_symbol)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    auto_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(auto_deploy_start, pattern="^auto_deploy$")],
        states={
            AUTO_INTERVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, auto_deploy_interval)
            ],
            AUTO_TOKEN_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, auto_deploy_token_name)
            ],
            AUTO_TOKEN_SYMBOL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, auto_deploy_token_symbol)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Add handlers (conversation handlers first)
    app.add_handler(create_conv)
    app.add_handler(import_conv)
    app.add_handler(remove_conv)
    app.add_handler(deploy_timer_conv)
    app.add_handler(deploy_token_conv)
    app.add_handler(batch_token_conv)
    app.add_handler(auto_conv)

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stop_auto", stop_auto))
    app.add_handler(CommandHandler("cancel", cancel))

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(wallet_menu, pattern="^wallet_menu$"))
    app.add_handler(CallbackQueryHandler(list_wallets_handler, pattern="^list_wallets$"))
    app.add_handler(CallbackQueryHandler(export_wallets_handler, pattern="^export_wallets$"))
    app.add_handler(CallbackQueryHandler(check_balance, pattern="^check_balance$"))
    app.add_handler(CallbackQueryHandler(deploy_menu, pattern="^deploy_menu$"))
    app.add_handler(CallbackQueryHandler(deploy_timer_all, pattern="^deploy_timer_all$"))
    app.add_handler(CallbackQueryHandler(view_transactions, pattern="^view_tx$"))
    app.add_handler(CallbackQueryHandler(network_info, pattern="^network_info$"))
    app.add_handler(CallbackQueryHandler(faucet, pattern="^faucet$"))

    print("🤖 Seismic Testnet Telegram Bot started!")
    print("Send /start to your bot on Telegram")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
