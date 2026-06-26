PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resumes (
  id TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  phone_key TEXT,
  job_type TEXT,
  match_score INTEGER,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resumes_phone_key ON resumes(phone_key);
CREATE INDEX IF NOT EXISTS idx_resumes_job_score
  ON resumes(job_type, match_score DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS rule_suggestions (
  id TEXT PRIMARY KEY,
  resume_id TEXT NOT NULL,
  job_type TEXT,
  suggestion TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  source_summary TEXT,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  adopted_at TEXT,
  rejected_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rule_suggestions_status
  ON rule_suggestions(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rule_suggestions_job_status
  ON rule_suggestions(job_type, status, created_at DESC);

CREATE TABLE IF NOT EXISTS batch_jobs (
  id TEXT PRIMARY KEY,
  parse_mode TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_items (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  file_path TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  message TEXT,
  resume_id TEXT,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(job_id) REFERENCES batch_jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_batch_items_job ON batch_items(job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_batch_items_status ON batch_items(job_id, status);

CREATE TABLE IF NOT EXISTS decision_logs (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  owner TEXT,
  platform TEXT,
  conversation_id TEXT,
  dry_run INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decision_logs_created_at
  ON decision_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_logs_platform
  ON decision_logs(platform, created_at DESC);

CREATE TABLE IF NOT EXISTS batch_reports (
  id TEXT PRIMARY KEY,
  report_type TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS question_logs (
  id TEXT PRIMARY KEY,
  question TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interview_sessions (
  id TEXT PRIMARY KEY,
  resume_id TEXT NOT NULL,
  candidate_name TEXT,
  job_type TEXT,
  status TEXT NOT NULL,
  questions TEXT NOT NULL,
  matches TEXT NOT NULL,
  bitable_record_id TEXT,
  resume_image_path TEXT,
  summary_image_path TEXT,
  feedback TEXT,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_interview_sessions_resume
  ON interview_sessions(resume_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_interview_sessions_status
  ON interview_sessions(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
  thread_id TEXT NOT NULL,
  checkpoint_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(thread_id, checkpoint_id)
);
