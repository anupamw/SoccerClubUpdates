# Soccer Club Updates

A Dockerized Python/FastAPI fan dashboard for following Manchester United in the Premier League. The app deliberately starts with EPL/Manchester United only while the club-selector model is prepared for future fan preferences.

## Run

```sh
docker compose up --build --detach --wait api
```

Open `http://localhost:8000/`. Create an account or use the demo login `fan` / `change-me`.

## Features

- Signed-in fan dashboard
- Premier League and Manchester United selection, currently restricted to that one valid combination
- Overview, Matches, Club News, Squad, League Table, and Password views
- Signup, sign-in, account lookup, password change, and logout
- SQLite account persistence with PBKDF2-HMAC-SHA256 password hashes
- Separate SQLite API request statistics
- Browser-accessible demo club data; no live football or news provider is connected

## Test

```sh
docker compose run --build --rm test
docker compose run --build --rm browser-test
```

GitHub Actions runs both suites on pull requests and pushes to `main`.

## API

```sh
curl http://localhost:8000/health/live
curl http://localhost:8000/api/v1/clubs
curl http://localhost:8000/api/v1/club/feed
curl http://localhost:8000/api/v1/debugstats
```

## Configuration

Copy `.env.example` to `.env` for local overrides. Use a strong `JWT_SECRET` outside local development. The account and API statistics databases use separate Compose named volumes.
