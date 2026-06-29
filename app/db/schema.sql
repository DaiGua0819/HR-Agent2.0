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
  parsed_name TEXT,
  linked_session_id TEXT,
  linked_platform TEXT,
  linked_owner TEXT,
  linked_platform_conversation_id TEXT,
  source_artifact_id TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resumes_phone_key ON resumes(phone_key);
CREATE INDEX IF NOT EXISTS idx_resumes_job_score
  ON resumes(job_type, match_score DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_resumes_linked_session
  ON resumes(linked_session_id);
CREATE INDEX IF NOT EXISTS idx_resumes_source_artifact
  ON resumes(source_artifact_id);

CREATE TABLE IF NOT EXISTS conversation_sessions (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  owner TEXT NOT NULL,
  candidate_name TEXT NOT NULL DEFAULT '',
  position TEXT NOT NULL DEFAULT '',
  applied_position TEXT NOT NULL DEFAULT '',
  platform_conversation_id TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL DEFAULT '',
  current_stage TEXT NOT NULL DEFAULT '',
  next_action TEXT NOT NULL DEFAULT '',
  recent_messages_fingerprint TEXT NOT NULL DEFAULT '',
  identity_confidence TEXT NOT NULL DEFAULT '',
  identity_warnings TEXT NOT NULL DEFAULT '[]',
  last_seen_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_sessions_platform_identity
  ON conversation_sessions(platform, owner, platform_conversation_id, position)
  WHERE platform_conversation_id <> '';
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_candidate
  ON conversation_sessions(platform, owner, candidate_name, position);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_updated
  ON conversation_sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  sender TEXT NOT NULL,
  text TEXT NOT NULL,
  raw_text TEXT NOT NULL DEFAULT '',
  sent_at TEXT NOT NULL DEFAULT '',
  platform_message_id TEXT NOT NULL DEFAULT '',
  message_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_messages_hash
  ON conversation_messages(session_id, message_hash);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_session
  ON conversation_messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS candidate_status (
  session_id TEXT PRIMARY KEY,
  asked_questions TEXT NOT NULL DEFAULT '[]',
  resume_requested INTEGER NOT NULL DEFAULT 0,
  resume_received INTEGER NOT NULL DEFAULT 0,
  resume_downloaded INTEGER NOT NULL DEFAULT 0,
  resume_path TEXT NOT NULL DEFAULT '',
  last_action TEXT NOT NULL DEFAULT '',
  next_question TEXT NOT NULL DEFAULT '',
  decided_result TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS resume_artifacts (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  owner TEXT NOT NULL,
  platform_conversation_id TEXT NOT NULL DEFAULT '',
  candidate_name_from_platform TEXT NOT NULL DEFAULT '',
  position TEXT NOT NULL DEFAULT '',
  file_path TEXT NOT NULL,
  file_hash TEXT NOT NULL,
  source_kind TEXT NOT NULL DEFAULT '',
  parse_status TEXT NOT NULL DEFAULT 'pending',
  parsed_name TEXT NOT NULL DEFAULT '',
  resume_id TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_resume_artifacts_session_hash
  ON resume_artifacts(session_id, file_hash);
CREATE INDEX IF NOT EXISTS idx_resume_artifacts_status
  ON resume_artifacts(parse_status, created_at);
CREATE INDEX IF NOT EXISTS idx_resume_artifacts_resume
  ON resume_artifacts(resume_id);

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
