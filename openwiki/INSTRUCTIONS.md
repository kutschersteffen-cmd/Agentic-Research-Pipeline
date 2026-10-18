# OpenWiki brief for this repository

Hand-written; OpenWiki reads it and never rewrites it.

## Scope

- Code: `backend/arp/` (the Python pipeline and API) and `frontend/src/` (the React app).
- Docs: `docs/` and the top-level Markdown files, as background for the code pages.
- Skip generated files: `frontend/src/api/schema.gen.ts`, `frontend/src/api/openapi.json`, lock files, build
  output, and everything `.openwikiignore` lists (secrets, `data/`, `runs/`, `engagements/`, `ballots/`,
  `graphify-out/`, `.obsidian/`).

## Priorities

1. Architecture: the main parts of `backend/arp/` and `frontend/src/` and how they connect.
2. Data flow: from source documents through the pipeline to the database, the API and the UI.
3. Extraction, grounding and publish (`backend/arp/extraction/`, `backend/arp/grounding.py`,
   `backend/arp/publish/`): how values are extracted, tied back to evidence, and published.

## Conventions

- Cite every source file by its full repo-relative path, such as `backend/arp/grounding.py`, never by its
  basename alone. The Atlas page finds a file's wiki page by that path.
- `notes/` holds decisions written by people. Where a note disagrees with the code, describe the code and
  mention the note.
