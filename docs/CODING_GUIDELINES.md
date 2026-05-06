# Coding Guidelines — Agent Branch

These apply to all code in `backend/agent/`, `backend/worker/`, and `frontend/dashboard/`.

---

## 1. Project Structure
- Separate routers, services, schemas — no 600-line `main.py`
- Prompts in `.txt` files, never inline strings
- One obvious purpose per file
- No `utils.py`, `helpers.py`, `misc.py` — use descriptive names
- `APIRouter` from day one

## 2. Async Everywhere
- Zero blocking I/O in request paths
- `httpx.AsyncClient` for all HTTP calls
- SQLAlchemy 2.0 async with `asyncpg`
- `redis.asyncio` for Redis
- `AsyncOpenAI` for LLM calls
- `asyncio.gather()` for concurrent operations
- Open async clients **once** in lifespan, reuse across requests

## 3. Lifespan & Singletons
- `@asynccontextmanager` lifespan function on every FastAPI app
- Attach shared resources to `app.state` (llm, http, redis, db engine)
- Shutdown handler disposes everything cleanly
- No module-level globals for resources
- No clients constructed inside route handlers

## 4. Dependency Injection
- Routes declare needs with `Depends()`
- `dependencies.py` provides: `get_session`, `get_llm`, `get_http_client`, `get_redis`, `get_settings`
- DB session uses `yield` pattern (auto-closes on response complete)
- `app.dependency_overrides` for tests — no monkey-patching
- No manual session construction in routes

## 5. Configuration
- Single `Settings` class with `pydantic-settings`, `extra="forbid"`
- Required fields with `Field(...)` — app refuses to start if missing
- `@lru_cache(maxsize=1)` wrapper — loaded once, reused everywhere
- No `os.getenv()` outside the `Settings` class
- `.env.example` with placeholder values committed to git

## 6. Pydantic at Every Boundary
- Every external data crossing a service boundary gets a Pydantic model
- Webhook payload, triage result, action decision, HIL requests, queue tasks — all typed
- LLM structured outputs use Pydantic models (no regex parsing)
- Validate once at the boundary — trust types inside the service
- `Literal` types for constrained values, `Field()` for constraints

## 7. Error Handling
- No bare `except:` — catch specific exception types
- Never silently swallow exceptions — always log
- `HTTPException` with correct status codes (never `200 OK` with an error body)
- No stack traces to clients — log full traceback server-side
- Structured errors: `{"error": "...", "retryable": true/false}` from tools
- Every external call has timeout: `httpx.AsyncClient(timeout=10.0)`

## 8. Retries
- `tenacity` for all retry logic with exponential backoff
- Retry only transient errors: timeouts, network failures, HTTP 429
- **Never** retry 4xx client errors
- Always set a maximum attempt count
- Webhook send failures: log but do not fail the prediction response

## 9. Logging
- `structlog` for JSON-structured logging — never `print()`
- Log with named fields: `log.info("investigation.started", alert_id=..., feature=...)`
- Never log secrets, API keys, passwords, or PII
- Use correct levels: DEBUG (dev), INFO (normal ops), WARNING (unexpected but handled), ERROR (needs attention), CRITICAL (system broken)

## 10. Caching
- `@lru_cache(maxsize=1)` on the Settings getter
- Also on deterministic, expensive, pure functions
- TTL cache for external calls stable within time windows
- Never cache: auth tokens, mutable config, expiring items

## 11. Prompts
- All prompts in `backend/agent/prompts/` as `.txt` files
- Separate system prompt from user prompt
- Prompts are code — version-control them, review them, defend them in the presentation

## 12. API Contracts
- `response_model=` on every endpoint — no raw DB rows returned
- Response model exposes only what the client needs
- HTTP status codes: `202` (accepted), `400` (bad request), `401` (auth), `404` (not found), `409` (conflict), `422` (validation), `500` (server error)

## 13. Security
- `.env` in `.gitignore` from commit zero
- `.env.example` with placeholder values committed
- No hardcoded secrets or API keys anywhere
- `gitleaks` pre-commit hook
- Agent endpoints validated with `X-Agent-Key` shared secret header
- Rotate immediately if a secret is accidentally committed

## 14. Git Hygiene
- Branch: `feature/agent`
- Conventional commits: `feat(agent):`, `fix(agent):`, `test(agent):`, `refactor(agent):`
- Imperative mood: "add webhook router" not "added webhook router"
- Subject line under 72 characters, no trailing period
- No direct commits to `main`
- Squash commits before merging

## 15. Testing
- Test Pydantic schemas with valid and invalid inputs
- Test each agent function in isolation with mocked LLM (`MockLLM`)
- One end-to-end test through the full supervisor flow with all external calls mocked
- `MockLLM` class: keyword-based dictionary responses, exposes `call_count` and `last_prompt`
- AAA pattern: Arrange → Act → Assert
- GitHub Actions on every push and PR
- Minimum 80% coverage on critical paths (triage, action, checkpoint, HIL)
- Never test third-party libraries or framework boilerplate

## 16. Docker
- One service per container — agent has its own Dockerfile
- Reference services by Docker Compose service names, never hardcoded IPs
- Named volumes for Postgres and Redis
- Environment variables via `docker-compose.yml` — never hardcoded in images
- `.dockerignore` excludes: `.git`, `.env`, `__pycache__`, `.venv`, `tests/`, `docs/`

## 17. Documentation
- Inline comments explain **WHY**, never **WHAT** (the code already shows what)
- Docstrings only on public modules and non-obvious functions
- README: what it is, how to set up, how to run, env vars, structure

## 18. Antipatterns — Never Do These

| ❌ Don't | ✅ Do instead |
|----------|--------------|
| `os.getenv()` scattered | Single `Settings` class |
| `print()` in production | `structlog` |
| Bare `except:` | Catch specific exceptions |
| `except: pass` | Log + re-raise or handle explicitly |
| `200 OK` with error body | Correct HTTP status code |
| Blocking I/O in async | `await` everything |
| Module-level globals for resources | `app.state` via lifespan |
| New client per request | Lifespan singletons |
| Inline prompt strings | `.txt` files in `prompts/` |
| Hardcoded URLs / model names | Settings class + env vars |
| Committing `.venv/`, `.env`, secrets | `.gitignore` from day one |
