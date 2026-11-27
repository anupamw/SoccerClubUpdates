import argparse
import json
import time

from app.core.config import get_settings
from app.core.football_data import (
    DEFAULT_REFRESH_INTERVAL_SECONDS,
    collect_league,
    has_recent_success,
    has_successful_collection,
    initialize_league_database,
)


def run(run_once: bool = False) -> None:
    settings = get_settings()
    if settings.data_collection_mode not in {"once", "daily"}:
        raise ValueError("DATA_COLLECTION_MODE must be 'once' or 'daily'")
    initialize_league_database()
    if run_once:
        print(json.dumps(collect_league(), sort_keys=True))
        return
    if settings.data_collection_mode == "once":
        if not has_successful_collection():
            print(json.dumps(collect_league(), sort_keys=True))
        while True:
            time.sleep(60 * 60)
    while True:
        if not has_recent_success():
            print(json.dumps(collect_league(), sort_keys=True))
        time.sleep(DEFAULT_REFRESH_INTERVAL_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-once", action="store_true")
    run(parser.parse_args().run_once)
