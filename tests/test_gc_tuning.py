import gc

import pytest

from thecargo.gc_tuning import freeze_startup_heap


@pytest.fixture
def restore_gc():
    threshold = gc.get_threshold()
    yield
    gc.unfreeze()
    gc.set_threshold(*threshold)


def test_startup_objects_leave_the_collected_generations(restore_gc):
    freeze_startup_heap()

    assert gc.get_freeze_count() > 0
    assert gc.get_count()[2] == 0


def test_young_collections_run_far_less_often(restore_gc):
    freeze_startup_heap()

    assert gc.get_threshold() == (10_000, 20, 20)
