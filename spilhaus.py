# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo>=0.24",
#     "numpy",
#     "pyproj>=3.7",
#     "rasterio>=1.4",
#     "pyogrio>=0.13",
#     "geopandas>=1.0",
#     "shapely>=2.0",
#     "matplotlib>=3.8",
# ]
# ///
"""
Spilhaus from PROJ, through the Python stack.

The Spilhaus projection landed in PROJ 9.6.0 (March 2025). This notebook
builds a world-ocean map with it using only public sources read remotely
(/vsicurl), and - the real point - reports which PROJ each downstream
package actually carries, because in a pip environment every package
that bundles GDAL or PROJ bundles its own copy.

Run it yourself:

    uvx marimo edit --sandbox spilhaus.py

Environment overrides:

    SPILHAUS_RASTER   any GDAL-readable global raster (default: GEBCO 2024 COG)
    SPILHAUS_OCEAN    any OGR-readable ocean polygon layer (default: Natural Earth 110m)
    SPILHAUS_NPIX     output grid size in pixels (default 1600)
"""

import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="Spilhaus from PROJ")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        r"""
        <small>Also in this series:
        <a href="../r/">the R version</a> (gdalraster, wk, ximage; rendered on two Ubuntu runners) |
        <a href="../wasm/">the browser version</a> (pyproj in Pyodide) |
        <a href="../">index</a> | <a href="https://github.com/mdsumner/spilhaus-tracker">source</a> |
        <a href="https://www.hypertidy.org/posts/2026-09-20_road-to-spilhaus/">the story so far</a></small>

        # Spilhaus, as it flows downstream from PROJ

        `+proj=spilhaus` was added in **PROJ 9.6.0** (March 2025). Whether *you*
        can use it from Python depends not on what PROJ is installed on your
        machine, but on which PROJ each package carries with it. In a `pip`
        environment, `pyproj`, `rasterio`, `pyogrio` and the `osgeo` bindings each
        ship (or link) a **separate** copy of PROJ and GDAL.

        This notebook:

        1. tabulates the PROJ and GDAL behind each package and probes each one for `+proj=spilhaus`;
        2. builds a Spilhaus world-ocean map from public remote sources (bathymetry COG over `/vsicurl`,
           Natural Earth ocean polygons, a handful of hand-typed landmarks);
        3. uses whichever library *can* do the transform, and says which one it was.

        Nothing is downloaded up front; every source is read remotely via GDAL's virtual file systems.
        """
    )
    return


@app.cell
def _():
    import os
    import shutil
    import subprocess
    import sys
    import warnings

    import numpy as np

    warnings.filterwarnings("ignore", category=FutureWarning)

    # Remote-read hygiene for /vsicurl: no directory listings, only fetch what is asked for.
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")
    os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
    os.environ.setdefault("VSI_CACHE", "TRUE")
    os.environ.setdefault("VSI_CACHE_SIZE", str(64 * 1024 * 1024))

    SPILHAUS = "+proj=spilhaus"

    # The same map with every parameter spelled out (values from the PROJ docs).
    # Bare "+proj=spilhaus" relies on defaults that live in PROJ's source code.
    SPILHAUS_EXPLICIT = (
        "+proj=spilhaus +lon_0=66.94970198 +lat_0=-49.56371678 "
        "+azi=40.17823482 +rot=45 +k_0=1 +x_0=0 +y_0=0 +R=6378137"
    )

    # A different member of the same family: naive recentring on the Atlantic.
    # Same projection method, different parameters, and the cut now runs through ocean.
    SPILHAUS_ALT = "+proj=spilhaus +lon_0=-30 +lat_0=-20 +azi=20 +rot=45"

    GEBCO_URL = "/vsicurl/https://data.source.coop/alexgleith/gebco-2024/GEBCO_2024.tif"
    RASTER_URL = os.environ.get("SPILHAUS_RASTER", GEBCO_URL)

    NE_OCEAN_URL = (
        "/vsicurl/https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
        "master/110m_physical/ne_110m_ocean.shp"
    )
    OCEAN_URL = os.environ.get("SPILHAUS_OCEAN", NE_OCEAN_URL)

    NPIX = int(os.environ.get("SPILHAUS_NPIX", "1600"))
    return NPIX, OCEAN_URL, RASTER_URL, SPILHAUS, SPILHAUS_ALT, SPILHAUS_EXPLICIT, np, os, shutil, subprocess, sys


@app.cell
def _(mo):
    mo.md(
        r"""
        ## 1. Who has which PROJ?

        Each row is one package's view of the world. The final column is the
        result of asking that package to create a CRS from `+proj=spilhaus`.
        """
    )
    return


