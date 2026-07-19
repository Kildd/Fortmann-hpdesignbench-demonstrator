"""
Cache-based evaluation context for IOHexperimenter optimization problems.

Avoids redundant re-evaluation of the (expensive) structural analysis
function by memorizing the last call in a single-entry cache. Also
publishes decoded parameter values and constraint violations as watchable
attributes for the IOH Analyzer logger.

Author: Max Dombrowski

Modifications by Elliot Melcer:

* changed search strings to match analysis.py in hp_slab
* docstrings
"""


class EvalContext:
    """
    Single-entry memo cache that runs the structural analysis at most once
    per unique candidate vector and distributes results to the IOH objective
    and constraint callbacks.

    The cache key is the integer index tuple of the candidate. On a cache
    hit the stored result is returned immediately; on a miss the decode and
    analysis functions are called and the result is stored.

    Adapted from: Max Dombrowski

    Attributes
    ----------
    decode : callable
        ``decode(x_idx) -> dict`` — maps an integer index vector to a
        parameter dictionary.
    results : callable
        ``analysis(params) -> dict`` — runs the structural analysis and
        returns a result dictionary with at least ``"y"``, ``"y_p"``, and
        ``"penalties_"`` keys.
    last_key : tuple[int, ...] or None
        Index tuple of the most recently evaluated candidate, or ``None``
        if no evaluation has been performed yet.
    last_data : dict or None
        Cached result dict from the last analysis call, or ``None``.
    hits : int
        Number of times the cached result was reused [-].
    misses : int
        Number of times a fresh analysis was triggered [-].
    y : float
        Most recent unpenalized objective value (published for IOH logger).
    y_p : float
        Most recent penalized objective value (published for IOH logger).
    """

    def __init__(self, decode_func, analysis_func):
        """
        Parameters
        ----------
        decode_func : callable
            ``decode(x_idx) -> dict`` — decodes an integer index vector
            to a named parameter dictionary.
        analysis_func : callable
            ``analysis(params) -> dict`` — performs the structural analysis
            and returns a result dict containing at least ``"y"``,
            ``"y_p"``, and ``"penalties_"`` keys.
        """
        # stored callables
        self.decode = decode_func       # decode(x_idx) -> params dict
        self.results = analysis_func    # heavy_analysis(params) -> {"y","y_p","violations",...}

        # tiny single-entry memo cache
        self.last_key = None            # tuple of ints (candidate)
        self.last_data = None           # whatever heavy_analysis returns
        self.hits = 0                   # hits = how often data was reused from cache
        self.misses = 0                 # misses = how often data had to be executed

        # containers for active constraints and var names to pass them to logger
        self._c_names: list[str] = []  # constraint names to publish on self as c__<name>
        self._var_names: list[str] = []  # variable names to publish on self as var__<name> and idx__<name>
        # public attributes for logger to watch
        self.y = 0.0  # unpenalised (optional)
        self.y_p = 0.0  # penalised

    # --- declare stable attributes so IOH can bind watchers once and reuse them ---
    def ensure_constraints(self, names: list[str]):
        """
        Declare stable ``c__<name>`` attributes for all active constraints.

        Must be called before attaching the problem to an IOH logger so
        that the logger can bind watchers to stable attribute names.

        Parameters
        ----------
        names : list[str]
            Ordered list of active constraint names.
        """
        self._c_names = list(names)
        for n in self._c_names:
            setattr(self, f"c__{n}", 0.0)

    def ensure_params(self, var_names: list[str]):
        """
        Declare stable ``var__<name>`` and ``idx__<name>`` attributes for
        all optimization variable parameters.

        Must be called before attaching the problem to an IOH logger.

        Parameters
        ----------
        var_names : list[str]
            Ordered list of optimization variable names (matching the
            decode function's output keys).
        """
        self._var_names = list(var_names)
        for n in self._var_names:
            # decoded value (float-like if possible)
            setattr(self, f"var__{n}", 0.0)
            # chosen catalogue index (always integer)
            setattr(self, f"idx__{n}", 0)

    def get(self, x_idx):
        """
        Return the analysis result for a candidate, using the cache when possible.

        On a cache miss, calls ``decode(x_idx)`` followed by
        ``analysis(params)`` and stores the result. On a hit, returns the
        stored result directly. After either path, updates all watchable
        attributes (``y``, ``y_p``, ``c__*``, ``var__*``, ``idx__*``).

        Parameters
        ----------
        x_idx : sequence of int
            Integer index vector identifying the candidate.

        Returns
        -------
        dict
            Analysis result dictionary (same object as returned by
            ``analysis_func``).
        """
        key = tuple(int(k) for k in x_idx)
        if key == self.last_key:
            self.hits += 1
            rec = self.last_data
        else:
            self.misses += 1
            # decode -> analysis
            params = self.decode(x_idx)
            rec = self.results(params)
            self.last_key = key
            self.last_data = rec

        # publish fields for the logger (objective channels)
        self.y = float(rec.get("y", 0.0))
        self.y_p = float(rec.get("y_p", 0.0))

        # publish constraint channels (raw, non-negative violations expected)
        viol = rec.get("penalties_", {}) or {} # Modified by: Elliot Melcer
        for n in self._c_names:
            setattr(self, f"c__{n}", float(viol.get(n, 0.0)))

        # publish parameter channels
        # prefer the analysis-returned decoded map to avoid re-decoding drift
        pmap = rec.get("params")
        if pmap is None:
            # fallback to a fresh decode if analysis didn't return "params"
            try:
                pmap = self.decode(x_idx)
            except Exception:
                pmap = {}

        for i, n in enumerate(self._var_names):
            # decoded value (attempt float cast; if not numeric, leave previous numeric value)
            v = pmap.get(n)
            try:
                setattr(self, f"var__{n}", float(v))
            except (TypeError, ValueError):
                # keep previous numeric value to avoid breaking IOH numeric property
                pass
            # catalogue index from x_idx ordering
            try:
                setattr(self, f"idx__{n}", int(x_idx[i]))
            except Exception:
                # if dimension mismatch, keep previous
                pass

        return rec

    def reset(self):
        """
        Clear the cache and reset hit/miss counters.

        Call before each optimization run to ensure a clean state.
        """
        self.last_key = None
        self.last_data = None
        self.hits = self.misses = 0