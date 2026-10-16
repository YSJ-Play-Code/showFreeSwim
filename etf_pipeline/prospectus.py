"""2단계: 투자설명서(PDF/HTML) 수집과 필드 추출.

수집은 범용 크롤러(홈페이지/목록 URL 의 '투자설명서'·.pdf 링크)이다.
JS 로 그려지는 사이트는 --render(playwright) 또는 managers_override.csv 의 list_urls 로 보완한다.
추출은 순수 함수라 텍스트만 주면 테스트할 수 있다.
"""
import io
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .http import FetchError, fetch

RISK_LABEL = {1: "매우 높은 위험", 2: "높은 위험", 3: "다소 높은 위험",
              4: "보통 위험", 5: "낮은 위험", 6: "매우 낮은 위험"}
RISK_ALIASES = {"매우높은위험": 1, "높은위험": 2, "다소높은위험": 3, "보통위험": 4, "낮은위험": 5, "매우낮은위험": 6}


# ---------- 링크 수집 ----------
def find_doc_links(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        href = a["href"]
        if href.lower().split("?")[0].endswith(".pdf") or "투자설명서" in label or "prospectus" in href.lower():
            links.append(urljoin(base, href))
    return list(dict.fromkeys(links))


# ---------- 텍스트 추출 (두 엔진: 재조회 시 교차 사용) ----------
def pdf_text(raw: bytes, engine: str = "pdfplumber") -> str:
    if engine == "pdfplumber":
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages[:25])
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages[:25])


def doc_text(raw: bytes, engine: str = "pdfplumber") -> str:
    if raw[:4] == b"%PDF":
        return pdf_text(raw, engine)
    return BeautifulSoup(raw.decode("utf-8", "ignore"), "lxml").get_text("\n")


# ---------- 코드 검증 ----------
def isin_valid(isin: str) -> bool:
    """ISIN 체크디지트(Luhn) 검증."""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", isin or ""):
        return False
    digits = "".join(str(int(c, 36)) for c in isin)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return total % 10 == 0


def ticker_from_isin(isin: str) -> str:
    return isin[3:9] if isin and isin.startswith("KR7") else ""


# ---------- 상품구분 ----------
def classify(name: str, text: str = "") -> dict:
    n = name or ""
    if re.search(r"레버리지|2X|3X|\(2배\)", n, re.I):
        strategy = "레버리지"
    elif re.search(r"인버스|곱버스|숏", n):
        strategy = "인버스"
    elif re.search(r"액티브|ACTIVE", n, re.I):
        strategy = "액티브"
    elif re.search(r"커버드콜|프리미엄|타겟", n):
        strategy = "커버드콜/인컴"
    else:
        strategy = "패시브(지수추종)"
    rules = [
        (r"채권|국채|국고채|회사채|금리|CD|KOFR|머니마켓|단기통안|액티브.*채", "채권"),
        (r"원유|WTI|금현물|골드|은선물|구리|농산물|원자재|천연가스", "원자재"),
        (r"달러|엔화|유로|위안|통화", "통화"),
        (r"리츠|부동산|인프라", "부동산/인프라"),
        (r"미국|나스닥|S&P|다우|중국|일본|인도|베트남|유럽|선진국|신흥국|글로벌|해외", "해외주식"),
    ]
    asset = "국내주식"
    for pat, label in rules:
        if re.search(pat, n):
            asset = label
            break
    return {"strategy": strategy, "asset_class": asset}


# ---------- 필드 추출 ----------
def parse_risk(text: str):
    """(등급, 라벨). '투자위험등급' 부근에서만 찾고, 번호·라벨이 서로 맞는지 본다."""
    for m in re.finditer(r"(?:투자\s*)?위험\s*등급[^\n]{0,40}", text):
        seg = text[m.start(): m.start() + 120]
        g = re.search(r"([1-6])\s*등급", seg)
        lab = re.search(r"(매우\s*높은|다소\s*높은|매우\s*낮은|높은|보통|낮은)\s*위험", seg)
        grade = int(g.group(1)) if g else None
        label = None
        if lab:
            label = re.sub(r"\s", "", lab.group(0))
            by_label = RISK_ALIASES.get(label)
            if grade is None:
                grade = by_label
            elif by_label and by_label != grade:
                continue  # 번호와 라벨 불일치 → 잘못 잡았을 가능성, 다음 후보
        if grade:
            return grade, RISK_LABEL[grade]
    return None, None


def parse_prospectus(text: str) -> dict:
    t = re.sub(r"[ \t]+", " ", text)
    isins = [c for c in re.findall(r"\bKR[0-9A-Z]{10}\b", t) if isin_valid(c)]
    isin = isins[0] if isins else ""
    name = ""
    m = re.search(r"(?:집합투자기구\s*(?:의)?\s*명칭|펀드\s*명|명\s*칭)\s*[:：]?\s*([^\n]{3,80})", t)
    if m:
        name = re.sub(r"\s*\(.*?(?:증권|투자신탁).*?\)\s*$", "", m.group(1)).strip()
    tk = re.search(r"(?:종목\s*코드|단축\s*코드|거래소\s*코드)\s*[:：]?\s*(\d{6})", t)
    ticker = tk.group(1) if tk else ticker_from_isin(isin)
    grade, label = parse_risk(t)
    fee = re.search(r"(?:총\s*보수|연간\s*총보수)[^\n%]{0,30}?(\d+(?:\.\d+)?)\s*%", t)
    ld = re.search(r"상장\s*일\s*[:：]?\s*(\d{4})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})", t)
    return {
        "etf_name": name, "isin": isin, "ticker": ticker,
        "risk_grade": grade, "risk_label": label,
        "total_fee": float(fee.group(1)) if fee else None,
        "listing_date": f"{ld.group(1)}-{int(ld.group(2)):02d}-{int(ld.group(3)):02d}" if ld else "",
        **classify(name, t),
    }


# ---------- 수집 ----------
def collect_manager(mgr: dict, fetcher=fetch, max_docs: int = 400) -> list[dict]:
    pages = [u for u in [mgr["homepage"], *[x for x in mgr.get("list_urls", "").split("|") if x]] if u]
    docs: list[str] = []
    for p in pages:
        try:
            docs += find_doc_links(fetcher(p).decode("utf-8", "ignore"), p)
        except FetchError:
            continue
    rows = []
    for url in list(dict.fromkeys(docs))[:max_docs]:
        try:
            rec = parse_prospectus(doc_text(fetcher(url)))
        except Exception as e:  # 손상 PDF 등
            rows.append({"source_url": url, "parse_error": str(e)})
            continue
        rec.update(source_url=url, manager_code=mgr["manager_code"], manager_name=mgr["manager_name"])
        rows.append(rec)
    return rows
