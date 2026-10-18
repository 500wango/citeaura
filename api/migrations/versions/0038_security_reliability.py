"""安全与可靠性补强：SSO 身份绑定、任务心跳、令牌过期、订阅与通知唯一性。

包含数据修正步骤，因此必须在真实数据上按顺序执行：
1. 先把同一租户下并存的"当前订阅"降级为 incomplete，才能建唯一索引；
2. 先把重复的 notification_key 置空，才能建唯一索引。
"""

from alembic import op
import sqlalchemy as sa

revision = "0038_security_reliability"
down_revision = "0037_custom_provider_transport"
branch_labels = None
depends_on = None


CURRENT_SUBSCRIPTION_STATUSES = ("active", "trialing", "past_due")


def upgrade():
    # --- 任务心跳：区分"慢但活着"和"worker 已死" -------------------------------
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))

    # --- 租户密钥掩码：列表接口不再为打码而解密 ---------------------------------
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.add_column(sa.Column("key_suffix", sa.String(length=8), nullable=True))

    # --- 集成令牌过期 -----------------------------------------------------------
    with op.batch_alter_table("api_access_tokens") as batch_op:
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_api_access_tokens_expires_at", ["expires_at"])

    # --- SSO 身份绑定 -----------------------------------------------------------
    op.create_table(
        "sso_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "issuer", "subject", name="uq_sso_identities_issuer_subject"),
    )
    op.create_index("ix_sso_identities_tenant_id", "sso_identities", ["tenant_id"])
    op.create_index("ix_sso_identities_user", "sso_identities", ["user_id"])

    # --- 每个租户只能有一条当前订阅 ---------------------------------------------
    # 应用层的 with_for_update() 在"两条新行并发插入"时锁不到任何行，
    # 必须由数据库兜底。多出来的当前订阅先降级为 incomplete 并把降级结果留档，
    # 让"谁失去了权限"可查、可恢复。
    op.create_table(
        "subscription_demotions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan", sa.String(length=32), nullable=True),
        sa.Column("status_before", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("demoted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_subscription_demotions_subscription_id", "subscription_demotions", ["subscription_id"])
    op.create_index("ix_subscription_demotions_tenant_id", "subscription_demotions", ["tenant_id"])
    op.execute(
        """
        INSERT INTO subscription_demotions
            (subscription_id, tenant_id, plan, status_before, started_at, provider_subscription_id)
        SELECT s.id, s.tenant_id, s.plan, s.status, s.started_at, s.provider_subscription_id
        FROM subscriptions s
        WHERE s.id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY tenant_id
                           ORDER BY started_at DESC NULLS LAST, id DESC
                       ) AS position
                FROM subscriptions
                WHERE status IN ('active', 'trialing', 'past_due')
            ) ranked
            WHERE ranked.position > 1
        )
        """
    )
    op.execute(
        """
        UPDATE subscriptions SET status = 'incomplete'
        WHERE id IN (
            SELECT subscription_id FROM subscription_demotions
        )
        """
    )
    op.create_index(
        "uq_subscriptions_tenant_current",
        "subscriptions",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'trialing', 'past_due')"),
        sqlite_where=sa.text("status IN ('active', 'trialing', 'past_due')"),
    )

    # --- 付款成功通知只能发一次 -------------------------------------------------
    op.execute(
        """
        UPDATE billing_events SET notification_key = NULL
        WHERE notification_key IS NOT NULL
          AND id NOT IN (
              SELECT MIN(id) FROM billing_events
              WHERE notification_key IS NOT NULL
              GROUP BY notification_key
          )
        """
    )
    op.drop_index("ix_billing_events_notification_key", table_name="billing_events")
    op.create_index(
        "uq_billing_events_notification_key",
        "billing_events",
        ["notification_key"],
        unique=True,
        postgresql_where=sa.text("notification_key IS NOT NULL"),
        sqlite_where=sa.text("notification_key IS NOT NULL"),
    )

    # --- 热点查询索引 -----------------------------------------------------------
    op.create_index("ix_platform_usage_tenant_created", "platform_usage", ["tenant_id", "created_at"])
    op.create_index(
        "ix_platform_usage_outbox_pending",
        "platform_usage_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])


def downgrade():
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_platform_usage_outbox_pending", table_name="platform_usage_outbox")
    op.drop_index("ix_platform_usage_tenant_created", table_name="platform_usage")
    op.drop_index("uq_billing_events_notification_key", table_name="billing_events")
    op.create_index(
        "ix_billing_events_notification_key", "billing_events", ["notification_key"],
    )
    op.drop_index("uq_subscriptions_tenant_current", table_name="subscriptions")
    op.drop_index("ix_subscription_demotions_tenant_id", table_name="subscription_demotions")
    op.drop_index("ix_subscription_demotions_subscription_id", table_name="subscription_demotions")
    # 降级前请先导出这张表：它记录了本次迁移把哪些租户的订阅降级为 incomplete。
    op.drop_table("subscription_demotions")
    op.drop_index("ix_sso_identities_user", table_name="sso_identities")
    op.drop_index("ix_sso_identities_tenant_id", table_name="sso_identities")
    op.drop_table("sso_identities")
    with op.batch_alter_table("api_access_tokens") as batch_op:
        batch_op.drop_index("ix_api_access_tokens_expires_at")
        batch_op.drop_column("expires_at")
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_column("key_suffix")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("heartbeat_at")
