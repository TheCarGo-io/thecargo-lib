import gc


def freeze_startup_heap(threshold: int = 10_000) -> None:
    """Keep the cyclic collector off the objects loaded at startup and run it less often.

    Measured on the shipment and communication APIs, the default gen0 threshold of 700 runs about four collections
    per list request, and every gen2 pass walks the whole heap of modules, mappers and compiled statements: 1.0 to
    1.4 ms of CPU per request, up to a fifth of a list call. Freezing the startup heap moves it to the permanent
    generation, and a gen0 threshold of 10 000 cut the collector to about 0.1 ms per request. Call it once, after
    startup has finished and before the first request.
    """
    gc.collect()
    gc.freeze()
    gc.set_threshold(threshold, 20, 20)
