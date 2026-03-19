"""
utils/memoize.py — Pickle-based function memoization.
"""
import os
import pickle


def memoize_function(func, cache_path: str, source_paths: list = None):
    """Caches the result of a zero-argument callable to a pickle file.

    On the first call the result is computed by calling ``func()`` and
    persisted to ``cache_path``.  On every subsequent call the pickled result
    is loaded from disk, skipping the computation entirely.

    If ``source_paths`` is provided, the cache is invalidated when any of
    those files are newer than the cache file (i.e. the input data changed).

    The caller is responsible for constructing the callable with all required
    arguments already bound (e.g. via a ``lambda``).

    Args:
        func: A zero-argument callable whose return value should be cached.
        cache_path: Absolute or relative path to the pickle cache file.
            Parent directories must already exist.
        source_paths: Optional list of file paths. If any source file is
            newer than the cache, the cache is recomputed.

    Returns:
        The return value of ``func()``, either freshly computed or loaded
        from the cache.
    """
    if os.path.exists(cache_path):
        cache_valid = True
        if source_paths:
            cache_mtime = os.path.getmtime(cache_path)
            for src in source_paths:
                if os.path.exists(src) and os.path.getmtime(src) > cache_mtime:
                    cache_valid = False
                    break
        if cache_valid:
            with open(cache_path, "rb") as fh:
                return pickle.load(fh)

    result = func()

    with open(cache_path, "wb") as fh:
        pickle.dump(result, fh)

    return result
