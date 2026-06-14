"""Unit coverage for the correctness fixes:

  1. reply / reply-all / forward WITH attachments preserve recipients, cc and
     threading (they go through create_reply*/create_forward + a saved draft).
  2. mail search --sender filters server-side so total/has_more are honest.
  3. mail read surfaces cid inline images in a dedicated `inline_images` list.
  4. context.credentials.valid reflects a cached credential probe, not a copy
     of `configured`.

These drive the command callbacks and helpers in-process with fakes, so no
Exchange connection is needed.
"""

import json
import types

import pytest

from outlook_cli import output
from outlook_cli.commands import mail

# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeMailbox:
    def __init__(self, email):
        self.email_address = email


class FakeAttachment:
    def __init__(self, name, size=10, content_type="text/plain", is_inline=False, content_id=None):
        self.name = name
        self.size = size
        self.content_type = content_type
        self.is_inline = is_inline
        self.content_id = content_id
        self.content = b"data"


class FakeSaveResult:
    def __init__(self, id_, changekey):
        self.id = id_
        self.changekey = changekey


class FakeReply:
    """Stands in for ReplyToItem/ReplyAllToItem/forward item."""

    def __init__(self):
        self.saved_to = None

    def save(self, folder):
        self.saved_to = folder
        return FakeSaveResult("draft-id", "draft-ck")


class FakeDraft:
    def __init__(self):
        self.attached = []
        self.sent = False

    def attach(self, att):
        self.attached.append(att)

    def send(self):
        self.sent = True


class FakeDrafts:
    def __init__(self, draft):
        self._draft = draft
        self.get_args = None

    def get(self, id=None, changekey=None):
        self.get_args = (id, changekey)
        return self._draft


class FakeAccount:
    def __init__(self, draft=None):
        self.drafts = FakeDrafts(draft) if draft is not None else None


# --------------------------------------------------------------------------
# 1. reply/reply-all/forward with attachments
# --------------------------------------------------------------------------


