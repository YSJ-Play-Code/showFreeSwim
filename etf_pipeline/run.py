"""실행기.

  python -m etf_pipeline.run all                    # 1~5단계 전체
  python -m etf_pipeline.run all --krx-csv KRX.csv  # KRX CSV 를 직접 받은 경우
  python -m etf_pipeline.run managers | collect | krx | verify
"""
import argparse
import csv
import json
import sys

from . import krx as krxmod
from . import managers as mg
from . import prospectus as pr
from . import store, verify
from .config import DATA
from .http import FetchError


def _write_csv(path, rows):
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["managers", "collect", "krx", "verify", "all"])
    ap.add_argument("--krx-csv")
    a = ap.parse_args(argv)
    DATA.mkdir(parents=True, exist_ok=True)
    st = a.stage

    krx_rows = None
    if st in ("krx", "verify", "all", "managers"):
        try:
            krx_rows = krxmod.load(a.krx_csv)
            _write_csv(DATA / "krx_etf.csv", krx_rows)
            print(f"[5] KRX 종목 {len(krx_rows)}개 로드")
        except (FetchError, RuntimeError, OSError) as e:
            print(f"[5] KRX 로드 실패: {e}", file=sys.stderr)
            if st in ("krx", "verify", "all"):
                return 2

    if st in ("managers", "all"):
        names = sorted({k["manager_name"] for k in krx_rows or [] if k.get("manager_name")})
        ms = mg.find_managers(names)
        _write_csv(DATA / "managers.csv", ms)
        ok = sum(m["status"] == "verified" for m in ms)
        print(f"[1] 운용사 {len(ms)}곳 중 홈페이지 검증 {ok}곳 (나머지는 managers.csv 의 note 참고)")

    if st in ("collect", "all"):
        rows = []
        for m in _read_csv(DATA / "managers.csv"):
            if m["status"] != "verified":
                continue
            got = pr.collect_manager(m)
            print(f"[2] {m['manager_name']}: 투자설명서 {len(got)}건")
            rows += got
        (DATA / "prospectus_raw.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))

    if st in ("verify", "all"):
        doc_rows = json.loads((DATA / "prospectus_raw.json").read_text())
        final, stats = verify.reconcile(doc_rows, krx_rows)
        db = store.connect()
        store.upsert(db, final)
        out = store.export_csv(db)
        (DATA / "verification_report.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
        print(f"[3-5] 적재 {len(final)}건 → {out}\n      검증결과 {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