@app.cell
def _(SPILHAUS, mo, shutil, subprocess, sys):
    import importlib.metadata as _md

    def _ver(pkg):
        try:
            return _md.version(pkg)
        except _md.PackageNotFoundError:
            return None

    probes = []  # rows for the table
    engines = {}  # name -> factory(proj_string) -> dict(forward=callable, inverse=callable)

    # --- pyproj -------------------------------------------------------------
    try:
        import pyproj

        _row = dict(package="pyproj", version=pyproj.__version__, gdal="-", proj=pyproj.proj_version_str)
        def _pyproj_factory(ps, _pp=pyproj):
            crs = _pp.CRS.from_proj4(ps)
            fwd = _pp.Transformer.from_crs(4326, crs, always_xy=True)
            inv = _pp.Transformer.from_crs(crs, 4326, always_xy=True)
            return dict(forward=fwd.transform, inverse=inv.transform)

        try:
            _pyproj_factory(SPILHAUS)  # the probe
            engines["pyproj"] = _pyproj_factory
            _row["spilhaus"] = "ok"
        except Exception as e:  # noqa: BLE001
            _row["spilhaus"] = f"FAIL: {type(e).__name__}"
        probes.append(_row)
    except ImportError:
        probes.append(dict(package="pyproj", version=None, gdal=None, proj=None, spilhaus="not installed"))

    # --- rasterio -----------------------------------------------------------
    try:
        import rasterio
        import rasterio.crs
        from rasterio.warp import transform as _rio_transform

        _proj = getattr(rasterio, "__proj_version__", None) or "?"
        _row = dict(package="rasterio", version=rasterio.__version__, gdal=rasterio.__gdal_version__, proj=str(_proj))
        def _rasterio_factory(ps, _rio=rasterio, _t=_rio_transform):
            crs = _rio.crs.CRS.from_proj4(ps)
            wgs = _rio.crs.CRS.from_epsg(4326)
            return dict(
                forward=lambda x, y: _t(wgs, crs, list(x), list(y)),
                inverse=lambda x, y: _t(crs, wgs, list(x), list(y)),
            )

        try:
            _rasterio_factory(SPILHAUS)  # the probe
            engines["rasterio"] = _rasterio_factory
            _row["spilhaus"] = "ok"
        except Exception as e:  # noqa: BLE001
            _row["spilhaus"] = f"FAIL: {type(e).__name__}"
        probes.append(_row)
    except ImportError:
        probes.append(dict(package="rasterio", version=None, gdal=None, proj=None, spilhaus="not installed"))

    # --- pyogrio (vector I/O; links GDAL, exposes no CRS-transform API) ------
    try:
        import pyogrio

        probes.append(
            dict(
                package="pyogrio",
                version=pyogrio.__version__,
                gdal=pyogrio.__gdal_version_string__,
                proj="(static in libgdal)",
                spilhaus="n/a (I/O only)",
            )
        )
    except ImportError:
        probes.append(dict(package="pyogrio", version=None, gdal=None, proj=None, spilhaus="not installed"))

    # --- osgeo (GDAL's own Python bindings) ---------------------------------
    try:
        from osgeo import gdal as _gdal
        from osgeo import osr as _osr

        _osr.UseExceptions()
        _gdal.UseExceptions()
        _proj = f"{_osr.GetPROJVersionMajor()}.{_osr.GetPROJVersionMinor()}.{_osr.GetPROJVersionMicro()}"
        _row = dict(package="osgeo (GDAL bindings)", version=_gdal.__version__, gdal=_gdal.__version__, proj=_proj)
        try:
            _srs = _osr.SpatialReference()
            _srs.ImportFromProj4(SPILHAUS)
            _row["spilhaus"] = "ok"
        except Exception as e:  # noqa: BLE001
            _row["spilhaus"] = f"FAIL: {type(e).__name__}"
        probes.append(_row)
    except ImportError:
        probes.append(dict(package="osgeo (GDAL bindings)", version=None, gdal=None, proj=None, spilhaus="not installed"))

    # --- geopandas / shapely: ride on pyproj and GEOS ------------------------
    try:
        import geopandas as _gpd
        import shapely as _shp

        probes.append(
            dict(
                package="geopandas",
                version=_gpd.__version__,
                gdal="(via pyogrio)",
                proj="(via pyproj)",
                spilhaus="inherits pyproj",
            )
        )
        probes.append(
            dict(package="shapely", version=_shp.__version__, gdal="-", proj=f"GEOS {_shp.geos_version_string}", spilhaus="n/a")
        )
    except ImportError:
        pass

    # --- command line tools on PATH -------------------------------------------
    def _cli_version(cmd, args):
        exe = shutil.which(cmd)
        if not exe:
            return None
        try:
            out = subprocess.run([exe, *args], capture_output=True, text=True, timeout=30)
            return (out.stdout or out.stderr).strip().splitlines()[0]
        except Exception as e:  # noqa: BLE001
            return f"error: {e}"

    cli = {
        "gdalinfo --version": _cli_version("gdalinfo", ["--version"]),
        "gdal --version (unified CLI, GDAL >= 3.11)": _cli_version("gdal", ["--version"]),
        "projinfo --version": _cli_version("projinfo", ["--version"]),
        "rio --version": _cli_version("rio", ["--version"]),
    }

    capable = [k for k in engines]
    mo.vstack(
        [
            mo.md(f"Python `{sys.version.split()[0]}` at `{sys.executable}`"),
            mo.ui.table(probes, selection=None, label="Native library provenance, one row per package"),
            mo.md(
                "**Command-line tools on PATH:**\n\n"
                + "\n".join(f"- `{k}`: {v if v else 'not found'}" for k, v in cli.items())
            ),
            mo.callout(
                mo.md(
                    f"Libraries that can build `+proj=spilhaus` here: **{', '.join(capable) or 'none'}**. "
                    "The rest of this notebook uses the first of these for coordinate transforms."
                ),
                kind="success" if capable else "danger",
            ),
        ]
    )
    return capable, cli, engines, probes


