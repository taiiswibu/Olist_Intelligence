"""Bounded, observable request scheduling for the read-only follow-up workflow."""
import asyncio
import math
import os
import random
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

VERSION = "followup-request-policy-v1"
TRANSIENT = {429, 502, 503, 504}
now = time.monotonic
sleep = asyncio.sleep


@dataclass(frozen=True)
class Policy:
    max_attempts: int = 2
    min_interval_seconds: float = 12
    max_wait_seconds: float = 30

    def __post_init__(self):
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise ValueError("Số lần gọi model phải từ một đến ba.")
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 60
               for v in (self.min_interval_seconds, self.max_wait_seconds)):
            raise ValueError("Thời gian chờ model phải hữu hạn, từ không đến sáu mươi giây.")

    def metadata(self):
        return {"version": VERSION, **asdict(self)}


def configured_policy():
    return Policy(max_attempts=int(os.getenv("FOLLOWUP_MAX_ATTEMPTS", "2")),
                  min_interval_seconds=float(os.getenv("FOLLOWUP_REQUEST_INTERVAL_SECONDS", "12")))


class ProviderCooldown(ValueError):
    def __init__(self, seconds):
        super().__init__("ProviderCooldown")
        self.seconds = round(seconds, 2)


class Gate:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.last_started = None
        self.not_before = 0

    def defer(self, seconds):
        self.not_before = max(self.not_before, now() + seconds)


@asynccontextmanager
async def scheduled(provider, policy):
    # Keep locks on their owning loop; TestClient/CLI loops never share asyncio locks.
    loop = asyncio.get_running_loop()
    gates = getattr(loop, "_olist_followup_gates", None)
    if gates is None:
        gates = loop._olist_followup_gates = {}
    key = (provider.name, getattr(provider, "base", ""), provider.model)
    gate = gates.setdefault(key, Gate())
    async with gate.lock:
        earliest = max(gate.not_before, (gate.last_started + policy.min_interval_seconds)
                       if gate.last_started is not None else 0)
        delay = max(0, earliest - now())
        if delay > policy.max_wait_seconds:
            raise ProviderCooldown(delay)
        if delay:
            await sleep(delay)
        gate.last_started = now()
        yield gate


def retry_delay(headers, attempt):
    """Read only Retry-After; never retain provider body, arbitrary headers or URLs."""
    value = headers.get("retry-after", "")
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            seconds = None
    if seconds is not None and math.isfinite(seconds) and seconds >= 0:
        return seconds
    return 2 ** (attempt - 1) + random.uniform(0, 1)
