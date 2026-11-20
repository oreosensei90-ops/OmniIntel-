ALTER TABLE jobs ADD COLUMN available_at INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_jobs_available ON jobs(state, available_at, created_at);
