#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
구글 뉴스 RSS 기반 종목명 검색 — "모멘텀은 있는데 뉴스가 없다"를 잡기 위한 최소 신호.

별도 인증키 불필요(공개 RSS). 풀텍스트/감성분석은 하지 않음 — 최근 N일 기사 건수만 센다.
"""
import datetime
from email.utils import parsedate_to_datetime

import requests
from defusedxml import ElementTree as ET

URL = "https://news.google.com/rss/search"
UA = "Mozilla/5.0"


def count_recent(query: str, days: int = 7):
    """query(종목명)로 구글뉴스 RSS 검색 후 최근 days일 내 기사 수.

    네트워크/파싱 실패 시 None(데이터 확인 불가) — "기사 0건"과 구분해야
    호출부에서 에러를 "뉴스 없음"으로 잘못 해석하지 않는다.
    """
    try:
        r = requests.get(URL, params={"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
                          headers={"User-Agent": UA}, timeout=15)
        root = ET.fromstring(r.content)
    except Exception:
        return None

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    n = 0
    for item in root.iter("item"):
        pub = item.findtext("pubDate")
        if not pub:
            continue
        try:
            dt = parsedate_to_datetime(pub)
            if dt.tzinfo is None:                 # 타임존 없는 RFC822 값 방어
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            if dt >= cutoff:
                n += 1
        except Exception:
            continue
    return n


if __name__ == "__main__":
    print("삼성전자 최근 7일 기사 수:", count_recent("삼성전자"))
