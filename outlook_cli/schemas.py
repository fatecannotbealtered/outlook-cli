"""Machine-readable output schemas for every leaf command.

The reference command embeds these so an agent knows the exact shape of each
command's `data` payload before invoking it. Field lists are derived from the
real dict-builders in commands/*.py and exchange.py; `untrusted_fields` mirrors
the `_untrusted` lists those builders emit (external data, not instructions).

Three maps wire it together:
  OUTPUT_SCHEMAS   label -> {shape, fields, untrusted_fields}
  COMMAND_SCHEMAS  "group sub" command path -> schema label
  COMMAND_EXAMPLES "group sub" command path -> [runnable command strings]
"""

# label -> schema definition. `shape` is "object" or "array"; an "array" label
# describes one element of the list named in its parent envelope.
OUTPUT_SCHEMAS: dict[str, dict] = {
    # --- shared item shapes ---
    "email": {
        "shape": "object",
        "fields": [
            "id",
            "subject",
            "sender",
            "to",
            "cc",
            "date",
            "is_read",
            "has_attachments",
            "preview",
            "_untrusted",
        ],
        "untrusted_fields": ["subject", "sender", "to", "cc", "preview"],
    },
    "calendar_event": {
        "shape": "object",
        "fields": [
            "id",
            "changekey",
            "subject",
            "start",
            "end",
            "location",
            "organizer",
            "attendees",
            "body",
            "is_all_day",
            "_untrusted",
        ],
        "untrusted_fields": [
            "subject",
            "location",
            "organizer",
            "attendees.email",
            "body",
        ],
    },
    # --- mail list-style commands ---
    "mail_list": {
        "shape": "object",
        "fields": [
            "count",
            "total",
            "offset",
            "has_more",
            "next_offset",
            "folder",
            "emails",
        ],
        "untrusted_fields": [
            "emails.subject",
            "emails.sender",
            "emails.to",
            "emails.cc",
            "emails.preview",
        ],
    },
    "mail_search": {
        "shape": "object",
        "fields": [
            "count",
            "total",
            "offset",
            "has_more",
            "next_offset",
            "emails",
        ],
        "untrusted_fields": [
            "emails.subject",
            "emails.sender",
            "emails.to",
            "emails.cc",
            "emails.preview",
        ],
    },
    "mail_read": {
        "shape": "object",
        "fields": [
            "id",
            "subject",
            "sender",
            "to",
            "cc",
            "date",
            "is_read",
            "has_attachments",
            "body",
            "attachments",
            "inline_images",
            "_untrusted",
        ],
        "untrusted_fields": [
            "subject",
            "sender",
            "to",
            "cc",
            "body",
            "attachments.name",
            "inline_images.filename",
            "inline_images.cid",
        ],
    },
    "mail_stats": {
        "shape": "object",
        "fields": [
            "period",
            "folder",
            "total",
            "unread",
            "read",
            "with_attachments",
            "top_senders",
            "by_day",
            "_untrusted",
        ],
        "untrusted_fields": ["top_senders.sender"],
    },
    "mail_thread": {
        "shape": "object",
        "fields": ["subject", "count", "thread"],
        "untrusted_fields": [
            "thread.subject",
            "thread.sender",
            "thread.to",
            "thread.cc",
            "thread.preview",
        ],
    },
    "mail_attachment_summary": {
        "shape": "object",
        "fields": [
            "count",
            "total",
            "offset",
            "has_more",
            "next_offset",
            "emails",
        ],
        "untrusted_fields": [
            "emails.subject",
            "emails.sender",
            "emails.attachments.name",
        ],
    },
    "mail_drafts": {
        "shape": "object",
        "fields": [
            "count",
            "total",
            "offset",
            "has_more",
            "next_offset",
            "drafts",
        ],
        "untrusted_fields": [
            "drafts.subject",
            "drafts.sender",
            "drafts.to",
            "drafts.cc",
            "drafts.preview",
        ],
    },
    "mail_draft_read": {
        "shape": "object",
        "fields": ["id", "subject", "to", "cc", "bcc", "body", "_untrusted"],
        "untrusted_fields": ["subject", "to", "cc", "bcc", "body"],
    },
    # --- write/result acknowledgements ---
    "mail_export_result": {
        "shape": "object",
        "fields": ["message", "path", "size"],
    },
    "mail_download_result": {
        "shape": "object",
        "fields": ["message", "files"],
    },
    "mail_action_result": {
        "shape": "object",
        "fields": ["message", "subject"],
    },
    "mail_categorize_result": {
        "shape": "object",
        "fields": ["message", "subject", "categories"],
    },
    "mail_batch_result": {
        "shape": "object",
        "fields": ["message", "success", "total", "failed_ids", "results"],
    },
    "mail_send_result": {
        "shape": "object",
        "fields": ["message", "to", "subject", "sent"],
    },
    "mail_reply_result": {
        "shape": "object",
        "fields": ["message", "original_subject", "sent"],
    },
    "mail_forward_result": {
        "shape": "object",
        "fields": ["message", "to", "original_subject", "sent"],
    },
    "mail_draft_edit_result": {
        "shape": "object",
        "fields": ["message", "id", "subject", "updated"],
    },
    # --- calendar ---
    "cal_list": {
        "shape": "object",
        "fields": [
            "total",
            "count",
            "offset",
            "has_more",
            "next_offset",
            "events",
        ],
        "untrusted_fields": [
            "events.subject",
            "events.location",
            "events.organizer",
            "events.attendees.email",
            "events.body",
        ],
    },
    "cal_create_result": {
        "shape": "object",
        "fields": ["message", "subject", "start", "end", "recurrence"],
    },
    "cal_update_result": {
        "shape": "object",
        "fields": ["message", "updated_fields", "event"],
        "untrusted_fields": [
            "event.subject",
            "event.location",
            "event.organizer",
            "event.attendees.email",
            "event.body",
        ],
    },
    "cal_delete_result": {
        "shape": "object",
        "fields": ["message", "subject"],
    },
    # --- folders ---
    "folders_list": {
        "shape": "object",
        "fields": ["count", "folders"],
        "untrusted_fields": ["folders.name"],
    },
    "folders_create_result": {
        "shape": "object",
        "fields": ["message", "created"],
    },
    "folders_message_result": {
        "shape": "object",
        "fields": ["message"],
    },
    # --- rules ---
    "rules_list": {
        "shape": "object",
        "fields": ["count", "rules"],
        "untrusted_fields": [
            "rules.name",
            "rules.conditions",
            "rules.actions",
            "rules.exceptions",
        ],
    },
    "rules_write_result": {
        "shape": "object",
        "fields": ["message", "rule"],
        "untrusted_fields": [
            "rule.name",
            "rule.conditions",
            "rule.actions",
            "rule.exceptions",
        ],
    },
    "rules_message_result": {
        "shape": "object",
        "fields": ["message"],
    },
    "rules_toggle_result": {
        "shape": "object",
        "fields": ["message", "is_enabled"],
    },
    # --- tools ---
    "tools_contacts": {
        "shape": "object",
        "fields": ["count", "contacts"],
        "untrusted_fields": [
            "contacts.name",
            "contacts.email",
            "contacts.department",
            "contacts.title",
            "contacts.phone",
        ],
    },
    "tools_free_busy": {
        "shape": "object",
        "fields": ["results", "suggested_free_slots"],
    },
    "tools_rooms": {
        "shape": "object",
        "fields": ["total_rooms", "count", "room_lists"],
        "untrusted_fields": ["room_lists.rooms.name", "room_lists.rooms.email"],
    },
    "tools_rooms_free_busy": {
        "shape": "object",
        "fields": [
            "period",
            "queried",
            "available_count",
            "busy_count",
            "available",
            "busy",
        ],
        "untrusted_fields": ["available.name", "available.email", "busy.name", "busy.email"],
    },
    "tools_oof_get": {
        "shape": "object",
        "fields": [
            "state",
            "internal_reply",
            "external_reply",
            "start",
            "end",
            "_untrusted",
        ],
        "untrusted_fields": ["internal_reply", "external_reply"],
    },
    "tools_message_result": {
        "shape": "object",
        "fields": ["message"],
    },
    "tools_respond_result": {
        "shape": "object",
        "fields": ["message", "subject", "source"],
    },
    # --- setup ---
    "setup_login_result": {
        "shape": "object",
        "fields": ["email", "server", "timezone", "permissions"],
    },
    "setup_status": {
        "shape": "object",
        "fields": [
            "configured",
            "email",
            "server",
            "timezone",
            "config_file",
            "permissions",
        ],
    },
    "setup_doctor": {
        "shape": "object",
        "fields": ["connection", "email", "inbox_total", "inbox_unread"],
    },
    # --- self-description commands ---
    "reference": {
        "shape": "object",
        "fields": [
            "tool",
            "version",
            "schema_version",
            "risk_tier",
            "minimum_skill_version",
            "release_readiness",
            "permission_levels",
            "security",
            "output",
            "global_options",
            "exit_codes",
            "commands",
            "schemas",
        ],
    },
    "context": {
        "shape": "object",
        "fields": [
            "tool",
            "version",
            "schema_version",
            "env",
            "account",
            "configured",
            "config",
            "credentials",
            "skill",
            "notices",
        ],
    },
    "doctor": {
        "shape": "object",
        "fields": ["checks", "notices"],
    },
    "changelog": {
        "shape": "object",
        "fields": ["current_version", "since", "entries"],
    },
    "update_check": {
        "shape": "object",
        "fields": [
            "current_version",
            "latest_version",
            "update_available",
            "install_method",
            "notices",
        ],
    },
    "update_result": {
        "shape": "object",
        "fields": [
            "preview",
            "confirm_token",
            "expires_at",
            "current_version",
            "previous_version",
            "target_version",
            "install_method",
            "supported",
            "command",
            "signature_status",
            "skill_sync_command",
            "skill_sync_status",
            "manual_url",
            "next_step",
        ],
    },
}

