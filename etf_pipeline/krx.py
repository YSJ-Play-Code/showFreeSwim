"""5단계: KRX ETF 전종목 기본정보 CSV 내려받기(또는 직접 받은 CSV 로드).

data.krx.co.kr [통계 > 기본통계 > 증권상품 > ETF > 전종목 기본정보] 의 CSV 다운로드와 같은 OTP 흐름.
KRX 가 로그인/정책 변경으로 자동 다운로드를 막으면 사이트에서 CSV 를 직접 받아
`--krx-csv 파일경로` 로 넘기면 된다 (cp949/utf-8 자동 판별).
"""
import csv
import io

from .config import RAW
from .http import fetch

OTP_URL = "https://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd"
DN_URL = "https://data.krx.co.kr/comm/fileDn/download_csv/download.cmd"
BLD = "dbms/MDC/STAT/standard/MDCSTAT04601"

COLMAP = {
    "isin": ["표준코드"], "ticker": ["단축코드", "종목코드"],
    "etf_name": ["한글 종목명", "한글종목명", "종목명"], "short_name": ["한글 종목약명", "한글종목약명"],
    "listing_date": ["상장일"], "tracking_index": ["기초지수명"],
    "manager_name": ["운용사", "집합투자업자"], "total_fee": ["총보수"],
    "base_asset": ["기초자산분류"], "base_market": ["기초시장분류"],
    "replication": ["복제방법"], "multiple": ["추적배수"], "tax_type": ["과세유형"],
}


def download_csv(refresh=True) -> bytes:
    H = {"Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd"}
    otp = fetch(OTP_URL, data={"locale": "ko_KR", "share": "1", "csvxls_isNo": "false",
                               "name": "fileDown", "url": BLD}, headers=H, refresh=refresh).decode().strip()
    return fetch(DN_URL, data={"code": otp}, headers=H, refresh=refresh)


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "ignore")


def parse_krx(raw: bytes) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(decode(raw))))
    out = []
    for r in rows:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        rec = {}
        for key, names in COLMAP.items():
            rec[key] = next((r[n] for n in names if n in r and r[n] != ""), "")
        if not rec["ticker"] and rec["isin"].startswith("KR7"):
            rec["ticker"] = rec["isin"][3:9]
        d = rec["listing_date"].replace("/", "-").replace(".", "-")
        rec["listing_date"] = d
        try:
            rec["total_fee"] = float(rec["total_fee"].replace("%", "").replace(",", ""))
        except ValueError:
            rec["total_fee"] = None
        if rec["ticker"]:
            out.append(rec)
    return out


def load(csv_path: str | None = None) -> list[dict]:
    if csv_path:
        raw = open(csv_path, "rb").read()
    else:
        raw = download_csv()
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "krx_etf_latest.csv").write_bytes(raw)
    rows = parse_krx(raw)
    if not rows:
        raise RuntimeError("KRX CSV 에서 종목을 읽지 못함(컬럼명 변경/로그인 필요 가능성). --krx-csv 로 직접 받은 파일을 사용하세요.")
    return rows
