import pytest

from arp.publish.facts import FactCandidate, plan_version
from arp.publish.reader import as_of_bound, visible
from arp.schemas.common import Citation

LEI = "5493001KJTIIGC8Y1R12"


def _cand(value):
    return FactCandidate(
        issuer_key=LEI, issuer_scheme="LEI", field_id="f1", period_end="2024-12-31", value=value, unit="EUR",
        state="approved", citation=Citation.model_construct(doc_id="d1", content_key="ck"),
        source_run_id="run1", observed_at="2026-10-01T00:00:00.000000+00:00", item_key="k1",
    )


def _v1(valid_from, valid_to=None):
    f = plan_version(None, _cand(1), release_id="rel_1", now=valid_from).fact
    return f.model_copy(update={"valid_to": valid_to})


def test_fact_published_after_as_of_is_invisible():
    assert visible([_v1("2026-11-02T09:00:00.000000+00:00")], "2026-10-31") == []


def test_as_of_date_covers_whole_day():
    f = _v1("2026-10-31T23:00:00.000000+00:00")
    assert visible([f], "2026-10-31") == [f]


def test_superseded_value_shown_before_supersession():
    t2 = "2026-11-01T09:00:00.000000+00:00"
    v1 = _v1("2026-10-01T09:00:00.000000+00:00", t2)
    v2 = plan_version(v1, _cand(2), release_id="rel_2", now=t2).fact
    assert visible([v1, v2], "2026-10-31") == [v1]
    assert visible([v1, v2], "2026-11-01") == [v2]


def test_withdrawn_version_still_visible_before_withdrawal():
    f = _v1("2026-10-01T09:00:00.000000+00:00", "2026-11-05T09:00:00.000000+00:00")
    assert visible([f], "2026-11-04") == [f]
    assert visible([f], "2026-11-05") == []


def test_as_of_bound_normalises_offset():
    assert as_of_bound("2026-10-31T10:00:00+02:00") == "2026-10-31T08:00:00.000000+00:00"
    assert as_of_bound("2026-10-31T10:00:00") == "2026-10-31T10:00:00.000000+00:00"
    assert as_of_bound("2026-10-31") == "2026-10-31T23:59:59.999999+00:00"


@pytest.mark.parametrize("bad", ["", "yesterday", "2026-13-01", None])
def test_bad_as_of_is_value_error(bad):
    with pytest.raises(ValueError, match="bad as_of"):
        as_of_bound(bad)
