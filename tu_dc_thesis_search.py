#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tu_dc_thesis_search.py
========================

ค้นหาวิทยานิพนธ์/งานวิจัยจาก TU Digital Collections ด้วยคีย์เวิร์ด แล้วดึง
ข้อมูลรายละเอียดของแต่ละรายการ:

    Title, Creator, Keyword, Abstract, Publisher, Date of issue

วิธีทำงาน (2 ขั้นตอน):
    1. ยิง search API (เหมือน tu_dc_thesis_api.py) เพื่อได้ "รายชื่อ" ที่ตรงคีย์เวิร์ด
       -> ได้ bibid / link ของแต่ละรายการ
    2. โหลดหน้า detail ของแต่ละรายการ (https://.../Info/item/dc:<bibid>)
       ซึ่งเป็น server-rendered HTML ที่มี Dublin Core meta tags ฝังอยู่
       (<meta name="DC.title" ...>, DC.creator, DC.subject, DC.description,
       DC.publisher, DC.date) แล้วดึงค่าจาก meta tags เหล่านี้ออกมาโดยตรง
       (ไม่ต้อง parse เนื้อหาหน้าเว็บที่เป็น Angular template)

หมายเหตุ:
    - DC.description ไม่ใช่ทุกเรคคอร์ดจะมี (บางรายการเก่า/บางประเภทไม่มีบทคัดย่อ)
    - DC.creator อาจมีหลายรายการ (ชื่อไทย/อังกฤษ) จะถูกรวมด้วย "; "
    - ต้องยิง 1 request ต่อ 1 รายการเพื่อดึง detail ดังนั้นถ้าผลลัพธ์เยอะจะใช้เวลา
      พอสมควร ใช้ --max-records จำกัดตอนทดสอบ และ --delay กันยิงถี่เกินไป

--------------------------------------------------------------------------
วิธีใช้
--------------------------------------------------------------------------
    pip install requests

    # ค้นด้วยคีย์เวิร์ด แล้วบันทึกเป็น CSV
    python tu_dc_thesis_search.py --keyword "การตลาด" --out result.csv

    # จำกัดปี และจำนวนสูงสุด (ทดสอบ)
    python tu_dc_thesis_search.py --keyword "การตลาด" --year-start 2020 --year-end 2023 --max-records 20

    # เอาผลลัพธ์เป็น JSON
    python tu_dc_thesis_search.py --keyword "การตลาด" --out result.json --format json

    # ถ้าเครื่องมีปัญหา SSL certificate ตอนต่อเว็บ ให้ใส่ --insecure (ข้าม verify)
    python tu_dc_thesis_search.py --keyword "การตลาด" --out result.csv --insecure
"""

import argparse
import csv
import html
import json
import re
import sys
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

BASE_URL = "https://digital.library.tu.ac.th/tu_dc/frontend/Search"
FIND_URL_TMPL = BASE_URL + "/find/{offset}/0"
DETAIL_URL_TMPL = "https://digital.library.tu.ac.th/tu_dc/frontend/Info/item/dc:{bibid}"

# กลุ่มคอลเลกชัน "งานวิจัยและวิทยานิพนธ์" (Research & Thesis)
THESIS_MAIN_COLLECTION_ID = 5

DEFAULT_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (compatible; tu-dc-thesis-fetcher/1.0; +personal research script)",
    "Referer": "https://digital.library.tu.ac.th/tu_dc/frontend/Search/",
}

META_RE = re.compile(
    r'<meta\s+name="DC\.(?P<field>[A-Za-z]+)"\s+content="(?P<value>.*?)"',
    re.IGNORECASE | re.DOTALL,
)


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


def fetch_page(
    session: requests.Session, offset: int, query: Dict[str, Any], verify: bool
) -> Dict[str, Any]:
    body = "data=" + requests.utils.quote(json.dumps(query, ensure_ascii=False))
    resp = session.post(
        FIND_URL_TMPL.format(offset=offset),
        data=body.encode("utf-8"),
        headers=DEFAULT_HEADERS,
        timeout=30,
        verify=verify,
    )
    resp.raise_for_status()
    return resp.json()


def iter_search_hits(
    keyword: str,
    main_collection_id: Optional[int] = THESIS_MAIN_COLLECTION_ID,
    collection_id: Optional[int] = None,
    year_start: str = "",
    year_end: str = "",
    per_page: int = 200,
    max_records: Optional[int] = None,
    delay: float = 0.4,
    verify: bool = True,
) -> Iterator[Dict[str, Any]]:
    """ไล่ดึงทีละหน้า (pagination) จาก search API แล้ว yield record (list-level) ทีละรายการ"""
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
        data = fetch_page(session, offset, query, verify)
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

        time.sleep(delay)


def parse_detail_meta(html_text: str) -> Dict[str, List[str]]:
    """ดึงค่า DC.* meta tags ทั้งหมดจากหน้า detail (server-rendered HTML)"""
    fields: Dict[str, List[str]] = {}
    for m in META_RE.finditer(html_text):
        field = m.group("field").lower()
        value = html.unescape(m.group("value")).strip()
        if not value:
            continue
        fields.setdefault(field, []).append(value)
    return fields


def fetch_detail(session: requests.Session, bibid: Any, verify: bool) -> Dict[str, str]:
    url = DETAIL_URL_TMPL.format(bibid=bibid)
    resp = session.get(url, headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]}, timeout=30, verify=verify)
    resp.raise_for_status()
    fields = parse_detail_meta(resp.text)

    title = fields.get("title", [""])[0]
    creator = "; ".join(fields.get("creator", []))
    keyword = "; ".join(fields.get("subject", []))
    abstract = " ".join(fields.get("description", []))
    publisher = "; ".join(fields.get("publisher", []))
    date_of_issue = fields.get("date", [""])[0]

    return {
        "title": title,
        "creator": creator,
        "keyword": keyword,
        "abstract": abstract,
        "publisher": publisher,
        "date_of_issue": date_of_issue,
        "link": url,
    }


def search_theses(
    keyword: str,
    year_start: str = "",
    year_end: str = "",
    main_collection_id: Optional[int] = THESIS_MAIN_COLLECTION_ID,
    collection_id: Optional[int] = None,
    max_records: Optional[int] = None,
    delay: float = 0.4,
    verify: bool = True,
) -> List[Dict[str, str]]:
    """ค้นด้วยคีย์เวิร์ด แล้วดึงรายละเอียดครบ (title/creator/keyword/abstract/publisher/date) ทีละรายการ"""
    session = requests.Session()
    results: List[Dict[str, str]] = []

    for i, hit in enumerate(
        iter_search_hits(
            keyword=keyword,
            main_collection_id=main_collection_id,
            collection_id=collection_id,
            year_start=year_start,
            year_end=year_end,
            max_records=max_records,
            delay=delay,
            verify=verify,
        ),
        start=1,
    ):
        bibid = hit.get("bibid")
        try:
            detail = fetch_detail(session, bibid, verify)
        except requests.RequestException as e:
            print(f"[warn] ดึง detail ของ bibid={bibid} ไม่สำเร็จ: {e}", file=sys.stderr)
            continue

        # เผื่อหน้า detail ไม่มี title (ไม่ควรเกิด) ให้ fallback จาก list record
        if not detail["title"]:
            detail["title"] = hit.get("title", "")

        results.append(detail)
        if i % 20 == 0:
            print(f"[info] ดึงรายละเอียดแล้ว {i} รายการ...", file=sys.stderr)

        time.sleep(delay)

    return results


def main():
    ap = argparse.ArgumentParser(
        description="ค้นหาวิทยานิพนธ์/งานวิจัยจาก TU Digital Collections ด้วยคีย์เวิร์ด "
        "แล้วดึง Title/Creator/Keyword/Abstract/Publisher/Date of issue"
    )
    ap.add_argument("--keyword", required=True, help="คำค้นหา")
    ap.add_argument("--main-collection-id", type=int, default=THESIS_MAIN_COLLECTION_ID,
                     help="เลขกลุ่มคอลเลกชันหลัก (ค่าเริ่มต้น 5 = งานวิจัยและวิทยานิพนธ์)")
    ap.add_argument("--collection-id", type=int, default=None,
                     help="เลขคอลเลกชันย่อย เช่น 20 = Thammasat University Theses (ปริญญาโท/เอกตัวจริง), "
                          "13 = Special Project (TU Undergraduate)")
    ap.add_argument("--year-start", default="", help="ปีเริ่มต้น")
    ap.add_argument("--year-end", default="", help="ปีสิ้นสุด")
    ap.add_argument("--max-records", type=int, default=None, help="จำกัดจำนวนรายการสูงสุดที่จะดึง")
    ap.add_argument("--delay", type=float, default=0.4, help="วินาทีที่หน่วงระหว่าง request แต่ละครั้ง")
    ap.add_argument("--out", default="result.csv", help="ไฟล์ผลลัพธ์ (.csv หรือ .json)")
    ap.add_argument("--format", choices=["csv", "json"], default=None,
                     help="รูปแบบผลลัพธ์ (ถ้าไม่ระบุจะเดาจากนามสกุลไฟล์ --out)")
    ap.add_argument("--insecure", action="store_true",
                     help="ข้าม SSL certificate verification (ใช้เมื่อเครื่องมีปัญหา cert)")
    args = ap.parse_args()

    if args.insecure:
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

    fmt = args.format or ("json" if args.out.lower().endswith(".json") else "csv")

    results = search_theses(
        keyword=args.keyword,
        year_start=args.year_start,
        year_end=args.year_end,
        main_collection_id=args.main_collection_id,
        collection_id=args.collection_id,
        max_records=args.max_records,
        delay=args.delay,
        verify=not args.insecure,
    )

    print(f"[info] ดึงเสร็จทั้งหมด {len(results):,} รายการ กำลังบันทึกลง {args.out}", file=sys.stderr)

    fieldnames = ["title", "creator", "keyword", "abstract", "publisher", "date_of_issue", "link"]

    if fmt == "json":
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    else:
        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    print("[done]", file=sys.stderr)


if __name__ == "__main__":
    main()