def test_send_reply_with_attachments_saves_fetches_attaches_sends(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hi", encoding="utf-8")

    draft = FakeDraft()
    account = FakeAccount(draft=draft)
    reply = FakeReply()

    mail._send_reply_with_attachments(account, reply, (str(f),))

    # The reply was persisted to the drafts folder (keeps threading), then the
    # saved draft was re-fetched by its id+changekey, the extra file attached,
    # and only then sent.
    assert reply.saved_to is account.drafts
    assert account.drafts.get_args == ("draft-id", "draft-ck")
    assert len(draft.attached) == 1
    assert draft.attached[0].name == "a.txt"
    assert draft.sent is True


def _make_item(monkeypatch):
    """A fake original message that records how reply/forward were created."""
    calls = {}

    item = types.SimpleNamespace()
    item.subject = "Hello"
    item.sender = FakeMailbox("boss@co.com")
    item.to_recipients = [FakeMailbox("me@co.com")]
    item.cc_recipients = [FakeMailbox("peer@co.com")]
    item.message_id = "<msg-1>"
    item.id = "item-1"

    def create_reply(subject, body, **kw):
        calls["create_reply"] = {"subject": subject, "body": body, **kw}
        return FakeReply()

    def create_reply_all(subject, body, **kw):
        calls["create_reply_all"] = {"subject": subject, "body": body, **kw}
        return FakeReply()

    def create_forward(subject, body, to_recipients=None, **kw):
        calls["create_forward"] = {"subject": subject, "to_recipients": to_recipients}
        return FakeReply()

    def reply(subject, body):
        calls["reply"] = {"subject": subject, "body": body}

    def reply_all(subject, body):
        calls["reply_all"] = {"subject": subject, "body": body}

    item.create_reply = create_reply
    item.create_reply_all = create_reply_all
    item.create_forward = create_forward
    item.reply = reply
    item.reply_all = reply_all
    return item, calls


def _run_mail(monkeypatch, cmd, args, item, confirm_token="ct_x"):
    """Invoke a mail subcommand in-process with permission/confirm/account stubbed."""
    account = FakeAccount(draft=FakeDraft())

    monkeypatch.setattr("outlook_cli.config.check_permission", lambda *_a, **_k: None)
    monkeypatch.setattr(mail, "get_account", lambda *a, **k: account)
    monkeypatch.setattr(mail, "find_mail_by_id", lambda *a, **k: item)
    monkeypatch.setattr(mail, "_confirm_item", lambda *a, **k: None)

    from click.testing import CliRunner

    output.init(format_mode="json")
    runner = CliRunner()
    return runner.invoke(
        cmd, args, obj={"dry_run": False, "confirm": confirm_token}, catch_exceptions=False
    )


def test_reply_with_attachments_uses_create_reply(monkeypatch, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    item, calls = _make_item(monkeypatch)

    result = _run_mail(
        monkeypatch,
        mail.mail_reply,
        ["--id", "item-1", "--body", "Thanks", "--attachments", str(f)],
        item,
    )
    assert result.exit_code == 0, result.output
    # Reply went through create_reply (threading preserved), not a bare Message.
    assert "create_reply" in calls
    assert calls["create_reply"]["subject"] == "Re: Hello"


def test_reply_all_with_attachments_uses_create_reply_all(monkeypatch, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    item, calls = _make_item(monkeypatch)

    result = _run_mail(
        monkeypatch,
        mail.mail_reply_all,
        ["--id", "item-1", "--body", "Thanks all", "--attachments", str(f)],
        item,
    )
    assert result.exit_code == 0, result.output
    # reply-all keeps the sender+cc fan-out by delegating to create_reply_all.
    assert "create_reply_all" in calls


def test_forward_with_attachments_uses_create_forward(monkeypatch, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    item, calls = _make_item(monkeypatch)

    result = _run_mail(
        monkeypatch,
        mail.mail_forward,
        ["--id", "item-1", "--to", "x@co.com", "--body", "Fwd", "--attachments", str(f)],
        item,
    )
    assert result.exit_code == 0, result.output
    assert "create_forward" in calls
    assert calls["create_forward"]["to_recipients"][0].email_address == "x@co.com"


def test_reply_without_attachments_uses_native_reply(monkeypatch):
    item, calls = _make_item(monkeypatch)
    result = _run_mail(monkeypatch, mail.mail_reply, ["--id", "item-1", "--body", "Thanks"], item)
    assert result.exit_code == 0, result.output
    assert "reply" in calls
    assert "create_reply" not in calls


# --------------------------------------------------------------------------
# 2. mail search --sender pushes the filter server-side
# --------------------------------------------------------------------------


class FakeQuerySet:
    """Records filter kwargs and serves a fixed list so count/slice are honest."""

    def __init__(self, items, recorder):
        self._items = items
        self._recorder = recorder

    def filter(self, *args, **kwargs):
        self._recorder.append(kwargs)
        # Apply the sender filter so the count reflects the server-side result.
        items = self._items
        if "sender__icontains" in kwargs:
            needle = kwargs["sender__icontains"].lower()
            items = [m for m in items if needle in m.sender.email_address.lower()]
        return FakeQuerySet(items, self._recorder)

    def order_by(self, *_a):
        return self

    def count(self):
        return len(self._items)

    def __getitem__(self, sl):
        return self._items[sl]


def _fake_search_item(sender_email, idx):
    it = types.SimpleNamespace()
    it.subject = f"Subj {idx}"
    it.sender = FakeMailbox(sender_email)
    it.to_recipients = []
    it.cc_recipients = []
    it.datetime_received = None
    it.is_read = True
    it.attachments = []
    it.text_body = "body"
    it.id = f"id-{idx}"
    return it


def test_search_sender_is_server_side_and_counts_are_honest(monkeypatch):
    items = [_fake_search_item("alice@co.com", i) for i in range(3)]
    items += [_fake_search_item("bob@co.com", i + 100) for i in range(2)]
    recorder = []

    class FakeInbox:
        def all(self):
            return FakeQuerySet(items, recorder)

    account = types.SimpleNamespace(inbox=FakeInbox())

    monkeypatch.setattr("outlook_cli.config.check_permission", lambda *_a, **_k: None)
    monkeypatch.setattr(mail, "get_account", lambda *a, **k: account)

    from click.testing import CliRunner

    output.init(format_mode="json")
    runner = CliRunner()
    result = runner.invoke(
        mail.mail_search,
        ["--sender", "alice", "--limit", "10"],
        obj={"dry_run": False, "confirm": None},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    # The sender filter must have been pushed to the server.
    assert any("sender__icontains" in kw for kw in recorder)

    doc = json.loads(result.output[result.output.find("{") :])["data"]
    # total reflects the full server-side match (3 alice), not a fetch window.
    assert doc["total"] == 3
    assert doc["count"] == 3
    assert doc["has_more"] is False


# --------------------------------------------------------------------------
# 3. mail read surfaces inline cid images
# --------------------------------------------------------------------------


def test_mail_read_surfaces_inline_images(monkeypatch):
    item = types.SimpleNamespace()
    item.subject = "With logo"
    item.sender = FakeMailbox("boss@co.com")
    item.to_recipients = []
    item.cc_recipients = []
    item.datetime_received = None
    item.is_read = True
    item.has_attachments = True
    item.text_body = "see image cid:logo.png"
    item.id = "item-1"
    item.attachments = [
        FakeAttachment("report.pdf", content_type="application/pdf"),
        FakeAttachment("logo.png", content_type="image/png", is_inline=True, content_id="logo.png"),
    ]

    monkeypatch.setattr("outlook_cli.config.check_permission", lambda *_a, **_k: None)
    monkeypatch.setattr(mail, "get_account", lambda *a, **k: object())
    monkeypatch.setattr(mail, "find_mail_by_id", lambda *a, **k: item)

    from click.testing import CliRunner

    output.init(format_mode="json")
    runner = CliRunner()
    result = runner.invoke(
        mail.mail_read,
        ["--id", "item-1"],
        obj={"dry_run": False, "confirm": None},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output[result.output.find("{") :])["data"]

    # The inline image is surfaced separately; the regular attachment stays put.
    assert [a["name"] for a in doc["attachments"]] == ["report.pdf"]
    assert len(doc["inline_images"]) == 1
    img = doc["inline_images"][0]
    assert img["cid"] == "logo.png"
    assert img["filename"] == "logo.png"
    assert img["content_type"] == "image/png"
    assert "inline_images.filename" in doc["_untrusted"]


# --------------------------------------------------------------------------
# 4. probe_credentials drives context.credentials.valid
# --------------------------------------------------------------------------


def test_probe_credentials_unconfigured(monkeypatch, tmp_path):
    from outlook_cli import exchange

    monkeypatch.setattr("outlook_cli.config.load", lambda: {})
    probe = exchange.probe_credentials()
    assert probe["valid"] is False
    assert probe["checked"] is False
    assert probe["reason"] == "not configured"


def test_probe_credentials_runs_and_caches(monkeypatch, tmp_path):
    from outlook_cli import config, exchange

    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        "outlook_cli.config.load",
        lambda: {"email": "u@co.com", "password": "secret", "server": "srv"},
    )

    calls = {"n": 0}

    def fake_run_probe(email, password, server, target_email):
        calls["n"] += 1
        return {"valid": True, "reason": ""}

    monkeypatch.setattr(exchange, "_run_probe", fake_run_probe)

    first = exchange.probe_credentials()
    assert first == {"valid": True, "reason": "", "checked": True}
    # Second call within TTL is served from cache — probe not re-run.
    second = exchange.probe_credentials()
    assert second["valid"] is True
    assert calls["n"] == 1


def test_probe_credentials_reports_failure_reason(monkeypatch, tmp_path):
    from outlook_cli import config, exchange

    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        "outlook_cli.config.load",
        lambda: {"email": "u@co.com", "password": "bad", "server": "srv"},
    )
    monkeypatch.setattr(
        exchange, "_run_probe", lambda *a: {"valid": False, "reason": "UnauthorizedError"}
    )

    probe = exchange.probe_credentials()
    assert probe["valid"] is False
    assert probe["reason"] == "UnauthorizedError"
    assert probe["checked"] is True


def test_context_valid_reflects_probe(monkeypatch):
    """context.credentials.valid comes from the probe, not a copy of configured."""
    import outlook_cli.main as main_mod
    from outlook_cli import exchange

    monkeypatch.setattr(
        "outlook_cli.config.load",
        lambda: {"email": "u@co.com", "password": "secret"},
    )
    monkeypatch.setattr(
        exchange,
        "probe_credentials",
        lambda: {"valid": False, "reason": "UnauthorizedError", "checked": True},
    )

    from click.testing import CliRunner

    output.init(format_mode="json")
    runner = CliRunner()
    result = runner.invoke(main_mod.context_cmd, [], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output[result.output.find("{") :])["data"]
    creds = doc["credentials"]
    # configured is True, but valid is False because the probe failed — proving
    # valid is no longer just a copy of configured.
    assert creds["configured"] is True
    assert creds["valid"] is False
    assert creds["reason"] == "UnauthorizedError"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
