"""1단계: 운용사 홈페이지 찾기 + 검증.

검증 규칙(후보 URL 을 차례로 재조회):
  - HTTP 200 으로 열릴 것
  - <title>/본문에 운용사명 또는 브랜드명이 들어 있을 것 (엉뚱한 사이트 방지)
KRX 에 나온 운용사 중 시드에 없는 곳은 homepage_unknown 으로 표시한다.
"""
import csv
import re

from bs4 import BeautifulSoup

from .config import DATA, SEED_MANAGERS
from .http import FetchError, fetch


def norm_name(s: str) -> str:
    s = re.sub(r"\(.*?\)|㈜|주식회사|\s", "", s or "")
    s = s.replace("자산운용", "").replace("투자운용", "").replace("투자신탁운용", "").replace("투자자산운용", "")
    return s.lower()


def check_homepage(url: str, name: str, brand: str, fetcher=fetch) -> tuple[bool, str]:
    try:
        html = fetcher(url, refresh=True).decode("utf-8", "ignore")
    except FetchError as e:
        return False, f"접속 실패: {e}"
    soup = BeautifulSoup(html, "lxml")
    text = (soup.title.string if soup.title and soup.title.string else "") + soup.get_text(" ")[:5000]
    keys = [k for k in (name, name.replace("자산운용", ""), brand) if k]
    if any(k.lower() in text.lower() for k in keys):
        return True, "ok"
    return False, "페이지에 운용사명/브랜드명이 없음(다른 사이트 가능성)"


def load_overrides() -> list[dict]:
    p = DATA / "managers_override.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig") as f:
        return [{"code": r.get("code") or "X_" + norm_name(r["manager_name"]).upper(),
                 "name": r["manager_name"], "brand": r.get("brand", ""),
                 "urls": [r["homepage"]], "list_urls": [u for u in (r.get("list_urls") or "").split("|") if u]}
                for r in csv.DictReader(f)]


def find_managers(krx_manager_names=(), fetcher=fetch) -> list[dict]:
    seeds = {norm_name(m["name"]): m for m in SEED_MANAGERS}
    for m in load_overrides():
        seeds[norm_name(m["name"])] = m
    for n in krx_manager_names:
        seeds.setdefault(norm_name(n), {"code": "X_" + norm_name(n).upper(), "name": n, "brand": "", "urls": []})
    out = []
    for m in seeds.values():
        rec = {"manager_code": m["code"], "manager_name": m["name"], "brand": m["brand"],
               "homepage": "", "list_urls": "|".join(m.get("list_urls", [])), "status": "homepage_unknown", "note": ""}
        notes = []
        for u in m["urls"]:
            ok, why = check_homepage(u, m["name"], m["brand"], fetcher)
            if ok:
                rec.update(homepage=u, status="verified", note="")
                break
            notes.append(f"{u} -> {why}")
        else:
            if m["urls"]:
                rec["status"] = "unreachable_or_mismatch"
            rec["note"] = " | ".join(notes) or "시드에 홈페이지 없음: managers_override.csv 에 추가 필요"
        out.append(rec)
    return sorted(out, key=lambda r: r["manager_code"])
