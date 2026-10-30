# AssetsX AI Engine v0.1.0

Universal visual-asset ingest, element analysis, deterministic editing, vector reconstruction, validation, and downloadable production handoff. **Backend only**: frontend belongs to the My Jersey Ecosystem.

## Reused Artboard AI vectorization logic

AssetsX adapts code from the user's existing Artboard AI repositories (not a different vectorizer):

- `nafiulnahid17/artboardai-engine` `artboard_engine/tracing.py` (`ad7c50bd`) — native VTracer spline tracing, bounded tracing options, explicit complexity/fidelity warnings.
- `nafiulnahid17/Artboard-AI---Resolution-Independent-` `app/pipeline/vectorization.py` (`a5aa5cca`) — select strategy, VTracer with deterministic contour fallback, validate native outputs.
- Same repository `app/vector/contour.py` (`40497d79`) — OpenCV palette-region paths and even-odd hole preservation.
- `app/vector/vtracer_engine.py` (`a129bb5f`) — VTracer isolated subprocess strategy.
- `app/validators/svg_validator.py` (`3d19d3e7`) — reject raster-filled faux vectors and unsafe SVGs.

**Adaptations:** artwork's native dimensions/aspect ratio preserved (not Artboard fixed 22×31-inch jersey panel); bounded complexity; selection-limited vectorization; safe upload handling; no raster images embedded in final SVG. Trace presets and export/validation rules **do not depend on AI mode**. Exact behavior varies by input and installed tracing backend.

## Features delivered in this baseline

- PNG/JPEG/WebP/SVG/PDF/EPS input, PDF-compatible AI input. Proprietary Illustrator `.ai` data is not supported.
- Color palette and visual-asset heuristics, editable SVG node list, raster color-region candidates, optional local OCR (Tesseract).
- Edit commands: selected region recolor/remove/opacity, crop, resize, rotate, flip, background-color change, basic color-key removal, contrast/sharpness, add text/rectangle/ellipse, SVG node recolor/remove/opacity/replace-text/move/rotate.
- Vector strategies: auto, monochrome, multicolor, shapes, color regions, preserve native SVG. Native VTracer if installed for opaque non-selected images; otherwise deterministic contour. User can select **one or more elements**.
- PNG, transparent PNG, clean SVG paths, EPS via Inkscape, PDF via CairoSVG, zip, validation report, Illustrator handoff document. Native `.ai` is not faked.
- Quality / Cost-Effective AI analysis routing via explicit OpenRouter model pools; failover by configured model order. No credentials bundled.
- Persistent job manifest, background executor and protected asset-download API.
- True-vector SVG preflight; no `<image>` nodes; compare input and outputs manually before production use.

## Important exclusions in v0.1.0

This is **an implemented baseline**, not a fully qualified commercial editor. Complex intelligent background removal, semantic object detection, real font identification/matching, font TTF/OTF modification, automatic pattern tiling/editing, path-node UI, raster-to-vector typography reconstruction, genuine native `.ai` export, cross-container distributed job recovery and working AI image edits are **not implemented**. AI image-edit prompts return an explicit error; vision analysis is optional and needs valid credentials. **Input PDF/EPS is raster-previewed and retraced**, so do not claim original paths or font identities are preserved. Local test success does not replace cloud/provider and Illustrator compatibility testing.

## Quick start

```bash
python -m pip install '.[test,trace]'
export ASSETSX_INBOUND_TOKEN='a-long-random-secret'
assetsx-server
pytest -q
```

`GET /health` is open; all `/v1` routes use `Authorization: Bearer $ASSETSX_INBOUND_TOKEN`.

1. `POST /v1/assets` multipart `file=@logo.png`: returns asset UUID, elements and palette.
2. `GET /v1/assets/{id}?ocr=true` yields detection and optional text.
3. `POST /v1/jobs` JSON example:

```json
{
  "asset_id": "<UUID from upload>", "mode": "cost_effective", "strategy": "auto",
  "selected_element_ids": [],
  "edits": [{"action": "add_shape", "params": {"x": 8, "y": 8, "width": 28, "height": 28, "color": "#ff0000"}}],
  "formats": ["png", "transparent_png", "svg", "eps", "pdf", "ai_handoff", "zip"]
}
```

4. Poll `GET /v1/jobs/{job_id}`; download `GET /v1/jobs/{job_id}/download/complete_asset_pack.zip`.

### Security/deployment

Run under a non-root container with persistent `ASSETSX_ROOT` volume, strictly provisioned inbound bearer token, reasonable reverse proxy rate limits and per-tenant auth at the orchestration layer. The service's local executor is single-replica only; production horizontal scale requires a real shared queue (e.g. Redis/RQ/Celery) and persistent shared storage. Limit EPS/Ghostscript execution to isolated deployment. External model availability and provider usage costs require separate live smoke tests.
