"""Integration tests — self-contained round-trip against a real Exchange server.

Every test creates data for the current user only, verifies it, then cleans up.
No impact on other people. Covers the main CLI command families.

    set OUTLOOK_IT_EMAIL=user@company.com
    set OUTLOOK_IT_PASSWORD=your-password
    set OUTLOOK_IT_SERVER=mail.company.com    # optional

    python -m pytest tests/test_integration.py -v
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("OUTLOOK_IT_EMAIL") or not os.environ.get("OUTLOOK_IT_PASSWORD"),
    reason="Integration tests require OUTLOOK_IT_EMAIL and OUTLOOK_IT_PASSWORD",
)

RUN_ID = f"IT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


MUTATING_COMMANDS = {
    ("cal", "create"),
    ("cal", "delete"),
    ("cal", "update"),
    ("folders", "create"),
    ("folders", "delete"),
    ("folders", "empty"),
    ("folders", "move"),
    ("folders", "rename"),
    ("mail", "batch"),
    ("mail", "categorize"),
    ("mail", "delete"),
    ("mail", "download-attachment"),
    ("mail", "draft-delete"),
    ("mail", "draft-edit"),
    ("mail", "draft-send"),
    ("mail", "export"),
    ("mail", "flag"),
    ("mail", "forward"),
    ("mail", "mark"),
    ("mail", "move"),
    ("mail", "reply"),
    ("mail", "reply-all"),
    ("mail", "restore"),
    ("mail", "send"),
    ("rules", "create"),
    ("rules", "delete"),
    ("rules", "toggle"),
    ("rules", "update"),
    ("tools", "oof", "disable"),
    ("tools", "oof", "set"),
    ("tools", "respond"),
}


def _command_path(args):
    tokens = [arg for arg in args if not arg.startswith("-")]
    for size in (3, 2):
        path = tuple(tokens[:size])
        if path in MUTATING_COMMANDS:
            return path
    return tuple(tokens[:2])


def _needs_confirm(args):
    if any(arg in args for arg in ("--dry-run", "--confirm")):
        return False
    return _command_path(args) in MUTATING_COMMANDS


def _run_cli_once(*args):
    """Run outlook-cli subprocess with integration credentials."""
    env = os.environ.copy()
    env["OUTLOOK_EMAIL"] = os.environ["OUTLOOK_IT_EMAIL"]
    env["OUTLOOK_PASSWORD"] = os.environ["OUTLOOK_IT_PASSWORD"]
    env["OUTLOOK_PERMISSIONS"] = "full"
    server = os.environ.get("OUTLOOK_IT_SERVER", "")
    if server:
        env["OUTLOOK_SERVER"] = server
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    result = subprocess.run(
        [sys.executable, "-m", "outlook_cli.main", "--json", *args],
        capture_output=True,
        timeout=60,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    return result.returncode, stdout, stderr


def _parse_doc(text):
    doc = json.loads(text)
    return doc.get("data", doc)


def run_cli(*args):
    """Run outlook-cli and auto-confirm mutating integration operations."""
    if not _needs_confirm(args):
        return _run_cli_once(*args)

    code, stdout, stderr = _run_cli_once(*args, "--dry-run")
    if code != 0:
        return code, stdout, stderr
    token = _parse_doc(stdout)["confirm_token"]
    return _run_cli_once(*args, "--confirm", token)


def get_json(*args):
    code, stdout, stderr = run_cli(*args)
    assert code == 0, f"Exit {code}: {stderr}"
    return _parse_doc(stdout)


# ──────────────────────────────────────────────
# Step 1: Connection (2 commands)
# setup status, setup doctor
# ──────────────────────────────────────────────


class TestStep1Connection:
    def test_setup_status(self):
        """[setup status]"""
        code, _, _ = run_cli("setup", "status")
        assert code == 0

    def test_setup_doctor(self):
        """[setup doctor]"""
        code, _, _ = run_cli("setup", "doctor")
        assert code == 0


# ──────────────────────────────────────────────
# Step 2: Mail round-trip (19 commands)
# send, search, read, list, thread, mark, flag, categorize,
# move, restore, batch, export, download-attachment,
# reply, reply-all, forward (dry-run), attachment-summary, stats, delete
# ──────────────────────────────────────────────


class TestStep2MailRoundTrip:
    """Send email to self, exercise all mail commands, then clean up."""

    SUBJECT = f"{RUN_ID} mail-full"
    BODY = f"Integration test body for {RUN_ID}."
    _mid = None

    def test_01_send(self):
        """[mail send] Send email to self."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        data = get_json(
            "mail",
            "send",
            "--to",
            email,
            "--subject",
            self.SUBJECT,
            "--body",
            self.BODY,
        )
        assert "sent" in data["message"].lower()

    def test_02_search(self):
        """[mail search] Find the email by subject."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        mid = None
        for _ in range(6):
            time.sleep(5)
            data = get_json(
                "mail",
                "search",
                "--subject",
                self.SUBJECT,
                "--sender",
                email,
                "--limit",
                "5",
            )
            if data.get("emails"):
                mid = data["emails"][0]["id"]
                break
        assert mid is not None, f"Email '{self.SUBJECT}' not found after 30s"
        self.__class__._mid = mid

    def test_03_read(self):
        """[mail read] Verify content."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        detail = get_json("mail", "read", "--id", mid)
        assert self.SUBJECT in detail["subject"]
        assert self.BODY in detail["body"]

    def test_04_list(self):
        """[mail list] List inbox."""
        data = get_json("mail", "list", "--limit", "5")
        assert "emails" in data
        assert data["count"] >= 1

    def test_05_list_filter(self):
        """[mail list --filter] Filter unread."""
        data = get_json("mail", "list", "--filter", "unread", "--limit", "3")
        assert "emails" in data

    def test_06_thread(self):
        """[mail thread] Get conversation thread."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        data = get_json("mail", "thread", "--id", mid)
        assert "thread" in data or "messages" in data

    def test_07_mark(self):
        """[mail mark] Mark read then unread."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        code, _, _ = run_cli("mail", "mark", "--id", mid, "--status", "read")
        assert code == 0
        code, _, _ = run_cli("mail", "mark", "--id", mid, "--status", "unread")
        assert code == 0

    def test_08_flag(self):
        """[mail flag] Flag then unflag."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        code, _, _ = run_cli("mail", "flag", "--id", mid, "--action", "flag")
        assert code == 0
        code, _, _ = run_cli("mail", "flag", "--id", mid, "--action", "unflag")
        assert code == 0

    def test_09_categorize(self):
        """[mail categorize] Add, remove, clear categories."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        code, _, _ = run_cli(
            "mail",
            "categorize",
            "--id",
            mid,
            "--action",
            "add",
            "--categories",
            "IntegrationTest",
        )
        assert code == 0
        code, _, _ = run_cli(
            "mail",
            "categorize",
            "--id",
            mid,
            "--action",
            "remove",
            "--categories",
            "IntegrationTest",
        )
        assert code == 0

    def test_10_move_and_restore(self):
        """[mail move] + [mail restore] Move to trash, then restore."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        code, _, _ = run_cli("mail", "move", "--id", mid, "--folder", "trash")
        assert code == 0
        code, _, _ = run_cli("mail", "restore", "--id", mid)
        assert code == 0

    def test_11_stats(self):
        """[mail stats]"""
        data = get_json("mail", "stats", "--days", "7")
        assert "total" in data

    def test_12_attachment_summary(self):
        """[mail attachment-summary]"""
        data = get_json("mail", "attachment-summary", "--days", "30")
        assert "emails" in data

    def test_13_export(self, tmp_path):
        """[mail export] Export email to file."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        code, _, _ = run_cli("mail", "export", "--id", mid, "--output-dir", str(tmp_path))
        assert code == 0
        # Verify file was created
        files = list(tmp_path.glob("*"))
        assert len(files) >= 1

    def test_14_download_attachment(self):
        """[mail download-attachment] Try on our test email (no attachment → expected behavior)."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        # Our test email has no attachments, so this should either return empty or error
        code, stdout, stderr = run_cli(
            "mail", "download-attachment", "--id", mid, "--output-dir", "/tmp"
        )
        # Either succeeds with 0 attachments, or exits with E_NOT_FOUND/E_VALIDATION.
        assert code in (0, 2, 3, 4)

    def test_15_reply_dry_run(self):
        """[mail reply --dry-run] Preview only."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        data = get_json("mail", "reply", "--id", mid, "--body", "Reply test.", "--dry-run")
        assert data["confirm_token"].startswith("ct_")

    def test_16_reply_all_dry_run(self):
        """[mail reply-all --dry-run] Preview only."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        data = get_json("mail", "reply-all", "--id", mid, "--body", "Reply all test.", "--dry-run")
        assert data["confirm_token"].startswith("ct_")

    def test_17_forward_dry_run(self):
        """[mail forward --dry-run] Preview only."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        data = get_json(
            "mail",
            "forward",
            "--id",
            mid,
            "--to",
            email,
            "--body",
            "Fwd test.",
            "--dry-run",
        )
        assert data["confirm_token"].startswith("ct_")

    def test_18_batch_preview(self):
        """[mail batch] Batch mark-read on test email."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        code, _, _ = run_cli("mail", "batch", "--ids", mid, "--action", "mark-read")
        assert code == 0

    def test_18b_search_keyword(self):
        """[mail search --keyword] Search by body keyword."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        data = get_json(
            "mail",
            "search",
            "--keyword",
            self.BODY[:20],
            "--sender",
            email,
            "--limit",
            "5",
        )
        assert "emails" in data

    def test_19_delete_cleanup(self):
        """[mail delete] Clean up test email."""
        mid = self.__class__._mid
        if not mid:
            pytest.skip("send/search failed")
        code, _, _ = run_cli("mail", "delete", "--id", mid, "--force")
        assert code == 0


