"""The prices a one-number-at-a-time negotiation may name, decided without the model.

A buyer opens low and never names more than its ceiling; a seller opens high and
never names less than its floor. Between the opening price and that limit the
moves shrink — a smaller second move tells the other side the room is running
out — and the last move lands exactly on the limit. Pure functions: no database,
no network, so the broker side and the carrier side share one set of rules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

ROUNDING = 5


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class Outcome(StrEnum):
    ACCEPTED = "accepted"
    COUNTER = "counter"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class Band:
    open: float
    limit: float


@dataclass(frozen=True, slots=True)
class Step:
    outcome: Outcome
    price: float | None


def _beyond(side: Side, price: float, mark: float) -> bool:
    return price > mark if side is Side.BUY else price < mark


def ladder(side: Side, band: Band, max_concessions: int) -> list[float]:
    """Every price we may name, in order: the opening price, shrinking moves, then the limit itself."""
    gap = band.limit - band.open if side is Side.BUY else band.open - band.limit
    if gap <= 0 or max_concessions <= 0:
        return [band.open]
    weights = list(range(max_concessions + 1, 1, -1))
    prices = [band.open]
    moved = 0.0
    for weight in weights[:-1]:
        moved += gap * weight / sum(weights)
        step = math.floor(moved / ROUNDING) * ROUNDING
        price = band.open + step if side is Side.BUY else band.open - step
        if _beyond(side, price, prices[-1]):
            prices.append(float(price))
    prices.append(band.limit)
    return prices


def _takes(side: Side, ask: float, price: float) -> bool:
    return ask <= price if side is Side.BUY else ask >= price


def next_step(
    side: Side,
    band: Band,
    *,
    offers: list[float],
    ask: float | None,
    max_concessions: int,
) -> Step:
    """What to say to `ask` after naming `offers`: take it, name the next price, or hand it to a person.

    An ask no worse than our last price — or than the next one we would name — is taken
    as asked, so we never counter past what they want. Once the limit is named, a worse
    ask goes to a person.
    """
    if ask is not None and offers and _takes(side, ask, offers[-1]):
        return Step(Outcome.ACCEPTED, ask)
    prices = ladder(side, band, max_concessions)
    if len(offers) >= len(prices):
        return Step(Outcome.ESCALATE, ask)
    candidate = prices[len(offers)]
    if ask is not None and _takes(side, ask, candidate):
        return Step(Outcome.ACCEPTED, ask)
    return Step(Outcome.COUNTER, candidate)