@app.cell
def _(SPILHAUS, capable, engines, np):
    # Forward/inverse constructors for any proj string, from whichever library was capable.
    if not capable:
        raise RuntimeError("No installed library can create +proj=spilhaus; nothing below can run.")

    ENGINE = capable[0]

    def make_forward(proj_string):
        _fwd = engines[ENGINE](proj_string)["forward"]

        def forward(lon, lat):
            """lon/lat arrays -> projected x/y arrays (NaN where undefined)."""
            lon = np.asarray(lon, dtype=float).ravel()
            lat = np.asarray(lat, dtype=float).ravel()
            x, y = _fwd(lon.tolist(), lat.tolist())
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            bad = ~np.isfinite(x) | ~np.isfinite(y) | (np.abs(x) > 1e15) | (np.abs(y) > 1e15)
            x[bad] = np.nan
            y[bad] = np.nan
            return x, y

        return forward

    def make_inverse(proj_string):
        _inv = engines[ENGINE](proj_string)["inverse"]

        def inverse(x, y):
            """projected x/y -> lon/lat, one point at a time so singular corners fail individually."""
            x = np.asarray(x, dtype=float).ravel()
            y = np.asarray(y, dtype=float).ravel()
            lon = np.full_like(x, np.nan)
            lat = np.full_like(y, np.nan)
            for i in range(len(x)):
                try:
                    a, b = _inv([x[i]], [y[i]])
                    lon[i], lat[i] = float(a[0]), float(b[0])
                except Exception:  # noqa: BLE001
                    pass
            bad = ~np.isfinite(lon) | (np.abs(lon) > 360) | (np.abs(lat) > 90)
            lon[bad] = np.nan
            lat[bad] = np.nan
            return lon, lat

        return inverse

    forward = make_forward(SPILHAUS)
    inverse = make_inverse(SPILHAUS)
    return ENGINE, forward, inverse, make_forward, make_inverse


@app.cell
def _(ENGINE, mo):
    mo.md(
        rf"""
        ## 2. The projection's domain

        Spilhaus maps the sphere onto a square. PROJ does not publish the square's
        half-width as metadata, so we forward-project a dense lon/lat grid (with
        **{ENGINE}**) and take the extent. The square's boundary is the *cut*: the
        line along which the sphere is opened, chosen to run almost entirely through
        land so the ocean is one connected piece. Inverse-projecting the boundary
        back to lon/lat traces the cut on the globe.
        """
    )
    return


