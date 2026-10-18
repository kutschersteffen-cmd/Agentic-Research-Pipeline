# Files

- [Data flow: documents to UI](data-flow.md) - End-to-end path of a value in the Agentic Research Pipeline, from a source document through ingestion, extraction and grounding, the per-company Postgres transaction, human review and publishing, to the API and the React UI.
- [Frontend application](frontend.md) - The React 19 + Vite single-page app in frontend/src, covering hash routing with lazily loaded pages, the single API client with bearer-token auth, the generated OpenAPI types and the compile-time API contract, and the extraction, review and run screens.
- [System architecture](overview.md) - How the Agentic Research Pipeline fits together. A FastAPI app and a Typer CLI share the same pipelines in backend/arp, which call models through one structured-output LLM interface, model per-item flows as LangGraph graphs, persist runs and facts in Postgres, and serve a React SPA in frontend/src.
