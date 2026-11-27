# Soccer Club Updates

A Dockerized Python/FastAPI Premier League dashboard. League tables and fixtures are collected in bulk from football-data.org and served from the app's persistent SQLite database.

## Run

```sh
docker compose up --build --detach --wait api
```

Open `http://localhost:8000/`. Create an account or use the demo login `fan` / `change-me`.

## League data

- The collector uses the competition, teams, standings, and matches bulk endpoints (four calls per successful refresh, plus any bounded retries) for the configured competition and current season.
- Provider data and account data share the persistent SQLite database at `DATABASE_PATH`; API reads use this local cache and never call football-data.org.
- Collection starts in `once` mode by default. `daily` mode refreshes on startup and every four hours.
- A transactionally reserved, persisted SQLite call ledger enforces a maximum of nine provider calls in every rolling hour, including retries, concurrent collectors, and restarts. A process lock coalesces overlapping refreshes.
- Freshness, sanitized sync outcomes, last-updated time, and remaining call budget are shown on the data-backed views. Cached records remain readable after collection errors.
- Overview, Matches, and Table use provider-backed league data. News and Squad explicitly remain outside this integration.
- football-data.org Free includes Premier League fixtures and league tables; goal scorers are not included in Free, so the collector does not request or require paid-tier event data. The normalized event schema retains source minute, period, and timestamp precision if a supported source is added later.

## Local provider configuration

Compose reads a local `.env` file automatically. Copy the example and add your football-data.org token locally; do not share the token or commit `.env`:

```sh
test -e .env || cp .env.example .env
```

Set `FOOTBALL_DATA_API_TOKEN` in `.env`. Optional non-secret settings are `FOOTBALL_DATA_BASE_URL`, `FOOTBALL_DATA_COMPETITION_CODE`, and `DATA_COLLECTION_MODE=once|daily`. The collector records a sanitized unavailable status if the token is not configured. Do not print or paste the token into logs or issue content.

The collector runs as a Compose dependency of the API. In `once` mode, it makes the initial request once after a successful collection and remains idle; after adding a token to an already-running setup, run `docker compose run --rm collector python -m app.collector --run-once` to retry. In `daily` mode, its long-running service refreshes every four hours and skips a refresh when a successful collection is still within that interval.

## Test

```sh
docker compose run --rm test
docker compose run --rm browser-test
```

GitHub Actions runs both suites on pull requests and pushes to `main`.

## API

```sh
curl http://localhost:8000/health/live
curl http://localhost:8000/api/v1/clubs
curl http://localhost:8000/api/v1/club/feed
curl http://localhost:8000/api/v1/league
curl http://localhost:8000/api/v1/league/matches
curl http://localhost:8000/api/v1/league/standings
curl http://localhost:8000/api/v1/debugstats
```

## Configuration

Use a strong `JWT_SECRET` outside local development. The account/league database and API statistics database use separate Compose named volumes.
