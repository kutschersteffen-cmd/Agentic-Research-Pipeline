"""`arp preflight` readiness checks (spec bank-jupyter-launch, AC-9/10/15/19/22-26), with stand-ins for the
model, the compute services, the running server and the outbound fetch."""

import httpx
import pytest

from arp import preflight
from arp.config import Settings

MODEL, VERIFIER = "gemini-3.6-flash", "gemini-3.6-pro"
FETCH = "https://example.test/doc.pdf"
ALL_OK = [
    "ok postgres", f"ok model {MODEL}", f"ok verifier {VERIFIER}", "ok compute models", "ok compute parse",
    "ok frontend", "ok fetch",
]


class FakeLLM:
    def __init__(self, model):
        self.model = model

    async def complete_structured(self, *, output_model, **kw):
        if self.model == "nope":
            raise RuntimeError("model not found\nsecond line")
        return output_model(ok=True), None


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Everything healthy; a test breaks one part."""
    w = type("World", (), {})()
    w.settings = Settings(
        _env_file=None, cache_dir=tmp_path, anthropic_api_key="sk-ant-other-provider", gemini_api_key="k",
        llm_model=MODEL, llm_verifier_model=VERIFIER, postgres_dsn="postgresql+psycopg://x/y",
        compute_models_url="https://models.test", compute_parse_url="https://parse.test", preflight_fetch_url=FETCH,
    )
    w.built, w.requested, w.agents, w.frontend_status, w.fetch_error = [], [], {}, 200, None
    monkeypatch.setattr(preflight, "require_postgres", lambda s: None)
    monkeypatch.setattr(preflight, "require_cutover", lambda s: None)
    monkeypatch.setattr(preflight, "_auth", lambda url: {})

    def factory(settings, *, model, cache_refresh):
        w.built.append((model, settings.anthropic_api_key, settings.gemini_available))
        return FakeLLM(model)

    def handler(request):
        w.requested.append(str(request.url))
        w.agents[str(request.url)] = request.headers.get("user-agent")
        if str(request.url) == FETCH:
            if w.fetch_error:
                raise httpx.ReadTimeout(w.fetch_error)
            return httpx.Response(200)
        if request.url.host == "127.0.0.1":
            return httpx.Response(w.frontend_status)
        return httpx.Response(200)

    async def run(settings=None):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await preflight.run_preflight(settings or w.settings, llm_factory=factory, http=http)

    w.run = run
    return w


async def test_all_ok_exact_lines(world):
    assert await world.run() == ALL_OK


async def test_fetch_identifies_itself(world):
    await world.run()
    assert world.agents[FETCH] == world.settings.edgar_user_agent


async def test_bad_model_fails_without_fallback(world):
    lines = await world.run(world.settings.model_copy(update={"llm_model": "nope"}))
    assert lines[1] == "FAIL model nope: model not found"
    assert len(lines) == 7 and all(line.startswith("ok ") for i, line in enumerate(lines) if i != 1)
    # the check asked for exactly that model, with no other provider able to answer for it
    assert world.built[0] == ("nope", "sk-ant-other-provider", False)  # a non-Gemini id: Gemini is taken away


async def test_bad_verifier(world):
    lines = await world.run(world.settings.model_copy(update={"llm_verifier_model": "nope"}))
    assert lines[2] == "FAIL verifier nope: model not found"
    assert len(lines) == 7


async def test_gemini_model_check_keeps_gemini_and_drops_anthropic(world):
    await world.run()
    assert world.built[0] == (MODEL, None, True)


async def test_unset_compute_is_skip(world):
    lines = await world.run(world.settings.model_copy(update={"compute_models_url": None}))
    assert lines[3] == "skip compute models"
    assert len(lines) == 7 and not any(line.startswith("FAIL") for line in lines)


async def test_unmigrated_db(world, monkeypatch):
    def not_migrated(settings):
        raise RuntimeError("the database schema is not current (missing tables: ['runs'], pending steps: [])")

    monkeypatch.setattr(preflight, "require_cutover", not_migrated)
    lines = await world.run()
    assert lines[0].startswith("FAIL postgres: the database schema is not current")
    assert len(lines) == 7


async def test_frontend_404(world):
    world.frontend_status = 404
    lines = await world.run()
    assert lines[5].startswith("FAIL frontend:")


async def test_fetch_timeout(world):
    world.fetch_error = "timeout"
    lines = await world.run()
    assert lines[6] == "FAIL fetch: timeout"
    assert FETCH in world.requested


def test_cli_exit_codes(world, monkeypatch):
    from typer.testing import CliRunner

    from arp.cli import app

    async def fake(settings, **kw):
        return fake.lines

    monkeypatch.setattr(preflight, "run_preflight", fake)
    monkeypatch.setattr("arp.config.get_settings", lambda: world.settings)
    fake.lines = ALL_OK
    ok = CliRunner().invoke(app, ["preflight"])
    assert (ok.exit_code, ok.stdout.splitlines()) == (0, ALL_OK)
    fake.lines = ["FAIL postgres: down", *ALL_OK[1:]]
    assert CliRunner().invoke(app, ["preflight"]).exit_code == 1
