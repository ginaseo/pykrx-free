#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
한국 주식 모닝 브리핑용 데이터 수집 스크립트 (로컬 PC에서 실행)

[실행]  (이 폴더에서)
    .venv\\Scripts\\python krx_briefing_fetch.py        # Windows venv 사용 시
    또는   python krx_briefing_fetch.py

[결과]
    이 폴더에 briefing_data.json 생성/갱신 → 클로드가 읽어 브리핑 작성.

* NVDA까지 받으려면:  pip install yfinance  (없으면 클로드가 자동으로 채움)
"""

import os, json, datetime
import pandas as pd
import krx_naver               # 자체 Naver OHLCV 클라 (pykrx 비의존)

# 출력 위치 = 스크립트 폴더 아래 results/. 없으면 생성.
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(OUT_DIR, exist_ok=True)

# KRX 공식 OpenAPI (인증키 방식, 로그인 없음). 지수 조회용.
try:
    import krx_openapi
except Exception:
    krx_openapi = None

HOLDINGS = [
    {"name": "삼성전자",   "code": "005930", "shares": 3,  "avg": 198033},
    {"name": "KODEX 200", "code": "069500", "shares": 34, "avg": 90170},
    {"name": "NAVER",      "code": "035420", "shares": 30, "avg": 248866},
    {"name": "한화솔루션", "code": "009830", "shares": 1,  "avg": 58200},
]
NVDA = {"avg": 103.48, "shares": 0.052639}

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    return (100 - 100 / (1 + gain / loss)).iloc[-1]

def analyze(code):
    end = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime("%Y%m%d")
    df = krx_naver.ohlcv(code, start, end)
    df = df[df["거래량"] > 0]
    if df.empty:
        return None
    close = df["종가"].astype(float)
    last = df.iloc[-1]
    cur = float(last["종가"])
    prev_close = float(close.iloc[-2]) if len(close) > 1 else cur
    H, L, C = float(last["고가"]), float(last["저가"]), cur
    P = (H + L + C) / 3
    return {
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "current": cur, "prev_close": prev_close,
        "pct": round((cur - prev_close) / prev_close * 100, 2),
        "rsi14": round(float(rsi(close)), 1),
        "ma5": round(float(close.rolling(5).mean().iloc[-1]), 1),
        "ma20": round(float(close.rolling(20).mean().iloc[-1]), 1),
        "ma50": round(float(close.rolling(50).mean().iloc[-1]), 1),
        "ma200": round(float(close.rolling(200).mean().iloc[-1]), 1) if len(close) >= 200 else None,
        "pivot_s1": round(2 * P - H, 1), "pivot_p": round(P, 1), "pivot_r1": round(2 * P - L, 1),
    }

def _recent_trading_day():
    """주말/오늘 데이터 없을 때 대비해 최근 영업일 후보를 역순으로."""
    base = datetime.datetime.now()
    out = []
    for i in range(0, 7):
        d = base - datetime.timedelta(days=i)
        if d.weekday() < 5:  # 평일만
            out.append(d.strftime("%Y%m%d"))
    return out


def index_snapshot(market, idx_name):
    """KRX OpenAPI(idx)로 지수 스냅샷. 로그인 불필요.

    market: 'KOSPI'/'KOSDAQ',  idx_name: 응답에서 고를 종합지수명('코스피'/'코스닥').
    idx 서비스 미신청(401/404)이면 사유를 담아 반환.
    """
    if krx_openapi is None:
        return {"note": "krx_openapi 모듈 없음"}
    last_err = None
    for d in _recent_trading_day():
        try:
            df = krx_openapi.index_daily(d, market)
        except Exception as e:
            last_err = str(e)
            continue
        if df is None or df.empty:
            continue
        row = df[df["IDX_NM"] == idx_name]
        if row.empty:
            row = df.iloc[[0]]  # 종합지수가 첫 행인 경우 대비
        r = row.iloc[0]
        cur = float(r["CLSPRC_IDX"])
        pct = float(r.get("FLUC_RT", 0) or 0)
        return {"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "current": round(cur, 2), "pct": pct}
    return {"note": f"지수 조회 실패(idx 서비스 이용신청 필요?): {last_err}"}

out = {"generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST"), "holdings": [], "indices": {}}

for h in HOLDINGS:
    a = analyze(h["code"])
    if a:
        a.update({"name": h["name"], "code": h["code"], "shares": h["shares"], "avg": h["avg"],
                  "return_pct": round((a["current"] - h["avg"]) / h["avg"] * 100, 2),
                  "pnl_krw": round((a["current"] - h["avg"]) * h["shares"])})
    out["holdings"].append(a or {"name": h["name"], "code": h["code"], "error": "no data"})

for nm, idxnm in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
    out["indices"][nm] = index_snapshot(nm, idxnm)

try:
    import yfinance as yf
    hist = yf.Ticker("NVDA").history(period="5d")
    cur = float(hist["Close"].iloc[-1]); prev = float(hist["Close"].iloc[-2])
    out["nvda"] = {"current": round(cur, 2), "pct": round((cur - prev) / prev * 100, 2),
                   "avg": NVDA["avg"], "shares": NVDA["shares"],
                   "return_pct": round((cur - NVDA["avg"]) / NVDA["avg"] * 100, 2),
                   "pnl_usd": round((cur - NVDA["avg"]) * NVDA["shares"], 2)}
except Exception:
    out["nvda"] = {"note": "yfinance 미설치 — NVDA는 클로드가 자동으로 채웁니다."}

with open(os.path.join(OUT_DIR, "briefing_data.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print("저장 완료 -> briefing_data.json")
print(json.dumps(out, ensure_ascii=False, indent=2))
