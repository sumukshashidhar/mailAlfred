from datetime import datetime, timezone

from src.models import Attachment, Email


class TestAttachment:
    def test_attachment_required_fields(self):
        att = Attachment(filename="doc.pdf", mime_type="application/pdf", size=1024)
        assert att.filename == "doc.pdf"
        assert att.mime_type == "application/pdf"
        assert att.size == 1024

    def test_attachment_defaults(self):
        att = Attachment(filename="doc.pdf", mime_type="application/pdf", size=1024)
        assert att.attachment_id == ""
        assert att.data == b""

    def test_attachment_with_data(self):
        att = Attachment(
            filename="image.png",
            mime_type="image/png",
            size=2048,
            attachment_id="ANGjdJ8xyz",
            data=b"\x89PNG\r\n",
        )
        assert att.attachment_id == "ANGjdJ8xyz"
        assert att.data == b"\x89PNG\r\n"


class TestEmail:
    def test_email_required_fields(self):
        email = Email(id="abc123", thread_id="thread1")
        assert email.id == "abc123"
        assert email.thread_id == "thread1"

    def test_email_defaults(self):
        email = Email(id="abc123", thread_id="thread1")
        assert email.subject == ""
        assert email.sender == ""
        assert email.recipients == []
        assert email.cc == []
        assert email.bcc == []
        assert email.date is None
        assert email.message_id == ""
        assert email.in_reply_to == ""
        assert email.references == []
        assert email.snippet == ""
        assert email.body_plain == ""
        assert email.body_html == ""
        assert email.labels == []
        assert email.attachments == []

    def test_email_full(self):
        dt = datetime(2026, 3, 4, 10, 0, 0, tzinfo=timezone.utc)
        att = Attachment(filename="report.pdf", mime_type="application/pdf", size=5000)
        email = Email(
            id="abc123",
            thread_id="thread1",
            subject="Meeting",
            sender="bob@example.com",
            recipients=["alice@example.com"],
            cc=["carol@example.com"],
            bcc=["dave@example.com"],
            date=dt,
            message_id="<msg123@example.com>",
            in_reply_to="<msg100@example.com>",
            references=["<msg100@example.com>", "<msg101@example.com>"],
            snippet="Let's meet...",
            body_plain="Let's meet at 3pm",
            body_html="<p>Let's meet at 3pm</p>",
            labels=["INBOX", "UNREAD"],
            attachments=[att],
        )
        assert email.date == dt
        assert email.recipients == ["alice@example.com"]
        assert email.cc == ["carol@example.com"]
        assert email.bcc == ["dave@example.com"]
        assert email.message_id == "<msg123@example.com>"
        assert email.in_reply_to == "<msg100@example.com>"
        assert len(email.references) == 2
        assert email.body_html == "<p>Let's meet at 3pm</p>"
        assert len(email.attachments) == 1
        assert email.attachments[0].filename == "report.pdf"

    def test_email_no_shared_mutable_defaults(self):
        """Each Email gets its own list instances."""
        a = Email(id="1", thread_id="t1")
        b = Email(id="2", thread_id="t2")
        a.labels.append("INBOX")
        a.recipients.append("x@x.com")
        a.attachments.append(Attachment(filename="a.txt", mime_type="text/plain", size=1))
        assert b.labels == []
        assert b.recipients == []
        assert b.attachments == []
