"""ADR-012: writes the synthetic fleet feed as the two files of the `fleet-feed` data asset that `prep` reads."""

import argparse
from datetime import date
from pathlib import Path

from app.domain.simulator import simulate


def write(out: Path, start: date, days: int, firmware_b_from: date | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for table, frame in simulate(start, days, firmware_b_from=firmware_b_from)._asdict().items():
        frame.to_parquet(out / f"{table}.parquet", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="ops.feed")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--firmware-b-from", type=date.fromisoformat)
    args = parser.parse_args()
    write(args.out, args.start, args.days, args.firmware_b_from)
