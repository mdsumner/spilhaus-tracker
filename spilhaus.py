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

    GEBCO_URL = "/vsicurl/https://data.source.coop/alexgleith/gebco-2024/GEBCO_2024.tif"
    RASTER_URL = os.environ.get("SPILHAUS_RASTER", GEBCO_URL)

    NE_OCEAN_URL = (
        "/vsicurl/https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
        "master/110m_physical/ne_110m_ocean.shp"
    )
    OCEAN_URL = os.environ.get("SPILHAUS_OCEAN", NE_OCEAN_URL)

    NPIX = int(os.environ.get("SPILHAUS_NPIX", "1600"))
    return NPIX, OCEAN_URL, RASTER_URL, SPILHAUS, np, os, shutil, subprocess, sys


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
    engines = {}  # name -> dict(forward=callable, inverse=callable) for capable libs

    # --- pyproj -------------------------------------------------------------
    try:
        import pyproj

        _row = dict(package="pyproj", version=pyproj.__version__, gdal="-", proj=pyproj.proj_version_str)
        try:
            _crs = pyproj.CRS.from_proj4(SPILHAUS)
            _fwd = pyproj.Transformer.from_crs(4326, _crs, always_xy=True)
            _inv = pyproj.Transformer.from_crs(_crs, 4326, always_xy=True)
            engines["pyproj"] = dict(
                forward=lambda x, y, t=_fwd: t.transform(x, y),
                inverse=lambda x, y, t=_inv: t.transform(x, y),
            )
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
        try:
            _rcrs = rasterio.crs.CRS.from_proj4(SPILHAUS)
            _r4326 = rasterio.crs.CRS.from_epsg(4326)
            engines["rasterio"] = dict(
                forward=lambda x, y, f=_rio_transform, a=_r4326, b=_rcrs: f(a, b, list(x), list(y)),
                inverse=lambda x, y, f=_rio_transform, a=_rcrs, b=_r4326: f(a, b, list(x), list(y)),
            )
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
def _(capable, engines, np):
    # A single forward/inverse pair, from whichever library was capable.
    if not capable:
        raise RuntimeError("No installed library can create +proj=spilhaus; nothing below can run.")

    ENGINE = capable[0]
    _fwd = engines[ENGINE]["forward"]
    _inv = engines[ENGINE]["inverse"]

    def forward(lon, lat):
        """lon/lat arrays -> Spilhaus x/y arrays (NaN where undefined)."""
        lon = np.asarray(lon, dtype=float).ravel()
        lat = np.asarray(lat, dtype=float).ravel()
        x, y = _fwd(lon.tolist(), lat.tolist())
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        bad = ~np.isfinite(x) | ~np.isfinite(y) | (np.abs(x) > 1e15) | (np.abs(y) > 1e15)
        x[bad] = np.nan
        y[bad] = np.nan
        return x, y

    def inverse(x, y):
        """Spilhaus x/y -> lon/lat, one point at a time so singular corners fail individually."""
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

    return ENGINE, forward, inverse


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
    _lon, _lat = np.meshgrid(np.linspace(-180, 180, 1441), np.linspace(-90, 90, 721))
    _x, _y = forward(_lon, _lat)
    HALF = float(np.nanmax(np.abs(np.concatenate([_x, _y]))))
    # tidy: the true half-width is slightly larger than any sampled point
    HALF = np.ceil(HALF / 1000.0) * 1000.0

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
    return HALF, corners, cut_lat, cut_lon


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

    dst_crs = rio.crs.CRS.from_proj4(SPILHAUS)
    dst_transform = from_bounds(-HALF, -HALF, HALF, HALF, NPIX, NPIX)
    dst_res_m = 2 * HALF / NPIX

    def _pick_overview(src):
        """Index into src.overviews(1) whose resolution is just finer than the target, else None."""
        ovr = src.overviews(1)
        if not ovr:
            return None
        # degrees per source pixel at level k, converted to metres at the equator
        base_m = abs(src.transform.a) * 111_320.0
        levels = [(k, base_m * f) for k, f in enumerate(ovr)]
        finer = [k for k, res in levels if res <= dst_res_m / 1.5]
        return max(finer) if finer else None

    _t0 = time.perf_counter()
    with rio.open(RASTER_URL) as _probe:
        raster_meta = dict(
            driver=_probe.driver,
            size=f"{_probe.width} x {_probe.height}",
            bands=_probe.count,
            dtype=_probe.dtypes[0],
            crs=str(_probe.crs),
            overviews=_probe.overviews(1),
            nodata=_probe.nodata,
        )
        _ovr = _pick_overview(_probe)

    with rio.open(RASTER_URL, overview_level=_ovr) as _src:
        with WarpedVRT(
            _src,
            crs=dst_crs,
            transform=dst_transform,
            width=NPIX,
            height=NPIX,
            resampling=Resampling.bilinear if _src.count > 1 else Resampling.average,
            add_alpha=True,
        ) as _vrt:
            warped = _vrt.read()
    raster_seconds = time.perf_counter() - _t0
    raster_meta["overview_used"] = _ovr
    raster_meta["seconds"] = round(raster_seconds, 1)

    mo.md(
        f"Warped `{RASTER_URL.split('/')[-1]}` to a {NPIX} x {NPIX} Spilhaus grid "
        f"({dst_res_m/1000:.1f} km/px) in **{raster_seconds:.1f} s**, reading overview level "
        f"`{_ovr}` of {raster_meta['overviews'] or 'none'}."
    )
    return Resampling, WarpedVRT, dst_crs, dst_res_m, dst_transform, from_bounds, raster_meta, rio, warped


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

    def rings_to_segments(gdf, densify_deg=0.5, max_jump=None):
        """All polygon rings -> list of (N,2) projected coordinate arrays, split at long jumps."""
        out = []
        for geom in gdf.geometry:
            geom = shapely.segmentize(geom, densify_deg)
            for poly in getattr(geom, "geoms", [geom]):
                for ring in [poly.exterior, *poly.interiors]:
                    c = np.asarray(ring.coords)
                    x, y = forward(c[:, 0], c[:, 1])
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
        ## 8. What to take from this

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

        Re-run this notebook after every `pip install -U` and watch the rows change.
        """
    )
    return


if __name__ == "__main__":
    app.run()
