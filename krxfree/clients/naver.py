#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
자체 Naver OHLCV 클라이언트.

Naver fchart 엔드포인트(count=기간형)를 직접 호출해 한 종목의 일봉 시계열을
1콜로 받아 DataFrame 반환.
"""
import datetime

import numpy as np
import pandas as pd
import requests
from defusedxml import ElementTree as ET

URL = "https://fchart.stock.naver.com/sise.nhn"
UA = "Mozilla/5.0"


def ohlcv(code: str, fromdate: str, todate: str) -> pd.DataFrame:
    """종목 일봉 OHLCV. fromdate/todate = 'YYYYMMDD'.

    컬럼: 시가/고가/저가/종가/거래량/등락률, index=날짜(datetime).
    """
    strtd = pd.to_datetime(fromdate)
    lastd = pd.to_datetime(todate)
    # count = 오늘 기준 필요한 일수 (여유 +2). Naver 는 시작일이 아니라 'count(최근N)'를 받음.
    count = (datetime.datetime.now() - strtd).days + 2
    if count < 1:
        count = 1

    r = requests.get(URL, params={"symbol": code, "timeframe": "day",
                                  "count": count, "requestType": "0"},
                     headers={"User-Agent": UA}, timeout=20)
    rows = []
    try:
        for node in ET.fromstring(r.text).iter("item"):
            rows.append(node.get("data").split("|"))
    except ET.ParseError:
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["날짜", "시가", "고가", "저가", "종가", "거래량"])
    df = df.set_index("날짜")
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.astype(np.int64)
    prev = df["종가"].shift(1)
    df["등락률"] = (df["종가"] - prev) / prev * 100
    return df.loc[(strtd <= df.index) & (df.index <= lastd)]


if __name__ == "__main__":
    df = ohlcv("005930", "20240102", "20240110")
    print("rows:", len(df))
    print(df.to_string())
