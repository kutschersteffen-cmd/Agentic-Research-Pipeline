# House-deck image slides: screenshots and pictures as typed visuals

Status: Draft, for owner approval
Slug: `house-deck-image-slides`
Plan: PR 4 of the house-deck builder plan (https://claude.ai/artifact/HrvD3WdtCD3e15cMGPjesm)
Risk: `risk:normal` (images are files in the report directory; no database schema change)
Size: M, delivered in four `S` slices (see `## Slices`)

## Decisions for the owner

1. **Does the model see the images?** Proposed: yes. Each image-slide fill call also gets every
   registered image as a preview (long edge 768 px), so the model picks and captions by what it sees.
   Cost: about 500 input tokens per image per image slide. The alternative is names, alt text and pixel
   size only. Only AC-43 depends on this choice; if not approved, AC-43 becomes: the fake got `images`
   None and its prompt contains `- a (2000×1000): Landing page`.

Everything else below is a default chosen by the spec author; the list is in `## Defaults taken`.

## Why

Building the 59-slide engineering deck on 18 Nov 2026 needed a 300-line script
(`/mnt/project-files/arp-tech-deck/builder-run/shots.py`) to put screenshots in. It rendered placeholder
`points` slides, then swapped their bodies for pictures in the HTML and in the PPTX after the build.
The house deck has no way to take images. The legacy `image` layout exists, but `slide_fill.py` hides
it and drops any `image_path` the model sets, because a path from the model would be read from local
disk.

## What the user can do afterwards that they cannot do today

- Hand ARP a set of screenshots or photos with a report (`--image name=path` on the CLI, an upload
  endpoint in the API) and get a deck where the model places them on image slides. No script after
  the build.
- Get three image layouts (hero, image beside points, captioned gallery) and an image behind the
  cover, cropped to each slot in code around a focus point the person chooses.
- Open the PPTX and edit every caption and point as text, and re-crop each picture in PowerPoint,
  because ARP crops with PowerPoint's own crop settings and keeps the full image.

## What exists today

- `arp/schemas/visuals.py`: eight typed visuals (`cover`, `section`, `kpi_row`, `chart`,
  `comparison_table`, `two_column`, `points`, `next_steps`) in the `Visual` union.
- `arp/reporting/render_model.py`: each visual renders to primitives (`Rect`, `Text`, `Line`, `ChartPrim`,
  `TablePrim`). Both writers draw that list: `html_writer.py` for the HTML/PDF/PNG and `pptx_writer.py`
  for the PPTX, so the two outputs match box for box (slide-components spec, AC-1).
- `arp/reporting/storyline.py`: the storyline prompt offers `CONTENT_VISUALS`.
  `slide_fill._fill_visual` asks the model for the chosen visual, validates it, retries once, then falls
  back to a `points` slide with a `bad_reference` finding.
- `arp/storage/reporting_store.py`: one directory per report under `reports/<report_id>/` (manifest,
  request, storyline, deck, findings, outputs). No database.
- `arp report plan` (`arp/cli/reporting.py`) and `POST /api/reports` (`arp/api/routers/reporting.py`)
  create a report. Templates and datasets are uploaded first through their own endpoints.
- `LLMClient.complete_structured(..., images=[bytes])` already sends PNG images (visual QA uses it).
- Pillow is installed only as a dependency of python-pptx. This change adds `Pillow` to
  `backend/pyproject.toml` as a direct dependency, since ARP now uses it itself.

## Three versions

| Version | What it delivers |
|---|---|
| Safe | `--image` on the CLI only, a `hero` image slide, centre crop, picture in both outputs. |
| Strong (the plan's PR 4) | CLI and API registration, `hero`, `split` and `gallery`, cover background, crop around a focus point, editable PPTX text. |
| **Most ambitious (specified here)** | Strong, plus: the model sees previews of the images; alt text in both outputs; a `low_resolution` finding; oversized images downscaled before embedding; one copy per image in the PPTX; images carried into re-runs; an endpoint that serves a report's image. |

The next step up would need a saliency model to choose the focus point when the person gives none, and
an upload UI in the app. Both are left out: the first needs a new model dependency, the second is
frontend work this item excludes.

## Goals

- G1. A person registers images with a report from the CLI or the API. They are validated and stored with
  the report.
- G2. The model may only use registered images; anything else is sent back once, then falls back.
- G3. A typed `image` visual with variants `hero`, `split` and `gallery`, plus an optional image behind
  the cover.
- G4. One image primitive, drawn by both writers from the same box and crop.
- G5. Cropping to the slot's aspect happens in code, around an optional focus point; the PPTX keeps the
  full image with PowerPoint crop values.
- G6. PPTX captions and points stay editable text, never part of a picture.
- G7. Image quality and size are managed: a `low_resolution` finding, downscaling above 3840 px, one
  embedded copy per image.

## Non-goals

- A frontend upload UI or image picker. The API is enough for one to follow.
- Mermaid diagrams as pictures (plan PR 7). This spec keeps the primitive open for it: it carries a
  media type, so PR 7 can add `image/svg+xml`.
- Flowchart slides, new chart kinds, template changes.
- Retention or clean-up of staged uploads that no report used.
- The legacy `image` layout and `SlideContent.image_path`. They stay hidden and dropped as today.

## Anti-goals

- The model never supplies a file path or a URL. It names a registered image, nothing else.
- No text is ever drawn into a picture. Captions and points are text shapes.
- No stretched images. A picture always keeps its aspect ratio; the slot is filled by cropping.

## Design

### Registering images

Three models, new in `arp/schemas/reporting.py`:

- `StagedImage`: what an upload returns: `image_id`, `media_type`, `width`, `height`, `sha256`.
- `ReportImageIn`: what a request names: `image_id`, `name`, `alt`, `focus`.
- `ReportImage`: what the stored request holds, all fields below.

| Field | Type | Set by |
|---|---|---|
| `name` | str, 1 to 32 characters `a-z 0-9 _ -`, starting with a letter or digit | person |
| `alt` | str, at most 200 characters, default `""` | person |
| `focus` | `[x, y]`, each from 0 to 1, or null (= centre) | person |
| `image_id` | str or null: the staged upload it came from | code |
| `media_type` | `image/png` or `image/jpeg` | code, from the decoded file |
| `width`, `height` | int, source pixels after EXIF orientation | code |
| `sha256` | hex digest of the stored file | code |

`ReportRequest` gains `images: list[ReportImageIn | ReportImage] = []` (at most 20, names unique;
`create_and_plan` replaces each `ReportImageIn` with the filled `ReportImage` before saving) and
`DeckSettings` gains `cover_image: str | None = None` (a registered name).

Validation, in this order, with these exact messages (`X` is the image name, or the upload's filename
when no name is known yet):

| Check | Message |
|---|---|
| name pattern | `image name 'X' must be 1-32 characters: a-z, 0-9, _ or -, starting with a letter or digit` |
| file over 20 MB (20 × 1024 × 1024 bytes) | `image 'X' is larger than 20 MB` |
| Pillow cannot decode it as PNG or JPEG (the extension is ignored) | `image 'X' is not a PNG or JPEG image` |
| more than 50,000,000 pixels | `image 'X' has more than 50 megapixels` |
| name used twice | `image name 'X' is registered twice` |
| more than 20 images | `at most 20 images per report` |
| focus out of range or malformed | `focus for 'X' must be two numbers from 0 to 1, like 0.5,0.3` |
| `--image-alt`, `--image-focus` or `cover_image` naming an unregistered image | `no image named 'X'; registered: a, b` (registered names in registration order, comma and space) |

A JPEG whose EXIF orientation is not 1 is stored rotated upright (re-encoded at quality 95), so both
writers and PowerPoint draw it the same way up.

**Storage.** Report images live in `reports/<report_id>/images/<name>.png` or `.jpg`. Staged uploads
live in a new directory `report_images/<image_id>/image.png` or `image.jpg`, with `meta.json` holding the
`StagedImage` (setting `report_images_dir`, default `REPO_ROOT / "report_images"`, next to
`report_templates_dir`). `ReportingStore` gains:

- `stage_image(data: bytes, filename: str) -> StagedImage`: validates the file, writes it, returns the
  entry (`image_id` is `img_` + a new id). Raises `ImageError` with a message above (`X` = filename).
- `save_report_image(report_id, name, data, alt="", focus=None) -> ReportImage`: validates and writes
  `images/<name>.<ext>`.
- `report_image_path(report_id, name) -> Path`.
- `load_report_images(report_id, request) -> dict[str, LoadedImage]`: name to `LoadedImage(entry:
  ReportImage, data: bytes)`, read from the report's `images/`.

`create_and_plan` checks every `ReportImageIn` (known `image_id`, names, focus, `cover_image`) before
anything is saved, then copies each staged file into the report through `save_report_image`, before the
storyline call, and stores the filled entries in `request.json`.

**CLI** (`arp report plan`, house deck only), all repeatable except the last:

- `--image NAME=PATH`
- `--image-alt NAME=TEXT`
- `--image-focus NAME=X,Y`
- `--cover-image NAME`

The CLI validates every flag and stages every file with `stage_image` before it calls
`create_and_plan`, then passes `ReportImageIn` entries exactly as the API does. So a bad flag or file
creates no report. Any of the flags with a format other than `house_deck` is an error: `--image needs --format house_deck`
(the flag named is the first one given). A missing file: `image 'NAME': file not found: PATH`. All CLI
errors are `typer.BadParameter`: exit code 2, message on stderr.

**API.**

- `POST /api/reports/images`, multipart `file`: 200 with
  `{"image_id", "media_type", "width", "height", "sha256"}`. 400 with the message as `detail` for a
  validation error, except 413 for the size check.
- `POST /api/reports` takes `images: [{"image_id", "name", "alt", "focus"}]` and `deck.cover_image`. An
  unknown `image_id`: 422 with detail `unknown image_id 'img_x'`. The other checks: 422 with `detail`
equal to the message string. These checks run in the handler (raising `HTTPException`), not as Pydantic
validators, so `detail` is a string, not FastAPI's list of errors.
- `GET /api/reports/{report_id}/images/{name}`: 200 with the stored bytes and its media type; 404 for an
  unknown report or name.

**Re-runs.** `ReportingService.rerun` copies the source report's `images/` into the new report, so the
new report renders on its own. The source report is untouched.

### The `image` visual

New in `arp/schemas/visuals.py`, added to `Visual` and to `FRIENDLY_NAMES` as `"image": "Image"`:

```python
class ImageItem(BaseModel):
    name: str                      # a registered image name
    caption: Words(10) = ""

class ImageVisual(BaseModel):
    type: Literal["image"] = "image"
    variant: Literal["hero", "split", "gallery"]
    images: list[ImageItem] = Field(min_length=1, max_length=6)
    points: list[Words(14)] = Field(default_factory=list, max_length=4)
    side: Literal["left", "right"] = "left"   # split: where the image sits
    emphasis: int | None = None               # split: 0-based index into points
```

Per variant (a schema validator; the errors go back to the model like any other):

- `hero`: exactly 1 image, no points.
- `split`: exactly 1 image, 2 to 4 points.
- `gallery`: 2 to 6 images, each with a non-empty caption, no points.
- Any variant: the same name twice is `image 'X' appears twice`.

Names are checked against the request's images when the fill is validated (`_check_visual`), with
the error `unknown image 'X'; registered: a, b`. Image names are not slide text: `lint.py` skips
`visual.images.*.name`.

### Geometry

All positions are canvas px (1920 × 1080) without a template frame, where the body box is
x 96, y 328, w 1728, h 592. Under a frame, the same rules apply inside the frame's body box.

**Caption band:** an image with a caption is 48 px shorter; its caption is a `Text` 16 px below the
image, 32 px tall, 24 px body font, colour `muted`, named `image:<n>:caption`.

- **hero:** `image:1` fills the body box (1728 × 592, or 1728 × 544 with a caption).
- **split:** the image is 1000 px wide and the full body height (minus the caption band). `side: left`
  puts it at x 96 and the points column at x 1160, w 664; `side: right` puts the points column at x 96,
  w 664, and the image at x 824. The points are drawn like one `two_column` column without its title
  and title rule: per point a number (`points:num:<n>`, `01`..), the text (`points:row:<n>`) and a rule
  under it (`points:rule:<n>`), with today's spacing. The stack is vertically centred in the body box. The emphasised
  point is set at weight 600.
- **gallery:** `n` images in a grid with 32 px gaps. Columns `c = n` for n ≤ 3, else `ceil(n / 2)`;
  rows `1` for n ≤ 3, else 2. Cell width `(1728 − 32(c − 1)) / c`, cell height `(592 − 32(rows − 1)) / rows`;
  each image is its cell minus the caption band. A second row with fewer images than columns is centred.
  Images are numbered `image:1`.. in reading order.
- **cover background** (`deck.cover_image` set): `cover:image` at x 760, y 0, w 1160, h 1080, drawn
  before the cover's other primitives. The answer and figures keep today's place, sizes and vertical centring
  (text x 856, w 968). When there is an answer or a figure, a `cover:card` `Rect` filled `panel` sits
  under them: x 808, w 1064, from 48 px above the top of `cover:answer:label` (or the first figure when
  there is no answer) to 48 px below the bottom of the last figure label (or of `cover:answer`). Without
  an answer or figures there is no card.

### Crop

The image primitive is new in `render_model.py`:

```python
@dataclass(frozen=True)
class ImagePrim:
    name: str
    x: float; y: float; w: float; h: float
    image: str                 # registered name
    media_type: str
    crop: tuple[float, float, float, float]   # left, top, right, bottom, fractions of the source
    alt: str
    emphasis: bool = False
```

Crop (code, `render_model.crop`): source `W × H`, slot `w × h`, focus `(fx, fy)` (default 0.5, 0.5).

- If `W / H > w / h`, the width is cut: `cw = H · w / h`, `left = clamp(fx · W − cw / 2, 0, W − cw)`,
  crop `(left / W, 0, (W − left − cw) / W, 0)`.
- Otherwise the height is cut: `ch = W · h / w`, `top = clamp(fy · H − ch / 2, 0, H − ch)`,
  crop `(0, top / H, 0, (H − top − ch) / H)`.

**Where the bytes come from.** `render_slide`, `render_deck_html` and `build_house_pptx` gain a keyword
argument `images: dict[str, LoadedImage] | None = None`. `render_house_outputs` and `build_house_deck`
pass `store.load_report_images(report_id, request)`. A visual that names an image missing from `images`
raises `VisualDataError` (`unknown image 'X'; registered: …`).

**PPTX** (`pptx_writer.py`): a picture shape named as the primitive, at its box, with `crop_left`,
`crop_top`, `crop_right`, `crop_bottom` equal to the crop, and its alt text (`descr`) set to `alt`, or to
the name when `alt` is empty. The full image stays embedded, so a person can re-crop it in PowerPoint.
python-pptx stores identical images once, so an image used on three slides is one media part.

**HTML** (`html_writer.py`): an `<img data-name="<name>">` at the box with `src` a data URI of the
(possibly downscaled) file, `alt` as above, `object-fit: cover` and `object-position: X% Y%`, where
`X = 100 · left / (left + right)` (50 when both are 0) and `Y` likewise from top and bottom. That shows
the same region as the PPTX crop.

**Downscale:** an image whose long edge is over 3840 px is embedded in both outputs as a copy scaled to a
3840 px long edge (Lanczos, same format; JPEG at quality 90). The stored original is unchanged. Crop
fractions are the same either way.

**`low_resolution` finding** (stage `fit`), computed by `render_house_outputs` for every slide. It
replaces the report's earlier `low_resolution` findings in `findings.json` and keeps all others, so
both a build and `POST /api/reports/{id}/render` leave the current set. It is raised when the crop's source region is narrower than 0.75 × the
slot width in canvas px, e.g. an 800 × 400 image in a hero slot. Message:
`image 'X' is shown at <k>× its pixels; use a larger image` (k to one decimal, slot width / crop width).

### Model calls

- **Storyline** (`draft_storyline`): when the request has images, `image` is added to the visuals the
  prompt offers, after the existing five, and the prompt lists the images, one line each:
  `- <name> (<width>×<height>): <alt>`, ending at the colon when `alt` is empty. Without images the prompt is unchanged.
- **Fill** (`_fill_visual` for `image`): the prompt lists the same lines and, per decision 1, `images=`
  carries one PNG preview per registered image in registration order, long edge 768 px (never upscaled).
- A storyline slide with `visual: image` when the request has no images falls back to `points` without
  calling the model, with one `bad_reference` finding: `no images registered`.
- The existing retry and fallback apply: an unknown name gets one retry with the error, then the `points`
  fallback with one `bad_reference` finding.

The fit ladder handles a `split` slide's points and captions like other visuals' text (type step, then
shorten); images themselves never overflow.

## Defaults taken

- Names, limits and messages as in the tables above (20 images, 20 MB, 50 megapixels, 3840 px, 768 px
  previews, 0.75 × resolution threshold).
- PNG and JPEG only. WebP, GIF and SVG are rejected with the "not a PNG or JPEG" message; SVG arrives with
  plan PR 7 as an internal source, not a registered one.
- The cover image is chosen by the person (`--cover-image`), never by the model.
- Upload first, then reference by `image_id`, the same pattern as templates and datasets.
- Split image 1000 px wide; caption band 48 px; gallery gaps 32 px; caption 24 px `muted`.
- Staged uploads are kept; their clean-up is out of scope.
- Pillow becomes a direct dependency.

## Acceptance

**Fixtures.** Images are generated by the test with Pillow, so they are exact:

- **`quad`**: a 2000 × 1000 PNG, left half `#ff0000`, right half `#0000ff`.
- **`tall`**: a 1000 × 2000 PNG, top half `#00ff00`, bottom half `#000000`.
- **`small`**: an 800 × 400 PNG, one colour.
- **`huge`**: a 6000 × 3000 PNG, one colour.
- **`rotated`**: a 400 × 200 JPEG with EXIF orientation 6.

"The image deck" is a `Deck` stored through `ReportingStore` with a request whose `images` were added with
`save_report_image` (no alt, no focus unless the row says so), rendered with `POST
/api/reports/{id}/render` (or, for "build PPTX/HTML", with `build_house_pptx` / `render_deck_html` given
`images=store.load_report_images(...)`). Slides, after a `points` slide 0:

1. `image` hero on `quad`
2. `image` split on `quad`, side left, 3 points of 5 words each
3. `image` gallery of 4: `quad`, `tall`, `quad2` (a second copy of `quad` under another name), `small`, each
   with a 3-word caption
4. `image` gallery of 5: the four above plus `huge`, each with a 3-word caption

"The hero deck" is slides 0 and 1 of the image deck only (no split or gallery), for rows slice 2 must pass
before slice 3 exists.

A "stand-in LLM" is the test stand-ins of `arp/standins.py` (`ARP_STANDINS_DIR`), so CLI and API rows run without a model; a "fake `LLMClient`" is an in-process object passed to the function, which records its arguments and answers from a list. Builds are light mode without a template. PPTX positions are converted at 9525 EMU/px; positions ±1 px,
crop fractions ±0.001.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `quad.png` on disk; a stand-in LLM | `arp report plan --format house_deck --image hero=quad.png --image-alt "hero=Landing page" --image-focus hero=0.2,0.5 ...` | exits 0; the stored `request.json` has one image `hero`, `media_type` `image/png`, width 2000, height 1000, alt `Landing page`, focus `[0.2, 0.5]` | holdout |
| AC-2 | AC-1's report | read `reports/<id>/images/hero.png` | its SHA-256 equals `quad.png`'s | holdout |
| AC-3 | no file `missing.png` | `arp report plan --format house_deck --image hero=missing.png ...` | exit code 2; stderr contains `image 'hero': file not found: missing.png`; `arp report list` shows no new report | holdout |
| AC-4 | a text file renamed `fake.png` | `--image shot=fake.png` | exit code 2; stderr contains `image 'shot' is not a PNG or JPEG image` | holdout |
| AC-5 | `quad.png` | `--image Hero=quad.png` | exit code 2; stderr contains `image name 'Hero' must be 1-32 characters: a-z, 0-9, _ or -, starting with a letter or digit` | holdout |
| AC-6 | `quad.png` | `--image a=quad.png --image a=quad.png` | exit code 2; stderr contains `image name 'a' is registered twice` | holdout |
| AC-7 | 21 copies of `small.png` | 21 `--image` flags | exit code 2; stderr contains `at most 20 images per report` | holdout |
| AC-8 | `quad.png` | `--image a=quad.png --image-focus a=1.5,0` | exit code 2; stderr contains `focus for 'a' must be two numbers from 0 to 1, like 0.5,0.3` | holdout |
| AC-9 | `quad.png` | `--image a=quad.png --cover-image b` | exit code 2; stderr contains `no image named 'b'; registered: a` | holdout |
| AC-10 | `quad.png` | `arp report plan --format pptx --image a=quad.png ...` | exit code 2; stderr contains `--image needs --format house_deck` | holdout |
| AC-11 | `quad.png` | `POST /api/reports/images` with it as `file` | 200; body has `image_id` starting `img_`, `media_type` `image/png`, `width` 2000, `height` 1000, `sha256` equal to the file's | holdout |
| AC-12 | a 21 MB file `big.png` | `POST /api/reports/images` | 413; detail `image 'big.png' is larger than 20 MB` | holdout |
| AC-13 | a GIF file `a.gif` | `POST /api/reports/images` | 400; detail `image 'a.gif' is not a PNG or JPEG image` | holdout |
| AC-14 | a 7072 × 7072 PNG `wide.png` | `POST /api/reports/images` | 400; detail `image 'wide.png' has more than 50 megapixels` | holdout |
| AC-15 | an `image_id` from AC-11; a stand-in LLM | `POST /api/reports` (house deck) with `images: [{"image_id": <id>, "name": "shot", "focus": [0.2, 0.5]}]` | 200; `GET /api/reports/{id}/images/shot` returns 200, content type `image/png`, bytes equal to `quad.png` | holdout |
| AC-16 | AC-15's report | read its stored `request.json` | image `shot` has focus `[0.2, 0.5]`, alt `""`, width 2000, height 1000 | holdout |
| AC-17 | a stand-in LLM | `POST /api/reports` with `images: [{"image_id": "img_nope", "name": "a"}]` | 422; detail is the string `unknown image_id 'img_nope'`; `GET /api/reports` lists no new report | holdout |
| AC-18 | an `image_id` from AC-11; a stand-in LLM | `POST /api/reports` with that image named `shot` and `deck.cover_image` `zz` | 422; detail is the string `no image named 'zz'; registered: shot` | holdout |
| AC-19 | a report with no image `x` | `GET /api/reports/{id}/images/x` | 404 | holdout |
| AC-20 | no report `rpt_nope` | `GET /api/reports/rpt_nope/images/x` | 404 | holdout |
| AC-21 | `rotated.jpg` | `save_report_image(rid, "r", <bytes>)` | the entry has width 200, height 400; the stored file decodes to 200 × 400 | holdout |
| AC-22 | a completed house-deck report with image `hero`; a stand-in LLM | `ReportingService.rerun` | the new report's `images/hero.png` has the same SHA-256 as the source's; the source report's directory listing is unchanged | holdout |
| AC-23 | the hero deck | build PPTX | slide 1 has one picture `image:1` at x 96, y 328, w 1728, h 592; crop left 0, right 0, top 0.1574, bottom 0.1574 (kept height 685.19 of 1000) | holdout |
| AC-24 | the hero deck with `quad`'s focus `[0.5, 0]` | build PPTX | slide 1 `image:1` crop top 0, bottom 0.3148 | holdout |
| AC-25 | the hero deck with slide 1 showing `tall` instead of `quad`, `tall`'s focus `[0.5, 1]` | build PPTX | `image:1` crop top 0.8287, bottom 0 (kept height 342.59 of 2000, at the bottom) | holdout |
| AC-26 | the hero deck with slide 1's caption `Our landing page` | build PPTX | `image:1` h 544; a text shape `image:1:caption` at y 888, h 32, text `Our landing page`, font 24 px | holdout |
| AC-27 | the hero deck, and separately the image deck | build HTML in Chromium and PPTX | for every `image:*` and `image:*:caption` primitive, the `[data-name]` element's box relative to its slide equals the PPTX shape box of that name | holdout |
| AC-28 | the hero deck with `quad`'s focus `[0.5, 0]` | build HTML | slide 1's `img[data-name="image:1"]` has computed `object-fit` `cover` and `object-position` `50% 0%` | holdout |
| AC-29 | the hero deck, `quad` registered with alt `Landing page` | build PPTX | slide 1's picture alt text (`descr`) is `Landing page` | holdout |
| AC-30 | as AC-29 | build HTML | slide 1's `img[data-name="image:1"]` has `alt` `Landing page` | holdout |
| AC-31 | the image deck, `small` registered with no alt | build PPTX | its picture's `descr` is `small` | holdout |
| AC-32 | the image deck | build PPTX | slide 3's `image:1:caption`..`image:4:caption` and slide 2's `points:row:1`..`3` are text frames (`has_text_frame` true) holding their text; slide 2 has exactly one picture shape | holdout |
| AC-33 | the hero deck | build PPTX | the media part behind slide 1's `image:1` decodes to 2000 × 1000 (the full source, not the cropped region) | holdout |
| AC-34 | the image deck | build PPTX | slide 2: `image:1` at x 96, w 1000, h 592; `points:row:1`..`3` with x ≥ 1160 and right edge ≤ 1824 | holdout |
| AC-35 | slide 2 with `side: right` | build PPTX | `image:1` x 824; `points:row:1` x ≥ 96 and right edge ≤ 760 | holdout |
| AC-36 | slide 2 with `emphasis: 1` | build PPTX | the runs of `points:row:2` are bold; those of `points:row:1` and `points:row:3` are not | holdout |
| AC-37 | the image deck | build PPTX | slide 3: `image:1`..`4` each w 848, h 232, at (96, 328), (976, 328), (96, 640), (976, 640); `image:<n>:caption` text shapes with the given captions, each top = its image's bottom + 16 | holdout |
| AC-38 | the image deck | build PPTX | slide 4: `image:1`..`3` w 554.67 at x 96, 682.67, 1269.33, y 328; `image:4`, `image:5` at x 389.33 and 976, y 640 | holdout |
| AC-39 | the image deck | build PPTX | the package holds exactly one media part with `quad`'s pixels, although `quad` and `quad2` appear on slides 1, 2, 3 and 4 | holdout |
| AC-40 | the image deck | build PPTX | the media part for `huge` decodes to 3840 × 1920; `reports/<id>/images/huge.png` is still 6000 × 3000 | holdout |
| AC-41 | the image deck | build HTML in Chromium | slide 4's `img` for `huge` has `naturalWidth` 3840 | holdout |
| AC-42 | the hero deck with slide 1 showing `small` instead of `quad` | `POST /api/reports/{id}/render`, then `GET /api/reports/{id}/findings` | exactly one `low_resolution` finding: stage `fit`, slide 1, message `image 'small' is shown at 2.2× its pixels; use a larger image` | holdout |
| AC-43 | a request with images `a` (`quad`, alt `Landing page`) and `b` (`tall`); a storyline slide with `visual: image`; a fake `LLMClient` passed to `fill_slide` in-process that records `images` and returns a valid hero on `a` | `fill_slide` | the fake got `images` of 2 PNGs, 768 × 384 then 384 × 768, in that order; the slide is an `image` hero on `a` | holdout |
| AC-44 | the hero deck (slide 1 shows `quad`, 2000 px wide) | render, then findings | no `low_resolution` finding | holdout |
| AC-45 | AC-43's request; a recording fake `LLMClient` | `draft_storyline` | the prompt's visual list is `kpi_row, chart, comparison_table, two_column, points, flow, image`; it contains the lines `- a (2000×1000): Landing page` and `- b (1000×2000):` (no trailing space) | holdout |
| AC-46 | AC-43's request; a fake `LLMClient` that returns a hero on `nope` on both calls | `fill_slide` | the slide is a `points` slide; one `bad_reference` finding whose message contains `unknown image 'nope'; registered: a, b`; the fake was called twice | holdout |
| AC-47 | a request with no images; a storyline slide with `visual: image`; a recording fake `LLMClient` | `fill_slide` | the slide is a `points` slide; one `bad_reference` finding with message `no images registered`; the fake was called 0 times | holdout |
| AC-48 | AC-43's request; a fake `LLMClient` that returns a gallery listing `a` twice, then a valid gallery | `fill_slide` | the second call's prompt contains `image 'a' appears twice`; the slide is the second answer | holdout |
| AC-49 | a gallery whose captions include `Up 47%`, 47 nowhere in the sources | `lint_deck` | exactly one `number_not_in_source` finding on that slide, naming `47%` | holdout |
| AC-50 | a hero on an image named `q3-2025` with no caption; no number in the sources | `lint_deck` | no `number_not_in_source` finding on that slide | holdout |
| AC-51 | a `cover` visual with an `answer` and 2 `figures`; `deck.cover_image` = `quad` | build PPTX | the cover has a picture `cover:image` at x 760, y 0, w 1160, h 1080 | holdout |
| AC-52 | as AC-51 | build PPTX | a `cover:card` rect at x 808, w 1064, fill the palette's `panel`; its top is `cover:answer:label`'s top − 48 and its bottom the last figure label's bottom + 48 | holdout |
| AC-53 | as AC-51 | build PPTX | `cover:answer` and `cover:figure:1` have the same box as on the same cover without `cover_image` | holdout |
| AC-54 | a `cover` with no answer and no figures; `deck.cover_image` = `quad` | build PPTX | `cover:image` present; no `cover:card` shape | holdout |
| AC-55 | `quad`, `tall`, `small`, `huge` uploaded to the running app with `POST /api/reports/images`, plus `quad` a second time; a report created via `POST /api/reports` registering them as `quad`, `tall`, `small`, `huge`, `quad2`; its `deck.json` replaced by the image deck through `ReportingStore.save_deck`; `POST /api/reports/{id}/render` | open the preview pages of slides 1 and 2 | each image fills its slot with no stretching, and no text overlaps an image or is clipped | evaluator |
| AC-56 | as AC-55 | open the preview pages of slides 3 and 4 | every caption sits under its own image and the images line up in rows | evaluator |
| AC-57 | as AC-55, with `deck.cover_image` set and a cover with an answer | open the cover's preview page | the card's text is fully readable on the card, and the image is visible right of the ink panel around the card | evaluator |
| AC-58 | a stored house deck with no image slides and no `cover_image` | `build_house_pptx` | shape names, positions and font sizes equal the shape list the test-writer records from `main` when this spec merges (kept in the holdout repo), ±1 | holdout |
| AC-59 | a request with no images; a recording fake `LLMClient` | `draft_storyline` | the visual list in the prompt is exactly `kpi_row, chart, comparison_table, two_column, points, flow` (slide-components AC-16 still holds) | holdout |
| AC-60 | a legacy (no `visual`) storyline slide; a fake `LLMClient` returning a `SlideContent` with `image_path` `/etc/passwd` | `fill_slide` | the returned slide's `image_path` is None | holdout |

Must not change: decks without images (AC-58), the storyline prompt without images (AC-59), the dropped
legacy `image_path` (AC-60). Rows of earlier specs this supersedes: none.

## Slices

Each slice is one `S` PR, in this order. A PR builds one slice and puts `Rows:` with that slice's rows
in its description; the last slice drops the line.

1. **Register and store images:** the models, store methods, CLI flags, upload and serve endpoints,
   copy on create and on re-run, Pillow dependency. Rows: AC-1 to AC-22.
2. **Image primitive and hero:** `ImagePrim`, crop, both writers, `hero`, alt text, downscale, one media
   part, `low_resolution`, on the hero deck. Rows: AC-23 to AC-30, AC-33, AC-42, AC-44, AC-58. (AC-27 on
   the hero deck only until slice 3.)
3. **Split, gallery and cover image.** Rows: AC-27, AC-31, AC-32, AC-34 to AC-41, AC-51 to AC-58.
4. **Model calls:** storyline offer, fill with previews, name checks, fallback, lint. Rows: AC-43,
   AC-45 to AC-50, AC-58, AC-59, AC-60.

## Wiki

After this lands, `openwiki/` needs an update for the reporting module (image registration and the
`image` visual); the weekly `/context-refresh` PR does that.
