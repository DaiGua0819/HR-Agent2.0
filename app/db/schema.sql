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
CREATE INDEX IF NOT EXISTS idx_resumes_updated
  ON resumes(updated_at, id);

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
CREATE INDEX IF NOT EXISTS idx_conversation_messages_created
  ON conversation_messages(created_at, id);

CREATE TABLE IF NOT EXISTS sync_receipts (
  batch_id TEXT PRIMARY KEY,
  body_hash TEXT NOT NULL,
  source TEXT NOT NULL,
  result TEXT NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sync_receipts_applied
  ON sync_receipts(applied_at DESC);

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
  feishu_event_id TEXT,
  calendar_id TEXT,
  resume_id TEXT NOT NULL,
  candidate_name TEXT,
  job_type TEXT,
  status TEXT NOT NULL,
  start_time INTEGER NOT NULL DEFAULT 0,
  end_time INTEGER NOT NULL DEFAULT 0,
  questions TEXT NOT NULL,
  question_set TEXT NOT NULL DEFAULT '{}',
  matches TEXT NOT NULL,
  feishu_doc TEXT NOT NULL DEFAULT '{}',
  bitable_record_id TEXT,
  bitable_table_id TEXT,
  bitable_table_name TEXT,
  bitable_resume_image TEXT NOT NULL DEFAULT '{}',
  bitable_interview_record_image TEXT NOT NULL DEFAULT '{}',
  bitable_skill_evaluation_document TEXT NOT NULL DEFAULT '{}',
  bitable_second_interview_evaluation_document TEXT NOT NULL DEFAULT '{}',
  resume_image_path TEXT,
  summary_image_path TEXT,
  feedback TEXT,
  interview_evaluation TEXT NOT NULL DEFAULT '{}',
  backfill_source TEXT NOT NULL DEFAULT '{}',
  rule_suggestion_ids TEXT NOT NULL DEFAULT '[]',
  last_backfill_error TEXT,
  backfill_attempts INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_interview_sessions_feishu_event
  ON interview_sessions(feishu_event_id)
  WHERE feishu_event_id IS NOT NULL AND feishu_event_id != '';
CREATE INDEX IF NOT EXISTS idx_interview_sessions_resume
  ON interview_sessions(resume_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_interview_sessions_status
  ON interview_sessions(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_interview_sessions_calendar_time
  ON interview_sessions(calendar_id, start_time);

CREATE TABLE IF NOT EXISTS interview_feishu_tokens (
  id TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interview_logs (
  id TEXT PRIMARY KEY,
  session_id TEXT,
  level TEXT NOT NULL,
  message TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_interview_logs_session
  ON interview_logs(session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS resume_review_states (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  user_name TEXT NOT NULL DEFAULT '',
  resume_id TEXT NOT NULL,
  read_status TEXT NOT NULL DEFAULT 'unread',
  decision TEXT NOT NULL DEFAULT 'undecided',
  reason_tags TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  assigned_to TEXT NOT NULL DEFAULT '',
  viewed_at TEXT NOT NULL DEFAULT '',
  decision_at TEXT NOT NULL DEFAULT '',
  pushed_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, resume_id)
);

CREATE INDEX IF NOT EXISTS idx_resume_review_states_user
  ON resume_review_states(user_id, read_status, decision, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_resume_review_states_resume
  ON resume_review_states(resume_id);

CREATE TABLE IF NOT EXISTS resume_review_events (
  id TEXT PRIMARY KEY,
  resume_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  before_json TEXT NOT NULL DEFAULT '{}',
  after_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resume_review_events_resume
  ON resume_review_events(resume_id, created_at DESC);

CREATE TABLE IF NOT EXISTS resume_assignments (
  id TEXT PRIMARY KEY,
  resume_id TEXT NOT NULL,
  from_user_id TEXT NOT NULL,
  assigned_to_user_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  completion_action TEXT NOT NULL DEFAULT '',
  source_decision_id TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  completed_by_user_id TEXT NOT NULL DEFAULT '',
  completed_by_user_name TEXT NOT NULL DEFAULT '',
  completed_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resume_assignments_user
  ON resume_assignments(assigned_to_user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_resume_assignments_resume
  ON resume_assignments(resume_id, status);

CREATE TABLE IF NOT EXISTS resume_saved_views (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  filters_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resume_saved_views_user
  ON resume_saved_views(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
  thread_id TEXT NOT NULL,
  checkpoint_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(thread_id, checkpoint_id)
);
