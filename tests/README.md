# Test Suite

This project now keeps executable tests under `tests/` only.

Run against a live API:

```bash
pytest -q
```

If the API is not listening on the default address, set `TEST_API_BASE_URL`:

```bash
TEST_API_BASE_URL=http://127.0.0.1:8001 pytest -q
```

The suite prefers a running service and auto-detects `http://127.0.0.1:8000`
first, then `http://127.0.0.1:8001`.
