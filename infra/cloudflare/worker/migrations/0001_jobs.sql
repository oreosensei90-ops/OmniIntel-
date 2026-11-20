CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL CHECK (job_type IN ('YOUTUBE_TO_NOTES', 'UPLOADED_MEDIA_TO_NOTES')),
  state TEXT NOT NULL CHECK (state IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED')),
  payload_json TEXT NOT NULL,
  input_key TEXT,
  result_key TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 2,
  lease_token TEXT,
  lease_expires_at INTEGER,
  last_error TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(state, created_at, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated_at);
