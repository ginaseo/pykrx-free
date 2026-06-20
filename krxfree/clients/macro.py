#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF(KODEX 200 등 지수상품) 보유 판단용 매크로 클라이언트.

개별종목 뉴스/공시보다 미국금리·환율·코스피추세·외국인수급이 더 설명력 있다는 전제(DESIGN 합의).

- 미국10년물(DGS10)/달러원(DEXKOUS): FRED 공개 CSV. 인증키 불필요.
- 코스피 추세: KRX OpenAPI idx_dd_trd(이미 이용신청됨, openapi.index_daily 재사용).
- 외국인 수급: data.krx.co.kr 내부 API(MDCSTAT02201). 로그인 세션 필요(login.login()).
"""
import datetime
import io

import pandas as pd
import requests

from . import openapi
from .login import _json_data, _num

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def _fred_series(series_id: str, days: int) -> pd.Series:
    """FRED 공개 CSV에서 series 값(index=date). 결측('.')은 제외."""
    start = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    r = requests.get(FRED_CSV, params={"id": series_id, "cosd": start}, timeout=20)
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "value"]
    df = df[df["value"] != "."]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = df["value"].astype(float)
    return df.set_index("date")["value"]


def us10y_trend(days: int = 30):
    """미국10년물(DGS10) 최신값(%)과 기간내 변화(bp). 실패 시 None."""
    try:
        s = _fred_series("DGS10", days)
        if s.empty:
            return None
        return {"latest_pct": float(s.iloc[-1]),
                "chg_bp": float(round((s.iloc[-1] - s.iloc[0]) * 100, 0))}
    except Exception:
        return None


def usdkrw_trend(days: int = 30):
    """달러/원(DEXKOUS) 최신값과 기간내 변화율(%). 실패 시 None."""
    try:
        s = _fred_series("DEXKOUS", days)
        if s.empty:
            return None
        return {"latest": float(s.iloc[-1]),
                "chg_pct": float(round((s.iloc[-1] / s.iloc[0] - 1) * 100, 2))}
    except Exception:
        return None


def kospi_trend(days: int = 20):
    """코스피 지수 최근 영업일 종가와 days 기준 변화율(%). 실패 시 None."""
    today = datetime.datetime.now()
    try:
        cur_dd, cur = _index_snapshot(today)
        past_dd, past = _index_snapshot(today - datetime.timedelta(days=int(days * 1.5)))
    except RuntimeError:
        return None
    if cur is None or past is None:
        return None
    return {"as_of": cur_dd, "close": cur,
            "chg_pct": round((cur / past - 1) * 100, 2)}


def _index_snapshot(from_dt):
    """from_dt 부터 거슬러 올라가며 KOSPI 지수값 있는 첫 영업일 (날짜, 종가) 반환."""
    d = from_dt
    for _ in range(10):
        if d.weekday() < 5:
            bas = d.strftime("%Y%m%d")
            try:
                df = openapi.index_daily(bas, "KOSPI")
            except openapi.KrxApiError:
                d -= datetime.timedelta(days=1)
                continue
            if df is not None and not df.empty and "IDX_NM" in df.columns:
                row = df[df["IDX_NM"] == "코스피"]
                if not row.empty and pd.notna(row.iloc[0]["CLSPRC_IDX"]):
                    return bas, float(row.iloc[0]["CLSPRC_IDX"])
        d -= datetime.timedelta(days=1)
    raise RuntimeError("최근 영업일 KOSPI 지수값을 찾지 못함")


def foreign_netflow(session, days: int = 7, mkt_id: str = "ALL"):
    """최근 days일 외국인 순매수 거래대금(원, KOSPI+KOSDAQ 합산). 로그인 세션 필요. 실패 시 None."""
    if session is None:
        return None
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    try:
        rows = _json_data(session, "dbms/MDC/STAT/standard/MDCSTAT02201",
                          strtDd=start.strftime("%Y%m%d"), endDd=end.strftime("%Y%m%d"),
                          mktId=mkt_id, etf="", etn="", elw="")
    except Exception:
        return None
    for r in rows:
        if (r.get("INVST_TP_NM") or "").strip() == "외국인":
            return _num(r.get("NETBID_TRDVAL"))
    return None


if __name__ == "__main__":
    from .login import login
    print("US10Y:", us10y_trend())
    print("USDKRW:", usdkrw_trend())
    print("KOSPI:", kospi_trend())
    print("외국인수급(7일):", foreign_netflow(login()))
