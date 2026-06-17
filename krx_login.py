#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KRX 로그인 + 내부 JSON API(getJsonData.cmd) 자체 클라이언트 — pykrx 비의존.

- data.krx.co.kr 회원 로그인(JSESSIONID) 후, 사이트 내부 통계 API 호출.
- 현재는 PER/PBR/배당(MDCSTAT03501)만 구현. (pykrx get_market_fundamental 대체)
- 인증: .env 의 KRX_ID / KRX_PW.
"""
import os
import time
import requests
import pandas as pd

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
LOGIN_JSP = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
JSON_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
REFERER = "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd"


def _creds():
    cid, cpw = os.getenv("KRX_ID"), os.getenv("KRX_PW")
    if cid and cpw:
        return cid, cpw
    try:
        from dotenv import dotenv_values
        here = os.path.dirname(os.path.abspath(__file__))
        for c in (os.path.join(here, ".env"), os.path.join(here, "pykrx-master", ".env")):
            if os.path.exists(c):
                v = dotenv_values(c)
                if v.get("KRX_ID") and v.get("KRX_PW"):
                    return v["KRX_ID"], v["KRX_PW"]
    except Exception:
        pass
    return None, None


class KrxLoginError(RuntimeError):
    pass


def login(login_id=None, login_pw=None) -> requests.Session:
    """KRX 로그인 후 인증된 requests.Session 반환."""
    if not login_id or not login_pw:
        login_id, login_pw = _creds()
    if not login_id or not login_pw:
        raise KrxLoginError(".env 에 KRX_ID/KRX_PW 없음")

    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    # warmup (초기 JSESSIONID + iframe 세션)
    s.get(LOGIN_PAGE, timeout=15)
    s.get(LOGIN_JSP, headers={"Referer": LOGIN_PAGE}, timeout=15)

    payload = {"mbrNm": "", "telNo": "", "di": "", "certType": "",
               "mbrId": login_id, "pw": login_pw}
    headers = {"Referer": LOGIN_PAGE}
    data = s.post(LOGIN_URL, data=payload, headers=headers, timeout=15).json()
    code = data.get("_error_code", "")
    if code == "CD011":  # 중복 로그인 -> 강제
        payload["skipDup"] = "Y"
        data = s.post(LOGIN_URL, data=payload, headers=headers, timeout=15).json()
        code = data.get("_error_code", "")
    if code != "CD001":
        raise KrxLoginError(f"로그인 실패: {code} {data.get('_error_message', '')}")
    return s


def _json_data(session: requests.Session, bld: str, **params) -> list:
    params["bld"] = bld
    headers = {"User-Agent": UA, "Referer": REFERER, "X-Requested-With": "XMLHttpRequest"}
    r = session.post(JSON_URL, data=params, headers=headers, timeout=20)
    return r.json().get("output", [])


def _num(x):
    s = str(x).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fundamental(session: requests.Session, date: str, market: str = "ALL") -> pd.DataFrame:
    """전종목 PER/PBR/EPS/BPS/DPS/배당수익률. market: STK/KSQ/KNX/ALL.

    반환 index=종목코드(6자리), 컬럼 PER/PBR/EPS/BPS/DPS/DIV/종가.
    """
    mkt = {"KOSPI": "STK", "KOSDAQ": "KSQ", "KONEX": "KNX", "ALL": "ALL"}.get(
        market.upper(), market.upper())
    rows = _json_data(session, "dbms/MDC/STAT/standard/MDCSTAT03501",
                      mktId=mkt, trdDd=date)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = pd.DataFrame(index=df["ISU_SRT_CD"].astype(str).str.zfill(6))
    out["종가"] = df["TDD_CLSPRC"].map(_num).values
    out["EPS"] = df["EPS"].map(_num).values
    out["PER"] = df["PER"].map(_num).values
    out["BPS"] = df["BPS"].map(_num).values
    out["PBR"] = df["PBR"].map(_num).values
    out["DPS"] = df["DPS"].map(_num).values
    out["DIV"] = df["DVD_YLD"].map(_num).values
    out.index.name = "종목코드"
    return out


def index_members(session: requests.Session, date: str, index_ticker: str = "1028") -> list:
    """지수 구성종목 6자리 코드 리스트(MDCSTAT00601). KOSPI200='1028'. 실패/빈값이면 [].

    로그인 세션 필요(KRX 가 무로그인 차단). index_ticker 앞1자리=indIdx, 나머지=indIdx2.
    """
    idx, idx2 = index_ticker[0], index_ticker[1:]
    rows = _json_data(session, "dbms/MDC/STAT/standard/MDCSTAT00601",
                      indIdx=idx, indIdx2=idx2, trdDd=date,
                      money="3", csvxls_isNo="false")
    out = []
    for r in rows:
        c = str(r.get("ISU_SRT_CD") or "").strip()
        if len(c) == 6 and c.isdigit():
            out.append(c)
    return out


if __name__ == "__main__":
    s = login()
    print("로그인 성공")
    df = fundamental(s, "20260612", "ALL")
    print("rows:", len(df), "| cols:", list(df.columns))
    for code in ["005930", "000270", "035420"]:
        if code in df.index:
            r = df.loc[code]
            print(f"{code}  PER={r['PER']}  PBR={r['PBR']}  DIV={r['DIV']}")
