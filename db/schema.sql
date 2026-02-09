PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  layer TEXT NOT NULL CHECK (layer IN ('instant', 'short', 'long', 'archive')),
  kind TEXT NOT NULL CHECK (kind IN ('note', 'decision', 'task', 'checkpoint', 'summary', 'evidence', 'retrieve')),
  summary TEXT NOT NULL,
  body_md_path TEXT NOT NULL,
  body_text TEXT NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL DEFAULT '[]',
  importance_score REAL NOT NULL DEFAULT 0.5 CHECK (importance_score >= 0 AND importance_score <= 1),
  confidence_score REAL NOT NULL DEFAULT 0.5 CHECK (confidence_score >= 0 AND confidence_score <= 1),
  stability_score REAL NOT NULL DEFAULT 0.5 CHECK (stability_score >= 0 AND stability_score <= 1),
  reuse_count INTEGER NOT NULL DEFAULT 0 CHECK (reuse_count >= 0),
  volatility_score REAL NOT NULL DEFAULT 0.5 CHECK (volatility_score >= 0 AND volatility_score <= 1),
  cred_refs_json TEXT NOT NULL DEFAULT '[]',
  source_json TEXT NOT NULL,
  scope_json TEXT NOT NULL,
  integrity_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_layer ON memories(layer);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance_score);
CREATE INDEX IF NOT EXISTS idx_memories_reuse_count ON memories(reuse_count);

CREATE TABLE IF NOT EXISTS memory_refs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id TEXT NOT NULL,
  ref_type TEXT NOT NULL,
  target TEXT NOT NULL,
  note TEXT,
  FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_refs_memory_id ON memory_refs(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_refs_target ON memory_refs(target);

CREATE TABLE IF NOT EXISTS memory_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  event_time TEXT NOT NULL,
  memory_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_events_type_time ON memory_events(event_type, event_time);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  id UNINDEXED,
  summary,
  body_text,
  tags,
  tokenize = 'unicode61'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories
BEGIN
  INSERT INTO memories_fts(id, summary, body_text, tags)
  VALUES (new.id, new.summary, new.body_text, new.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories
BEGIN
  DELETE FROM memories_fts WHERE id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories
BEGIN
  DELETE FROM memories_fts WHERE id = old.id;
  INSERT INTO memories_fts(id, summary, body_text, tags)
  VALUES (new.id, new.summary, new.body_text, new.tags_json);
END;
