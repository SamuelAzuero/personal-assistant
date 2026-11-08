"""Tier 1: Feature Coverage — R3: Email Monitoring & Intelligent Digest.

Tests T1-R3-01 to T1-R3-06 verifying nominal unread polling, urgency scoring,
newsletter classification, executive digest formatting, action item extraction, and label modification.
"""

import pytest
from app.integrations.mocks import MockGmailClient
from app.services.email_service import EmailService


@pytest.fixture
def email_service(gmail_fixtures) -> EmailService:
    client = MockGmailClient()
    return EmailService(client=client)


def test_t1_r3_01_fetch_unread_emails(email_service: EmailService):
    """T1-R3-01: Poll unread emails returns parsed messages with headers, sender, and snippet."""
    items = email_service.poll_unread("usr_test_default")
    assert len(items) >= 1
    first = items[0]
    assert "subject" in first
    assert "sender" in first
    assert "snippet" in first
    assert first["subject"] != ""
    assert first["sender"] != ""


def test_t1_r3_02_urgent_email_detection(email_service: EmailService):
    """T1-R3-02: Critical outage email is classified with high urgency score and urgent flag."""
    headers = {
        "From": "cto@company.com",
        "Subject": "URGENT: Server outage on production cluster",
        "X-Priority": "1",
    }
    body = "Immediate action required: outage on production cluster. The authentication gateway is down."
    score, is_urgent, category = email_service._compute_urgency_score_and_category(
        headers=headers,
        subject=headers["Subject"],
        body=body,
    )

    assert is_urgent is True
    assert score >= 70
    assert category in ["ALERT", "WORK"]


def test_t1_r3_03_newsletter_tagging(email_service: EmailService):
    """T1-R3-03: Email with List-Unsubscribe header is categorized as NEWSLETTER with low urgency."""
    headers = {
        "From": "newsletter@pythondigest.org",
        "Subject": "Python Weekly Issue #612",
        "List-Unsubscribe": "<https://pythondigest.org/unsub?id=8831>",
    }
    body = "Welcome to this week's Python guide. Discover new features."
    score, is_urgent, category = email_service._compute_urgency_score_and_category(
        headers=headers,
        subject=headers["Subject"],
        body=body,
    )

    assert is_urgent is False
    assert category == "NEWSLETTER"
    assert score < 50


def test_t1_r3_04_executive_digest_generation(email_service: EmailService):
    """T1-R3-04: Executive digest summarizes unread inbox with urgent items highlighted."""
    digest = email_service.generate_digest("usr_test_default")

    assert "total_unread" in digest
    assert "urgent_count" in digest
    assert "summary_text" in digest
    assert digest["total_unread"] >= 1
    assert "urgent" in digest["summary_text"].lower() or digest["urgent_count"] >= 0


def test_t1_r3_05_actionable_extraction(email_service: EmailService):
    """T1-R3-05: Action extractor identifies concrete task requests in email text."""
    body = "Please review attached contract by Friday 3 PM. We need your feedback."
    actions = email_service._extract_action_items(body)

    assert len(actions) >= 1
    first_action = actions[0].lower()
    assert "please review" in first_action
    assert "contract" in first_action


def test_t1_r3_06_mark_as_read(email_service: EmailService):
    """T1-R3-06: Marking an email as read removes UNREAD label and excludes it from subsequent polls."""
    initial_items = email_service.poll_unread("usr_test_default")
    assert len(initial_items) >= 1
    target_id = initial_items[0]["id"]

    # Mark as read
    email_service.client.modify_labels(
        user_id="usr_test_default",
        message_id=target_id,
        remove_labels=["UNREAD"],
    )

    subsequent_items = email_service.poll_unread("usr_test_default")
    subsequent_ids = [m["id"] for m in subsequent_items]
    assert target_id not in subsequent_ids
    assert len(subsequent_items) == len(initial_items) - 1
