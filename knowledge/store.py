"""Incremental SQLite FTS5 and NumPy vector store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .catalog import load_catalog
from .embeddings import LocalEmbeddingModel, MODEL_VERSION
from .ingestion import DEFAULT_DATA_DIR, load_chunk_snapshot
from .models import KnowledgeChunk, KnowledgeQuerySpec, KnowledgeSource


DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "knowledge.sqlite3"
STORE_SCHEMA_VERSION = 2


class KnowledgeStore:
    def __init__(self, path: Path = DEFAULT_DB_PATH):
        self.path = Path(path)
        self.last_build_stats: dict[str, int] = {}

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        existing_chunks = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks'"
        ).fetchone()
        chunk_columns = (
            {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
            if existing_chunks
            else set()
        )
        if existing_chunks and (
            version < STORE_SCHEMA_VERSION or "document_id" not in chunk_columns
        ):
            # One-time migration from the disposable prototype schema.
            connection.executescript(
                """
                DROP TABLE IF EXISTS chunks_fts;
                DROP TABLE IF EXISTS chunks;
                DROP TABLE IF EXISTS sources;
                """
            )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                canonical_uri TEXT NOT NULL,
                active_version_id TEXT,
                FOREIGN KEY(source_id) REFERENCES sources(source_id)
            );
            CREATE TABLE IF NOT EXISTS document_versions (
                version_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                raw_digest TEXT NOT NULL,
                normalized_digest TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                active INTEGER NOT NULL,
                PRIMARY KEY(document_id, version_id),
                FOREIGN KEY(document_id) REFERENCES documents(document_id)
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                section TEXT NOT NULL,
                locator TEXT NOT NULL,
                logical_position TEXT NOT NULL,
                text TEXT NOT NULL,
                content_digest TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                recommendation_allowed INTEGER NOT NULL,
                metadata_json TEXT NOT NULL,
                active INTEGER NOT NULL,
                FOREIGN KEY(source_id) REFERENCES sources(source_id),
                FOREIGN KEY(document_id) REFERENCES documents(document_id)
            );
            CREATE TABLE IF NOT EXISTS embeddings (
                content_digest TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding BLOB NOT NULL,
                PRIMARY KEY(content_digest, embedding_model)
            );
            CREATE TABLE IF NOT EXISTS chunk_metric_codes (
                chunk_id TEXT NOT NULL,
                metric_code TEXT NOT NULL,
                PRIMARY KEY(chunk_id, metric_code),
                FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chunk_populations (
                chunk_id TEXT NOT NULL,
                population TEXT NOT NULL,
                PRIMARY KEY(chunk_id, population),
                FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chunk_support_types (
                chunk_id TEXT NOT NULL,
                support_type TEXT NOT NULL,
                PRIMARY KEY(chunk_id, support_type),
                FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS ingestion_runs (
                ingestion_run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                chunk_count INTEGER NOT NULL,
                embedded_count INTEGER NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                text,
                tokenize='trigram'
            );
            """
        )
        connection.execute(f"PRAGMA user_version = {STORE_SCHEMA_VERSION}")

    def build(self, embedder: LocalEmbeddingModel) -> int:
        """Upsert the current snapshot and embed only unseen content digests."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        catalog = {source.source_id: source for source in load_catalog()}
        raw_chunks = load_chunk_snapshot(self.path.parent)
        chunks = self._normalize_snapshot(raw_chunks)
        now = datetime.now(timezone.utc).isoformat()
        run_id = hashlib.sha256(f"{now}:{self.path}".encode()).hexdigest()[:24]
        embedded_count = 0
        with self.connect() as connection:
            self._ensure_schema(connection)
            connection.execute(
                "INSERT INTO ingestion_runs VALUES (?, ?, NULL, 'running', ?, 0)",
                (run_id, now, len(chunks)),
            )
            for source in catalog.values():
                if source.ingest_policy == "full_text":
                    connection.execute(
                        "INSERT INTO sources VALUES (?, ?) ON CONFLICT(source_id) "
                        "DO UPDATE SET payload_json=excluded.payload_json",
                        (source.source_id, source.model_dump_json()),
                    )

            missing_digests = self._missing_embedding_digests(connection, chunks)
            if missing_digests:
                text_by_digest = {chunk.content_digest: chunk.text for chunk in chunks}
                vectors = embedder.embed_passages(
                    [text_by_digest[digest] for digest in missing_digests]
                )
                if len(vectors) != len(missing_digests):
                    raise ValueError("embedding count does not match missing chunk count")
                connection.executemany(
                    "INSERT INTO embeddings VALUES (?, ?, ?)",
                    [
                        (
                            digest,
                            MODEL_VERSION,
                            np.asarray(vector, dtype=np.float32).tobytes(),
                        )
                        for digest, vector in zip(missing_digests, vectors, strict=True)
                    ],
                )
                embedded_count = len(missing_digests)

            by_document: dict[str, list[KnowledgeChunk]] = {}
            for chunk in chunks:
                by_document.setdefault(chunk.document_id, []).append(chunk)
            for document_id, document_chunks in by_document.items():
                first = document_chunks[0]
                source = catalog[first.source_id]
                version_id = first.version_id
                normalized_digest = hashlib.sha256(
                    "".join(sorted(item.content_digest for item in document_chunks)).encode()
                ).hexdigest()
                connection.execute(
                    "INSERT INTO documents VALUES (?, ?, ?, ?) ON CONFLICT(document_id) "
                    "DO UPDATE SET source_id=excluded.source_id, canonical_uri=excluded.canonical_uri",
                    (document_id, source.source_id, source.url, version_id),
                )
                connection.execute(
                    "UPDATE document_versions SET active=0 WHERE document_id=?",
                    (document_id,),
                )
                connection.execute(
                    "INSERT INTO document_versions VALUES (?, ?, ?, ?, ?, ?, 1) "
                    "ON CONFLICT(document_id, version_id) DO UPDATE SET active=1",
                    (
                        version_id,
                        document_id,
                        normalized_digest,
                        normalized_digest,
                        "snapshot-parser/1.0",
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE documents SET active_version_id=? WHERE document_id=?",
                    (version_id, document_id),
                )
                connection.execute(
                    "UPDATE chunks SET active=0 WHERE document_id=?",
                    (document_id,),
                )

            for chunk in chunks:
                self._upsert_chunk(connection, chunk)

            connection.execute(
                "UPDATE ingestion_runs SET completed_at=?, status='completed', embedded_count=? "
                "WHERE ingestion_run_id=?",
                (datetime.now(timezone.utc).isoformat(), embedded_count, run_id),
            )
        self.last_build_stats = {
            "chunk_count": len(chunks),
            "embedded_count": embedded_count,
            "reused_embedding_count": len(chunks) - embedded_count,
        }
        return len(chunks)

    def _normalize_snapshot(
        self, chunks: tuple[KnowledgeChunk, ...]
    ) -> tuple[KnowledgeChunk, ...]:
        by_source: dict[str, list[KnowledgeChunk]] = {}
        for chunk in chunks:
            by_source.setdefault(chunk.source_id, []).append(chunk)
        result = []
        for source_id, source_chunks in by_source.items():
            version_id = hashlib.sha256(
                "".join(sorted(item.content_digest for item in source_chunks)).encode()
            ).hexdigest()
            for index, chunk in enumerate(source_chunks):
                result.append(
                    chunk.model_copy(
                        update={
                            "document_id": chunk.document_id or source_id,
                            "version_id": chunk.version_id or version_id,
                            "logical_position": chunk.logical_position
                            or f"{chunk.domain}/{chunk.section.casefold()}/{index:04d}",
                        }
                    )
                )
        return tuple(result)

    def _missing_embedding_digests(self, connection, chunks):
        digests = sorted({chunk.content_digest for chunk in chunks})
        if not digests:
            return []
        placeholders = ",".join("?" for _ in digests)
        existing = {
            row[0]
            for row in connection.execute(
                f"SELECT content_digest FROM embeddings WHERE embedding_model=? "
                f"AND content_digest IN ({placeholders})",
                (MODEL_VERSION, *digests),
            )
        }
        return [digest for digest in digests if digest not in existing]

    def _upsert_chunk(self, connection, chunk: KnowledgeChunk) -> None:
        existed = connection.execute(
            "SELECT text FROM chunks WHERE chunk_id=?", (chunk.chunk_id,)
        ).fetchone()
        connection.execute(
            """INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(chunk_id) DO UPDATE SET
                 source_id=excluded.source_id, document_id=excluded.document_id,
                 version_id=excluded.version_id, domain=excluded.domain,
                 section=excluded.section, locator=excluded.locator,
                 logical_position=excluded.logical_position, text=excluded.text,
                 content_digest=excluded.content_digest, token_count=excluded.token_count,
                 recommendation_allowed=excluded.recommendation_allowed,
                 metadata_json=excluded.metadata_json, active=1""",
            (
                chunk.chunk_id,
                chunk.source_id,
                chunk.document_id,
                chunk.version_id,
                chunk.domain,
                chunk.section,
                chunk.locator,
                chunk.logical_position,
                chunk.text,
                chunk.content_digest,
                chunk.token_count,
                int(chunk.recommendation_allowed),
                json.dumps(chunk.metadata, ensure_ascii=False, sort_keys=True),
            ),
        )
        for table in ("chunk_metric_codes", "chunk_populations", "chunk_support_types"):
            connection.execute(f"DELETE FROM {table} WHERE chunk_id=?", (chunk.chunk_id,))
        connection.executemany(
            "INSERT INTO chunk_metric_codes VALUES (?, ?)",
            [(chunk.chunk_id, item) for item in chunk.metric_codes],
        )
        connection.executemany(
            "INSERT INTO chunk_populations VALUES (?, ?)",
            [(chunk.chunk_id, item) for item in chunk.populations],
        )
        connection.executemany(
            "INSERT INTO chunk_support_types VALUES (?, ?)",
            [(chunk.chunk_id, item) for item in chunk.support_types],
        )
        if existed is None or existed["text"] != chunk.text:
            connection.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (chunk.chunk_id,))
            connection.execute(
                "INSERT INTO chunks_fts(chunk_id, text) VALUES (?, ?)",
                (chunk.chunk_id, chunk.text),
            )

    def load_all(
        self,
        domain: str | None = None,
        *,
        spec: KnowledgeQuerySpec | None = None,
    ):
        where, params = self._filters(domain=domain, spec=spec)
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT c.*, s.payload_json, e.embedding,
                    (SELECT group_concat(metric_code, char(31)) FROM chunk_metric_codes m
                     WHERE m.chunk_id=c.chunk_id) AS metric_codes,
                    (SELECT group_concat(population, char(31)) FROM chunk_populations p
                     WHERE p.chunk_id=c.chunk_id) AS populations,
                    (SELECT group_concat(support_type, char(31)) FROM chunk_support_types t
                     WHERE t.chunk_id=c.chunk_id) AS support_types
                    FROM chunks c
                    JOIN sources s USING(source_id)
                    JOIN embeddings e ON e.content_digest=c.content_digest
                       AND e.embedding_model=?
                    WHERE c.active=1 {where}
                    ORDER BY c.chunk_id""",
                (MODEL_VERSION, *params),
            ).fetchall()
        return tuple(self._decode_row(row) for row in rows)

    def lexical_search(
        self,
        query: str,
        limit: int,
        domain: str | None = None,
        *,
        spec: KnowledgeQuerySpec | None = None,
    ):
        tokens = [item for item in query.replace('"', " ").split() if len(item) >= 3]
        if not tokens:
            tokens = [query.strip()]
        match = " OR ".join(f'"{token}"' for token in tokens)
        where, filter_params = self._filters(domain=domain, spec=spec)
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT c.*, s.payload_json, e.embedding,
                           bm25(chunks_fts) AS lexical_score
                    ,(SELECT group_concat(metric_code, char(31)) FROM chunk_metric_codes m
                      WHERE m.chunk_id=c.chunk_id) AS metric_codes
                    ,(SELECT group_concat(population, char(31)) FROM chunk_populations p
                      WHERE p.chunk_id=c.chunk_id) AS populations
                    ,(SELECT group_concat(support_type, char(31)) FROM chunk_support_types t
                      WHERE t.chunk_id=c.chunk_id) AS support_types
                    FROM chunks_fts
                    JOIN chunks c ON c.chunk_id=chunks_fts.chunk_id
                    JOIN sources s ON s.source_id=c.source_id
                    JOIN embeddings e ON e.content_digest=c.content_digest
                       AND e.embedding_model=?
                    WHERE chunks_fts MATCH ? AND c.active=1 {where}
                    ORDER BY lexical_score LIMIT ?""",
                (MODEL_VERSION, match, *filter_params, limit),
            ).fetchall()
        return tuple(self._decode_row(row) for row in rows)

    def _filters(self, *, domain=None, spec=None):
        clauses = []
        params: list[object] = []
        resolved_domain = spec.domain if spec else domain
        if resolved_domain:
            clauses.append("c.domain=?")
            params.append(resolved_domain)
        if spec:
            if spec.protocols:
                placeholders = ",".join("?" for _ in spec.protocols)
                clauses.append(f"json_extract(c.metadata_json, '$.protocol') IN ({placeholders})")
                params.extend(spec.protocols)
            if spec.metric_codes:
                placeholders = ",".join("?" for _ in spec.metric_codes)
                clauses.append(
                    "EXISTS (SELECT 1 FROM chunk_metric_codes m WHERE m.chunk_id=c.chunk_id "
                    f"AND m.metric_code IN ({placeholders}))"
                )
                params.extend(spec.metric_codes)
            clauses.append(
                "EXISTS (SELECT 1 FROM chunk_populations p WHERE p.chunk_id=c.chunk_id "
                "AND p.population=?)"
            )
            params.append(spec.population)
            placeholders = ",".join("?" for _ in spec.support_types)
            clauses.append(
                "EXISTS (SELECT 1 FROM chunk_support_types t WHERE t.chunk_id=c.chunk_id "
                f"AND t.support_type IN ({placeholders}))"
            )
            params.extend(spec.support_types)
            clauses.append("c.recommendation_allowed=?")
            params.append(int(spec.recommendation_allowed))
        return (" AND " + " AND ".join(clauses) if clauses else ""), params

    @staticmethod
    def _decode_row(row):
        chunk = KnowledgeChunk(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            document_id=row["document_id"],
            version_id=row["version_id"],
            domain=row["domain"],
            section=row["section"],
            locator=row["locator"],
            logical_position=row["logical_position"],
            text=row["text"],
            content_digest=row["content_digest"],
            token_count=row["token_count"],
            metric_codes=tuple((row["metric_codes"] or "").split("\x1f"))
            if row["metric_codes"]
            else (),
            populations=tuple((row["populations"] or "general").split("\x1f")),
            support_types=tuple((row["support_types"] or "background").split("\x1f")),
            recommendation_allowed=bool(row["recommendation_allowed"]),
            metadata=json.loads(row["metadata_json"]),
        )
        source = KnowledgeSource.model_validate_json(row["payload_json"])
        vector = np.frombuffer(row["embedding"], dtype=np.float32).copy()
        return chunk, source, vector
