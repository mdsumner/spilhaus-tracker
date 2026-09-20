# spilhaus-tracker

A marimo notebook that draws the world ocean in the Spilhaus projection from
public remote sources, and - the actual point - reports which PROJ and GDAL
each Python package in the environment is really using.

`+proj=spilhaus` was added in [PROJ 9.6.0](https://proj.org/en/stable/operations/projections/spilhaus.html)
(March 2025). Whether it works from Python depends on which PROJ each package
bundles. In a pip environment that is one copy per package, on independent
release schedules. The first table in the notebook is the answer to
"can I use Spilhaus here", and it changes every time you upgrade something.

## Run it

Nothing to clone or download; the notebook is a single file with its
dependencies declared inline (PEP 723):

    uvx marimo edit --sandbox spilhaus.py

or as a read-only app:

    uvx marimo run --sandbox spilhaus.py

Environment overrides:

| variable          | default                                              | purpose |
|-------------------|------------------------------------------------------|---------|
| `SPILHAUS_RASTER` | GEBCO 2024 COG on source.coop, via `/vsicurl/`        | any GDAL-readable global raster |
| `SPILHAUS_OCEAN`  | Natural Earth 110m ocean shapefile on GitHub, via `/vsicurl/` | any OGR-readable ocean polygon layer |
| `SPILHAUS_NPIX`   | 1600                                                 | output grid size in pixels |

## What it does

1. **Provenance table.** For pyproj, rasterio, pyogrio, the osgeo bindings, geopandas
   and shapely: package version, linked GDAL, linked PROJ, and the result of
   `CRS("+proj=spilhaus")`. Plus whatever `gdalinfo`, `gdal`, `projinfo` and `rio` are on `PATH`.
2. **Domain.** Forward-projects a lon/lat grid to find the square's half-width, then
   inverse-projects the square's boundary to trace the cut on the globe.
3. **Raster.** Warps bathymetry to the Spilhaus square with rasterio's `WarpedVRT`,
   reading only the overview level and tiles needed from the remote COG.
4. **CLI probes.** The same warp via `gdalwarp`, `gdal raster reproject` and `rio warp`,
   each succeeding or failing according to the PROJ it links.
5. **Vector.** Natural Earth ocean polygons read remotely with pyogrio; rings projected
   coordinate-by-coordinate with whichever library is Spilhaus-capable, with cut-crossing
   segments dropped.
6. **Points.** A dict of landmarks pushed through the forward transform.
7. **Composite map**, saved as `spilhaus_composite.png`.
8. **Naming.** WKT2 renderings of the bare proj-string (method named, no parameters), the
   explicit proj-string, and ESRI:54099 (the only authority code, and a sqrt(2)-larger square),
   with Hobart's coordinate under each.
9. **Another centre.** The same method recentred on the Atlantic, so the cut runs through ocean:
   Spilhaus's contribution was the parameters, not the projection.

The notebook does not require pyproj to support Spilhaus. It uses the first
capable library it finds (pyproj, then rasterio) and says which one it used.

## R version

`spilhaus.qmd` is the same document in R, with the primitives kept visible:
**gdalraster** for I/O and the warp, **wk** for vertex-level geometry, **ximage**
to draw a matrix; sf and terra appear in the provenance table and in a one-line
appendix. R's version of the problem is different from Python's: on Linux the
packages share one system `libproj`, so the question is what the system has,
and the Action renders the document on three Ubuntu runners (stock apt, the
ubuntugis-unstable PPA, and conda-forge) to show the difference. On macOS and Windows the CRAN
binaries carry their own PROJ instead.

Render locally with `quarto render spilhaus.qmd`; the same `SPILHAUS_*`
environment overrides apply.

## Browser version

`spilhaus_wasm.py` is the vector-and-points half, exported with
`marimo export html-wasm` and run by Pyodide in the browser. Pyodide ships
its own pyproj with its own PROJ, so this is one more runtime to add to the
table. If that PROJ predates 9.6 the page says so and stops.

## Hosting

`.github/workflows/pages.yml` builds both on every push and on a weekly
schedule, and publishes to GitHub Pages:

- `/` - index linking everything below;
- `/python/` - static HTML export of `spilhaus.py` with outputs baked in (runs the
  real warp against GEBCO in the Action);
- `/wasm/` - the Pyodide export of `spilhaus_wasm.py`;
- `/r/apt/`, `/r/ubuntugis/` and `/r/conda-forge/` - `spilhaus.qmd` rendered against each GDAL/PROJ source.

The weekly rebuild is deliberate: it re-resolves the dependencies, so the
provenance table tracks upstream releases without anyone touching the repo.

## Sources

- GEBCO 2024 as COG: https://source.coop/alexgleith/gebco-2024
- Natural Earth: https://github.com/nvkelso/natural-earth-vector
- PROJ Spilhaus docs: https://proj.org/en/stable/operations/projections/spilhaus.html
