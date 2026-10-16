"""검증·재조회.

단계별 검증
  ① 운용사   : managers.check_homepage (접속·이름 일치, 후보 URL 재조회)
  ② 설명서   : 구조 검증(ISIN 체크디지트, 6자리 코드, ISIN↔코드 일치, 위험등급 번호↔명칭 일치)
  ③ 교차검증 : KRX 기본정보(코드·ISIN·종목명·운용사·상장일·총보수)와 대조
불일치/오류면 원본을 캐시 무시하고 다시 받아 다른 PDF 엔진으로 재추출(최대 MAX_REQUERY_ROUNDS).
그래도 안 맞으면 임의로 덮어쓰지 않고 mismatch 로 표시해 두 값을 모두 남긴다.
위험등급은 KRX 에 없는 항목이라 교차검증 불가 → 설명서 내부 일관성만 검증하고 메모에 명시한다.
"""
import re

from .config import FEE_TOLERANCE, MAX_REQUERY_ROUNDS
from .http import FetchError, fetch
from .managers import norm_name
from .prospectus import RISK_LABEL, doc_text, isin_valid, parse_prospectus, ticker_from_isin


def norm_title(s: str) -> str:
    return re.sub(r"[\s\-_()]|증권|상장지수|투자신탁|\[.*?\]", "", (s or "")).lower()


def structural_issues(r: dict) -> list[str]:
    out = []
    if not r.get("etf_name"):
        out.append("상품명 추출 실패")
    if not r.get("isin"):
        out.append("ISIN 없음/체크디지트 오류")
    elif not isin_valid(r["isin"]):
        out.append("ISIN 체크디지트 불일치")
    if not re.fullmatch(r"\d{6}", r.get("ticker") or ""):
        out.append("거래소 코드(6자리) 이상")
    elif r.get("isin") and r["isin"].startswith("KR7") and ticker_from_isin(r["isin"]) != r["ticker"]:
        out.append(f"ISIN({r['isin']})과 거래소 코드({r['ticker']}) 불일치")
    if r.get("risk_grade") not in RISK_LABEL:
        out.append("위험등급 추출 실패")
    return out


def krx_issues(r: dict, k: dict) -> list[str]:
    out = []
    if k.get("isin") and r.get("isin") and k["isin"] != r["isin"]:
        out.append(f"ISIN 불일치 doc={r['isin']} krx={k['isin']}")
    names = [norm_title(k.get("etf_name")), norm_title(k.get("short_name"))]
    dn = norm_title(r.get("etf_name"))
    if dn and not any(n and (n in dn or dn in n) for n in names):
        out.append(f"상품명 불일치 doc={r.get('etf_name')} krx={k.get('etf_name')}")
    if k.get("manager_name") and r.get("manager_name") and norm_name(k["manager_name"]) != norm_name(r["manager_name"]):
        out.append(f"운용사 불일치 doc={r['manager_name']} krx={k['manager_name']}")
    if k.get("listing_date") and r.get("listing_date") and k["listing_date"] != r["listing_date"]:
        out.append(f"상장일 불일치 doc={r['listing_date']} krx={k['listing_date']}")
    if k.get("total_fee") is not None and r.get("total_fee") is not None \
            and abs(k["total_fee"] - r["total_fee"]) > FEE_TOLERANCE:
        out.append(f"총보수 불일치 doc={r['total_fee']} krx={k['total_fee']}")
    return out


def _evaluate(r, by_ticker, by_isin):
    k = by_ticker.get(r.get("ticker")) or by_isin.get(r.get("isin"))
    issues = structural_issues(r)
    if k:
        issues += krx_issues(r, k)
    return k, issues


def reconcile(doc_rows: list[dict], krx_rows: list[dict], fetcher=fetch) -> tuple[list[dict], dict]:
    by_t = {k["ticker"]: k for k in krx_rows}
    by_i = {k["isin"]: k for k in krx_rows if k.get("isin")}
    final, seen, stats = [], set(), {"verified": 0, "mismatch": 0, "invalid": 0, "prospectus_only": 0,
                                     "krx_only": 0, "requeried_fixed": 0}
    for r in doc_rows:
        if r.get("parse_error"):
            stats["invalid"] += 1
            final.append({**r, "source_kind": "prospectus", "verify_status": "invalid",
                          "verify_notes": f"파싱 오류: {r['parse_error']}"})
            continue
        k, issues = _evaluate(r, by_t, by_i)
        rounds = 0
        while issues and r.get("source_url") and rounds < MAX_REQUERY_ROUNDS:
            rounds += 1
            try:
                raw = fetcher(r["source_url"], refresh=True)
                engine = "pypdf" if rounds % 2 else "pdfplumber"
                new = parse_prospectus(doc_text(raw, engine))
            except (FetchError, Exception):
                continue
            new.update({x: r[x] for x in ("source_url", "manager_code", "manager_name") if x in r})
            k2, issues2 = _evaluate(new, by_t, by_i)
            if len(issues2) < len(issues):
                r, k, issues = new, k2, issues2
                if not issues:
                    stats["requeried_fixed"] += 1
        row = {**r, "source_kind": "prospectus"}
        notes = ["위험등급은 KRX에 없어 설명서 단독 근거"]
        if k:
            seen.add(k["ticker"])
            row["tracking_index"] = k.get("tracking_index", "")
            for f in ("listing_date", "total_fee"):  # 설명서에 없던 값만 KRX 로 보충
                if row.get(f) in (None, ""):
                    row[f] = k.get(f)
                    notes.append(f"{f}: KRX 보충")
            status = "verified" if not issues else "mismatch"
        else:
            status = "prospectus_only" if not issues else "invalid"
            if not issues:
                notes.append("KRX 목록에 없음(상장폐지/오추출 확인 필요)")
        row.update(verify_status=status, verify_notes="; ".join(issues + notes))
        stats[status] += 1
        final.append(row)
    for k in krx_rows:  # 설명서를 못 찾은 상장 종목 → 재조회 대상
        if k["ticker"] not in seen:
            final.append({**k, "source_kind": "krx", "verify_status": "krx_only",
                          "verify_notes": "KRX에만 존재: 투자설명서 미수집(운용사 목록 URL 추가/재수집 필요)"})
            stats["krx_only"] += 1
    return final, stats
