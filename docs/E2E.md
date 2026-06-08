# End-to-End Tests

The default CI test suite does not require a real Exchange mailbox. Live tests
are opt-in because they send mail to the configured account, create temporary
calendar events, create folders, create inbox rules, and then clean them up.

## Environment

Set these variables before running live tests:

```bash
OUTLOOK_IT_EMAIL=user@example.com
OUTLOOK_IT_PASSWORD=your-password
OUTLOOK_IT_SERVER=mail.example.com   # optional
```

The test runner sets `OUTLOOK_PERMISSIONS=full` for the subprocesses it starts.

## Command

```bash
python -m pytest tests/test_integration.py -v
```

## Safety

- Tests generate subjects and folder names with a unique `IT-YYYYMMDD-HHMMSS`
  prefix.
- Tests operate on the current user's mailbox only.
- Cleanup uses soft delete where message deletion is required.
- If a test is interrupted, search for the run prefix and clean up remaining
  test messages, folders, calendar events, or rules manually.
