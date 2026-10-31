from datetime import date

import pandas as pd
import pytest

from app.domain.simulator import Feed, simulate
from ml.features import training_rows

START = date(2026, 1, 1)


@pytest.fixture(scope="session")
def feed() -> Feed:
    return simulate(START, 90)


@pytest.fixture(scope="session")
def rows(feed: Feed) -> pd.DataFrame:
    return training_rows(feed.telemetry, feed.failures)