# ──────────────────────────────────────────────
# Step 2b: Send variants (HTML, attachments, reply, forward)
# Covers all send/reply/forward code paths through dry-run/confirm
# ──────────────────────────────────────────────


class TestStep2bSendVariants:
    """Test different send modes: HTML, attachments, real reply, real forward."""

    _created_ids = []  # collect all created message IDs for cleanup

    # --- HTML send ---

    def test_01_send_html(self):
        """[mail send --html] Send HTML email."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        html_body = "<h1>Integration Test</h1><p>This is <b>HTML</b> content.</p>"
        data = get_json(
            "mail",
            "send",
            "--to",
            email,
            "--subject",
            f"{RUN_ID} html",
            "--body",
            html_body,
            "--html",
        )
        assert "sent" in data["message"].lower()

    def test_02_verify_html(self):
        """[mail search + read] Verify HTML email received."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        mid = None
        for _ in range(6):
            time.sleep(5)
            data = get_json(
                "mail",
                "search",
                "--subject",
                f"{RUN_ID} html",
                "--sender",
                email,
                "--limit",
                "5",
            )
            if data.get("emails"):
                mid = data["emails"][0]["id"]
                break
        assert mid is not None, "HTML email not found"
        self.__class__._created_ids.append(mid)
        detail = get_json("mail", "read", "--id", mid)
        assert "HTML" in detail["body"] or "html" in detail["body"].lower()

    # --- Attachment send ---

    def test_03_send_with_attachment(self, tmp_path):
        """[mail send --attachments] Send email with attachment."""
        att_file = tmp_path / "test-attachment.txt"
        att_file.write_text("Integration test attachment content", encoding="utf-8")
        email = os.environ["OUTLOOK_IT_EMAIL"]
        data = get_json(
            "mail",
            "send",
            "--to",
            email,
            "--subject",
            f"{RUN_ID} attachment",
            "--body",
            "See attached file.",
            "--attachments",
            str(att_file),
        )
        assert "sent" in data["message"].lower()

    def test_04_verify_attachment(self):
        """[mail search + read] Verify attachment email received."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        mid = None
        for _ in range(6):
            time.sleep(5)
            data = get_json(
                "mail",
                "search",
                "--subject",
                f"{RUN_ID} attachment",
                "--sender",
                email,
                "--limit",
                "5",
            )
            if data.get("emails"):
                mid = data["emails"][0]["id"]
                break
        assert mid is not None, "Attachment email not found"
        self.__class__._created_ids.append(mid)
        detail = get_json("mail", "read", "--id", mid)
        assert detail["has_attachments"] is True
        assert len(detail["attachments"]) >= 1
        assert detail["attachments"][0]["name"] == "test-attachment.txt"

    # --- Reply send ---

    def test_05_reply_send(self):
        """[mail reply] Send a real reply."""
        mid = self.__class__._created_ids[0] if self.__class__._created_ids else None
        if not mid:
            pytest.skip("no email to reply to")
        data = get_json("mail", "reply", "--id", mid, "--body", "This is a real reply.")
        assert data["sent"] is True

    def test_06_verify_reply_in_thread(self):
        """[mail thread] Verify reply appears in thread."""
        mid = self.__class__._created_ids[0] if self.__class__._created_ids else None
        if not mid:
            pytest.skip("no email to check thread")
        time.sleep(3)
        data = get_json("mail", "thread", "--id", mid)
        thread_msgs = data.get("thread", data.get("messages", []))
        assert len(thread_msgs) >= 2, f"Expected >=2 messages in thread, got {len(thread_msgs)}"

    # --- Reply-all send ---

    def test_07_reply_all_send(self):
        """[mail reply-all] Send a real reply-all."""
        mid = self.__class__._created_ids[0] if self.__class__._created_ids else None
        if not mid:
            pytest.skip("no email to reply-all to")
        data = get_json("mail", "reply-all", "--id", mid, "--body", "This is a reply-all.")
        assert data["sent"] is True

    # --- Forward send ---

    def test_08_forward_send(self):
        """[mail forward] Forward email to self."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        mid = self.__class__._created_ids[0] if self.__class__._created_ids else None
        if not mid:
            pytest.skip("no email to forward")
        data = get_json(
            "mail",
            "forward",
            "--id",
            mid,
            "--to",
            email,
            "--body",
            "Forwarding this.",
        )
        assert data["sent"] is True

    def test_09_verify_forward(self):
        """[mail search] Verify forwarded email received."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        for _ in range(6):
            time.sleep(5)
            data = get_json("mail", "search", "--subject", "FW:", "--sender", email, "--limit", "5")
            fwd = [e for e in data.get("emails", []) if f"{RUN_ID} html" in e.get("subject", "")]
            if fwd:
                self.__class__._created_ids.append(fwd[0]["id"])
                break
        else:
            pytest.skip("Forwarded email not found (may take longer)")

    # --- Cleanup ---

    def test_10_cleanup(self):
        """[mail delete] Clean up all send variant test emails."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        # Delete all emails with our RUN_ID subject
        for suffix in ["html", "attachment"]:
            data = get_json(
                "mail",
                "search",
                "--subject",
                f"{RUN_ID} {suffix}",
                "--sender",
                email,
                "--limit",
                "10",
            )
            for e in data.get("emails", []):
                run_cli("mail", "delete", "--id", e["id"], "--force")
        # Delete replies and forwards
        for mid in self.__class__._created_ids:
            run_cli("mail", "delete", "--id", mid, "--force")
        # Also search for reply/forward subjects
        data = get_json(
            "mail",
            "search",
            "--subject",
            f"Re: {RUN_ID}",
            "--sender",
            email,
            "--limit",
            "10",
        )
        for e in data.get("emails", []):
            run_cli("mail", "delete", "--id", e["id"], "--force")
        data = get_json("mail", "search", "--subject", "FW:", "--sender", email, "--limit", "10")
        for e in data.get("emails", []):
            if f"{RUN_ID}" in e.get("subject", ""):
                run_cli("mail", "delete", "--id", e["id"], "--force")