# command path -> schema label.
COMMAND_SCHEMAS: dict[str, str] = {
    # mail
    "mail list": "mail_list",
    "mail search": "mail_search",
    "mail read": "mail_read",
    "mail stats": "mail_stats",
    "mail thread": "mail_thread",
    "mail attachment-summary": "mail_attachment_summary",
    "mail export": "mail_export_result",
    "mail download-attachment": "mail_download_result",
    "mail move": "mail_action_result",
    "mail mark": "mail_action_result",
    "mail flag": "mail_action_result",
    "mail categorize": "mail_categorize_result",
    "mail restore": "mail_action_result",
    "mail batch": "mail_batch_result",
    "mail delete": "mail_action_result",
    "mail send": "mail_send_result",
    "mail reply": "mail_reply_result",
    "mail reply-all": "mail_reply_result",
    "mail forward": "mail_forward_result",
    "mail drafts": "mail_drafts",
    "mail draft-read": "mail_draft_read",
    "mail draft-edit": "mail_draft_edit_result",
    "mail draft-send": "mail_reply_result",
    "mail draft-delete": "mail_action_result",
    # calendar
    "cal list": "cal_list",
    "cal get": "calendar_event",
    "cal create": "cal_create_result",
    "cal update": "cal_update_result",
    "cal delete": "cal_delete_result",
    # folders
    "folders list": "folders_list",
    "folders create": "folders_create_result",
    "folders rename": "folders_message_result",
    "folders move": "folders_message_result",
    "folders empty": "folders_message_result",
    "folders delete": "folders_message_result",
    # rules
    "rules list": "rules_list",
    "rules create": "rules_write_result",
    "rules update": "rules_write_result",
    "rules delete": "rules_message_result",
    "rules toggle": "rules_toggle_result",
    # tools
    "tools contacts": "tools_contacts",
    "tools free-busy": "tools_free_busy",
    "tools rooms": "tools_rooms",
    "tools rooms-free-busy": "tools_rooms_free_busy",
    "tools oof get": "tools_oof_get",
    "tools oof set": "tools_message_result",
    "tools oof disable": "tools_message_result",
    "tools respond": "tools_respond_result",
    # setup
    "setup login": "setup_login_result",
    "setup status": "setup_status",
    "setup doctor": "setup_doctor",
    # self-description
    "reference": "reference",
    "context": "context",
    "doctor": "doctor",
    "changelog": "changelog",
    "update": "update_result",
}

