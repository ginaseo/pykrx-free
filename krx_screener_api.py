#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
코스피200(≈KODEX 200) 무로그인 스크리너 — KRX OpenAPI + Naver 기반

[인증] KRX 로그인 안 함. .env 의 API= 인증키만 사용(krx_openapi 경유).
       개별종목 기술적 지표용 OHLCV 는 pykrx Naver(무인증).

[데이터 한계]
  - KRX OpenAPI 엔 PER/PBR/배당 없음 -> '가치' 팩터 미포함(모멘텀/유동성/사이즈/기술적).
  - 코스피200 정확한 구성종목 명단 미제공 -> 'KOSPI 시총 상위 200'을 근사 유니버스로 사용.

[결과] kospi200_screen.json 생성.

[주의] 투자 자문 아님. 공개데이터 기반 단순 스크리닝. 투자 판단·손익 책임은 사용자.
"""

import os
import json
import datetime

import pandas as pd

# pykrx import 전에 .env 로드(KRX_ID/KRX_PW/DART_API). 로그인 경로 대비.
# DART_API 가 비어 있으면 KRX 로그인으로 get_market_fundamental 사용.
try:
    from dotenv import load_dotenv
    _here = os.path.dirname(os.path.abspath(__file__))
    for _c in (os.path.join(_here, ".env"), os.path.join(_here, "pykrx-master", ".env")):
        if os.path.exists(_c):
            load_dotenv(_c)
            break
except Exception:
    pass

import krx_naver              # 자체 Naver OHLCV 클라 (pykrx 비의존)
import krx_login              # 자체 KRX 로그인 PER/PBR 클라 (pykrx 비의존)
import krx_openapi             # KRX OpenAPI (인증키)
try:
    import krx_dart            # OpenDART (성장성/안정성 팩터). 키 없으면 None.
except Exception:
    krx_dart = None

# 출력 위치 = 스크립트 폴더 아래 results/. 없으면 생성.
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(OUT_DIR, exist_ok=True)

HELD = {"005930", "069500", "035420", "009830"}  # 보유 -> held 표시
UNIVERSE_TOP = 200     # 시총 상위 N = 코스피200 근사
STAGE2_POOL = 25       # 기술적 확인 대상
TOP_N = 12             # 최종 출력
MOMENTUM_TDAYS = 20    # 모멘텀 기준 거래일 수


# ---------- 영업일 helper (API emptiness 로 판정, 호출 최소화) ----------
def _weekdays_back(from_dt, n=8):
    out, d = [], from_dt
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= datetime.timedelta(days=1)
    return out


def _recent_trading_snapshot(start_dt):
    """start_dt 부터 거슬러 올라가며 데이터 있는 첫 영업일의 KOSPI 스냅샷 반환."""
    for d in _weekdays_back(start_dt):
        bas = d.strftime("%Y%m%d")
        try:
            df = krx_openapi.stock_daily(bas, "KOSPI")
        except krx_openapi.KrxApiError:
            continue
        if df is not None and not df.empty and df["TDD_CLSPRC"].fillna(0).gt(0).any():
            return bas, df
    raise RuntimeError("최근 영업일 KOSPI 스냅샷을 찾지 못함")


def minmax(s):
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or pd.isna(hi) or hi == lo:
        return pd.Series(0.5, index=s.index)
    return (s - lo) / (hi - lo)


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    return float((100 - 100 / (1 + gain / loss)).iloc[-1])


def value_factors(today):
    """PER/PBR/DIV DataFrame(index=종목코드) 반환. 불가하면 None.

    KRX 공식값 = 자체 로그인 클라(krx_login)로 getJsonData 직접 호출. pykrx 비의존.
    KRX_ID/KRX_PW 없으면 None -> 가치 팩터 제외.
    """
    if os.getenv("KRX_ID") and os.getenv("KRX_PW"):
        try:
            s = krx_login.login()
            f = krx_login.fundamental(s, today, "KOSPI")  # index=종목코드, PER/PBR/DIV 포함
            if f is not None and not f.empty and "PER" in f.columns:
                return f[["PER", "PBR", "DIV"]]
        except Exception:
            return None
    return None


def main():
    now = datetime.datetime.now()

    # === 1) 최근 영업일 스냅샷 + 모멘텀 기준일 스냅샷 ===
    today, cur = _recent_trading_snapshot(now)
    past_anchor = datetime.datetime.strptime(today, "%Y%m%d") - datetime.timedelta(
        days=int(MOMENTUM_TDAYS * 1.5)
    )
    past_dd, past = _recent_trading_snapshot(past_anchor)

    # === 2) 유니버스: 시총 상위 200 (코스피200 근사) ===
    cur = cur[cur["TDD_CLSPRC"].fillna(0) > 0].copy()
    cur = cur.sort_values("MKTCAP", ascending=False).head(UNIVERSE_TOP)

    # === 3) 종목 메타(소속/구분) 결합 — 있으면 ===
    try:
        base = krx_openapi.stock_base_info(today, "KOSPI")
        meta_cols = [c for c in ("SECT_TP_NM", "SECUGRP_NM", "MKT_TP_NM") if c in base.columns]
        if meta_cols:
            # stk_bydd_trd 에 이미 있는(대개 빈) 동일 컬럼은 버리고 base 값으로 교체
            cur = cur.drop(columns=[c for c in meta_cols if c in cur.columns]).join(
                base[meta_cols], how="left")
    except krx_openapi.KrxApiError:
        meta_cols = []

    # === 4) 팩터 ===
    # 모멘텀: 기간 수익률 (현재종가 / 과거종가 - 1)
    cur = cur.join(past["TDD_CLSPRC"].rename("PAST_CLS"), how="left")
    ret = (cur["TDD_CLSPRC"] / cur["PAST_CLS"] - 1) * 100
    cur["mom_pct"] = ret.round(2)
    f_mom = minmax(ret.clip(lower=-25, upper=40).fillna(0))
    f_mom = f_mom.where(ret <= 40, f_mom * 0.6)  # 과열 감점

    # 유동성: 거래대금
    f_liq = minmax(cur["ACC_TRDVAL"].fillna(0).clip(upper=cur["ACC_TRDVAL"].quantile(0.95)))

    # 사이즈: 시총 (대형 안정 가점, 약하게)
    f_size = minmax(cur["MKTCAP"].fillna(0).clip(upper=cur["MKTCAP"].quantile(0.95)))

    cur["f_momentum"] = f_mom.round(3)
    cur["f_liquidity"] = f_liq.round(3)
    cur["f_size"] = f_size.round(3)

    # 가치 팩터(PER/PBR) — DART 미발급 시 KRX 로그인으로 획득. 불가하면 제외.
    vf = value_factors(today)
    value_on = vf is not None
    if value_on:
        cur = cur.join(vf, how="left")
        per = cur["PER"].where(cur["PER"] > 0)
        pbr = cur["PBR"].where(cur["PBR"] > 0)
        f_per = 1 - minmax(per.clip(upper=per.quantile(0.95)))
        f_pbr = 1 - minmax(pbr.clip(upper=pbr.quantile(0.95)))
        f_value = ((f_per.fillna(0.3) + f_pbr.fillna(0.3)) / 2)
        cur["f_value"] = f_value.round(3)
        cur["score"] = 0.30 * f_mom + 0.25 * f_value + 0.25 * f_liq + 0.20 * f_size
    else:
        cur["score"] = 0.55 * f_mom + 0.30 * f_liq + 0.15 * f_size

    # === 5) 상위 후보 기술적 확인 (Naver OHLCV, 무로그인) ===
    pool = cur.sort_values("score", ascending=False).head(STAGE2_POOL)
    h_start = (datetime.datetime.strptime(today, "%Y%m%d") - datetime.timedelta(days=400)).strftime("%Y%m%d")
    tech = {}
    for code in pool.index:
        try:
            o = krx_naver.ohlcv(code, h_start, today)
            o = o[o["거래량"] > 0]
            c = o["종가"].astype(float)
            if len(c) < 60:
                continue
            ma5, ma20, ma60 = (c.rolling(w).mean().iloc[-1] for w in (5, 20, 60))
            ma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else None
            px = float(c.iloc[-1])
            tech[code] = {
                "rsi14": round(rsi(c), 1),
                "above_ma20": bool(px > ma20),
                "ma_uptrend": bool(ma5 > ma20 > ma60),
                "vs_ma200_pct": round((px / ma200 - 1) * 100, 1) if ma200 else None,
            }
        except Exception:
            continue

    for code, t in tech.items():
        bonus = 0.0
        if t["ma_uptrend"]:
            bonus += 0.05
        if t["above_ma20"]:
            bonus += 0.03
        if 40 <= t["rsi14"] <= 70:
            bonus += 0.04
        cur.loc[code, "score"] += bonus

    # === 5-b) DART 성장성/안정성 가점 (pool 한정, 키 있을 때만) ===
    dart = {}
    if krx_dart is not None and (os.getenv("DART_API") or True):
        try:
            cmap = krx_dart.load_corp_map()
        except Exception:
            cmap = {}
        for code in pool.index:
            cc = cmap.get(code)
            if not cc:
                continue
            fin = krx_dart.financials(cc, 2025) or krx_dart.financials(cc, 2024)
            if not fin:
                continue
            dart[code] = fin
            b = 0.0
            if (fin.get("op_growth_pct") or 0) > 0:
                b += 0.03
            if (fin.get("rev_growth_pct") or 0) >= 10:
                b += 0.02
            if (fin.get("roe_pct") or 0) >= 8:
                b += 0.03
            dr = fin.get("debt_ratio_pct")
            if dr is not None and dr > 200:
                b -= 0.03      # 고부채 감점
            cur.loc[code, "score"] += b

    # === 6) 출력 ===
    final = cur.sort_values("score", ascending=False)
    recs = []
    for code, r in final.head(TOP_N + len(HELD)).iterrows():
        recs.append({
            "code": code,
            "name": r.get("ISU_NM"),
            "held": code in HELD,
            "score": round(float(r["score"]), 3),
            "close": None if pd.isna(r["TDD_CLSPRC"]) else float(r["TDD_CLSPRC"]),
            "momentum_pct": None if pd.isna(r["mom_pct"]) else float(r["mom_pct"]),
            "trdval_won": None if pd.isna(r["ACC_TRDVAL"]) else int(r["ACC_TRDVAL"]),
            "mktcap_won": None if pd.isna(r["MKTCAP"]) else int(r["MKTCAP"]),
            # 참고: KRX OpenAPI 엔 업종 분류가 없음. SECT_TP_NM(소속부)은 KOSPI 일반종목 대개 빈값.
            "sector": (None if pd.isna(r.get("SECT_TP_NM")) or not str(r.get("SECT_TP_NM")).strip()
                       else str(r.get("SECT_TP_NM"))),
            "PER": (None if "PER" not in cur.columns or pd.isna(r.get("PER")) else round(float(r["PER"]), 1)),
            "PBR": (None if "PBR" not in cur.columns or pd.isna(r.get("PBR")) else round(float(r["PBR"]), 2)),
            "DIV": (None if "DIV" not in cur.columns or pd.isna(r.get("DIV")) else round(float(r["DIV"]), 2)),
            "factors": {
                "momentum": float(r["f_momentum"]),
                "value": (float(r["f_value"]) if "f_value" in cur.columns else None),
                "liquidity": float(r["f_liquidity"]),
                "size": float(r["f_size"]),
            },
            "technical": tech.get(code),
            "fundamentals_dart": ({
                "rev_growth_pct": dart[code].get("rev_growth_pct"),
                "op_growth_pct": dart[code].get("op_growth_pct"),
                "roe_pct": dart[code].get("roe_pct"),
                "debt_ratio_pct": dart[code].get("debt_ratio_pct"),
                "year": dart[code].get("year"),
            } if code in dart else None),
        })

    out = {
        "generated": now.strftime("%Y-%m-%d %H:%M KST"),
        "as_of": today,
        "momentum_base": past_dd,
        "universe": f"KOSPI 시총 상위 {UNIVERSE_TOP} (코스피200 근사)",
        "value_source": ("KRX 공식값 (자체 로그인 클라 krx_login)" if value_on else "없음(가치 팩터 제외)"),
        "method": (
            "모멘텀30/가치25/유동성25/사이즈20 + 기술적 가점"
            if value_on else
            "모멘텀55/유동성30/사이즈15 + 기술적 가점 (가치 미포함)"
        ),
        "dart_factors": ("성장성/안정성 가점 적용(매출·영업익 성장률, ROE, 부채비율)" if dart else "없음"),
        "disclaimer": "투자 자문 아님. 공개데이터 기반 단순 스크리닝. 투자 판단·손익 책임은 사용자.",
        "recommendations": recs,
    }
    with open(os.path.join(OUT_DIR, "kospi200_screen.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("저장 완료 -> kospi200_screen.json")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
