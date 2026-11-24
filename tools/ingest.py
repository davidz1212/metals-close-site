"""把采集层产出的 JSON 快照导入 SQLite。

用法：
    python tools/ingest.py                      # 导入 data/seed 下全部 YYYY-MM-DD.json
    python tools/ingest.py --date 2026-11-13    # 只导入指定日期
    python tools/ingest.py --source <目录>       # 指定源文件目录

文件命名约定（同一目录下）：
    2026-11-13.json              必填，完整快照
    ratio-percentile.json        可选，金银比百分位排名
    ratio-history.json           可选，金银比历史序列
    curves.json                  可选，库存/交割观察曲线
    close-verification.json      可选，收盘价交叉核验
也可使用 2026-11-13.ratio-percentile.json 这类带日期前缀的文件覆盖通用文件。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import db  # noqa: E402

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
DATASETS = ("ratio-percentile", "ratio-history", "curves", "close-verification")


def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="ingest daily report JSON into SQLite")
    parser.add_argument("--source", default=str(ROOT / "data" / "seed"))
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_dir():
        print(f"ERROR: source not found: {source}")
        return 1

    db.init_db()
    snapshots: list[tuple[str, Path]] = []
    for path in sorted(source.glob("*.json")):
        m = DATE_RE.match(path.name)
        if m and (args.date is None or m.group(1) == args.date):
            snapshots.append((m.group(1), path))

    if not snapshots:
        print("No snapshot files matched.")
        return 1

    for report_date, path in snapshots:
        payload = load_json(path)
        if not isinstance(payload, dict):
            print(f"SKIP {path.name}: invalid JSON object")
            continue
        extra: dict[str, dict | None] = {}
        for dataset in DATASETS:
            dated = source / f"{report_date}.{dataset}.json"
            common = source / f"{dataset}.json"
            extra[dataset] = load_json(dated if dated.exists() else common)

        existed = db.upsert_report(
            report_date,
            payload,
            heatmap=extra["ratio-percentile"],
            ratio_history=extra["ratio-history"],
            curves=extra["curves"],
            verification=extra["close-verification"],
        )
        print(
            f"{'UPDATE' if existed else 'INSERT'} {report_date} "
            f"fields={len(payload.get('fields') or {})} "
            f"datasets=" + ",".join(k for k, v in extra.items() if v)
        )

    print(f"DONE: {db.counts()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
