BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_ai_review_events

CREATE TABLE ai_reject_reason (
    code VARCHAR(32) NOT NULL, 
    label_zh VARCHAR(64) NOT NULL, 
    label_en VARCHAR(64) NOT NULL, 
    requires_note BOOLEAN DEFAULT false NOT NULL, 
    sort_order INTEGER NOT NULL, 
    active BOOLEAN DEFAULT true NOT NULL, 
    id UUID NOT NULL, 
    org_id UUID NOT NULL, 
    site_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    created_by UUID, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_ai_reject_reason PRIMARY KEY (id), 
    CONSTRAINT uq_ai_reject_reason_org_code UNIQUE (org_id, code), 
    CONSTRAINT ck_ai_reject_reason_sort_order_non_negative CHECK (sort_order >= 0)
);

CREATE TABLE ai_review_event (
    id UUID NOT NULL, 
    org_id UUID NOT NULL, 
    site_id UUID, 
    event_type VARCHAR(32) NOT NULL, 
    tool VARCHAR(64), 
    scenario VARCHAR(64), 
    draft_id UUID NOT NULL, 
    prompt_version VARCHAR(64), 
    model_profile VARCHAR(64), 
    output_chars INTEGER, 
    structured_field_count INTEGER, 
    action VARCHAR(32), 
    final_ref VARCHAR(512), 
    final_hash VARCHAR(64), 
    reviewer_id UUID, 
    review_seconds INTEGER, 
    reject_reason_code VARCHAR(32), 
    reject_reason_note VARCHAR(500), 
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    created_by UUID, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_ai_review_event PRIMARY KEY (id), 
    CONSTRAINT ck_ai_review_event_event_type CHECK (event_type IN ('ai_draft_created','review_opened','review_submitted','draft_expired')), 
    CONSTRAINT ck_ai_review_event_action CHECK (action IS NULL OR action IN ('adopted_as_is','adopted_with_edits','rejected')), 
    CONSTRAINT ck_ai_review_event_reject_reason_code CHECK (reject_reason_code IS NULL OR reject_reason_code IN ('factual_error','off_tone','missing_info','policy_violation','duplicate','not_needed','other')), 
    CONSTRAINT ck_ai_review_event_draft_created_fields CHECK (event_type <> 'ai_draft_created' OR (tool IS NOT NULL AND scenario IS NOT NULL AND prompt_version IS NOT NULL AND output_chars IS NOT NULL AND structured_field_count IS NOT NULL)), 
    CONSTRAINT ck_ai_review_event_review_opened_fields CHECK (event_type <> 'review_opened' OR reviewer_id IS NOT NULL), 
    CONSTRAINT ck_ai_review_event_review_submitted_fields CHECK (event_type <> 'review_submitted' OR (action IS NOT NULL AND reviewer_id IS NOT NULL AND final_ref IS NOT NULL AND final_hash IS NOT NULL AND review_seconds IS NOT NULL)), 
    CONSTRAINT ck_ai_review_event_rejected_requires_reason CHECK (event_type <> 'review_submitted' OR ((action = 'rejected' AND reject_reason_code IS NOT NULL) OR (action <> 'rejected' AND reject_reason_code IS NULL))), 
    CONSTRAINT ck_ai_review_event_other_requires_note CHECK (reject_reason_code IS NULL OR reject_reason_code <> 'other' OR (reject_reason_note IS NOT NULL AND length(trim(reject_reason_note)) > 0)), 
    CONSTRAINT ck_ai_review_event_note_only_for_other CHECK (reject_reason_code = 'other' OR reject_reason_note IS NULL), 
    CONSTRAINT ck_ai_review_event_draft_created_no_review_fields CHECK (event_type <> 'ai_draft_created' OR (action IS NULL AND final_ref IS NULL AND final_hash IS NULL AND reviewer_id IS NULL AND review_seconds IS NULL AND reject_reason_code IS NULL AND reject_reason_note IS NULL)), 
    CONSTRAINT ck_ai_review_event_review_opened_no_result_fields CHECK (event_type <> 'review_opened' OR (action IS NULL AND final_ref IS NULL AND final_hash IS NULL AND review_seconds IS NULL AND reject_reason_code IS NULL AND reject_reason_note IS NULL)), 
    CONSTRAINT ck_ai_review_event_review_submitted_no_draft_fields CHECK (event_type <> 'review_submitted' OR (tool IS NULL AND scenario IS NULL AND prompt_version IS NULL AND model_profile IS NULL AND output_chars IS NULL AND structured_field_count IS NULL)), 
    CONSTRAINT ck_ai_review_event_expired_no_extra_fields CHECK (event_type <> 'draft_expired' OR (tool IS NULL AND scenario IS NULL AND prompt_version IS NULL AND model_profile IS NULL AND output_chars IS NULL AND structured_field_count IS NULL AND action IS NULL AND final_ref IS NULL AND final_hash IS NULL AND reviewer_id IS NULL AND review_seconds IS NULL AND reject_reason_code IS NULL AND reject_reason_note IS NULL)), 
    CONSTRAINT ck_ai_review_event_final_hash_length CHECK (final_hash IS NULL OR length(final_hash) = 64), 
    CONSTRAINT ck_ai_review_event_review_seconds_range CHECK (review_seconds IS NULL OR (review_seconds >= 0 AND review_seconds <= 86400)), 
    CONSTRAINT ck_ai_review_event_output_chars_non_negative CHECK (output_chars IS NULL OR output_chars >= 0), 
    CONSTRAINT ck_ai_review_event_structured_fields_non_negative CHECK (structured_field_count IS NULL OR structured_field_count >= 0)
);

