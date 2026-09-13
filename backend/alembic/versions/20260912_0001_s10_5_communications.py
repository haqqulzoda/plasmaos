"""Add the communications domain and committed lifecycle publication intents.

Revision ID: 20260912_0001_s10_5_communications
Revises: 20260904_0001_s8_2_analysis_language
"""

from alembic import op

revision = "20260912_0001_s10_5_communications"
down_revision = "20260904_0001_s8_2_analysis_language"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE broadcasts (
	id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	subject VARCHAR(200) NOT NULL,
	body TEXT NOT NULL,
	message_type VARCHAR(24) NOT NULL,
	audience_mode VARCHAR(24) NOT NULL,
	selected_user_ids JSONB DEFAULT '[]'::jsonb NOT NULL,
	status VARCHAR(16) DEFAULT 'DRAFT' NOT NULL,
	recipient_count INTEGER DEFAULT '0' NOT NULL,
	delivered_count INTEGER DEFAULT '0' NOT NULL,
	failed_count INTEGER DEFAULT '0' NOT NULL,
	retry_count INTEGER DEFAULT '0' NOT NULL,
	last_error_code VARCHAR(64),
	next_dispatch_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	queued_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT ck_broadcast_status CHECK (status IN ('DRAFT','QUEUED','SENDING','SENT','PARTIAL','FAILED')),
	CONSTRAINT ck_broadcast_message_type CHECK (message_type IN ('ANNOUNCEMENT','SYSTEM_ALERT')),
	CONSTRAINT ck_broadcast_audience CHECK (audience_mode IN ('ALL_ELIGIBLE_USERS','SELECTED_USERS')),
	CONSTRAINT ck_broadcast_content_size CHECK (length(subject) BETWEEN 1 AND 200 AND length(body) BETWEEN 1 AND 5000),
	CONSTRAINT ck_broadcast_selected_size CHECK (jsonb_typeof(selected_user_ids) = 'array' AND jsonb_array_length(selected_user_ids) <= 1000),
	CONSTRAINT ck_broadcast_counts CHECK (recipient_count >= 0 AND delivered_count >= 0 AND failed_count >= 0 AND delivered_count + failed_count <= recipient_count AND retry_count >= 0),
	FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE RESTRICT
)
""")
    op.execute("""
CREATE INDEX ix_broadcast_created ON broadcasts (created_at DESC, id DESC)
""")
    op.execute("""
CREATE INDEX ix_broadcast_dispatch ON broadcasts (next_dispatch_at) WHERE status IN ('QUEUED','SENDING')
""")
    op.execute("""
CREATE TABLE notification_events (
	id UUID NOT NULL,
	dedupe_key VARCHAR(200) NOT NULL,
	event_type VARCHAR(64) NOT NULL,
	category VARCHAR(24) NOT NULL,
	template_key VARCHAR(100),
	payload JSONB DEFAULT '{}'::jsonb NOT NULL,
	broadcast_id UUID,
	subject VARCHAR(200),
	body TEXT,
	message_type VARCHAR(24),
	is_test BOOLEAN DEFAULT false NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_notification_event_category UNIQUE (id, category),
	CONSTRAINT ck_notification_category CHECK (category IN ('SYSTEM','TENDER_ALERT','ADMIN')),
	CONSTRAINT ck_notification_payload_size CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 4096),
	CONSTRAINT ck_notification_content_authority CHECK ((broadcast_id IS NULL AND template_key IS NOT NULL AND subject IS NULL AND body IS NULL AND message_type IS NULL AND NOT is_test) OR (broadcast_id IS NOT NULL AND category = 'ADMIN' AND template_key IS NULL AND subject IS NOT NULL AND length(subject) BETWEEN 1 AND 200 AND body IS NOT NULL AND length(body) BETWEEN 1 AND 5000 AND message_type IN ('ANNOUNCEMENT','SYSTEM_ALERT'))),
	UNIQUE (dedupe_key),
	FOREIGN KEY(broadcast_id) REFERENCES broadcasts (id) ON DELETE RESTRICT
)
""")
    op.execute("""
