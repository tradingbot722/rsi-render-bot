# bot.py
# Telegram RSI Signal Bot (TwelveData) — Render-ready (Background Worker)
# Env vars required:
#   TELEGRAM_BOT_TOKEN   = 123456:ABC...
#   TWELVE_API_KEY       = your_twelvedata_key
#   SYMBOLS              = EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD,NZD/USD,EUR/JPY,GBP/JPY
#   TIMEFRAME            = 1min   (or 5min, 15min, 1h, etc — TwelveData interval format)
#   RSI_PERIOD           = 14
#
# Optional env vars:
#   OVERBOUGHT           = 70
#   OVERSOLD             = 30
#   COOLDOWN_MINUTES     = 20   (anti-spam per symbol+direction)
#   CHECK_EVERY_SECONDS  = 60   (used only if timeframe isn't parseable)
#   DEBUG_LOG            = 0/1
#
# Commands:
#   /start   subscribe to signals
#   /stop    unsubscribe
#   /status  show settings + your subscription state

import os
import json
import time
import math
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

SUBSCRIBERS_FILE = "subscribers.json"
TWELVE_RSI_URL = "https://api.twelvedata.com/rsi"


def env_str(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None or str(v).strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return str(v).strip()


def env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return int(str(v).strip())


def env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return float(str(v).strip())


def parse_symbols(raw: str) -> List[str]:
    # Accept commas / newlines / semicolons
    parts = []
    for chunk in raw.replace("\n", ",").replace(";", ",").split(","):
        s = chunk.strip()
        if s:
            parts.append(s)
    # Deduplicate preserving order
    seen = set()
    out = []
    for s in parts:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def load_subscribers() -> List[int]:
    try:
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [int(x) for x in data]
    except FileNotFoundError:
        return []
    except Exception:
        return []
    return []


def save_subscribers(ids: List[int]) -> None:
    try:
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(set(ids))), f, ensure_ascii=False, indent=2)
    except Exception:
        # On Render free tier, filesystem is ephemeral; still fine.
        pass


def interval_to_seconds(interval: str) -> Optional[int]:
    """
    TwelveData intervals examples: 1min, 5min, 15min, 30min, 45min, 1h, 2h, 1day, etc.
    We'll align only for min/h.
    """
    s = interval.strip().lower()
    try:
        if s.endswith("min"):
            n = int(s[:-3])
            return n * 60
        if s.endswith("m"):
            n = int(s[:-1])
            return n * 60
        if s.endswith("h"):
            n = int(s[:-1])
            return n * 3600
    except Exception:
        return None
    return None


def seconds_until_next_boundary(step_seconds: int) -> int:
    """
    Align to exact candle boundaries in UTC.
    For 5min => :00, :05, :10, ...
    """
    now = datetime.now(timezone.utc).timestamp()
    # Next multiple of step_seconds
    next_t = (math.floor(now / step_seconds) + 1) * step_seconds
    return max(1, int(round(next_t - now)))


class RSIBot:
    def __init__(self):
        self.telegram_token = env_str("TELEGRAM_BOT_TOKEN")
        self.twelve_key = env_str("TWELVE_API_KEY")

        self.symbols = parse_symbols(env_str("SYMBOLS", "EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD,NZD/USD,EUR/JPY,GBP/JPY"))
        self.timeframe = env_str("TIMEFRAME", "1min")
        self.rsi_period = env_int("RSI_PERIOD", 14)