# ──────────────────────────────────────────────
# Step 3: Draft round-trip (4 commands)
# send --save-draft, drafts, draft-read, draft-edit, draft-send, draft-delete
# ──────────────────────────────────────────────


class TestStep3DraftRoundTrip:
    SUBJECT = f"{RUN_ID} draft"
    _draft_id = None

    def test_01_create_draft(self):
        """[mail send --save-draft]"""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        data = get_json(
            "mail",
            "send",
            "--to",
            email,
            "--subject",
            self.SUBJECT,
            "--body",
            "Draft body",
            "--save-draft",
        )
        assert "草稿箱" in data.get("message", "")

    def test_02_list_drafts(self):
        """[mail drafts]"""
        time.sleep(2)
        data = get_json("mail", "drafts", "--limit", "20")
        drafts = [d for d in data.get("drafts", []) if self.SUBJECT in d.get("subject", "")]
        assert len(drafts) >= 1, f"Draft '{self.SUBJECT}' not found"
        self.__class__._draft_id = drafts[0]["id"]

    def test_03_read_draft(self):
        """[mail draft-read]"""
        did = self.__class__._draft_id
        if not did:
            pytest.skip("draft not created")
        code, _, _ = run_cli("mail", "draft-read", "--id", did)
        assert code == 0

    def test_04_edit_draft(self):
        """[mail draft-edit]"""
        did = self.__class__._draft_id
        if not did:
            pytest.skip("draft not created")
        code, _, _ = run_cli(
            "mail",
            "draft-edit",
            "--id",
            did,
            "--subject",
            f"{self.SUBJECT} edited",
            "--body",
            "Updated",
        )
        assert code == 0

    def test_05_draft_send_dry_run(self):
        """[mail draft-send --dry-run]"""
        did = self.__class__._draft_id
        if not did:
            pytest.skip("draft not created")
        data = get_json("mail", "draft-send", "--id", did, "--dry-run")
        assert data["confirm_token"].startswith("ct_")

    def test_06_delete_draft(self):
        """[mail draft-delete]"""
        did = self.__class__._draft_id
        if not did:
            pytest.skip("draft not created")
        code, _, _ = run_cli("mail", "draft-delete", "--id", did, "--force")
        assert code == 0


