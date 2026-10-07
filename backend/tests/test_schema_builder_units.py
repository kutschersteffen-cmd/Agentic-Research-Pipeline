from arp.extraction.schema_builder import _readable_unit


def test_drafted_unit_kept_only_when_the_normaliser_can_read_it():
    assert _readable_unit("USD") == "USD"
    assert _readable_unit("USD million") == "USD million"
    assert _readable_unit("%") == "%"
    assert _readable_unit("millions (report in the reporting currency, USD or EUR; state currency)") is None
    assert _readable_unit(None) is None
