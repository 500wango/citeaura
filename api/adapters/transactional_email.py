"""通过平台 SMTP 账号发送 CiteAura 事务邮件。"""

import logging
from decimal import Decimal, InvalidOperation

from api import config
from api.adapters import notify


logger = logging.getLogger(__name__)


def _money(amount_minor, currency):
    """格式化支付服务商的最小货币单位金额。"""
    try:
        amount = Decimal(int(amount_minor)) / Decimal("100")
    except (TypeError, ValueError, InvalidOperation):
        return "Amount unavailable"
    return f"{str(currency or 'usd').upper()} {amount:,.2f}"


def send_welcome_email(email, tenant_name, user_id):
    """发送注册成功欢迎邮件。"""
    return notify.send_product_email(
        email,
        "Welcome to CiteAura",
        (
            f"Welcome to CiteAura, {tenant_name}!\n\n"
            "Your workspace is ready with a 14-day trial. Start by adding a project domain "
            "to generate your first AI visibility report.\n\n"
            f"Open CiteAura: {config.public_base_url()}/app\n\n"
            "Best,\nThe CiteAura team"
        ),
        f"welcome-user-{user_id}",
    )


def send_welcome_email_safe(email, tenant_name, user_id):
    """发送欢迎邮件，失败时不影响注册响应。"""
    if not config.auth_smtp_configured():
        logger.info("welcome email skipped: auth SMTP is not configured")
        return {"status": "skipped", "reason": "smtp_not_configured"}
    try:
        return send_welcome_email(email, tenant_name, user_id)
    except Exception:  # noqa: BLE001 - notification failure must not fail registration
        logger.exception("welcome email delivery failed for user %s", user_id)
        return {"status": "failed", "reason": "smtp_send_failed"}


def send_payment_success_email(
    email,
    plan_name,
    billing_interval,
    amount_minor,
    currency,
    payment_reference,
):
    """为一个 Stripe 付款事件发送成功通知。"""
    return notify.send_product_email(
        email,
        "CiteAura payment successful",
        (
            "Your CiteAura payment was successful.\n\n"
            f"Plan: {plan_name}\n"
            f"Billing interval: {billing_interval}\n"
            f"Amount: {_money(amount_minor, currency)}\n"
            f"Payment reference: {payment_reference}\n\n"
            f"Manage your workspace: {config.public_base_url()}/app\n\n"
            "Stripe will send the official receipt or invoice according to your billing email settings.\n\n"
            "Best,\nThe CiteAura team"
        ),
        f"payment-success-{payment_reference}",
    )


def send_payment_success_email_safe(
    email,
    plan_name,
    billing_interval,
    amount_minor,
    currency,
    payment_reference,
):
    """发送付款通知，失败时不改变计费结果。"""
    if not config.auth_smtp_configured():
        logger.info("payment email skipped: auth SMTP is not configured")
        return {"status": "skipped", "reason": "smtp_not_configured"}
    try:
        return send_payment_success_email(
            email,
            plan_name,
            billing_interval,
            amount_minor,
            currency,
            payment_reference,
        )
    except Exception:  # noqa: BLE001 - notification failure must not fail Stripe webhook
        logger.exception("payment email delivery failed for event %s", payment_reference)
        return {"status": "failed", "reason": "smtp_send_failed"}
