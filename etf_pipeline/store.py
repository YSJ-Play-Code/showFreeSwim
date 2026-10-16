"""3·4단계: 테이블 생성과 데이터 적재 (SQLite + CSV 내보내기)."""
import csv
import datetime as dt
import sqlite3

from .config import DATA, DB_PATH

COLUMNS = [  # (컬럼, 설명)
    ("etf_name", "ETF 상품명"), ("manager_code", "자산운용코드(자체부여)"), ("manager_name", "운용사"),
    ("ticker", "거래소 단축코드(6자리)"), ("isin", "표준코드(ISIN)"),
    ("risk_grade", "위험등급(1~6)"), ("risk_label", "위험등급 명칭"),
    ("asset_class", "상품구분(자산)"), ("strategy", "상품구분(전략)"),
    ("listing_date", "상장일"), ("total_fee", "총보수(%)"), ("tracking_index", "기초지수"),
    ("source_url", "근거 투자설명서 URL"), ("source_kind", "prospectus|krx"),
    ("verify_status", "verified|krx_only|mismatch|prospectus_only|invalid"), ("verify_notes", "검증 메모"),
    ("updated_at", "갱신시각"),
]
NAMES = [c for c, _ in COLUMNS]

DDL = "CREATE TABLE IF NOT EXISTS etf_products (\n  " + ",\n  ".join(
    f"{c} {'REAL' if c in ('total_fee',) else 'INTEGER' if c == 'risk_grade' else 'TEXT'}" for c in NAMES
) + ",\n  PRIMARY KEY (ticker)\n);"


def connect(path=DB_PATH) -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute(DDL)
    return db


def upsert(db, rows: list[dict]):
    now = dt.datetime.now().isoformat(timespec="seconds")
    for r in rows:
        r = {**r, "updated_at": now}
        db.execute(f"INSERT OR REPLACE INTO etf_products ({','.join(NAMES)}) VALUES ({','.join('?' * len(NAMES))})",
                   [r.get(c) for c in NAMES])
    db.commit()


def export_csv(db, path=DATA / "etf_products.csv"):
    cur = db.execute(f"SELECT {','.join(NAMES)} FROM etf_products ORDER BY manager_code, etf_name")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(NAMES)
        w.writerows(cur)
    return path
