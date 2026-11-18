import json

from arp.schemas.engagement import EngagementRecord, FirTheme, InfluenceLevel, Objective

FIXTURE_PRE_VOICE = json.dumps({
    "company_id": "c1",
    "name": "Acme",
    "issues": [{
        "issue_id": "iss_1",
        "theme": "board_governance",
        "opened_at": "2025-01-01T00:00:00Z",
        "status": "open",
        "severity": "medium",
        "source": "manual",
        "milestone_stage": "identified",
        "escalation_stage": "private_engagement",
        "correspondence": [{"entry_id": "corr_1", "date": "2025-01-02", "type": "email", "summary": "hi"}],
    }],
})


def test_old_record_json_still_validates():
    rec = EngagementRecord.model_validate(json.loads(FIXTURE_PRE_VOICE))
    assert rec.issues[0].objectives == [] and rec.issues[0].engager_role is None
    assert rec.issues[0].data_source == "app" and rec.issues[0].correspondence[0].is_initiation is False


def test_fir_theme_has_the_15_values_in_order():
    assert [t.value for t in FirTheme] == ["climate_mitigation", "climate_adaptation", "natural_capital",
        "resources_circular", "pollution", "human_capital", "human_rights", "consumer_protection",
        "digital_responsibility", "communities", "governance_board_pay", "business_ethics",
        "tax_accounting", "shareholder_rights", "other"]


def test_influence_levels():
    assert [i.value for i in InfluenceLevel] == ["1", "2", "3", "4A", "4B", "5"]


def test_objective_minimal():
    o = Objective(description="d", objective_type="strategic")
    assert o.status == "initiated" and o.objective_id.startswith("obj") and o.source == "app"