CREATE TABLE notification_deliveries (
	id UUID NOT NULL,
	user_id UUID NOT NULL,
	event_id UUID NOT NULL,
	category VARCHAR(24) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	read_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_notification_delivery_user_event UNIQUE (user_id, event_id),
	CONSTRAINT fk_delivery_event_category FOREIGN KEY(event_id, category) REFERENCES notification_events (id, category) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE INDEX ix_notification_category_inbox ON notification_deliveries (user_id, category, created_at DESC, id DESC)
""")
    op.execute("""
CREATE INDEX ix_notification_inbox ON notification_deliveries (user_id, created_at DESC, id DESC)
""")
    op.execute("""
CREATE INDEX ix_notification_unread ON notification_deliveries (user_id, category, created_at DESC, id DESC) WHERE read_at IS NULL
""")
    op.execute("""
CREATE INDEX ix_notification_unread_count ON notification_deliveries (user_id) WHERE read_at IS NULL
""")
    op.execute("""
CREATE TABLE broadcast_recipients (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	broadcast_id UUID NOT NULL,
	user_id UUID NOT NULL,
	status VARCHAR(16) DEFAULT 'PENDING' NOT NULL,
	error_code VARCHAR(64),
	delivered_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_broadcast_recipient_user UNIQUE (broadcast_id, user_id),
	CONSTRAINT ck_broadcast_recipient_status CHECK (status IN ('PENDING','DELIVERED','FAILED')),
	FOREIGN KEY(broadcast_id) REFERENCES broadcasts (id) ON DELETE RESTRICT,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)
""")
    op.execute("""
CREATE INDEX ix_broadcast_pending ON broadcast_recipients (broadcast_id, id) WHERE status = 'PENDING'
""")
    op.execute("""
CREATE TABLE notification_outbox (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	user_id UUID NOT NULL,
	dedupe_key VARCHAR(200) NOT NULL,
	event_type VARCHAR(64) NOT NULL,
	category VARCHAR(24) NOT NULL,
	template_key VARCHAR(100) NOT NULL,
	payload JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT ck_notification_outbox_payload_size CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 4096),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	UNIQUE (dedupe_key)
)
""")
    op.execute("""
CREATE INDEX ix_notification_outbox_pending ON notification_outbox (created_at, id) WHERE published_at IS NULL
""")
    _create_guards_and_producers()


def _create_guards_and_producers():
    op.execute("""
CREATE FUNCTION communications_stage_lifecycle() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_id uuid; event_name text; event_category text; template_name text; event_key text; data jsonb;
BEGIN
 IF TG_TABLE_NAME = 'tender_recommendations' THEN
   SELECT user_id INTO owner_id FROM company_profiles WHERE id = NEW.company_profile_id;
   event_name := 'RECOMMENDATION_CREATED'; event_category := 'TENDER_ALERT'; template_name := 'notifications.recommendation_created';
   event_key := 'recommendation:' || NEW.id::text;
   data := jsonb_build_object('recommendation_id', NEW.id, 'tender_id', NEW.tender_id);
 ELSIF TG_TABLE_NAME = 'analysis_versions' THEN
   IF NEW.status NOT IN ('COMPLETED','NEEDS_REVIEW') OR NEW.origin = 'LEGACY_BACKFILL' THEN RETURN NEW; END IF;
   SELECT user_id INTO owner_id FROM tender_analyses WHERE id = NEW.analysis_id AND ownership_state = 'OWNED';
   event_name := 'ANALYSIS_COMPLETED'; event_category := 'SYSTEM'; template_name := 'notifications.analysis_completed';
   event_key := 'analysis_version:' || NEW.id::text;
   data := jsonb_build_object('analysis_id',NEW.analysis_id,'analysis_version_id',NEW.id,'version_number',NEW.version_number,'analysis_language',NEW.analysis_language);
 ELSIF TG_TABLE_NAME = 'admin_activity_events' THEN
   IF NEW.action <> 'USER_APPROVED' OR NEW.outcome <> 'SUCCESS' THEN RETURN NEW; END IF;
   owner_id := NEW.target_user_id;
   event_name := 'ACCOUNT_APPROVED'; event_category := 'SYSTEM'; template_name := 'notifications.account_approved';
   event_key := 'account_approval:' || NEW.id::text;
   data := jsonb_build_object('approval_event_id',NEW.id);
 END IF;
 IF owner_id IS NOT NULL THEN
   INSERT INTO notification_outbox(user_id,dedupe_key,event_type,category,template_key,payload)
   VALUES(owner_id,event_key,event_name,event_category,template_name,data) ON CONFLICT(dedupe_key) DO NOTHING;
 END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER communications_recommendation_created AFTER INSERT ON tender_recommendations FOR EACH ROW EXECUTE FUNCTION communications_stage_lifecycle()
""")
    op.execute("""