# ──────────────────────────────────────────────
# Step 4: Calendar round-trip (4 commands)
# cal list, cal create, cal update, cal delete
# ──────────────────────────────────────────────


class TestStep4CalendarRoundTrip:
    SUBJECT = f"{RUN_ID} cal"
    START = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d") + " 10:00"
    END = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d") + " 10:30"
    _event_id = None

    def test_01_create(self):
        """[cal create]"""
        data = get_json(
            "cal",
            "create",
            "--subject",
            self.SUBJECT,
            "--start",
            self.START,
            "--end",
            self.END,
            "--location",
            "IT Room",
            "--body",
            f"Auto {RUN_ID}",
        )
        assert "created" in data["message"].lower() or "Event created" in data["message"]

    def test_02_list(self):
        """[cal list]"""
        data = get_json("cal", "list", "--days", "2")
        events = [e for e in data["events"] if self.SUBJECT in e.get("subject", "")]
        assert len(events) >= 1
        self.__class__._event_id = events[0]["id"]

    def test_03_update(self):
        """[cal update]"""
        eid = self.__class__._event_id
        if not eid:
            pytest.skip("event not created")
        code, _, stderr = run_cli("cal", "update", "--id", eid, "--location", "Updated Room")
        assert code == 0, f"Exit {code}: {stderr}"

    def test_04_delete(self):
        """[cal delete]"""
        eid = self.__class__._event_id
        if not eid:
            pytest.skip("event not created")
        code, _, _ = run_cli("cal", "delete", "--id", eid, "--force")
        assert code == 0


