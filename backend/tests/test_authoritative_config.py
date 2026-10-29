import json

from arp.schemas.decision import AuthoritativeOutput, MechanismConfig
from arp.storage.decision_store import DecisionStore

# A framework file as written before frameworks had a purpose.
OLD_FILE = json.dumps({"framework_id": "fw_old", "version": 1, "name": "Old framework", "ratified": True})


def test_ac_11_old_file_loads_as_score():
    config = MechanismConfig.model_validate(json.loads(OLD_FILE))
    assert config.purpose == "score"
    assert config.outputs == []
    assert config.dataset_id is None


def test_outputs_roundtrip(tmp_path):
    store = DecisionStore(tmp_path)
    config = MechanismConfig(
        purpose="authoritative",
        dataset_id="ds_1",
        outputs=[AuthoritativeOutput(column="auth_scope1", name="Scope 1", unit="tCO2e")],
    )
    saved = store.save(config)
    loaded = store.get(saved.framework_id)
    assert loaded.purpose == "authoritative"
    assert loaded.dataset_id == "ds_1"
    assert loaded.outputs == [AuthoritativeOutput(column="auth_scope1", name="Scope 1", data_type="number", unit="tCO2e")]