@app.cell
def _(forward, inverse, np):
    def square_half(fwd, n=1441):
        """Half-width of the projected square: forward-project a dense grid and take the extent."""
        lon, lat = np.meshgrid(np.linspace(-180, 180, n), np.linspace(-90, 90, (n + 1) // 2))
        x, y = fwd(lon, lat)
        half = float(np.nanmax(np.abs(np.concatenate([x, y]))))
        # the true half-width is slightly larger than any sampled point
        return float(np.ceil(half / 1000.0) * 1000.0)

    HALF = square_half(forward)

    # Trace the cut: inverse-project the square boundary just inside the edge.
    _n = 300
    _t = np.linspace(-1, 1, _n)
    _edge = 0.996 * HALF
    _boundary = np.concatenate(
        [
            np.c_[_t * _edge, np.full(_n, -_edge)],
            np.c_[np.full(_n, _edge), _t * _edge],
            np.c_[_t[::-1] * _edge, np.full(_n, _edge)],
            np.c_[np.full(_n, -_edge), _t[::-1] * _edge],
        ]
    )
    cut_lon, cut_lat = inverse(_boundary[:, 0], _boundary[:, 1])

    # the two singular corner points, from the literature: (115E, 30N) and (65W, 30S)
    corners = {"corner A (Asia)": (115.0, 30.0), "corner B (South America)": (-65.0, -30.0)}
    return HALF, corners, cut_lat, cut_lon, square_half


@app.cell
def _(HALF, corners, cut_lat, cut_lon, mo, np):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _fig, _ax = plt.subplots(figsize=(9, 4.2))
    _ax.scatter(cut_lon, cut_lat, s=4, color="#b8342c", label="square boundary, inverse-projected (the cut)")
    for _name, (_lo, _la) in corners.items():
        _ax.plot(_lo, _la, "o", ms=7, mfc="none", mec="black", mew=1.2)
        _ax.annotate(_name, (_lo, _la), xytext=(6, 6), textcoords="offset points", fontsize=8)
    _ax.set_xlim(-180, 180)
    _ax.set_ylim(-90, 90)
    _ax.set_aspect("equal")
    _ax.grid(True, lw=0.3, alpha=0.6)
    _ax.set_title(f"Where the Spilhaus cut falls on the globe  (square half-width {HALF/1e6:.3f} Mm)")
    _ax.legend(loc="lower left", fontsize=8)
    _fig.tight_layout()
    mo.vstack(
        [
            mo.md(
                f"Half-width of the square: **{HALF:,.0f} m**; "
                f"{np.isfinite(cut_lon).sum()} of {len(cut_lon)} boundary samples inverted "
                "(the misses cluster at the two singular corners)."
            ),
            _fig,
        ]
    )
    return matplotlib, plt


@app.cell
def _(mo):
    mo.md(
        r"""
        ## 3. Raster: bathymetry over `/vsicurl`

        Default source is Alex Leith's GEBCO 2024 COG on source.coop, read with
        rasterio's `WarpedVRT` - GDAL's warper, driven from Python. We open the
        source at the overview level closest to the output resolution so the
        4 GB file is never read in full; only the tiles needed come over the wire.

        > Set `SPILHAUS_RASTER` to point at another global raster (any GDAL path,
        > `/vsicurl/`, `/vsis3/`, a WMTS descriptor, ...).
        """
    )
    return


@app.cell
def _(HALF, NPIX, RASTER_URL, SPILHAUS, mo, np):
    import time

    import rasterio as rio
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.vrt import WarpedVRT

    def _pick_overview(src, dst_res_m):
        """Index into src.overviews(1) whose resolution is just finer than the target, else None."""
        ovr = src.overviews(1)
        if not ovr:
            return None
        # degrees per source pixel at level k, converted to metres at the equator
        base_m = abs(src.transform.a) * 111_320.0
        levels = [(k, base_m * f) for k, f in enumerate(ovr)]
        finer = [k for k, res in levels if res <= dst_res_m / 1.5]
        return max(finer) if finer else None

    def warp_square(proj_string, half, npix, url=RASTER_URL):
        """Warp the source raster onto the [-half, half]^2 square of proj_string at npix x npix.

        Returns (array with alpha band last, metadata dict)."""
        dst_crs = rio.crs.CRS.from_proj4(proj_string)
        dst_transform = from_bounds(-half, -half, half, half, npix, npix)
        res_m = 2 * half / npix
        t0 = time.perf_counter()
        with rio.open(url) as probe:
            meta = dict(
                driver=probe.driver,
                size=f"{probe.width} x {probe.height}",
                bands=probe.count,
                dtype=probe.dtypes[0],
                crs=str(probe.crs),
                overviews=probe.overviews(1),
                nodata=probe.nodata,
            )
            ovr = _pick_overview(probe, res_m)
        with rio.open(url, overview_level=ovr) as src:
            with WarpedVRT(
                src,
                crs=dst_crs,
                transform=dst_transform,
                width=npix,
                height=npix,
                resampling=Resampling.bilinear if src.count > 1 else Resampling.average,
                add_alpha=True,
            ) as vrt:
                arr = vrt.read()
        meta["overview_used"] = ovr
        meta["seconds"] = round(time.perf_counter() - t0, 1)
        meta["res_m"] = res_m
        return arr, meta

    warped, raster_meta = warp_square(SPILHAUS, HALF, NPIX)
    dst_res_m = raster_meta["res_m"]

    mo.md(
        f"Warped `{RASTER_URL.split('/')[-1]}` to a {NPIX} x {NPIX} Spilhaus grid "
        f"({dst_res_m/1000:.1f} km/px) in **{raster_meta['seconds']} s**, reading overview level "
        f"`{raster_meta['overview_used']}` of {raster_meta['overviews'] or 'none'}."
    )
    return Resampling, WarpedVRT, dst_res_m, from_bounds, raster_meta, rio, warp_square, warped


@app.cell
def _(HALF, dst_res_m, matplotlib, mo, np, plt, warped):
    from matplotlib.colors import LightSource, LinearSegmentedColormap

    def render_raster(ax, arr, half, res_m):
        """Draw the warped array. Single band -> bathymetry with land flat; 3+ bands -> RGB."""
        alpha = arr[-1] > 0
        if arr.shape[0] >= 4:  # RGB(+alpha)
            rgb = np.moveaxis(arr[:3], 0, -1).astype(float) / 255.0
            rgba = np.dstack([rgb, alpha.astype(float)])
            ax.imshow(rgba, extent=(-half, half, -half, half), interpolation="nearest")
            return "rgb"
        z = arr[0].astype(float)
        z[~alpha] = np.nan
        ocean = np.where(z < 0, z, np.nan)
        land = np.where(z >= 0, z, np.nan)
        # ocean: deep-to-shallow blues, with a gentle hillshade for ridges and trenches
        cmap = LinearSegmentedColormap.from_list(
            "bathy", ["#08143f", "#123c7a", "#2a6fb5", "#6aa9d8", "#b9d9ea", "#e3f1f6"]
        )
        norm = matplotlib.colors.Normalize(vmin=-7000, vmax=0)
        rgba = cmap(norm(np.nan_to_num(ocean, nan=0.0)))
        ls = LightSource(azdeg=315, altdeg=45)
        hs = ls.hillshade(np.nan_to_num(ocean, nan=0.0), vert_exag=15.0, dx=res_m, dy=res_m)
        rgba[..., :3] *= (0.65 + 0.45 * hs)[..., None]
        rgba[..., :3] = rgba[..., :3].clip(0, 1)
        rgba[..., 3] = np.where(np.isfinite(ocean), 1.0, 0.0)
        ax.imshow(rgba, extent=(-half, half, -half, half), interpolation="nearest")
        land_rgba = np.zeros(z.shape + (4,))
        land_rgba[..., :3] = matplotlib.colors.to_rgb("#d9d2c5")
        land_rgba[..., 3] = np.where(np.isfinite(land), 1.0, 0.0)
        ax.imshow(land_rgba, extent=(-half, half, -half, half), interpolation="nearest")
        return "bathymetry"

    _fig, _ax = plt.subplots(figsize=(8, 8))
    raster_kind = render_raster(_ax, warped, HALF, dst_res_m)
    _ax.set_xlim(-HALF, HALF)
    _ax.set_ylim(-HALF, HALF)
    _ax.set_axis_off()
    _ax.set_title(f"Raster only ({raster_kind}), warped by GDAL via rasterio")
    _fig.tight_layout()
    mo.vstack([_fig])
    return LinearSegmentedColormap, raster_kind, render_raster


@app.cell
def _(mo):
    mo.md(
        r"""
        ## 4. The same warp through other doors

        Same source, same target CRS, same grid - requested via each command-line
        tool that happens to be on `PATH`. Success or failure here is *purely* a
        function of which PROJ that binary links.
        """
    )
    return


@app.cell
def _(HALF, RASTER_URL, SPILHAUS, mo, os, shutil, subprocess):
    import tempfile

    _out_dir = tempfile.mkdtemp(prefix="spilhaus_")
    _small = 256  # tiny output; this is a capability probe, not a render
    _te = ["-te", str(-HALF), str(-HALF), str(HALF), str(HALF)]

    _cmds = {
        "gdalwarp (classic CLI)": ["gdalwarp", "-q", "-overwrite", "-t_srs", SPILHAUS, *_te, "-ts", str(_small), str(_small), RASTER_URL, f"{_out_dir}/gdalwarp.tif"],
        "gdal raster reproject (unified CLI)": [
            "gdal", "raster", "reproject", "--overwrite", "--dst-crs", SPILHAUS,
            "--bbox", f"{-HALF},{-HALF},{HALF},{HALF}", "--bbox-crs", SPILHAUS,
            "--size", f"{_small},{_small}", RASTER_URL, f"{_out_dir}/gdal_cli.tif",
        ],
        "rio warp (rasterio CLI)": [
            "rio", "warp", "--overwrite", "--dst-crs", SPILHAUS,
            "--bounds", str(-HALF), str(-HALF), str(HALF), str(HALF),
            "--dimensions", str(_small), str(_small), RASTER_URL, f"{_out_dir}/rio.tif",
        ],
    }

    cli_results = []
    for _label, _cmd in _cmds.items():
        _exe = shutil.which(_cmd[0])
        if not _exe:
            cli_results.append(dict(tool=_label, result="not on PATH", detail=""))
            continue
        try:
            _p = subprocess.run(_cmd, capture_output=True, text=True, timeout=600)
            if _p.returncode == 0 and os.path.exists(_cmd[-1]):
                cli_results.append(dict(tool=_label, result="ok", detail=f"{os.path.getsize(_cmd[-1])//1024} KiB written"))
            else:
                _err = (_p.stderr or _p.stdout).strip().splitlines()
                cli_results.append(dict(tool=_label, result="FAIL", detail=_err[-1] if _err else f"exit {_p.returncode}"))
        except subprocess.TimeoutExpired:
            cli_results.append(dict(tool=_label, result="timeout", detail=""))

    mo.ui.table(cli_results, selection=None, label="Command-line warp probes")
    return (cli_results,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## 5. Vector: Natural Earth ocean polygons

        Read remotely with `pyogrio` (via `geopandas.read_file`) straight from the
        Natural Earth GitHub repository with `/vsicurl/` - no download step.

        Why *ocean* rather than *land*: the Spilhaus cut runs through the
        continents, so ocean rings barely straddle it. The few segments that do
        cross are detected as absurdly long jumps in projected space and dropped,
        and coastlines are drawn as lines rather than filled polygons. (A polygon
        fill would need the rings split along the cut first; that is a separate,
        interesting exercise.)

        `geopandas.to_crs` delegates to `pyproj`; if that PROJ predates 9.6, it
        cannot help here, so the transform goes coordinate-by-coordinate through
        whichever engine section 1 found, using `shapely.transform`.
        """
    )
    return


@app.cell
def _(ENGINE, OCEAN_URL, forward, mo, np):
    import geopandas as gpd
    import shapely

    ocean = gpd.read_file(OCEAN_URL)

    def rings_to_segments(gdf, densify_deg=0.5, max_jump=None, fwd=forward):
        """All polygon rings -> list of (N,2) projected coordinate arrays, split at long jumps."""
        out = []
        for geom in gdf.geometry:
            geom = shapely.segmentize(geom, densify_deg)
            for poly in getattr(geom, "geoms", [geom]):
                for ring in [poly.exterior, *poly.interiors]:
                    c = np.asarray(ring.coords)
                    x, y = fwd(c[:, 0], c[:, 1])
                    xy = np.c_[x, y]
                    step = np.hypot(np.diff(x), np.diff(y))
                    # segments that are artefacts of the lon/lat representation, not coastline:
                    # both ends on the antimeridian, or both ends at a pole
                    lon0, lon1 = c[:-1, 0], c[1:, 0]
                    lat0, lat1 = c[:-1, 1], c[1:, 1]
                    synthetic = ((np.abs(lon0) > 179.99) & (np.abs(lon1) > 179.99)) | (
                        (np.abs(lat0) > 89.99) & (np.abs(lat1) > 89.99)
                    )
                    ok = np.isfinite(step) & (step < max_jump) & ~synthetic
                    # split into runs of consecutive good segments
                    idx = np.flatnonzero(~ok)
                    start = 0
                    for i in list(idx) + [len(step)]:
                        if i - start >= 1:
                            out.append(xy[start : i + 1])
                        start = i + 1
        return out

    return gpd, ocean, rings_to_segments, shapely


@app.cell
def _(HALF, ENGINE, mo, ocean, rings_to_segments):
    coast_segments = rings_to_segments(ocean, densify_deg=0.5, max_jump=HALF / 8)
    mo.md(
        f"Ocean layer: {len(ocean)} feature(s), CRS `{ocean.crs}`; "
        f"{len(coast_segments)} coastline runs after projecting with **{ENGINE}** and dropping cut-crossing segments."
    )
    return (coast_segments,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## 6. Points: landmarks, transformed directly

        No GeoDataFrame, no raster: a dict of lon/lat pairs pushed through the
        forward transform. This is the smallest possible "does my PROJ have
        Spilhaus" test, and the one to paste into a bug report.
        """
    )
    return


@app.cell
def _(forward, mo, np):
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
    _lon = [v[0] for v in landmarks.values()]
    _lat = [v[1] for v in landmarks.values()]
    _x, _y = forward(_lon, _lat)
    landmark_xy = {k: (float(x), float(y)) for k, x, y in zip(landmarks, _x, _y)}
    _rows = [dict(name=k, lon=v[0], lat=v[1], x=round(landmark_xy[k][0]), y=round(landmark_xy[k][1])) for k, v in landmarks.items()]
    mo.ui.table(_rows, selection=None, label="Landmarks in Spilhaus metres")
    return landmark_xy, landmarks


@app.cell
def _(mo):
    mo.md(r"""## 7. Composite""")
    return


@app.cell
def _(ENGINE, HALF, coast_segments, dst_res_m, landmark_xy, mo, plt, probes, raster_kind, render_raster, warped):
    from matplotlib import patheffects
    from matplotlib.collections import LineCollection

    fig, ax = plt.subplots(figsize=(11, 11))
    ax.set_facecolor("#d9d2c5")
    render_raster(ax, warped, HALF, dst_res_m)
    ax.add_collection(LineCollection(coast_segments, colors="#3a3a3a", linewidths=0.45))
    for _name, (_x, _y) in landmark_xy.items():
        ax.plot(_x, _y, "o", ms=5, color="#f2b134", mec="black", mew=0.6, zorder=5)
        ax.annotate(
            _name, (_x, _y), xytext=(5, 4), textcoords="offset points", fontsize=8.5, zorder=6,
            annotation_clip=True,
            path_effects=[patheffects.withStroke(linewidth=2.5, foreground="white")],
        )
    ax.set_xlim(-HALF, HALF)
    ax.set_ylim(-HALF, HALF)
    ax.set_axis_off()
    _proj_used = next((p["proj"] for p in probes if p["package"] == ENGINE), "?")
    ax.set_title(
        f"The world ocean in Spilhaus projection\n"
        f"raster warped by GDAL (rasterio); coastlines and points transformed by {ENGINE} (PROJ {_proj_used})",
        fontsize=12,
        pad=16,
    )
    fig.tight_layout()
    fig.savefig("spilhaus_composite.png", dpi=150, facecolor="white")
    mo.vstack([fig, mo.md("Saved as `spilhaus_composite.png` next to the notebook.")])
    return LineCollection, ax, fig, patheffects


@app.cell
def _(mo):
    mo.md(
        r"""
        ## 8. Naming the thing: proj-string, WKT, and the missing authority code

        `+proj=spilhaus` is a fine thing to type. It is a poor thing to store, cite,
        or hand to someone in five years. Three renderings of "the same" projection:

        1. the bare proj-string, exported to WKT2 - the method is named, but every
           parameter is *implicit*: the numbers live in PROJ's source code;
        2. the same proj-string with all parameters spelled out - now the WKT carries
           the numbers, and round-trips;
        3. **ESRI:54099**, the only authority code you will find. It is a *different* map:
           ESRI's Adams Square II convention has the square a factor of sqrt(2) larger,
           which PROJ expresses by mapping it to `+k_0=1.41421356237`.

        There is no EPSG code. Nobody has registered one, and for a projection whose
        whole point is one specific choice of parameters that is a gap worth noticing.
        """
    )
    return


@app.cell
def _(SPILHAUS, SPILHAUS_ALT, SPILHAUS_EXPLICIT, mo, np, rio):
    from rasterio.warp import transform as _xf

    def _wkt(crs_in):
        try:
            crs = rio.crs.CRS.from_string(crs_in)
            return crs, crs.to_wkt(version="WKT2_2019", pretty=True)
        except Exception as e:  # noqa: BLE001
            return None, f"({type(e).__name__}: {e})"

    _hobart = (147.33, -42.88)
    renderings = []
    for _label, _src in [
        ("bare proj-string", SPILHAUS),
        ("explicit proj-string", SPILHAUS_EXPLICIT),
        ("ESRI:54099", "ESRI:54099"),
        ("alternative centre (section 9)", SPILHAUS_ALT),
    ]:
        _crs, _w = _wkt(_src)
        _xy = "-"
        _p4 = "-"
        if _crs is not None:
            try:
                _x, _y = _xf("EPSG:4326", _crs, [_hobart[0]], [_hobart[1]])
                _xy = f"{_x[0]:,.0f}, {_y[0]:,.0f}"
            except Exception:  # noqa: BLE001
                _xy = "transform failed"
            try:
                _p4 = _crs.to_proj4()
            except Exception:  # noqa: BLE001
                _p4 = "(no proj-string export)"
        renderings.append(dict(rendering=_label, input=_src, proj_string_export=_p4, hobart_xy=_xy, wkt2=_w))

    mo.vstack(
        [
            mo.ui.table(
                [{k: v for k, v in r.items() if k != "wkt2"} for r in renderings],
                selection=None,
                label="Same projection, several names. hobart_xy is Hobart's projected coordinate under each.",
            ),
            mo.accordion({f"WKT2:2019 for {r['rendering']}": mo.md(f"```\n{r['wkt2']}\n```") for r in renderings}),
            mo.callout(
                mo.md(
                    "Look for `PARAMETER[...]` entries in the first WKT: there are none. The map is fully "
                    "determined only by defaults in PROJ. The second rendering is what a technical citation "
                    "should carry. ESRI:54099 places Hobart somewhere else entirely; it is a bigger square."
                ),
                kind="info",
            ),
        ]
    )
    return (renderings,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## 9. Another member of the family

        Spilhaus's genius was not the projection method (it is Adams' World in a Square II,
        1929) but the *parameters*: a centre, an azimuth and a rotation chosen so the cut falls
        almost entirely on land. Change them and you have a perfectly valid map of the same
        family that nobody would call the Spilhaus map. Below, a naive recentring on the
        Atlantic. Same method, same code path, and the square's edges now slice the ocean.
        """
    )
    return


@app.cell
def _(HALF, NPIX, SPILHAUS_ALT, landmarks, make_forward, mo, ocean, plt, render_raster, rings_to_segments, square_half, warp_square):
    from matplotlib import patheffects as _pe
    from matplotlib.collections import LineCollection as _LC

    forward_alt = make_forward(SPILHAUS_ALT)
    HALF_ALT = square_half(forward_alt)
    _npix = max(400, NPIX // 2)
    warped_alt, meta_alt = warp_square(SPILHAUS_ALT, HALF_ALT, _npix)
    coast_alt = rings_to_segments(ocean, densify_deg=0.5, max_jump=HALF_ALT / 8, fwd=forward_alt)
    _lx, _ly = forward_alt([v[0] for v in landmarks.values()], [v[1] for v in landmarks.values()])

    _fig, _ax = plt.subplots(figsize=(8, 8))
    _ax.set_facecolor("#d9d2c5")
    render_raster(_ax, warped_alt, HALF_ALT, meta_alt["res_m"])
    _ax.add_collection(_LC(coast_alt, colors="#3a3a3a", linewidths=0.45))
    _ax.plot(_lx, _ly, "o", ms=4, color="#f2b134", mec="black", mew=0.6, zorder=5)
    for _name, _x, _y in zip(landmarks, _lx, _ly):
        _ax.annotate(
            _name, (_x, _y), xytext=(4, 3), textcoords="offset points", fontsize=7.5, zorder=6,
            annotation_clip=True, path_effects=[_pe.withStroke(linewidth=2, foreground="white")],
        )
    _ax.set_xlim(-HALF_ALT, HALF_ALT)
    _ax.set_ylim(-HALF_ALT, HALF_ALT)
    _ax.set_axis_off()
    _ax.set_title(f"{SPILHAUS_ALT}\n(half-width {HALF_ALT/1e6:.3f} Mm vs {HALF/1e6:.3f} Mm for the default)", fontsize=10, pad=12)
    _fig.tight_layout()
    mo.vstack([_fig])
    return HALF_ALT, coast_alt, forward_alt, meta_alt, warped_alt


@app.cell
def _(mo):
    mo.md(
        r"""
        ## 10. What to take from this

        - A projection "existing in PROJ" is necessary, not sufficient. Each package
          that bundles PROJ picks up the feature only when *its* wheel is rebuilt against
          a new enough PROJ, on its own release cadence. The provenance table in section 1 is
          the actual answer to "can I use Spilhaus here".
        - GDAL-based paths (`rasterio`, `pyogrio`, the `osgeo` bindings, CLI tools) each
          link a PROJ too; they do not share one with `pyproj`.
        - On conda-forge all of these share a single `libproj`, so the table collapses to one
          row of truth. That is a real difference between the two ecosystems, and worth knowing
          when someone asks why a projection "works in QGIS but not in my notebook".
        - The pattern generalises: any new PROJ operation, any new GDAL driver or CLI subcommand
          (`gdal raster reproject`, section 4) flows downstream on the same uneven schedule.
        - A proj-string is a recipe with hidden defaults. When it matters, write the WKT with the
          parameters in it (section 8), and do not assume the one authority code you can find
          describes the map you have in mind.

        Re-run this notebook after every `pip install -U` and watch the rows change.
        """
    )
    return


if __name__ == "__main__":
    app.run()
