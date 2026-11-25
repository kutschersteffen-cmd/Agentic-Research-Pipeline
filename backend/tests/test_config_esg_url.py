from arp.config import Settings

_NAMES = ("ARP_ESG_API_URL", "ARP_ESG_API_BASE_URL")


def _clean(monkeypatch, tmp_path):
    for n in _NAMES:
        monkeypatch.delenv(n, raising=False)
    monkeypatch.chdir(tmp_path)


def test_documented_name_sets_esg_url(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    monkeypatch.setenv("ARP_ESG_API_URL", "https://esg-a.example/v1")
    assert Settings().esg_api_base_url == "https://esg-a.example/v1"


def test_old_name_still_works_and_documented_name_wins(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    monkeypatch.setenv("ARP_ESG_API_BASE_URL", "https://esg-b.example/v1")
    assert Settings().esg_api_base_url == "https://esg-b.example/v1"
    monkeypatch.setenv("ARP_ESG_API_URL", "https://esg-a.example/v1")
    assert Settings().esg_api_base_url == "https://esg-a.example/v1"


def test_dotenv_and_env_precedence(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("ARP_ESG_API_BASE_URL=https://esg-f.example/v1\nARP_ESG_API_URL=https://esg-e.example/v1\n")
    assert Settings().esg_api_base_url == "https://esg-e.example/v1"
    monkeypatch.setenv("ARP_ESG_API_BASE_URL", "https://esg-b.example/v1")
    assert Settings().esg_api_base_url == "https://esg-b.example/v1"  # process env beats .env


def test_field_name_init_and_model_copy(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    assert Settings().esg_api_base_url is None
    monkeypatch.setenv("ARP_ESG_API_URL", "https://esg-a.example/v1")
    assert Settings(esg_api_base_url="https://esg-c.example/v1").esg_api_base_url == "https://esg-c.example/v1"
    s = Settings().model_copy(update={"esg_api_base_url": "https://esg-d.example/v1"})
    assert s.esg_api_base_url == "https://esg-d.example/v1"


def test_lower_case_names(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    monkeypatch.setenv("arp_esg_api_url", "https://esg-l.example/v1")
    assert Settings().esg_api_base_url == "https://esg-l.example/v1"
