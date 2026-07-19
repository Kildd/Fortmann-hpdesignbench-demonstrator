"""
Experiment runner for HpDesignBench optimization studies.

Applies an optimization algorithm to one or more IOH problem bundles,
records per-evaluation data with an IOH Analyzer logger, patches the
generated IOHprofiler metadata files to report the custom suite name
``HpDesignBench``, and optionally zips the result folders.

Adapted from: Max Dombrowski

Modifications by Elliot Melcer:

* one shared logger for all problems in a call
* docstrings
"""
import os
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from ioh.iohcpp.logger import trigger as ltr
import ioh
import json


SUITE_NAME = "HpDesignBench"


def _zip_folders(folders: list[Path], zip_path: Path, base_dir: Path) -> None:
    """
    Zip a list of folders into a single archive.

    Parameters
    ----------
    folders : list[Path]
        Folders to include in the archive.
    zip_path : Path
        Destination path for the ``.zip`` file.
    base_dir : Path
        Root directory used to compute relative archive paths.
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in folders:
            for file in folder.rglob("*"):
                if file.is_file():
                    zf.write(file, arcname=file.relative_to(base_dir))


def run_experiment(
    problem_bundle: dict[str, dict],
    algorithm,
    n_runs: int,
    name: str = "",
    zip_results: bool = True,
    delete_after_zip: bool = False,
    return_summary: bool = False,
):
    """
    Run an optimization algorithm on a set of IOH problems and log results.

    For each problem in ``problem_bundle`` the algorithm is called
    ``n_runs`` times. All runs share a single IOH Analyzer logger.
    After all problems are processed, the IOHprofiler JSON metadata files
    are patched to report ``HpDesignBench`` as the suite name, and the
    new result folders are optionally zipped.

    Parameters
    ----------
    problem_bundle : dict[str, dict]
        Mapping of problem IDs to problem bundle dicts as returned by
        :func:`build_problems_for_slab`. Each bundle must contain:

        - ``"problem"`` — IOH problem instance.
        - ``"ctx"`` — :class:`EvalContext` instance.
        - ``"var_names"`` — list of optimization variable names.
        - ``"active_constraint_names"`` — list of active constraint names.
        - ``"decode"`` — callable ``decode(x_idx) -> dict``.

    algorithm : callable
        Optimization algorithm object with a ``name`` attribute (and
        optionally an ``info`` attribute). Called as ``algorithm(problem)``
        for each run.
    n_runs : int
        Number of independent optimization runs per problem.
    name : str, optional
        Label for the logger folder and zip file. Defaults to
        ``"my_benchmarking_study"`` if empty.
    zip_results : bool, optional
        If ``True``, zip all newly created result folders after the
        experiment. Default is ``True``.
    delete_after_zip : bool, optional
        If ``True``, remove the source folders after zipping. Only
        effective when ``zip_results=True``. Default is ``False``.
    return_summary : bool, optional
        If ``True``, return a dict with wall-clock timing and per-run
        evaluation counters from each problem's :class:`EvalContext`.
        Default is ``False``.
    """
    started_at = time.perf_counter()
    run_summaries: list[dict] = []

    out_root = Path(os.getcwd()) / "logger_results"
    out_root.mkdir(parents=True, exist_ok=True)

    # snapshot existing JSONs so we only patch the ones written this call
    pre_existing = set(out_root.rglob("IOHprofiler_f*.json"))
    # snapshot existing folders so we only zip the ones written this call
    pre_existing_folders = {p.name for p in out_root.iterdir() if p.is_dir()}

    folder_name = name if name else "my_benchmarking_study"
    print("Logging root:", out_root.resolve(), "\n")

    # One logger for the whole call (all problems share it) # Modification by: Elliot Melcer
    trigger_alw = [ltr.Each(1)]
    logger = ioh.logger.Analyzer(
        root=str(out_root),
        folder_name=folder_name,
        algorithm_name=algorithm.name,
        algorithm_info=getattr(algorithm, "info", "No additional information provided"),
        store_positions=True,
        triggers=trigger_alw,
    )

    try:
        for problem_id, bundle in problem_bundle.items():
            problem = bundle["problem"]
            eval_context = bundle["ctx"]
            var_names = bundle["var_names"]
            constraint_names = bundle["active_constraint_names"]
            decode = bundle["decode"]

            eval_context.ensure_constraints(constraint_names)
            eval_context.ensure_params(var_names)

            # Each problem has its own EvalContext, so the watches must
            # be (re)bound before this problem is attached. See note below.
            logger.watch(eval_context, "y")
            logger.watch(eval_context, "y_p")
            logger.watch(eval_context, "misses")
            logger.watch(eval_context, "hits")
            for constr in constraint_names:
                logger.watch(eval_context, f"c__{constr}")
            for var in var_names:
                logger.watch(eval_context, f"var__{var}")

            problem.attach_logger(logger)

            for run in range(n_runs):
                problem.reset()
                eval_context.reset()
                algorithm(problem)

                best_y = problem.state.current_best.y
                best_x = list(problem.state.current_best.x)
                best_vars = {n: decode(best_x)[n] for n in var_names}
                print(f"[{problem.meta_data.name}] run {run + 1}/{n_runs}  "
                      f"best y = {best_y:.3f}")
                print(f"    x_idx = {best_x}")
                print(f"    vars  = {best_vars}")
                print("")
                print("")

                if return_summary:
                    run_summaries.append(
                        {
                            "problem_id": problem_id,
                            "problem_name": problem.meta_data.name,
                            "run": run + 1,
                            "hits": eval_context.hits,
                            "misses": eval_context.misses,
                            "optimizer_evaluations": getattr(
                                algorithm, "n_optimizer_evaluations_", None
                            ),
                            "best_y": best_y,
                        }
                    )

            problem.detach_logger()
    finally:
        logger.close()

    # patch suite name into newly written JSONs (once, after all problems)
    new_jsons = set(out_root.rglob("IOHprofiler_f*.json")) - pre_existing
    for jf in new_jsons:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            data["suite"] = SUITE_NAME
            jf.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[warn] could not patch suite name in {jf.name}: {e}")

    # ---- zip the result folders created during this call ----
    if zip_results:
        new_folders = [
            p for p in out_root.iterdir()
            if p.is_dir() and p.name not in pre_existing_folders
        ]
        if new_folders:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base = folder_name if name else "experiment"
            zip_path = out_root / f"{base}_{timestamp}.zip"
            _zip_folders(new_folders, zip_path, out_root)
            print(f"\nZipped {len(new_folders)} folder(s) to: {zip_path}")

            if delete_after_zip:
                for folder in new_folders:
                    shutil.rmtree(folder, ignore_errors=True)
                print("Removed source folders after zipping.")
        else:
            print("\nNo new folders to zip.")

    if return_summary:
        return {
            "wall_time_s": time.perf_counter() - started_at,
            "runs": run_summaries,
        }