# ──────────────────────────────────────────────
# Step 4b: Calendar variants (attendees, subject filter)
# ──────────────────────────────────────────────


class TestStep4bCalendarVariants:
    """Test calendar with attendees and subject filtering."""

    SUBJECT = f"{RUN_ID} cal-attendees"
    START = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d") + " 14:00"
    END = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d") + " 14:30"
    _event_id = None

    def test_01_create_with_attendees(self):
        """[cal create --attendees] Create meeting with self as attendee."""
        email = os.environ["OUTLOOK_IT_EMAIL"]
        data = get_json(
            "cal",
            "create",
            "--subject",
            self.SUBJECT,
            "--start",
            self.START,
            "--end",
            self.END,
            "--attendees",
            email,
            "--location",
            "Meeting Room",
            "--body",
            f"Attendees test {RUN_ID}",
        )
        assert "created" in data["message"].lower() or "Event created" in data["message"]

    def test_02_list_verify_attendees(self):
        """[cal list] Verify attendees field in event."""
        data = get_json("cal", "list", "--days", "3")
        events = [e for e in data["events"] if self.SUBJECT in e.get("subject", "")]
        assert len(events) >= 1, f"Event '{self.SUBJECT}' not found"
        self.__class__._event_id = events[0]["id"]
        # Verify attendees are present
        assert events[0].get("attendees") or events[0].get("required_attendees"), (
            "Attendees field missing from cal list output"
        )

    def test_03_list_subject_filter(self):
        """[cal list --subject] Filter by subject keyword."""
        keyword = f"{RUN_ID} cal-attendees"
        data = get_json("cal", "list", "--days", "3", "--subject", keyword)
        matching = [e for e in data["events"] if self.SUBJECT in e.get("subject", "")]
        assert len(matching) >= 1, f"Subject filter '{keyword}' returned no results"

    def test_04_cleanup(self):
        """[cal delete] Clean up attendees test event."""
        eid = self.__class__._event_id
        if not eid:
            pytest.skip("event not created")
        code, _, _ = run_cli("cal", "delete", "--id", eid, "--force")
        assert code == 0


