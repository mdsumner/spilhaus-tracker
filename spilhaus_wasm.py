# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo>=0.24",
#     "numpy",
#     "pyproj",
#     "shapely>=2.0",
#     "geopandas>=1.0",
#     "matplotlib",
# ]
# ///
"""
Spilhaus in the browser: the vector-only half of spilhaus.py, exported with
`marimo export html-wasm` and run by Pyodide.

Pyodide ships its own pyproj build, with its own PROJ. There is no GDAL in
the browser, so no rasterio, pyogrio or /vsicurl here: this page is exactly
the "which PROJ did I actually get" question, asked of one more runtime.
"""

import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="Spilhaus in the browser")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        r"""
        # Spilhaus in the browser

        This page is Python running in your browser via **Pyodide**. It carries its
        own `pyproj`, built against its own PROJ. Whether `+proj=spilhaus` works here
        is decided by whichever PROJ the Pyodide maintainers built against - a fourth
        or fifth answer to "what PROJ do I have", alongside the ones in the
        [full notebook](../) and [the R version](../r/).

        There is no GDAL in the browser, so this page does the vector and point half
        only: a hand-typed set of landmarks, and Natural Earth coastlines fetched as
        GeoJSON with the browser's own `fetch`.
        """
    )
    return


@app.cell
def _(mo):
    import sys

    import numpy as np

    rows = []
    engine = None
    try:
        import pyproj

        row = dict(package="pyproj", version=pyproj.__version__, proj=pyproj.proj_version_str)
        try:
            crs = pyproj.CRS.from_proj4("+proj=spilhaus")
            fwd = pyproj.Transformer.from_crs(4326, crs, always_xy=True)
            engine = fwd
            row["spilhaus"] = "ok"
        except Exception as e:  # noqa: BLE001
            row["spilhaus"] = f"FAIL: {type(e).__name__}"
        rows.append(row)
    except ImportError:
        rows.append(dict(package="pyproj", version=None, proj=None, spilhaus="not installed"))

    try:
        import shapely as _shp

        rows.append(dict(package="shapely", version=_shp.__version__, proj=f"GEOS {_shp.geos_version_string}", spilhaus="n/a"))
    except ImportError:
        pass

    runtime = "Pyodide (browser)" if sys.platform == "emscripten" else f"CPython {sys.version.split()[0]} ({sys.platform})"

    mo.vstack(
        [
            mo.md(f"Runtime: **{runtime}**"),
            mo.ui.table(rows, selection=None, label="Native library provenance in this runtime"),
            mo.callout(
                mo.md(
                    "`+proj=spilhaus` is available here; the map below is drawn with it."
                    if engine
                    else "`+proj=spilhaus` is **not** available in this runtime's PROJ. "
                    "The table above is the whole result: nothing below can be drawn until Pyodide's pyproj is rebuilt against PROJ >= 9.6."
                ),
                kind="success" if engine else "warn",
            ),
        ]
    )
    return engine, np, rows, runtime


@app.cell
def _(engine, mo, np):
    mo.stop(engine is None, mo.md("_Skipping the map: no Spilhaus-capable PROJ in this runtime._"))

    def forward(lon, lat):
        x, y = engine.transform(np.asarray(lon, float), np.asarray(lat, float))
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        bad = ~np.isfinite(x) | ~np.isfinite(y) | (np.abs(x) > 1e15)
        x[bad] = np.nan
        y[bad] = np.nan
        return x, y

    _lon, _lat = np.meshgrid(np.linspace(-180, 180, 721), np.linspace(-90, 90, 361))
    _x, _y = forward(_lon, _lat)
    HALF = float(np.ceil(np.nanmax(np.abs(np.concatenate([_x, _y]))) / 1000.0) * 1000.0)
    return HALF, forward


@app.cell
def _(HALF, forward, mo, np):
    import json
    import urllib.request

    NE_GEOJSON = (
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_coastline.geojson"
    )

    def _fetch_json(url):
        # In Pyodide urllib is patched to use the browser's fetch; on CPython it is plain HTTP.
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))

    try:
        _gj = _fetch_json(NE_GEOJSON)
        _status = f"fetched {len(_gj['features'])} coastline features"
    except Exception as e:  # noqa: BLE001
        _gj = {"features": []}
        _status = f"coastline fetch failed ({type(e).__name__}); drawing landmarks only"

    import shapely
    from shapely.geometry import shape

    coast_segments = []
    for _f in _gj["features"]:
        _g = shapely.segmentize(shape(_f["geometry"]), 0.5)
        for _line in getattr(_g, "geoms", [_g]):
            _c = np.asarray(_line.coords)
            _x, _y = forward(_c[:, 0], _c[:, 1])
            _step = np.hypot(np.diff(_x), np.diff(_y))
            _ok = np.isfinite(_step) & (_step < HALF / 8)
            _start = 0
            for _i in list(np.flatnonzero(~_ok)) + [len(_step)]:
                if _i - _start >= 1:
                    coast_segments.append(np.c_[_x, _y][_start : _i + 1])
                _start = _i + 1

    mo.md(f"Coastlines: {_status}; {len(coast_segments)} drawable runs.")
    return (coast_segments,)


@app.cell
def _(HALF, coast_segments, forward, mo, np):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import patheffects
    from matplotlib.collections import LineCollection

    landmarks = {
        "Hobart": (147.33, -42.88),
        "Tokyo": (139.69, 35.69),
        "Reykjavik": (-21.94, 64.15),
        "Cape of Good Hope": (18.47, -34.36),
        "Bering Strait": (-169.0, 65.8),
        "Drake Passage": (-63.0, -59.0),
        "Point Nemo": (-123.39, -48.88),
        "Challenger Deep": (142.20, 11.37),
        "Puerto Rico Trench": (-66.5, 19.7),
        "Mid-Atlantic Ridge (Azores)": (-27.0, 38.0),
        "Macquarie Island": (158.94, -54.62),
        "Mawson Station": (62.87, -67.60),
        "Casey Station": (110.53, -66.28),
    }
    _lx, _ly = forward([v[0] for v in landmarks.values()], [v[1] for v in landmarks.values()])

    fig, ax = plt.subplots(figsize=(9, 9))
    ax.set_facecolor("#e9eef4")
    ax.add_patch(plt.Rectangle((-HALF, -HALF), 2 * HALF, 2 * HALF, fc="#e9eef4", ec="#333333", lw=0.8))
    ax.add_collection(LineCollection(coast_segments, colors="#2d4a6d", linewidths=0.7))
    ax.plot(_lx, _ly, "o", ms=5, color="#f2b134", mec="black", mew=0.6, zorder=5)
    for _name, _x, _y in zip(landmarks, _lx, _ly):
        ax.annotate(
            _name, (_x, _y), xytext=(5, 4), textcoords="offset points", fontsize=8.5, zorder=6,
            path_effects=[patheffects.withStroke(linewidth=2.5, foreground="white")],
        )
    ax.set_xlim(-HALF, HALF)
    ax.set_ylim(-HALF, HALF)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("Spilhaus, drawn by pyproj running in your browser", pad=12)
    fig.tight_layout()
    mo.vstack([fig])
    return


if __name__ == "__main__":
    app.run()
