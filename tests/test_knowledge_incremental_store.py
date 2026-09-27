import numpy as np
import pytest

from knowledge.models import KnowledgeChunk, KnowledgeQuerySpec
from knowledge.store import KnowledgeStore


class _CountingEmbedder:
    def __init__(self):
        self.calls = []

    def embed_passages(self, texts):
        self.calls.append(tuple(texts))
        return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)


def _chunk(chunk_id, digest, text, *, domain="jump", allowed=True):
    return KnowledgeChunk(
        chunk_id=chunk_id,
        source_id="pmc5377563",
        document_id="pmc5377563",
        version_id="v" * 64,
        domain=domain,
        section="Methods",
        locator="Methods ¶1",
        logical_position=f"{domain}/methods/{chunk_id}",
        text=text,
        content_digest=digest,
        token_count=5,
        metric_codes=("jump_height_m",),
        populations=("general",),
        support_types=("method",),
        recommendation_allowed=allowed,
    )


def _write(path, chunks):
    (path / "chunks.jsonl").write_text(
        "\n".join(item.model_dump_json() for item in chunks) + "\n",
        encoding="utf-8",
    )


def test_repeated_build_reuses_embeddings_and_rows(tmp_path):
    chunks = (_chunk("c1", "1" * 64, "jump measurement method"),)
    _write(tmp_path, chunks)
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    embedder = _CountingEmbedder()

    assert store.build(embedder) == 1
    assert store.last_build_stats["embedded_count"] == 1
    assert store.build(embedder) == 1
    assert store.last_build_stats["embedded_count"] == 0
    assert len(embedder.calls) == 1

    with store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM chunks").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 1


def test_changed_chunk_only_embeds_new_content(tmp_path):
    _write(tmp_path, (_chunk("c1", "1" * 64, "first text"),))
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    embedder = _CountingEmbedder()
    store.build(embedder)

    _write(
        tmp_path,
        (
            _chunk("c1", "1" * 64, "first text"),
            _chunk("c2", "2" * 64, "second text"),
        ),
    )
    store.build(embedder)

    assert store.last_build_stats["embedded_count"] == 1
    assert embedder.calls[-1] == ("second text",)


def test_core_metadata_filter_never_relaxes(tmp_path):
    _write(tmp_path, (_chunk("c1", "1" * 64, "jump measurement method"),))
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    store.build(_CountingEmbedder())
    matching = KnowledgeQuerySpec(
        query_id="q1",
        query="jump measurement",
        domain="jump",
        metric_codes=("jump_height_m",),
        population="general",
        support_types=("method",),
        recommendation_allowed=True,
        recommendation_intent="measurement_review",
        planner_version="test",
    )
    blocked = matching.model_copy(update={"population": "clinical"})

    assert len(store.load_all(spec=matching)) == 1
    assert store.load_all(spec=blocked) == ()


def test_failed_update_keeps_previous_active_index(tmp_path):
    _write(tmp_path, (_chunk("c1", "1" * 64, "first text"),))
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    store.build(_CountingEmbedder())
    _write(
        tmp_path,
        (
            _chunk("c1", "1" * 64, "first text"),
            _chunk("c2", "2" * 64, "second text"),
        ),
    )

    class _BrokenEmbedder:
        def embed_passages(self, texts):
            return np.asarray([], dtype=np.float32)

    with pytest.raises(ValueError, match="embedding count"):
        store.build(_BrokenEmbedder())

    assert [item[0].chunk_id for item in store.load_all()] == ["c1"]


def test_protocol_filter_applies_before_dense_and_lexical_ranking(tmp_path):
    chunks = tuple(
        _chunk(f"c{i}", str(i) * 64, "jump measurement method").model_copy(
            update={"metadata": {"protocol": protocol} if protocol else {}}
        )
        for i, protocol in enumerate(("overground_walk", "treadmill_walk", None), 1)
    )
    _write(tmp_path, chunks)
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    store.build(_CountingEmbedder())
    spec = KnowledgeQuerySpec(
        query_id="ground", query="measurement", domain="jump",
        metric_codes=("jump_height_m",), population="general", support_types=("method",),
        recommendation_allowed=True, recommendation_intent="measurement_review",
        planner_version="test", protocols=("overground_walk",),
    )
    assert [c.chunk_id for c, _, _ in store.load_all(spec=spec)] == ["c1"]
    assert [c.chunk_id for c, _, _ in store.lexical_search("measurement", 20, spec=spec)] == ["c1"]
    absent = spec.model_copy(update={"protocols": ("overground_run",)})
    assert store.load_all(spec=absent) == ()
    assert store.lexical_search("measurement", 20, spec=absent) == ()
