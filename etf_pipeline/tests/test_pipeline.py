import unittest

from etf_pipeline import krx, prospectus as pr, verify
from etf_pipeline.managers import check_homepage
from etf_pipeline.http import FetchError


def make_isin(short6: str) -> str:
    """KR7 + 6자리 + 003 + 체크디지트로 유효한 테스트용 ISIN 생성."""
    body = "KR7" + short6 + "00"
    for c in "0123456789":
        if pr.isin_valid(body + c):
            return body + c


ISIN = make_isin("069500")
DOC = f"""투자설명서
집합투자기구의 명칭: KODEX 200 증권 상장지수투자신탁[주식]
표준코드 {ISIN}
상장일 2002년 10월 14일
투자위험등급: 2등급(높은 위험)
총보수 연 0.15%
"""
KRX_CSV = ("표준코드,단축코드,한글 종목명,한글 종목약명,상장일,기초지수명,운용사,총보수\n"
           f"{ISIN},069500,KODEX 200,KODEX 200,2002/10/14,코스피 200,삼성자산운용,0.15\n"
           f"KR7000000009,999999,TEST ETF,TEST,2020/01/01,X,신한자산운용,0.3\n").encode("cp949")


class T(unittest.TestCase):
    def test_isin(self):
        self.assertTrue(pr.isin_valid(ISIN))
        self.assertFalse(pr.isin_valid(ISIN[:-1] + str((int(ISIN[-1]) + 1) % 10)))

    def test_parse(self):
        r = pr.parse_prospectus(DOC)
        self.assertEqual((r["isin"], r["ticker"], r["risk_grade"]), (ISIN, "069500", 2))
        self.assertEqual(r["listing_date"], "2002-10-14")
        self.assertEqual(r["total_fee"], 0.15)
        self.assertIn("KODEX 200", r["etf_name"])

    def test_risk_label_conflict_is_skipped(self):
        self.assertEqual(pr.parse_risk("투자위험등급: 1등급(낮은 위험)")[0], None)

    def test_classify(self):
        self.assertEqual(pr.classify("KODEX 레버리지")["strategy"], "레버리지")
        self.assertEqual(pr.classify("TIGER 미국S&P500")["asset_class"], "해외주식")
        self.assertEqual(pr.classify("KODEX 국고채3년")["asset_class"], "채권")

    def test_krx_parse_cp949(self):
        rows = krx.parse_krx(KRX_CSV)
        self.assertEqual(rows[0]["ticker"], "069500")
        self.assertEqual(rows[0]["listing_date"], "2002-10-14")

    def test_verified(self):
        doc = {**pr.parse_prospectus(DOC), "manager_code": "SAMSUNG", "manager_name": "삼성자산운용", "source_url": "u"}
        final, st = verify.reconcile([doc], krx.parse_krx(KRX_CSV), fetcher=lambda *a, **k: b"")
        self.assertEqual(st["verified"], 1)
        self.assertEqual(st["krx_only"], 1)  # 999999 는 설명서 미수집

    def test_mismatch_requery_then_flag(self):
        doc = {**pr.parse_prospectus(DOC), "manager_name": "삼성자산운용", "manager_code": "SAMSUNG",
               "source_url": "u", "total_fee": 0.99}
        calls = []

        def fetcher(url, refresh=False, **k):
            calls.append(refresh)
            return DOC.encode()  # 재조회하면 올바른 값(0.15)이 나오는 경우

        final, st = verify.reconcile([doc], krx.parse_krx(KRX_CSV), fetcher=fetcher)
        self.assertTrue(all(calls) and calls)
        self.assertEqual(st["requeried_fixed"], 1)
        bad = {**doc}
        final, st = verify.reconcile([bad], krx.parse_krx(KRX_CSV),
                                     fetcher=lambda *a, **k: DOC.replace("0.15%", "0.99%").encode())
        self.assertEqual(st["mismatch"], 1)
        self.assertIn("총보수 불일치", [r for r in final if r["ticker"] == "069500"][0]["verify_notes"])

    def test_homepage_name_check(self):
        ok, _ = check_homepage("u", "삼성자산운용", "KODEX", lambda *a, **k: "<title>삼성자산운용 KODEX</title>".encode())
        self.assertTrue(ok)
        ok, why = check_homepage("u", "삼성자산운용", "KODEX", lambda *a, **k: b"<title>other</title>")
        self.assertFalse(ok)

        def boom(*a, **k):
            raise FetchError("403")
        self.assertFalse(check_homepage("u", "x", "", boom)[0])


if __name__ == "__main__":
    unittest.main()
