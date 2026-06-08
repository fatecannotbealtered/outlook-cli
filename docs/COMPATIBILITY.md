# Compatibility

outlook-cli talks to Outlook/Exchange through Exchange Web Services (EWS) via
`exchangelib`.

## Supported Targets

| Target | Status | Notes |
|--------|--------|-------|
| Exchange Server 2016 | Expected | Requires EWS enabled and username/password authentication accepted by policy. |
| Exchange Server 2019 | Expected | Requires EWS enabled and username/password authentication accepted by policy. |
| Microsoft 365 / Exchange Online | Conditional | Works only where EWS and the configured auth method are allowed by tenant policy. |
| Shared mailboxes | Conditional | Requires delegate permission; use `--account` or `OUTLOOK_SHARED_MAILBOX`. |

## Known Limits

- OAuth-only tenants may reject username/password auth.
- Room list, room availability, inbox rules, and OOF support depend on server
  policy and EWS feature availability.
- IDs returned by list/search commands are Exchange item IDs and should be
  treated as opaque strings.
- All command output times are ISO 8601 UTC; command input accepts ISO 8601 and
  legacy local forms for operator convenience.

## Verification

Run:

```bash
outlook-cli doctor
outlook-cli setup doctor
outlook-cli reference --compact
```

For live end-to-end verification, see `docs/E2E.md`.