# command path -> runnable examples. Read commands use --compact; mutating
# commands show the dry-run -> confirm flow.
COMMAND_EXAMPLES: dict[str, list[str]] = {
    # mail
    "mail list": ["outlook-cli mail list --filter unread --limit 20 --compact"],
    "mail search": ["outlook-cli mail search --subject invoice --days 30 --compact"],
    "mail read": ["outlook-cli mail read --id <mail_id> --compact"],
    "mail stats": ["outlook-cli mail stats --days 7 --top 10 --compact"],
    "mail thread": ["outlook-cli mail thread --id <mail_id> --compact"],
    "mail attachment-summary": [
        "outlook-cli mail attachment-summary --days 7 --ext pdf,xlsx --compact"
    ],
    "mail export": [
        "outlook-cli mail export --id <mail_id> --output-dir . --dry-run --compact",
        "outlook-cli mail export --id <mail_id> --output-dir . --confirm <token> --compact",
    ],
    "mail download-attachment": [
        "outlook-cli mail download-attachment --id <mail_id> --dry-run --compact",
        "outlook-cli mail download-attachment --id <mail_id> --confirm <token> --compact",
    ],
    "mail move": [
        "outlook-cli mail move --id <mail_id> --folder Archive --dry-run --compact",
        "outlook-cli mail move --id <mail_id> --folder Archive --confirm <token> --compact",
    ],
    "mail mark": [
        "outlook-cli mail mark --id <mail_id> --status read --dry-run --compact",
        "outlook-cli mail mark --id <mail_id> --status read --confirm <token> --compact",
    ],
    "mail flag": [
        "outlook-cli mail flag --id <mail_id> --action flag --dry-run --compact",
        "outlook-cli mail flag --id <mail_id> --action flag --confirm <token> --compact",
    ],
    "mail categorize": [
        "outlook-cli mail categorize --id <mail_id> --action add --categories Red --dry-run",
        "outlook-cli mail categorize --id <mail_id> --action add --categories Red"
        " --confirm <token>",
    ],
    "mail restore": [
        "outlook-cli mail restore --id <mail_id> --dry-run --compact",
        "outlook-cli mail restore --id <mail_id> --confirm <token> --compact",
    ],
    "mail batch": [
        "outlook-cli mail batch --ids <id1>,<id2> --action mark-read --dry-run --compact",
        "outlook-cli mail batch --ids <id1>,<id2> --action mark-read --confirm <token> --compact",
    ],
    "mail delete": [
        "outlook-cli mail delete --id <mail_id> --dry-run --compact",
        "outlook-cli mail delete --id <mail_id> --confirm <token> --compact",
    ],
    "mail send": [
        'outlook-cli mail send --to a@co.com --subject Hi --body "Hello" --dry-run',
        'outlook-cli mail send --to a@co.com --subject Hi --body "Hello" --confirm <token>',
    ],
    "mail reply": [
        'outlook-cli mail reply --id <mail_id> --body "Thanks" --dry-run --compact',
        'outlook-cli mail reply --id <mail_id> --body "Thanks" --confirm <token> --compact',
    ],
    "mail reply-all": [
        'outlook-cli mail reply-all --id <mail_id> --body "Thanks all" --dry-run',
        'outlook-cli mail reply-all --id <mail_id> --body "Thanks all" --confirm <token>',
    ],
    "mail forward": [
        "outlook-cli mail forward --id <mail_id> --to a@co.com --dry-run --compact",
        "outlook-cli mail forward --id <mail_id> --to a@co.com --confirm <token> --compact",
    ],
    "mail drafts": ["outlook-cli mail drafts --limit 20 --compact"],
    "mail draft-read": ["outlook-cli mail draft-read --id <draft_id> --compact"],
    "mail draft-edit": [
        'outlook-cli mail draft-edit --id <draft_id> --body "Updated" --dry-run',
        'outlook-cli mail draft-edit --id <draft_id> --body "Updated" --confirm <token>',
    ],
    "mail draft-send": [
        "outlook-cli mail draft-send --id <draft_id> --dry-run --compact",
        "outlook-cli mail draft-send --id <draft_id> --confirm <token> --compact",
    ],
    "mail draft-delete": [
        "outlook-cli mail draft-delete --id <draft_id> --dry-run --compact",
        "outlook-cli mail draft-delete --id <draft_id> --confirm <token> --compact",
    ],
    # calendar
    "cal list": ["outlook-cli cal list --days 7 --compact"],
    "cal get": ["outlook-cli cal get --id <event_id> --compact"],
    "cal create": [
        'outlook-cli cal create --subject Sync --start "2026-06-20 10:00" --end "2026-06-20 11:00"'
        " --dry-run",
        'outlook-cli cal create --subject Sync --start "2026-06-20 10:00" --end "2026-06-20 11:00"'
        " --confirm <token>",
    ],
    "cal update": [
        "outlook-cli cal update --id <event_id> --location Room1 --dry-run --compact",
        "outlook-cli cal update --id <event_id> --location Room1 --confirm <token> --compact",
    ],
    "cal delete": [
        "outlook-cli cal delete --id <event_id> --dry-run --compact",
        "outlook-cli cal delete --id <event_id> --confirm <token> --compact",
    ],
    # folders
    "folders list": ["outlook-cli folders list --max-depth 3 --compact"],
    "folders create": [
        "outlook-cli folders create --name Projects/Alpha --dry-run --compact",
        "outlook-cli folders create --name Projects/Alpha --confirm <token> --compact",
    ],
    "folders rename": [
        "outlook-cli folders rename --name Projects/Alpha --new-name Beta --dry-run",
        "outlook-cli folders rename --name Projects/Alpha --new-name Beta --confirm <token>",
    ],
    "folders move": [
        "outlook-cli folders move --name Projects/Alpha --target Archive --dry-run",
        "outlook-cli folders move --name Projects/Alpha --target Archive --confirm <token>",
    ],
    "folders empty": [
        "outlook-cli folders empty --name Projects/Alpha --dry-run --compact",
        "outlook-cli folders empty --name Projects/Alpha --confirm <token> --compact",
    ],
    "folders delete": [
        "outlook-cli folders delete --name Projects/Alpha --dry-run --compact",
        "outlook-cli folders delete --name Projects/Alpha --confirm <token> --compact",
    ],
    # rules
    "rules list": ["outlook-cli rules list --compact"],
    "rules create": [
        "outlook-cli rules create --name Triage --sender boss@co.com --move-to Important --dry-run",
        "outlook-cli rules create --name Triage --sender boss@co.com --move-to Important"
        " --confirm <token>",
    ],
    "rules update": [
        "outlook-cli rules update --id <rule_id> --priority 2 --dry-run --compact",
        "outlook-cli rules update --id <rule_id> --priority 2 --confirm <token> --compact",
    ],
    "rules delete": [
        "outlook-cli rules delete --id <rule_id> --dry-run --compact",
        "outlook-cli rules delete --id <rule_id> --confirm <token> --compact",
    ],
    "rules toggle": [
        "outlook-cli rules toggle --id <rule_id> --action disable --dry-run --compact",
        "outlook-cli rules toggle --id <rule_id> --action disable --confirm <token> --compact",
    ],
    # tools
    "tools contacts": ["outlook-cli tools contacts --query zhang --compact"],
    "tools free-busy": [
        "outlook-cli tools free-busy --email a@co.com --start 2026-06-20 --compact"
    ],
    "tools rooms": ["outlook-cli tools rooms --keyword floor3 --compact"],
    "tools rooms-free-busy": [
        'outlook-cli tools rooms-free-busy --start "2026-06-20 10:00" --end "2026-06-20 11:00"'
    ],
    "tools oof get": ["outlook-cli tools oof get --compact"],
    "tools oof set": [
        'outlook-cli tools oof set --message "Away" --dry-run --compact',
        'outlook-cli tools oof set --message "Away" --confirm <token> --compact',
    ],
    "tools oof disable": [
        "outlook-cli tools oof disable --dry-run --compact",
        "outlook-cli tools oof disable --confirm <token> --compact",
    ],
    "tools respond": [
        "outlook-cli tools respond --id <event_id> --action accept --dry-run --compact",
        "outlook-cli tools respond --id <event_id> --action accept --confirm <token> --compact",
    ],
    # setup
    "setup login": [
        "outlook-cli setup login --email user@co.com --password <pw> --dry-run --compact",
        "outlook-cli setup login --email user@co.com --password <pw> --confirm <token> --compact",
    ],
    "setup status": ["outlook-cli setup status --compact"],
    "setup doctor": ["outlook-cli setup doctor --compact"],
    # self-description
    "reference": ["outlook-cli reference --compact"],
    "context": ["outlook-cli context --compact"],
    "doctor": ["outlook-cli doctor --compact"],
    "changelog": ["outlook-cli changelog --since 1.0.0 --compact"],
    "update": [
        "outlook-cli update --check --compact",
        "outlook-cli update --dry-run --compact",
        "outlook-cli update --confirm <token> --compact",
    ],
}