CREATE INDEX ix_ai_review_event_org_type_time ON ai_review_event (org_id, event_type, occurred_at);

CREATE INDEX ix_ai_review_event_org_draft_time ON ai_review_event (org_id, draft_id, occurred_at);

CREATE UNIQUE INDEX uq_ai_review_event_draft_created ON ai_review_event (org_id, draft_id) WHERE event_type = 'ai_draft_created' AND deleted_at IS NULL;

CREATE UNIQUE INDEX uq_ai_review_event_draft_terminal ON ai_review_event (org_id, draft_id) WHERE event_type IN ('review_submitted','draft_expired') AND deleted_at IS NULL;

INSERT INTO ai_reject_reason (id, org_id, code, label_zh, label_en, requires_note, sort_order, active) VALUES ('00000000-0000-0000-0000-0000006ad3a9', '00000000-0000-0000-0000-000000000000', 'factual_error', '事实错误', 'Factual error', false, 10, true);

INSERT INTO ai_reject_reason (id, org_id, code, label_zh, label_en, requires_note, sort_order, active) VALUES ('00000000-0000-0000-0000-0000006ad3aa', '00000000-0000-0000-0000-000000000000', 'off_tone', '语气不符', 'Off tone', false, 20, true);

INSERT INTO ai_reject_reason (id, org_id, code, label_zh, label_en, requires_note, sort_order, active) VALUES ('00000000-0000-0000-0000-0000006ad3ab', '00000000-0000-0000-0000-000000000000', 'missing_info', '信息缺失', 'Missing information', false, 30, true);

INSERT INTO ai_reject_reason (id, org_id, code, label_zh, label_en, requires_note, sort_order, active) VALUES ('00000000-0000-0000-0000-0000006ad3ac', '00000000-0000-0000-0000-000000000000', 'policy_violation', '违反规范', 'Policy violation', false, 40, true);

INSERT INTO ai_reject_reason (id, org_id, code, label_zh, label_en, requires_note, sort_order, active) VALUES ('00000000-0000-0000-0000-0000006ad3ad', '00000000-0000-0000-0000-000000000000', 'duplicate', '重复', 'Duplicate', false, 50, true);

INSERT INTO ai_reject_reason (id, org_id, code, label_zh, label_en, requires_note, sort_order, active) VALUES ('00000000-0000-0000-0000-0000006ad3ae', '00000000-0000-0000-0000-000000000000', 'not_needed', '不需要', 'Not needed', false, 60, true);

INSERT INTO ai_reject_reason (id, org_id, code, label_zh, label_en, requires_note, sort_order, active) VALUES ('00000000-0000-0000-0000-0000006ad3af', '00000000-0000-0000-0000-000000000000', 'other', '其他', 'Other', true, 70, true);

INSERT INTO alembic_version (version_num) VALUES ('0001_ai_review_events') RETURNING alembic_version.version_num;

COMMIT;

