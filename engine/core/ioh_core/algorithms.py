"""
Optimization algorithm wrappers for IOHexperimenter problems.

Provides :class:`NLoptDirectLocalSearch` (NLopt DIRECT-L) and
:class:`RandomSearch` as drop-in callables compatible with the IOH
problem interface used in HpDesignBench.

Adapted from: Max Dombrowski

Modifications by Elliot Melcer:

* added algorithm info
* removed extra evaluation of the best solution in NLopt
* docstrings
"""
import nlopt
import numpy as np


class NLoptDirectLocalSearch:
    """
    NLopt DIRECT-L wrapper around an IOHexperimenter problem.
    Adapted from: Max Dombrowski

    Uses the locally biased variant of the DIviding RECTangles (DIRECT)
    algorithm (``nlopt.GN_DIRECT_L``) for derivative-free global
    optimization over integer index bounds.

    Attributes
    ----------
    max_evaluations : int
        Maximum number of objective function evaluations [-].
    name : str
        Algorithm identifier string used by the IOH logger.
    info : str
        Human-readable algorithm description.
    """

    def __init__(self, max_evaluations: int = 50):
        """
        Parameters
        ----------
        max_evaluations : int, optional
            Maximum number of objective function evaluations.
            Default is ``50``.
        """
        self.max_evaluations = int(max_evaluations)
        self.name = "NLOPT_DIRECT_L"
        self.info = "locally biased variant of DIviding RECTangles (DIRECT) algorithm for global optimization" #(Added by: Elliot Melcer)
        self.n_optimizer_evaluations_ = 0

    def __call__(self, problem):
        """
        Run the DIRECT-L optimizer on an IOH problem.

        Parameters
        ----------
        problem : ioh.Problem
            An IOHexperimenter problem instance exposing
            ``meta_data.n_variables``, ``bounds.lb``, ``bounds.ub``,
            and callable evaluation via ``problem(x_int)``.

        Returns
        -------
        tuple[float, list[int]]
            ``(f_best, x_best_int)`` — the best objective value found and
            the corresponding integer index vector.
        """
        # Dimension & bounds from IOH
        n = int(problem.meta_data.n_variables)
        lb = [float(problem.bounds.lb[i]) for i in range(n)]
        ub = [float(problem.bounds.ub[i]) for i in range(n)]

        # Choose a DIRECT variant (global, derivative-free)
        # GN_DIRECT_L is usually a good default.
        opt = nlopt.opt(nlopt.GN_DIRECT_L, n)

        opt.set_lower_bounds(lb)
        opt.set_upper_bounds(ub)

        self.n_optimizer_evaluations_ = 0

        def objective(x, grad):
            # DIRECT ignores grad; just comply with the signature.
            # Map floats to ints for IOH
            x_int = [int(round(xi)) for xi in x]
            self.n_optimizer_evaluations_ += 1
            y = problem(x_int)   # penalised objective
            return float(y)

        opt.set_min_objective(objective)
        opt.set_maxeval(self.max_evaluations)

        # Initial point (DIRECT is global, but NLopt wants a start point anyway)
        x0 = [(lo + hi) / 2.0 for lo, hi in zip(lb, ub)]

        try:
            x_best = opt.optimize(x0)
            f_best = float(opt.last_optimum_value())
        except nlopt.RoundoffLimited:
            # If DIRECT bails out with numerical issues, still grab the best seen
            x_best = opt.last_optimize_result()  # may not be super helpful, but keep structure
            f_best = float(opt.last_optimum_value())
        # (If you want to be strict, you can re-raise instead.)

        # Cast back to ints
        x_best_int = [int(round(xi)) for xi in x_best]

        # Keep IOH state consistent
        # problem(x_best_int) #(Modified by: Elliot Melcer)

        return f_best, x_best_int


class RandomSearch:
    """
    Simple random search over integer index bounds.
    Author: Max Dombrowski

    Samples uniformly from the integer index ranges defined by the IOH
    problem bounds and tracks the best objective value found.

    Attributes
    ----------
    name : str
        Algorithm identifier string used by the IOH logger.
    info : str
        Human-readable algorithm description.
    evaluations : int
        Number of random samples to draw per call [-].
    rng : numpy.random.Generator
        Random number generator instance.
    best_y_ : float
        Best objective value found in the last call (set after ``__call__``).
    best_x_ : list[int]
        Integer index vector achieving ``best_y_`` (set after ``__call__``).

    """

    def __init__(self, max_evaluations: int, seed: int | None = None):
        """
        Parameters
        ----------
        max_evaluations : int
            Number of random samples to draw per optimization call.
        seed : int or None, optional
            Seed for the random number generator. ``None`` uses a
            non-deterministic seed. Default is ``None``.
        """
        self.name = "RANDOM_SEARCH"
        self.info = "Very simple random search over integer index bounds"
        self.evaluations = int(max_evaluations)
        self.rng = np.random.default_rng(seed)

    def __call__(self, problem):
        """
        Run the random search on an IOH problem.

        Parameters
        ----------
        problem : ioh.Problem
            An IOHexperimenter problem instance exposing
            ``bounds.lb``, ``bounds.ub``, ``meta_data.n_variables``,
            and callable evaluation via ``problem(x)``.

        Returns
        -------
        RandomSearch
            Returns ``self`` with :attr:`best_y_` and :attr:`best_x_`
            updated to the best solution found.
        """
        lb = np.asarray(problem.bounds.lb, dtype=int)
        ub = np.asarray(problem.bounds.ub, dtype=int)
        dim = len(lb)

        # safety
        assert dim == problem.meta_data.n_variables

        # sample uniformly over integer index ranges
        best_y = None
        best_x = None
        for _ in range(self.evaluations):
            x = self.rng.integers(low=lb, high=ub + 1)  # inclusive upper bound for indices
            y = problem(x)  # IOH problem is callable; evaluates objective (+ constraints internally)
            if (best_y is None) or (y < best_y):
                best_y, best_x = y, x.copy()

        # store for convenience
        self.best_y_ = float(best_y)
        self.best_x_ = [int(v) for v in best_x]
        return self