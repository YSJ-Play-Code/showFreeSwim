#!/usr/bin/env python3
"""전국 수영장 데이터 수집기.

입력 소스
  --localdata  LOCALDATA(행정안전부) '체육시설 > 수영장업' 전체 CSV (민간 신고 수영장)
  --public     문화체육관광부 '전국 공공체육시설 현황' CSV (구민체육센터 등 공공 수영장)
  --manual     직접 확인한 자유수영 시간/가격/휴관 정보 (data/manual_pools.json)

출력: data/pools.json  ({"meta": 수집 조건·통계, "pools": [...]})
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import re
import sys
from pathlib import Path

CRITERIA = {
    "status_include": ["영업", "정상", "운영"],
    "status_exclude": ["폐업", "휴업", "취소", "말소", "폐쇄", "미운영", "운영중지"],
    "type_keyword": "수영",
    "exclude_name_keywords": ["어린이", "키즈", "유아", "베이비", "아기", "물놀이"],
    "korea_bbox": {"lat": [33.0, 38.7], "lng": [124.5, 132.0]},
}

CRITERIA_TEXT = [
    "영업상태가 '영업/정상/운영'인 시설만 (폐업·휴업·취소 제외)",
    "시설 유형 또는 시설명에 '수영'이 포함된 시설 (LOCALDATA 수영장업은 전체)",
    "성인 이용 가능 시설만 (어린이·키즈·유아·물놀이장 전용 제외)",
    "도로명주소 기준 중복 제거 (같은 시설이 두 소스에 있으면 1건)",
    "대한민국 범위 좌표가 있는 시설만 지도 표시 (좌표 없는 시설은 건수만 기록)",
]

CITY_ALIASES = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
    "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시",
    "세종": "세종특별자치시", "세종특별자치시": "세종특별자치시",
    "경기": "경기도", "충북": "충청북도", "충남": "충청남도", "전남": "전라남도",
    "경북": "경상북도", "경남": "경상남도", "제주": "제주특별자치도",
    # 지도 경계 데이터는 개편 전 명칭을 사용
    "강원": "강원도", "강원특별자치도": "강원도",
    "전북": "전라북도", "전북특별자치도": "전라북도",
}

COLS = {
    "name": ["사업장명", "시설명", "체육시설명", "업소명"],
    "status": ["상세영업상태명", "영업상태명", "운영상태", "운영여부"],
    "type": ["개방서비스명", "시설유형", "시설유형명", "세부시설유형", "업종", "종목명", "종목"],
    "road_addr": ["도로명전체주소", "도로명주소", "소재지도로명주소"],
    "jibun_addr": ["소재지전체주소", "지번주소", "소재지지번주소", "주소"],
    "phone": ["소재지전화", "전화번호", "연락처"],
    "source_id": ["관리번호", "시설번호", "시설코드"],
    "lat": ["위도", "lat", "LAT"],
    "lng": ["경도", "lng", "lon", "LNG"],
}


def pick(row, key):
    for c in COLS[key]:
        v = row.get(c)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def pick_tm(row, axis):
    for k, v in row.items():
        if k and re.match(r"좌표정보.*" + axis, k, re.I) and str(v).strip():
            return str(v).strip()
    return ""


def read_csv(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"{path}: 인코딩을 판별할 수 없습니다 (UTF-8/CP949 아님)")
    return list(csv.DictReader(io.StringIO(text)))


_transformer = None


def tm_to_wgs84(x, y):
    global _transformer
    if _transformer is None:
        from pyproj import Transformer
        # LOCALDATA 좌표계: EPSG:5174 (Korean 1985 / Modified Central Belt)
        _transformer = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
    lng, lat = _transformer.transform(float(x), float(y))
    return lat, lng


def in_korea(lat, lng):
    b = CRITERIA["korea_bbox"]
    return b["lat"][0] <= lat <= b["lat"][1] and b["lng"][0] <= lng <= b["lng"][1]


def parse_region(addr):
    toks = addr.split()
    if not toks:
        return None, None
    city = CITY_ALIASES.get(toks[0], toks[0])
    if city == "세종특별자치시":
        return city, "세종시"
    if len(toks) < 2:
        return city, None
    # '경기도 수원시 장안구' → 지도 경계는 시 단위이므로 '수원시'
    return city, toks[1]


def norm_name(s):
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s)
    s = re.sub(r"\s+|수영장|실내|체육센터|스포츠센터", "", s)
    return s


def norm_addr(s):
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r",.*$", "", s)
    return re.sub(r"\s+", "", s)


def status_ok(status):
    if not status:
        return True
    if any(k in status for k in CRITERIA["status_exclude"]):
        return False
    return any(k in status for k in CRITERIA["status_include"])


def collect_source(path, kind):
    rows = read_csv(path)
    stats = {"name": kind, "file": Path(path).name, "rows": len(rows), "kept": 0,
             "excluded": {"status": 0, "type": 0, "child_only": 0, "no_address": 0}}
    out = []
    for row in rows:
        name = pick(row, "name")
        if not status_ok(pick(row, "status")):
            stats["excluded"]["status"] += 1
            continue
        if kind == "public":
            t = pick(row, "type")
            if CRITERIA["type_keyword"] not in t and CRITERIA["type_keyword"] not in name:
                stats["excluded"]["type"] += 1
                continue
        if any(k in name for k in CRITERIA["exclude_name_keywords"]):
            stats["excluded"]["child_only"] += 1
            continue
        addr = pick(row, "road_addr") or pick(row, "jibun_addr")
        city, district = parse_region(addr)
        if not addr or not district:
            stats["excluded"]["no_address"] += 1
            continue

        lat = lng = None
        la, ln = pick(row, "lat"), pick(row, "lng")
        try:
            if la and ln:
                lat, lng = float(la), float(ln)
            else:
                x, y = pick_tm(row, "x"), pick_tm(row, "y")
                if x and y:
                    lat, lng = tm_to_wgs84(x, y)
        except ValueError:
            lat = lng = None
        if lat is not None and not in_korea(lat, lng):
            lat = lng = None

        sid = pick(row, "source_id") or hashlib.md5((name + addr).encode()).hexdigest()[:10]
        out.append({
            "id": ("L-" if kind == "localdata" else "P-") + sid,
            "name": name, "city": city, "district": district, "address": addr,
            "lat": round(lat, 6) if lat is not None else None,
            "lng": round(lng, 6) if lng is not None else None,
            "phone": pick(row, "phone"), "source": kind,
            "prices": None, "sessions": [], "regularOff": None, "holidayClosed": None,
            "notices": "", "verified": False,
        })
        stats["kept"] += 1
    return out, stats


def merge_manual(pools, manual):
    by_key = {}
    for p in pools:
        by_key.setdefault((p["city"], p["district"], norm_name(p["name"])), p)
    matched, added = 0, 0
    for m in manual:
        key = (m["city"], m["district"], norm_name(m["name"]))
        target = by_key.get(key)
        fields = ("prices", "sessions", "regularOff", "holidayClosed", "notices", "verified")
        if target:
            for f in fields:
                if m.get(f) is not None:
                    target[f] = m[f]
            matched += 1
        else:
            rec = dict(m)
            rec["id"] = "M-" + str(m.get("id"))
            rec["source"] = "manual"
            rec.setdefault("phone", "")
            pools.append(rec)
            by_key[key] = rec
            added += 1
    return matched, added


KST = dt.timezone(dt.timedelta(hours=9))


def month_end(d):
    nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return nxt - dt.timedelta(days=1)


def build(args, today):
    pools, sources = [], []
    seen = set()
    for kind, paths in (("localdata", args.localdata), ("public", args.public)):
        for path in paths:
            recs, stats = collect_source(path, kind)
            stats["excluded"]["duplicate"] = 0
            for r in recs:
                k = norm_addr(r["address"]) + "|" + norm_name(r["name"])
                if k in seen:
                    stats["excluded"]["duplicate"] += 1
                    stats["kept"] -= 1
                    continue
                seen.add(k)
                pools.append(r)
            sources.append(stats)

    manual = json.loads(Path(args.manual).read_text(encoding="utf-8")) if args.manual else []
    matched, added = merge_manual(pools, manual)
    sources.append({"name": "manual", "file": Path(args.manual).name if args.manual else None,
                    "rows": len(manual), "kept": added, "matched": matched})

    coverage = month_end(today)
    if args.next_month:
        coverage = month_end(coverage + dt.timedelta(days=1))

    by_city = {}
    for p in pools:
        by_city[p["city"]] = by_city.get(p["city"], 0) + 1

    meta = {
        "collectedAt": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "coverageFrom": today.isoformat(),
        "coverageUntil": coverage.isoformat(),
        "nationwide": any(s["name"] in ("localdata", "public") for s in sources),
        "criteria": CRITERIA_TEXT,
        "sources": sources,
        "counts": {
            "total": len(pools),
            "withCoords": sum(1 for p in pools if p["lat"] is not None),
            "noCoords": sum(1 for p in pools if p["lat"] is None),
            "withSchedule": sum(1 for p in pools if p["sessions"]),
            "verified": sum(1 for p in pools if p.get("verified")),
            "byCity": dict(sorted(by_city.items(), key=lambda kv: -kv[1])),
        },
    }
    pools.sort(key=lambda p: (p["city"], p["district"] or "", p["name"]))
    return {"meta": meta, "pools": pools}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--localdata", nargs="*", default=[], help="LOCALDATA 수영장업 CSV 경로")
    ap.add_argument("--public", nargs="*", default=[], help="전국 공공체육시설 현황 CSV 경로")
    ap.add_argument("--manual", default="data/manual_pools.json", help="수동 확인 데이터 JSON")
    ap.add_argument("--out", default="data/pools.json")
    ap.add_argument("--next-month", action="store_true", help="다음달 운영정보까지 확보된 경우 조회기간을 다음달 말일로 확장")
    ap.add_argument("--today", help="기준일 YYYY-MM-DD (기본: 오늘)")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(KST).date()
    data = build(args, today)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    c = data["meta"]["counts"]
    print(f"저장: {args.out}  총 {c['total']}개 (지도표시 {c['withCoords']}, 좌표없음 {c['noCoords']}, 자유수영정보 {c['withSchedule']})")
    for s in data["meta"]["sources"]:
        print("  -", json.dumps(s, ensure_ascii=False))
    if not data["meta"]["nationwide"]:
        print("경고: 전국 소스(--localdata/--public)가 없어 수동 데이터만 저장되었습니다.", file=sys.stderr)


if __name__ == "__main__":
    main()