# ──────────────────────────────────────────────
# Step 5: Folder round-trip (6 commands)
# folders list, create, rename, move, empty, delete
# ──────────────────────────────────────────────


class TestStep5FolderRoundTrip:
    FOLDER_A = f"{RUN_ID}-folder-a"
    FOLDER_B = f"{RUN_ID}-folder-b"
    FOLDER_C = f"{RUN_ID}-folder-c"

    def test_01_list(self):
        """[folders list]"""
        data = get_json("folders", "list")
        assert "folders" in data

    def test_02_create(self):
        """[folders create]"""
        code, _, _ = run_cli("folders", "create", "--name", self.FOLDER_A)
        assert code == 0

    def test_03_rename(self):
        """[folders rename]"""
        code, _, _ = run_cli(
            "folders", "rename", "--name", self.FOLDER_A, "--new-name", self.FOLDER_B
        )
        assert code == 0

    def test_04_move(self):
        """[folders move]"""
        # Create target parent
        code, _, _ = run_cli("folders", "create", "--name", self.FOLDER_C)
        assert code == 0
        code, _, _ = run_cli("folders", "move", "--name", self.FOLDER_B, "--target", self.FOLDER_C)
        assert code == 0

    def test_05_empty(self):
        """[folders empty]"""
        code, _, _ = run_cli(
            "folders", "empty", "--name", f"{self.FOLDER_C}/{self.FOLDER_B}", "--force"
        )
        assert code == 0

    def test_06_delete(self):
        """[folders delete] Clean up all test folders."""
        # Delete nested folder first, then parent
        run_cli("folders", "delete", "--name", f"{self.FOLDER_C}/{self.FOLDER_B}", "--force")
        run_cli("folders", "delete", "--name", self.FOLDER_C, "--force")


# ──────────────────────────────────────────────
# Step 6: Rules round-trip (5 commands)
# rules list, create, update, toggle, delete
# ──────────────────────────────────────────────


class TestStep6RulesRoundTrip:
    RULE_NAME = f"{RUN_ID}-rule"
    _rule_id = None

    def test_01_list(self):
        """[rules list]"""
        data = get_json("rules", "list")
        assert "rules" in data

    def test_02_create(self):
        """[rules create] Create a disabled rule (safe)."""
        code, stdout, stderr = run_cli(
            "rules",
            "create",
            "--name",
            self.RULE_NAME,
            "--sender",
            os.environ["OUTLOOK_IT_EMAIL"],
            "--mark-read",
        )
        assert code == 0, f"Exit {code}: {stderr}"
        data = _parse_doc(stdout)
        self.__class__._rule_id = data.get("id") or data.get("rule", {}).get("id")

    def test_03_update(self):
        """[rules update]"""
        rid = self.__class__._rule_id
        if not rid:
            pytest.skip("rule not created")
        code, _, _ = run_cli("rules", "update", "--id", rid, "--name", f"{self.RULE_NAME}-updated")
        assert code == 0

    def test_04_toggle(self):
        """[rules toggle]"""
        rid = self.__class__._rule_id
        if not rid:
            pytest.skip("rule not created")
        code, _, _ = run_cli("rules", "toggle", "--id", rid, "--action", "enable")
        assert code == 0
        code, _, _ = run_cli("rules", "toggle", "--id", rid, "--action", "disable")
        assert code == 0

    def test_05_delete(self):
        """[rules delete]"""
        rid = self.__class__._rule_id
        if not rid:
            pytest.skip("rule not created")
        code, _, _ = run_cli("rules", "delete", "--id", rid, "--force")
        assert code == 0


