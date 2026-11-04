# Vegvarsel logo

A winding road and amber warning sign on a midnight-blue tile. The simplified
silhouette keeps the integration recognizable at small sizes. The area outside
the tile is transparent.

## Artwork and exports

- `vegvarsel-master.png`: original 1254 × 1254 RGBA artwork.
- `../../custom_components/vegvarsel/brand/icon.png`: 256 × 256 integration icon.
- `../../custom_components/vegvarsel/brand/icon@2x.png`: 512 × 512 integration icon.
- `../vegvarsel-logo.png`: 1024 × 1024 documentation image.

Recreate the exports with `python tools/make_logo.py` (requires Pillow).
The exporter resizes the master and preserves transparency; it does not call an
image-generation service. Edit or replace the master before rerunning it.

## Generation prompt

Created with the built-in image generation tool on 2026-11-04, with transparent
background enabled. Prompt:

```text
Use case: logo-brand.
Asset type: final app icon for Vegvarsel, a Home Assistant integration for alerts about road incidents on personal driving routes in Norway.
Primary request: Create a polished, distinctive, beautifully simple logo that reads clearly even at 32 pixels. One centered rounded-square deep midnight-navy tile, generous curved corners, with a bold flowing icy-white/cyan road sweeping upward in a subtle V-shaped bend from the lower center toward the upper left. The road has two solid, smooth, tapering edges and only two or three short center lane markings. A small amber rounded warning triangle with a navy exclamation mark sits in the upper right of the tile, balanced as part of the composition, entirely inside the tile. The road and alert are the only two motifs. Nordic restraint, confident proportions, precise geometric construction, balanced negative space. Strong silhouette. Flat vector-like brand artwork, not a mockup. Avoid fine detail.
Palette: deep midnight navy tile, icy white/light cyan road, warm amber warning sign. High contrast. No red.
Composition: square canvas; tile occupies about 88% of canvas, centered with equal transparent padding all sides. All artwork inside tile. Background outside rounded tile genuinely transparent.
Constraints: icon only, no letters or words, no typography, no watermark. No mountains, tunnels, scenery, cars, houses, pins, shields, circles, extra badges, gradients, texture, lighting effects, shadows, 3D, bevels, or presentation board. Only one icon. Crisp, clean edges. The warning triangle must have a clearly visible upright exclamation mark.
```
