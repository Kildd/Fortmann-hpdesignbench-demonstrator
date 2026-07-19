# Vendored pure-Python packages

`structuralcodes` is copied here so the GitHub Pages / Pyodide path does **not**
need `micropip`.

The native Shewchuk `triangle` wheel is unavailable under Pyodide. The browser
path uses `engine/triangle_compat.py` (scipy + shapely) as a drop-in
`triangulate` shim so the **fiber** section integrator still runs.

Native local runs use the real `triangle` package from `requirements-engine.txt`.