CREATE TRIGGER communications_analysis_completed AFTER INSERT ON analysis_versions FOR EACH ROW EXECUTE FUNCTION communications_stage_lifecycle()
""")
    op.execute("""
CREATE TRIGGER communications_account_approved AFTER INSERT ON admin_activity_events FOR EACH ROW EXECUTE FUNCTION communications_stage_lifecycle()
""")
    op.execute("""
CREATE FUNCTION communications_guard_broadcast() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.status <> 'DRAFT' AND (NEW.subject,NEW.body,NEW.message_type,NEW.audience_mode,NEW.selected_user_ids,NEW.created_by_user_id)
 IS DISTINCT FROM (OLD.subject,OLD.body,OLD.message_type,OLD.audience_mode,OLD.selected_user_ids,OLD.created_by_user_id)
 THEN RAISE EXCEPTION 'broadcast_frozen' USING ERRCODE='23514'; END IF;
 IF NEW.recipient_count <> OLD.recipient_count AND NOT (OLD.status='QUEUED' AND OLD.recipient_count=0 AND NEW.recipient_count=(SELECT count(*) FROM broadcast_recipients WHERE broadcast_id=NEW.id)) THEN RAISE EXCEPTION 'broadcast_count_frozen' USING ERRCODE='23514'; END IF;
 IF NEW.delivered_count < OLD.delivered_count OR NEW.failed_count < OLD.failed_count THEN
 RAISE EXCEPTION 'broadcast_counter_regression' USING ERRCODE='23514'; END IF;
 IF NEW.status <> OLD.status AND NOT (
 (OLD.status='DRAFT' AND NEW.status='QUEUED') OR
 (OLD.status='QUEUED' AND NEW.status IN ('SENDING','SENT','PARTIAL','FAILED')) OR
 (OLD.status='SENDING' AND NEW.status IN ('SENT','PARTIAL','FAILED')))
 THEN RAISE EXCEPTION 'broadcast_invalid_transition' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER communications_broadcast_frozen BEFORE UPDATE ON broadcasts FOR EACH ROW EXECUTE FUNCTION communications_guard_broadcast()
""")
    op.execute("""
CREATE FUNCTION communications_guard_event() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'notification_event_immutable' USING ERRCODE='23514'; END $$
""")
    op.execute("""
CREATE TRIGGER communications_event_immutable BEFORE UPDATE ON notification_events FOR EACH ROW EXECUTE FUNCTION communications_guard_event()
""")
    op.execute("""
CREATE FUNCTION communications_guard_recipient() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'broadcast_recipient_frozen' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' AND ((NEW.broadcast_id,NEW.user_id) IS DISTINCT FROM (OLD.broadcast_id,OLD.user_id) OR (OLD.status <> 'PENDING' AND NEW IS DISTINCT FROM OLD))
 THEN RAISE EXCEPTION 'broadcast_recipient_frozen' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER communications_recipient_frozen BEFORE UPDATE OR DELETE ON broadcast_recipients FOR EACH ROW EXECUTE FUNCTION communications_guard_recipient()
""")
    op.execute("""
CREATE FUNCTION communications_guard_snapshot_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM (SELECT DISTINCT broadcast_id FROM inserted_recipients) r JOIN broadcasts b ON b.id=r.broadcast_id WHERE b.status <> 'QUEUED' OR b.recipient_count <> 0)
 THEN RAISE EXCEPTION 'broadcast_snapshot_closed' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$
""")
    op.execute("""
CREATE TRIGGER communications_snapshot_insert AFTER INSERT ON broadcast_recipients REFERENCING NEW TABLE AS inserted_recipients FOR EACH STATEMENT EXECUTE FUNCTION communications_guard_snapshot_insert()
""")


def downgrade():
    op.execute(
        "DROP TRIGGER communications_recommendation_created ON tender_recommendations"
    )
    op.execute("DROP TRIGGER communications_analysis_completed ON analysis_versions")
    op.execute("DROP TRIGGER communications_account_approved ON admin_activity_events")
    op.drop_table("notification_outbox")
    op.drop_table("broadcast_recipients")
    op.drop_table("notification_deliveries")
    op.drop_table("notification_events")
    op.drop_table("broadcasts")
    op.execute("DROP FUNCTION communications_stage_lifecycle()")
    op.execute("DROP FUNCTION communications_guard_broadcast()")
    op.execute("DROP FUNCTION communications_guard_event()")
    op.execute("DROP FUNCTION communications_guard_recipient()")
    op.execute("DROP FUNCTION communications_guard_snapshot_insert()")
