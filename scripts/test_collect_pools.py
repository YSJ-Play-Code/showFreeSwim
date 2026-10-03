import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from pyproj import Transformer

import collect_pools as cp

LOCALDATA_HEADER = ["번호", "개방서비스명", "관리번호", "영업상태명", "상세영업상태명", "소재지전화",
                    "소재지전체주소", "도로명전체주소", "사업장명", "좌표정보(x)", "좌표정보(y)"]
PUBLIC_HEADER = ["시설명", "시설유형", "도로명주소", "지번주소", "위도", "경도", "운영여부"]


def write_csv(path, header, rows, encoding):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    Path(path).write_bytes(buf.getvalue().encode(encoding))


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        fwd = Transformer.from_crs("EPSG:4326", "EPSG:5174", always_xy=True)
        x, y = fwd.transform(127.0276, 37.4979)
        write_csv(self.dir / "local.csv", LOCALDATA_HEADER, [
            [1, "수영장업", "A1", "영업/정상", "영업", "02-1", "서울특별시 강남구 역삼동 1",
             "서울특별시 강남구 테헤란로 1 (역삼동)", "역삼 수영장", x, y],
            [2, "수영장업", "A2", "폐업", "폐업", "", "", "서울특별시 강남구 테헤란로 2", "폐업 수영장", x, y],
            [3, "수영장업", "A3", "영업/정상", "영업", "", "", "경기도 수원시 장안구 정조로 1", "키즈 수영장", x, y],
            [4, "수영장업", "A4", "영업/정상", "영업", "", "", "경기도 수원시 장안구 정조로 9", "장안 아쿠아", "", ""],
        ], "cp949")
        write_csv(self.dir / "public.csv", PUBLIC_HEADER, [
            ["역삼수영장", "수영장", "서울특별시 강남구 테헤란로 1", "", "37.4979", "127.0276", "운영"],
            ["강원 체육관", "체육관", "강원특별자치도 춘천시 중앙로 1", "", "37.88", "127.73", "운영"],
            ["춘천 실내수영장", "수영장", "강원특별자치도 춘천시 중앙로 2", "", "37.88", "127.73", "운영"],
        ], "utf-8-sig")
        (self.dir / "manual.json").write_text(json.dumps([
            {"id": 1, "name": "역삼수영장", "city": "서울특별시", "district": "강남구", "address": "x",
             "lat": 37.5, "lng": 127.0, "prices": {"member": 3000, "nonMember": 5000},
             "sessions": [{"s": 6, "e": 7, "d": ["월"]}], "regularOff": "월", "holidayClosed": True,
             "notices": "", "verified": True},
        ], ensure_ascii=False), encoding="utf-8")

    def run_collect(self, *extra):
        out = self.dir / "pools.json"
        cp.main(["--localdata", str(self.dir / "local.csv"), "--public", str(self.dir / "public.csv"),
                 "--manual", str(self.dir / "manual.json"), "--out", str(out), "--today", "2026-10-03", *extra])
        return json.loads(out.read_text(encoding="utf-8"))

    def test_filters_dedupe_and_merge(self):
        data = self.run_collect()
        names = sorted(p["name"] for p in data["pools"])
        self.assertEqual(names, ["역삼 수영장", "장안 아쿠아", "춘천 실내수영장"])

        local = data["meta"]["sources"][0]
        self.assertEqual(local["excluded"]["status"], 1)
        self.assertEqual(local["excluded"]["child_only"], 1)
        public = data["meta"]["sources"][1]
        self.assertEqual(public["excluded"]["type"], 1)
        self.assertEqual(public["excluded"]["duplicate"], 1)

        yeoksam = next(p for p in data["pools"] if p["name"] == "역삼 수영장")
        self.assertAlmostEqual(yeoksam["lat"], 37.4979, places=4)
        self.assertAlmostEqual(yeoksam["lng"], 127.0276, places=4)
        self.assertEqual(yeoksam["prices"]["nonMember"], 5000)
        self.assertTrue(yeoksam["verified"])
        self.assertEqual(data["meta"]["sources"][2]["matched"], 1)

    def test_region_normalization(self):
        data = self.run_collect()
        jangan = next(p for p in data["pools"] if p["name"] == "장안 아쿠아")
        self.assertEqual((jangan["city"], jangan["district"]), ("경기도", "수원시"))
        self.assertIsNone(jangan["lat"])
        chuncheon = next(p for p in data["pools"] if p["name"] == "춘천 실내수영장")
        self.assertEqual(chuncheon["city"], "강원도")
        self.assertEqual(data["meta"]["counts"]["noCoords"], 1)

    def test_coverage_period(self):
        self.assertEqual(self.run_collect()["meta"]["coverageUntil"], "2026-10-31")
        self.assertEqual(self.run_collect("--next-month")["meta"]["coverageUntil"], "2026-11-30")


if __name__ == "__main__":
    unittest.main()
