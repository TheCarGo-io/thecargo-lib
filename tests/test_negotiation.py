import random

import pytest

from thecargo.negotiation import Band, Outcome, Side, ladder, next_step


def test_two_moves_shrink_and_end_exactly_at_the_ceiling():
    assert ladder(Side.BUY, Band(open=950, limit=1045), 2) == [950, 1005, 1045]


def test_three_moves_shrink_each_time():
    assert ladder(Side.BUY, Band(open=950, limit=1045), 3) == [950, 990, 1020, 1045]


def test_selling_steps_down_to_the_floor():
    assert ladder(Side.SELL, Band(open=1200, limit=1000), 2) == [1200, 1080, 1000]


def test_no_room_or_no_moves_leaves_only_the_opening_price():
    assert ladder(Side.BUY, Band(open=950, limit=950), 2) == [950]
    assert ladder(Side.BUY, Band(open=950, limit=1045), 0) == [950]


def test_a_tiny_gap_never_repeats_a_price():
    assert ladder(Side.BUY, Band(open=950, limit=953), 2) == [950, 953]


def test_the_first_answer_names_the_opening_price():
    step = next_step(
        Side.BUY, Band(open=950, limit=1045), offers=[], ask=None, max_concessions=2
    )
    assert (step.outcome, step.price) == (Outcome.COUNTER, 950)


def test_an_ask_at_or_under_our_price_is_taken_as_asked():
    band = Band(open=950, limit=1045)
    assert next_step(Side.BUY, band, offers=[], ask=900, max_concessions=2).price == 900
    assert (
        next_step(Side.BUY, band, offers=[950], ask=950, max_concessions=2).outcome
        is Outcome.ACCEPTED
    )


def test_a_higher_ask_gets_the_next_step_never_more_than_asked():
    band = Band(open=950, limit=1045)
    assert (
        next_step(Side.BUY, band, offers=[950], ask=1100, max_concessions=2).price
        == 1005
    )
    taken = next_step(Side.BUY, band, offers=[950], ask=990, max_concessions=2)
    assert (taken.outcome, taken.price) == (Outcome.ACCEPTED, 990)


def test_an_ask_above_the_ceiling_after_the_last_move_goes_to_a_person():
    step = next_step(
        Side.BUY,
        Band(open=950, limit=1045),
        offers=[950, 1005, 1045],
        ask=1100,
        max_concessions=2,
    )
    assert (step.outcome, step.price) == (Outcome.ESCALATE, 1100)


@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
def test_random_haggling_never_crosses_the_limit_or_the_move_count(side):
    rng = random.Random(7)
    for _ in range(2000):
        start = rng.randint(200, 5000)
        room = rng.randint(0, 900)
        band = Band(
            open=start, limit=start + room if side is Side.BUY else start - room
        )
        moves = rng.randint(0, 4)
        offers: list[float] = []
        for _ in range(8):
            ask = rng.choice([None, rng.randint(100, 6000)])
            step = next_step(side, band, offers=offers, ask=ask, max_concessions=moves)
            if step.price is not None and step.outcome is not Outcome.ESCALATE:
                if side is Side.BUY:
                    assert step.price <= band.limit
                else:
                    assert step.price >= band.limit
            if step.outcome is not Outcome.COUNTER:
                break
            offers.append(step.price)
        assert len(offers) <= moves + 1


@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
def test_each_move_is_no_bigger_than_the_one_before_give_or_take_rounding(side):
    rng = random.Random(11)
    for _ in range(2000):
        start = rng.randint(200, 5000)
        room = rng.randint(30, 900)
        band = Band(
            open=start, limit=start + room if side is Side.BUY else start - room
        )
        prices = ladder(side, band, rng.randint(1, 4))
        moves = [abs(b - a) for a, b in zip(prices, prices[1:])]
        assert all(later <= earlier + 5 for earlier, later in zip(moves, moves[1:]))
