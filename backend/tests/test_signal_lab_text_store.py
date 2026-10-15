from arp.signal_lab.text_store import TextStore, make_record


def _rec(item="a", company="c1", event="2020-01-10T00:00:00Z", known="2020-01-10T00:00:00Z", body="b", **kw):
    return make_record(
        source="tr_news", source_item_id=item, company_id=company, event_time=event,
        knowledge_time=known, title="t", body=body, **kw,
    )


def test_add_is_idempotent(pg):
    store = TextStore(pg)
    rec = _rec()
    assert store.add(rec) is True
    assert store.add(rec) is False
    assert [r.item_id for r in store.items()] == [rec.item_id]


def test_correction_keeps_event_time_and_is_visible_by_knowledge_time(pg):
    store = TextStore(pg)
    v1 = _rec(body="one", known="2020-02-01T00:00:00Z")
    v2 = _rec(body="two", known="2020-03-01T00:00:00Z")
    assert v1.event_time == v2.event_time and v1.item_id != v2.item_id
    store.add(v1)
    store.add(v2)
    assert [r.item_id for r in store.items(known_by="2020-02-15T00:00:00Z")] == [v1.item_id]
    assert [r.item_id for r in store.items(known_by="2020-03-02T00:00:00Z")] == [v2.item_id]
    assert [r.item_id for r in store.items()] == [v2.item_id]


def test_event_window_and_company_filter(pg):
    store = TextStore(pg)
    d1 = _rec("1", "c1", "2020-01-01T12:00:00Z", "2020-01-01T12:00:00Z")
    d2 = _rec("2", "c2", "2020-01-02T12:00:00Z", "2020-01-02T12:00:00Z")
    d3 = _rec("3", "c1", "2020-01-03T12:00:00Z", "2020-01-03T12:00:00Z")
    for r in (d1, d2, d3):
        store.add(r)
    ids = lambda **kw: [r.item_id for r in store.items(**kw)]  # noqa: E731
    assert ids(company_id="c1") == [d1.item_id, d3.item_id]
    assert ids(event_from="2020-01-02T12:00:00Z", event_to="2020-01-03T12:00:00Z") == [d2.item_id, d3.item_id]
    assert ids(company_id="c1", event_from="2020-01-02T00:00:00Z") == [d3.item_id]


def test_null_company_is_stored_and_filterable(pg):
    store = TextStore(pg)
    n = _rec("n", None)
    c = _rec("c", "c1", event="2020-01-11T00:00:00Z")
    store.add(n)
    store.add(c)
    got = store.items(company_id=None)
    assert {r.item_id for r in got} == {n.item_id, c.item_id}
    assert next(r for r in got if r.item_id == n.item_id).company_id is None
    assert [r.item_id for r in store.items(company_id="c1")] == [c.item_id]


def test_latest_revision_time(pg):
    store = TextStore(pg)
    assert store.latest_revision_time("tr_news", "a") is None
    store.add(_rec(body="x"))
    assert store.latest_revision_time("tr_news", "a") is None
    store.add(_rec(body="y", revision_time="2020-02-01T00:00:00Z"))
    store.add(_rec(body="z", revision_time="2020-03-01T00:00:00+00:00"))
    assert store.latest_revision_time("tr_news", "a") == "2020-03-01T00:00:00Z"
