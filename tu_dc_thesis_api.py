#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tu_dc_thesis_api.py
====================

สคริปต์ดึงข้อมูล "วิทยานิพนธ์ / งานวิจัย" จากเว็บ TU Digital Collections
(https://digital.library.tu.ac.th/tu_dc/frontend/Search/) โดยเรียกใช้ API
ภายในที่หน้าเว็บใช้เอง (reverse-engineered จาก network request ตอนกดค้นหา)
ไม่ใช่ API สาธารณะที่มีเอกสารทางการ — ถ้าเว็บเปลี่ยนโครงสร้างในอนาคต
อาจต้องตรวจสอบ endpoint นี้ใหม่

--------------------------------------------------------------------------
สรุป API ที่เจอ
--------------------------------------------------------------------------
Endpoint:
    POST https://digital.library.tu.ac.th/tu_dc/frontend/Search/find/{offset}/{advance}

    - {offset}  = จำนวนรายการที่ข้ามไปแล้ว (ไม่ใช่เลขหน้า) เช่น
                  per_page=100 -> หน้าแรก offset=0, หน้าสอง offset=100, ...
    - {advance} = 0 สำหรับค้นหาแบบธรรมดา (ที่สคริปต์นี้ใช้), 1 สำหรับ
                  advance search แบบหลายเงื่อนไข (ยังไม่ได้ทำในสคริปต์นี้)

Headers:
    Content-Type: application/x-www-form-urlencoded;charset=UTF-8

Body (form field เดียว ชื่อ "data"):
    data=<URL-encoded JSON string>

    โครงสร้าง JSON object ที่ต้องส่ง (ตรงกับ $scope.query ของหน้าเว็บ):
    {
        "main": "<คำค้น หรือ '' ถ้าไม่ระบุ>",
        "option": "all",
        "collection_id": "all",
        "main_collection_id": "all",
        "pubyear_start": "",
        "pubyear_end": "",
        "filter": {
            "main_collection_id": [5],   # กรองเฉพาะกลุ่ม "งานวิจัยและวิทยานิพนธ์"
            "collection_id": [],
            "keyword_full": [],
            "author_data_full": [],
            "pubyear": []
        },
        "filter_include": true,
        "aggregate": false,
        "sort": "_score",
        "per_page": 200,
        "like_search": 0
    }

    หมายเหตุ main_collection_id=5 คือกลุ่มคอลเลกชัน "งานวิจัยและวิทยานิพนธ์"
    (Research & Thesis) ซึ่งรวมวิทยานิพนธ์ระดับปริญญาตรี-โท-เอก, การค้นคว้า
    อิสระ, Special Project ฯลฯ ยืนยันจากฟิลด์ degree_name / degree_discipline
    ที่ปรากฏเฉพาะกลุ่มนี้ ถ้าต้องการกลุ่มอื่นให้เปลี่ยนเลขนี้ (ดูได้จาก
    response key "aggs.collections_tree" ของการค้นหาแบบไม่ระบุ filter)

Response (JSON):
    {
        "result": {
            "metadata": {"total": {"value": <จำนวนทั้งหมด>, "relation": "eq"},
                         "per_page": <ตามที่ส่งไป>},
            "result": [ {...record...}, ... ]
        },
        "aggs": {...},          # มีเฉพาะตอน aggregate=true
        ...
    }

ฟิลด์สำคัญในแต่ละ record:
    bibid, title, contributors (list ของ {person_id, name}),
    keyword, subject, collection_id, collection_name,
    main_collection_id, main_collection_name, pubyear,
    degree_name, degree_discipline, faculty_college,
    cover (URL รูปปก), link (URL หน้ารายละเอียด), pk

--------------------------------------------------------------------------
วิธีใช้
--------------------------------------------------------------------------
    pip install requests

    # ดึงวิทยานิพนธ์ทั้งหมด (ทุกปี) บันทึกเป็น CSV
    python tu_dc_thesis_api.py --out theses.csv

    # ค้นเฉพาะที่มีคำว่า "การตลาด" ในชื่อเรื่อง/คำสำคัญ
    python tu_dc_thesis_api.py --keyword "การตลาด" --out marketing_theses.csv

    # จำกัดช่วงปี และจำกัดจำนวนสูงสุดที่จะดึง (กันดึงนานเกินไปตอนทดสอบ)
    python tu_dc_thesis_api.py --year-start 2020 --year-end 2024 --max-records 500

    # เอาผลลัพธ์เป็น JSON แทน CSV
    python tu_dc_thesis_api.py --out theses.json --format json
"""

import argparse
import csv
import json
import sys
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

BASE_URL = "https://digital.library.tu.ac.th/tu_dc/frontend/Search"
FIND_URL_TMPL = BASE_URL + "/find/{offset}/0"

# กลุ่มคอลเลกชัน "งานวิจัยและวิทยานิพนธ์" (Research & Thesis)
THESIS_MAIN_COLLECTION_ID = 5

DEFAULT_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (compatible; tu-dc-thesis-fetcher/1.0; +personal research script)",
    "Referer": "https://digital.library.tu.ac.th/tu_dc/frontend/Search/",
}


def build_query(
    keyword: str = "",
    main_collection_id: Optional[int] = THESIS_MAIN_COLLECTION_ID,
    collection_id: Optional[int] = None,
    year_start: str = "",
    year_end: str = "",
    per_page: int = 200,
    sort: str = "_score",
) -> Dict[str, Any]:
    """สร้าง query object ให้ตรงกับที่หน้าเว็บส่งจริง"""
    filt_main = [main_collection_id] if main_collection_id is not None else []
    filt_coll = [collection_id] if collection_id is not None else []
    return {
        "main": keyword or "",
        "option": "all",
        "collection_id": "all",
        "main_collection_id": "all",
        "pubyear_start": year_start or "",
        "pubyear_end": year_end or "",
        "filter": {
            "main_collection_id": filt_main,
            "collection_id": filt_coll,
            "keyword_full": [],
            "author_data_full": [],
            "pubyear": [],
        },
        "filter_include": True,
        "aggregate": False,
        "sort": sort,
        "per_page": per_page,
        "like_search": 0,
    }


def fetch_page(session: requests.Session, offset: int, query: Dict[str, Any]) -> Dict[str, Any]:
    body = "data=" + requests.utils.quote(json.dumps(query, ensure_ascii=False))
    resp = session.post(
        FIND_URL_TMPL.format(offset=offset),
        data=body.encode("utf-8"),
        headers=DEFAULT_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def iter_records(
    keyword: str = "",
    main_collection_id: Optional[int] = THESIS_MAIN_COLLECTION_ID,
    collection_id: Optional[int] = None,
    year_start: str = "",
    year_end: str = "",
    per_page: int = 200,
    max_records: Optional[int] = None,
    delay: float = 0.4,
) -> Iterator[Dict[str, Any]]:
    """ไล่ดึงทีละหน้า (pagination) แล้ว yield record ออกมาทีละรายการ"""
    query = build_query(
        keyword=keyword,
        main_collection_id=main_collection_id,
        collection_id=collection_id,
        year_start=year_start,
        year_end=year_end,
        per_page=per_page,
    )
    session = requests.Session()

    offset = 0
    total = None
    fetched = 0
    while True:
        data = fetch_page(session, offset, query)
        result = data.get("result", {})
        meta = result.get("metadata", {})
        if total is None:
            total = meta.get("total", {}).get("value", 0)
            print(f"[info] พบทั้งหมด {total:,} รายการ", file=sys.stderr)

        records = result.get("result", [])
        if not records:
            break

        for rec in records:
            yield rec
            fetched += 1
            if max_records is not None and fetched >= max_records:
                return

        offset += len(records)
        if offset >= total:
            break

        time.sleep(delay)  # กันยิงถี่เกินไปใส่เซิร์ฟเวอร์ของมหาวิทยาลัย


def flatten_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    contributors = rec.get("contributors") or []
    names = "; ".join(c.get("name", "") for c in contributors)
    degree = rec.get("degree_name") or []
    discipline = rec.get("degree_discipline") or []
    faculty = rec.get("faculty_college") or []
    return {
        "bibid": rec.get("bibid"),
        "title": rec.get("title"),
        "authors": names,
        "pubyear": rec.get("pubyear"),
        "degree_name": ", ".join(degree) if isinstance(degree, list) else degree,
        "degree_discipline": ", ".join(discipline) if isinstance(discipline, list) else discipline,
        "faculty_college": ", ".join(faculty) if isinstance(faculty, list) else faculty,
        "main_collection_name": rec.get("main_collection_name"),
        "collection_name": rec.get("collection_name"),
        "link": rec.get("link"),
        "cover": rec.get("cover"),
    }


def main():
    ap = argparse.ArgumentParser(description="ดึงรายการวิทยานิพนธ์/งานวิจัยจาก TU Digital Collections")
    ap.add_argument("--keyword", default="", help="คำค้นหา (ค้นในชื่อเรื่อง/คำสำคัญ/ผู้แต่ง ฯลฯ)")
    ap.add_argument("--main-collection-id", type=int, default=THESIS_MAIN_COLLECTION_ID,
                     help="เลขกลุ่มคอลเลกชันหลัก (ค่าเริ่มต้น 5 = งานวิจัยและวิทยานิพนธ์)")
    ap.add_argument("--collection-id", type=int, default=None, help="เลขคอลเลกชันย่อย (ถ้าต้องการเจาะจง)")
    ap.add_argument("--year-start", default="", help="ปีเริ่มต้น (พ.ศ. หรือ ค.ศ. ตามที่เว็บเก็บ)")
    ap.add_argument("--year-end", default="", help="ปีสิ้นสุด")
    ap.add_argument("--per-page", type=int, default=200, help="จำนวนรายการต่อ request (ทดสอบสูงสุดถึง 1000)")
    ap.add_argument("--max-records", type=int, default=None, help="จำกัดจำนวนรายการสูงสุดที่จะดึง (ไว้ทดสอบ)")
    ap.add_argument("--delay", type=float, default=0.4, help="วินาทีที่หน่วงระหว่าง request แต่ละครั้ง")
    ap.add_argument("--out", default="theses.csv", help="ไฟล์ผลลัพธ์ (.csv หรือ .json)")
    ap.add_argument("--format", choices=["csv", "json"], default=None,
                     help="รูปแบบผลลัพธ์ (ถ้าไม่ระบุจะเดาจากนามสกุลไฟล์ --out)")
    args = ap.parse_args()

    fmt = args.format or ("json" if args.out.lower().endswith(".json") else "csv")

    records = []
    for rec in iter_records(
        keyword=args.keyword,
        main_collection_id=args.main_collection_id,
        collection_id=args.collection_id,
        year_start=args.year_start,
        year_end=args.year_end,
        per_page=args.per_page,
        max_records=args.max_records,
        delay=args.delay,
    ):
        records.append(rec)
        if len(records) % 200 == 0:
            print(f"[info] ดึงมาแล้ว {len(records):,} รายการ...", file=sys.stderr)

    print(f"[info] ดึงเสร็จทั้งหมด {len(records):,} รายการ กำลังบันทึกลง {args.out}", file=sys.stderr)

    if fmt == "json":
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    else:
        flat: List[Dict[str, Any]] = [flatten_record(r) for r in records]
        fieldnames = list(flat[0].keys()) if flat else [
            "bibid", "title", "authors", "pubyear", "degree_name",
            "degree_discipline", "faculty_college", "main_collection_name",
            "collection_name", "link", "cover",
        ]
        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flat)

    print("[done]", file=sys.stderr)


if __name__ == "__main__":
    main()
