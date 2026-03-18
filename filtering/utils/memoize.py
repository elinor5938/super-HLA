"""
utils/memoize.py — Pickle-based function memoization.
"""
import os
import pickle


def memoize_function(func, cache_path: str):
    """Caches the result of a zero-argument callable to a pickle file.

    On the first call the result is computed by calling ``func()`` and
    persisted to ``cache_path``.  On every subsequent call the pickled result
    is loaded from disk, skipping the computation entirely.

    The caller is responsible for constructing the callable with all required
    arguments already bound (e.g. via a ``lambda``).

    Args:
        func: A zero-argument callable whose return value should be cached.
        cache_path: Absolute or relative path to the pickle cache file.
            Parent directories must already exist.

    Returns:
        The return value of ``func()``, either freshly computed or loaded
        from the cache.

    Example:
        >>> result = memoize_function(
        ...     lambda: expensive_computation(arg1, arg2),
        ...     "/data/memoization/stage-0/result.pickle"
        ... )
    """
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as fh:
            return pickle.load(fh)

    result = func()

    with open(cache_path, "wb") as fh:
        pickle.dump(result, fh)

    return result