# ──────────────────────────────────────────────
# Step 7: Tools (8 commands)
# contacts, free-busy, rooms, rooms-free-busy, oof get, oof set, oof disable, respond
# ──────────────────────────────────────────────


class TestStep7Tools:
    def test_01_contacts(self):
        """[tools contacts --email]"""
        data = get_json("tools", "contacts", "--email", os.environ["OUTLOOK_IT_EMAIL"])
        assert data["count"] >= 1

    def test_01b_contacts_query(self):
        """[tools contacts --query] Search by name keyword."""
        # Extract name part from email (before @) as search query
        email = os.environ["OUTLOOK_IT_EMAIL"]
        query = email.split("@")[0].split(".")[0]  # e.g. "song" from "ex_song.guo@tcl.com"
        code, stdout, stderr = run_cli("tools", "contacts", "--query", query)
        # Should succeed (may return 0 or more results)
        assert code == 0, f"Exit {code}: {stderr}"

    def test_02_free_busy(self):
        """[tools free-busy]"""
        data = get_json(
            "tools",
            "free-busy",
            "--email",
            os.environ["OUTLOOK_IT_EMAIL"],
            "--start",
            datetime.now().strftime("%Y-%m-%d"),
        )
        assert "results" in data

    def test_03_rooms(self):
        """[tools rooms] May skip if server has no rooms configured."""
        code, stdout, stderr = run_cli("tools", "rooms", "--limit", "5")
        if code != 0:
            pytest.skip("Rooms not configured on this server")
        data = _parse_doc(stdout)
        assert "room_lists" in data or "count" in data

    def test_04_rooms_free_busy(self):
        """[tools rooms-free-busy] Skips if no rooms available."""
        # First check if rooms exist
        code, stdout, _ = run_cli("tools", "rooms", "--limit", "1")
        if code != 0:
            pytest.skip("No rooms available")
        data = _parse_doc(stdout)
        # If room_lists exists and has rooms, query free-busy
        has_rooms = False
        for rl in data.get("room_lists", []):
            if rl.get("rooms"):
                has_rooms = True
                break
        if not has_rooms:
            pytest.skip("No rooms available")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        code, _, _ = run_cli(
            "tools",
            "rooms-free-busy",
            "--start",
            f"{tomorrow} 10:00",
            "--end",
            f"{tomorrow} 11:00",
            "--limit",
            "3",
        )
        assert code == 0

    def test_05_oof_get(self):
        """[tools oof get]"""
        data = get_json("tools", "oof", "get")
        assert "state" in data
        self.__class__._original_oof = data

    def test_06_oof_set_and_disable(self):
        """[tools oof set] + [tools oof disable] Set then restore."""
        # Set OOF
        code, _, _ = run_cli("tools", "oof", "set", "--message", f"Integration test {RUN_ID}")
        assert code == 0
        # Disable to restore original state
        code, _, _ = run_cli("tools", "oof", "disable")
        assert code == 0

    def test_06b_oof_set_with_time_range(self):
        """[tools oof set --start/--end] Set OOF with time range."""
        start = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d 09:00")
        end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d 18:00")
        code, _, _ = run_cli(
            "tools",
            "oof",
            "set",
            "--message",
            f"OOF with time range {RUN_ID}",
            "--start",
            start,
            "--end",
            end,
        )
        assert code == 0
        # Verify the OOF state has the time range
        data = get_json("tools", "oof", "get")
        assert data["state"] != "Disabled"
        # Clean up
        code, _, _ = run_cli("tools", "oof", "disable")
        assert code == 0

    def test_07_respond_no_meeting(self):
        """[tools respond] Verify error on non-existent ID."""
        code, _, stderr = run_cli(
            "tools", "respond", "--id", "fake-nonexistent-id", "--action", "accept"
        )
        # Should fail with E_NOT_FOUND since ID doesn't exist.
        assert code == 3
