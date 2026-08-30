import numpy as np

from arp.emerging_themes.clustering import _jaccard, _label_member_sets, cluster_tags
from arp.schemas.emerging_themes import ExtractedTag, MentionSourceType, RawMention


def test_label_member_sets_drops_noise_label():
    labels = np.array([0, 0, -1, 1, 1, -1])
    members = _label_member_sets(labels)
    assert members == {0: {0, 1}, 1: {3, 4}}


def test_jaccard_basic():
    assert _jaccard({1, 2, 3}, {2, 3, 4}) == 2 / 4
    assert _jaccard(set(), set()) == 0.0
    assert _jaccard({1}, {1}) == 1.0


def _tag(i: int, mention_id: str, label: str) -> ExtractedTag:
    return ExtractedTag(tag_id=f"t{i}", mention_id=mention_id, label=label, claim=f"claim {i}", quote="q", grounded=True)


async def test_cluster_tags_smoke_two_well_separated_groups(monkeypatch):
    """Integration smoke test against the real UMAP+HDBSCAN stack (the
    `emerging_themes` extra): two well-separated synthetic embedding
    clusters should not error out and should account for every input tag
    across whatever clusters (+ noise) HDBSCAN finds -- deliberately not
    asserting an exact cluster count, since UMAP/HDBSCAN's exact boundary
    on a tiny synthetic dataset is not what this test is meant to pin
    down (see test_emerging_themes_lineage.py for the deterministic,
    non-stochastic behavior this pipeline actually depends on).
    """
    rng = np.random.default_rng(0)
    group_a = rng.normal(loc=5.0, scale=0.05, size=(6, 32)).astype(np.float32)
    group_b = rng.normal(loc=-5.0, scale=0.05, size=(6, 32)).astype(np.float32)
    fake_vectors = np.vstack([group_a, group_b])

    def fake_embed_texts(texts: list[str]) -> np.ndarray:
        assert len(texts) == len(fake_vectors)
        return fake_vectors

    monkeypatch.setattr("arp.retrieval.embeddings.embed_texts", fake_embed_texts)

    tags = [_tag(i, f"m{i}", "battery" if i < 6 else "carbon capture") for i in range(12)]
    mentions_by_id = {f"m{i}": RawMention(mention_id=f"m{i}", source_type=MentionSourceType.GDELT, title="t", text="x", url=f"https://example.com/{i}") for i in range(12)}
    company_ids_by_mention: dict[str, list[str]] = {}

    clusters = cluster_tags(tags, mentions_by_id, company_ids_by_mention, "2026-W01", min_cluster_size=3, stability_reruns=1)

    covered_tag_ids = {tid for c in clusters for tid in c.member_tag_ids}
    assert covered_tag_ids  # at least one real cluster was found
    assert covered_tag_ids.issubset({t.tag_id for t in tags})
    for cluster in clusters:
        assert cluster.mention_count == len(cluster.member_tag_ids)  # one mention per tag in this fixture
        assert 0.0 <= cluster.stability_score <= 1.0
        assert cluster.centroid  # non-empty mean vector


async def test_cluster_tags_returns_empty_below_min_cluster_size():
    tags = [_tag(i, f"m{i}", "battery") for i in range(2)]
    clusters = cluster_tags(tags, {}, {}, "2026-W01", min_cluster_size=3)
    assert clusters == []
