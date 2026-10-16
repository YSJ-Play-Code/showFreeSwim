"""경로·시드 설정.

SEED_MANAGERS 의 URL 은 '후보'일 뿐이다. 1단계(managers.py)가 실제로 접속해
응답 코드와 페이지 제목으로 검증하고, 틀리면 다음 후보로 재조회한다.
KRX 에는 있으나 시드에 없는 운용사는 data/etf/managers_override.csv 에
(manager_name,homepage,list_urls) 로 직접 추가하면 된다.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "etf"
RAW = DATA / "raw"          # 내려받은 원본(HTML/PDF/CSV) 캐시
DB_PATH = DATA / "etf.sqlite"

# code: 이 프로그램이 부여하는 운용사 식별코드(자산운용코드). 협회 코드로 바꾸려면 override CSV 사용.
SEED_MANAGERS = [
    {"code": "SAMSUNG", "name": "삼성자산운용", "brand": "KODEX",
     "urls": ["https://www.samsungfund.com/etf/main.do", "https://www.samsungfund.com"]},
    {"code": "MIRAE", "name": "미래에셋자산운용", "brand": "TIGER",
     "urls": ["https://investments.miraeasset.com/tigeretf/ko/index.do", "https://www.tigeretf.com"]},
    {"code": "KB", "name": "KB자산운용", "brand": "RISE",
     "urls": ["https://www.riseetf.co.kr", "https://www.kbam.co.kr"]},
    {"code": "KIM", "name": "한국투자신탁운용", "brand": "ACE",
     "urls": ["https://www.aceetf.co.kr", "https://www.kim.co.kr"]},
    {"code": "HANWHA", "name": "한화자산운용", "brand": "PLUS",
     "urls": ["https://www.plusetf.co.kr", "https://www.hanwhafund.com"]},
    {"code": "SHINHAN", "name": "신한자산운용", "brand": "SOL",
     "urls": ["https://www.shinhanfund.com", "https://www.shinhanam.com"]},
    {"code": "KIWOOM", "name": "키움투자자산운용", "brand": "KIWOOM",
     "urls": ["https://www.kiwoomam.com", "https://www.kiwoomam.com/etf"]},
    {"code": "NHAMUNDI", "name": "NH-Amundi자산운용", "brand": "HANARO",
     "urls": ["https://www.nh-amundi.com", "https://www.nh-amundi.com/etf"]},
    {"code": "WOORI", "name": "우리자산운용", "brand": "WON",
     "urls": ["https://www.wooriam.kr", "https://www.wooriam.com"]},
    {"code": "TIMEFOLIO", "name": "타임폴리오자산운용", "brand": "TIME",
     "urls": ["https://www.timefolio.co.kr"]},
    {"code": "HANA", "name": "하나자산운용", "brand": "1Q",
     "urls": ["https://www.hanaw.com", "https://www.hanaam.com"]},
    {"code": "KYOBO", "name": "교보악사자산운용", "brand": "",
     "urls": ["https://www.kyoboaxa-im.co.kr"]},
]

HTTP_TIMEOUT = 25
HTTP_RETRIES = 3
MAX_REQUERY_ROUNDS = 2      # 검증 실패 시 재조회 최대 횟수
FEE_TOLERANCE = 0.011       # 총보수 허용 오차(%p)
