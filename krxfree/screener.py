#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
코스피200 스크리너 — KRX OpenAPI + Naver + (로그인) PER/PBR + DART

[유니버스] 로그인 시 KRX 지수구성종목(MDCSTAT00601) 자동 → 수동 명단 → 시총상위200.
[가치]     PER/PBR/배당 = KRX 공식값(로그인). 없으면 가치 팩터 제외.
[가점]     기술적(Naver) + DART(성장성/ROE/부채, 금융·보험 부채감점 면제).

[결과] results/kospi200_screen.json
[주의] 투자 자문 아님. 출력 수치는 실측/실측기반만(DESIGN.md 데이터 원칙).
"""

import os
import json
import datetime

import pandas as pd

# .env 로드(KRX_ID/KRX_PW → 로그인 세션 판단에 os.getenv 사용).
try:
    from dotenv import load_dotenv
    from .paths import env_candidates
    for _c in env_candidates():
        if os.path.exists(_c):
            load_dotenv(_c)
            break
except Exception:
    pass

from .clients import naver, login, openapi, news
from .clients import macro as macro_client
try:
    from .clients import dart
except Exception:
    dart = None
from .loaders import load_members, load_held
from .paths import RESULTS_DIR

OUT_DIR = RESULTS_DIR
os.makedirs(OUT_DIR, exist_ok=True)

MEMBERS_MIN = 150      # 구성종목 명단이 이 미만이면 불완전으로 보고 폴백
UNIVERSE_TOP = 200     # 시총 상위 N = 코스피200 근사(폴백)
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
            df = openapi.stock_daily(bas, "KOSPI")
        except openapi.KrxApiError:
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


def krx_session():
    """KRX 로그인 세션 1회 생성(PER/PBR + 지수구성종목 공용). 자격증명 없거나 실패 시 None."""
    if not (os.getenv("KRX_ID") and os.getenv("KRX_PW")):
        return None
    try:
        return login.login()
    except Exception:
        return None


def value_factors(today, session):
    """PER/PBR/DIV DataFrame(index=종목코드) 반환. 세션 없거나 불가하면 None.
    KRX 공식값 = 로그인 세션으로 getJsonData(MDCSTAT03501) 호출.
    """
    if session is None:
        return None
    try:
        f = login.fundamental(session, today, "KOSPI")
        if f is not None and not f.empty and "PER" in f.columns:
            return f[["PER", "PBR", "DIV"]]
    except Exception:
        return None
    return None


HELD = load_held()


def main():
    now = datetime.datetime.now()

    # === 1) 최근 영업일 스냅샷 + 모멘텀 기준일 스냅샷 ===
    today, cur = _recent_trading_snapshot(now)
    past_anchor = datetime.datetime.strptime(today, "%Y%m%d") - datetime.timedelta(
        days=int(MOMENTUM_TDAYS * 1.5)
    )
    past_dd, past = _recent_trading_snapshot(past_anchor)

    # KRX 로그인 1회(있으면) — PER/PBR + 코스피200 구성종목 둘 다 이 세션 사용.
    session = krx_session()

    # === 2) 유니버스: KRX 자동 명단 → 수동 명단 → 시총 상위 200 근사 ===
    cur = cur[cur["TDD_CLSPRC"].fillna(0) > 0].copy()
    members, members_src = None, None
    if session is not None:
        try:
            m = login.index_members(session, today, "1028")  # KOSPI200
            if m and len(m) >= MEMBERS_MIN:
                members, members_src = m, "KRX 지수구성종목(MDCSTAT00601)"
        except Exception:
            pass
    if members is None:
        fm = load_members()
        if fm and len(fm) >= MEMBERS_MIN:
            members, members_src = fm, "kospi200_members.json"
        elif fm:
            print(f"[universe] 수동 명단 {len(fm)}개 < {MEMBERS_MIN} -> 불완전, 시총상위 폴백")
    if members:
        hit = [c for c in members if c in cur.index]
        cur = cur.loc[hit].copy()
        universe_label = f"코스피200 실제 구성종목 ({len(hit)}종목, {members_src})"
        print(f"[universe] {members_src}: {len(members)}개 중 스냅샷 매칭 {len(hit)}개")
    else:
        cur = cur.sort_values("MKTCAP", ascending=False).head(UNIVERSE_TOP)
        universe_label = f"KOSPI 시총 상위 {UNIVERSE_TOP} (코스피200 근사)"

    # === 3) 종목 메타(소속/구분) 결합 — 있으면 ===
    try:
        base = openapi.stock_base_info(today, "KOSPI")
        meta_cols = [c for c in ("SECT_TP_NM", "SECUGRP_NM", "MKT_TP_NM") if c in base.columns]
        if meta_cols:
            cur = cur.drop(columns=[c for c in meta_cols if c in cur.columns]).join(
                base[meta_cols], how="left")
    except openapi.KrxApiError:
        meta_cols = []

    # === 4) 팩터 ===
    cur = cur.join(past["TDD_CLSPRC"].rename("PAST_CLS"), how="left")
    ret = (cur["TDD_CLSPRC"] / cur["PAST_CLS"] - 1) * 100
    cur["mom_pct"] = ret.round(2)
    f_mom = minmax(ret.clip(lower=-25, upper=40).fillna(0))
    f_mom = f_mom.where(ret <= 40, f_mom * 0.6)  # 과열 감점

    f_liq = minmax(cur["ACC_TRDVAL"].fillna(0).clip(upper=cur["ACC_TRDVAL"].quantile(0.95)))
    f_size = minmax(cur["MKTCAP"].fillna(0).clip(upper=cur["MKTCAP"].quantile(0.95)))

    cur["f_momentum"] = f_mom.round(3)
    cur["f_liquidity"] = f_liq.round(3)
    cur["f_size"] = f_size.round(3)

    # 가치 팩터(PER/PBR) — KRX 공식값(로그인). 없으면 제외.
    vf = value_factors(today, session)
    value_on = vf is not None
    if value_on:
        cur = cur.join(vf, how="left")
        # PER/PBR 은 KRX 공식값만. 공식값 없는 종목(우선주 등)은 null (추측 계산 금지).
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
            o = naver.ohlcv(code, h_start, today)
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

    # === 5-b) DART 성장성/안정성 가점 + 공시 필터 (pool ∪ 보유종목, 키 있을 때만) ===
    # 공시는 보유종목도 포함해서 본다 — 신규 후보 거를 때뿐 아니라 "투자논리 깨짐" 경고용.
    fundamentals = {}
    sectors = {}          # {종목코드: 업종버킷} — 부채 감점 면제 판정 + 출력용
    disclosure_map = {}   # {종목코드: {"hard_negative":[...], "soft_negative":[...], "positive":[...]}}
    excluded = set()      # 강한 악재 공시(관리종목/상장폐지/횡령 등) -> 신규 후보만 제외, 보유종목은 경고로 유지
    dart_codes = sorted(set(pool.index) | (HELD & set(cur.index)))
    if dart is not None:
        try:
            cmap = dart.load_corp_map()
        except Exception:
            cmap = {}
        try:
            sectors = dart.sectors_for(dart_codes, cmap)  # company.json, 캐시
        except Exception:
            sectors = {}
        disc_bgn = (datetime.datetime.strptime(today, "%Y%m%d")
                    - datetime.timedelta(days=30)).strftime("%Y%m%d")
        for code in dart_codes:
            cc = cmap.get(code) or cmap.get(dart.base_code(code))  # 우선주->본주
            if not cc:
                continue
            _fy = now.year - 1                  # 최신 사업보고서(직전 회계연도), 미공시면 그 전년
            fin = dart.financials(cc, _fy) or dart.financials(cc, _fy - 1)
            b = 0.0
            if fin:
                fundamentals[code] = fin
                if (fin.get("op_growth_pct") or 0) > 0:
                    b += 0.03
                if (fin.get("rev_growth_pct") or 0) >= 10:
                    b += 0.02
                if (fin.get("roe_pct") or 0) >= 8:
                    b += 0.03
                dr = fin.get("debt_ratio_pct")
                # 금융·보험은 구조적 고부채 -> 부채비율 감점 면제(업종 불리 교정)
                if dr is not None and dr > 200 and not dart.is_financial(sectors.get(code)):
                    b -= 0.03

            try:
                flags = dart.disclosure_flags(cc, disc_bgn, today)
            except Exception:
                flags = None
            disclosure_map[code] = flags   # None = 조회 실패(모름). "공시 없음"과 절대 혼동 금지.
            if flags is not None:
                if flags["hard_negative"] and code not in HELD:
                    excluded.add(code)
                elif flags["soft_negative"]:
                    has_ci = any("유상증자결정" in (it.get("report_nm") or "") for it in flags["soft_negative"])
                    has_cb = any("전환사채권발행결정" in (it.get("report_nm") or "") for it in flags["soft_negative"])
                    if has_ci or has_cb:
                        try:
                            dil = dart.dilution_flags(cc, disc_bgn, today)
                        except Exception:
                            dil = None
                        if dil is not None:
                            if dil["capital_increase"] or dil["convertible_bond"]:
                                flags["dilution"] = dil
                            b += dart.dilution_severity(dil)
                        # dil 조회 실패면 감점 보류(모르는 걸 페널티로 단정 안 함)
                    else:
                        b -= 0.05  # 그 외 SOFT_NEGATIVE(교환사채 등)는 기존 고정 감점
                if flags["positive"]:
                    b += 0.02

            if code in cur.index:
                cur.loc[code, "score"] += b

    if excluded:
        cur = cur.drop(index=[c for c in excluded if c in cur.index])

    # === 5-c) 뉴스 건수 (최근 7일, Google News RSS) — "재료 없는 변동성" 탐지용 ===
    news_count_map = {}   # 실패(None)는 저장 안 함 -> "확인 안 됨"과 "0건 확인"을 구분
    for code in dart_codes:
        nm = cur.loc[code, "ISU_NM"] if code in cur.index and "ISU_NM" in cur.columns else None
        if not nm or pd.isna(nm):
            continue
        try:
            cnt = news.count_recent(str(nm), days=7)
        except Exception:
            cnt = None
        if cnt is not None:
            news_count_map[code] = cnt

    enriched_codes = set(dart_codes)  # 공시/뉴스/펀더멘털 체크를 실제로 한 종목만 라벨링 대상
    MOMENTUM_HIGH_PCT = 15  # 이 이상 모멘텀이면 "왜 오르는지" 라벨링 대상
    NEWS_LOW_THRESHOLD = 2  # 최근 7일 기사 수 이하면 "뉴스로 설명 안 되는 변동" 신호

    def _growth_good(code):
        fin = fundamentals.get(code)
        return bool(fin and ((fin.get("op_growth_pct") or -999) > 0
                              or (fin.get("rev_growth_pct") or -999) >= 10))

    def _momentum_label(code, mom_pct):
        if mom_pct is None or mom_pct < MOMENTUM_HIGH_PCT:
            return None
        if code not in enriched_codes:
            return None  # 공시/뉴스/실적 체크 자체를 안 한 종목 -> 모르면 라벨 안 닮(오탐 방지)
        if _growth_good(code):
            return "실적 동반 상승"
        if (disclosure_map.get(code) or {}).get("positive"):
            return "공시 모멘텀"
        nc = news_count_map.get(code)
        if nc is not None and nc <= NEWS_LOW_THRESHOLD:
            return "원인 불명 변동성"
        return "재료 미확인 상승"

    def _thesis_status(code):
        flags = disclosure_map.get(code)
        if flags is None:
            return "확인 불가"  # 공시 조회 자체가 안 됨(미체크/API실패) -> "양호"로 단정 금지
        if flags.get("hard_negative"):
            return "재검토 필요"
        fin = fundamentals.get(code)
        growth_bad = bool(fin and (fin.get("op_growth_pct") or 0) < 0 and (fin.get("rev_growth_pct") or 0) < 0)
        if flags.get("soft_negative") or growth_bad:
            return "주의"
        return "양호"

    # === 5-d) ETF/지수상품 보유 판단용 매크로 (개별종목 무관, 1회만 계산) ===
    macro = {
        "us10y": macro_client.us10y_trend(),
        "usdkrw": macro_client.usdkrw_trend(),
        "kospi": macro_client.kospi_trend(),
        "foreign_netflow_7d_won": macro_client.foreign_netflow(session, days=7),
    }

    # === 5-e) KODEX 200(ETF) 보유 현황 — 개별주 유니버스엔 없음(ETF), 팩터 미적용
    KODEX200_CODE = "069500"
    kodex200_holding = None
    if KODEX200_CODE in HELD:
        try:
            etf_cur = openapi.etf_daily(today)
            etf_past = openapi.etf_daily(past_dd)
            if KODEX200_CODE in etf_cur.index:
                row = etf_cur.loc[KODEX200_CODE]
                close = float(row["TDD_CLSPRC"])
                mom_pct = None
                if KODEX200_CODE in etf_past.index:
                    past_close = float(etf_past.loc[KODEX200_CODE]["TDD_CLSPRC"])
                    if past_close:
                        mom_pct = round((close / past_close - 1) * 100, 2)
                kodex200_holding = {
                    "code": KODEX200_CODE,
                    "name": row.get("ISU_NM"),
                    "close": close,
                    "nav": None if pd.isna(row.get("NAV")) else float(row["NAV"]),
                    "fluc_rt": None if pd.isna(row.get("FLUC_RT")) else float(row["FLUC_RT"]),
                    "momentum_pct": mom_pct,
                    "note": "개별주 팩터(모멘텀/가치/유동성/사이즈) 미적용. macro 섹션으로 판단",
                }
        except openapi.KrxApiError:
            kodex200_holding = None

    # === 6) 출력 ===
    final = cur.sort_values("score", ascending=False)
    # 보유종목은 점수 순위와 무관하게 항상 포함(thesis 판단 노출 보장) + 비보유 상위 TOP_N
    top_non_held = [c for c in final.index if c not in HELD][:TOP_N]
    out_codes = sorted(set(top_non_held) | (HELD & set(final.index)),
                        key=lambda c: -float(final.loc[c, "score"]))
    recs = []
    for code in out_codes:
        r = final.loc[code]
        recs.append({
            "code": code,
            "name": r.get("ISU_NM"),
            "held": code in HELD,
            "score": round(float(r["score"]), 3),
            "close": None if pd.isna(r["TDD_CLSPRC"]) else float(r["TDD_CLSPRC"]),
            "momentum_pct": None if pd.isna(r["mom_pct"]) else float(r["mom_pct"]),
            "trdval_won": None if pd.isna(r["ACC_TRDVAL"]) else int(r["ACC_TRDVAL"]),
            "mktcap_won": None if pd.isna(r["MKTCAP"]) else int(r["MKTCAP"]),
            # 업종: DART KSIC 버킷 우선. 없으면 KRX SECT_TP_NM(대개 빈값) fallback.
            "sector": (sectors.get(code)
                       or (None if pd.isna(r.get("SECT_TP_NM")) or not str(r.get("SECT_TP_NM")).strip()
                           else str(r.get("SECT_TP_NM")))),
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
                "rev_growth_pct": fundamentals[code].get("rev_growth_pct"),
                "op_growth_pct": fundamentals[code].get("op_growth_pct"),
                "roe_pct": fundamentals[code].get("roe_pct"),
                "debt_ratio_pct": fundamentals[code].get("debt_ratio_pct"),
                "year": fundamentals[code].get("year"),
            } if code in fundamentals else None),
            "momentum_label": _momentum_label(
                code, None if pd.isna(r["mom_pct"]) else float(r["mom_pct"])),
            "disclosure": ({k: v for k, v in (disclosure_map.get(code) or {}).items() if v}
                            or None),
            "disclosure_checked": disclosure_map.get(code) is not None,
            "thesis_status": (_thesis_status(code) if code in HELD else None),
            "news_count_7d": news_count_map.get(code),
        })

    out = {
        "generated": now.strftime("%Y-%m-%d %H:%M KST"),
        "as_of": today,
        "momentum_base": past_dd,
        "universe": universe_label,
        "value_source": ("KRX 공식값 (로그인 클라 krxfree.clients.login)" if value_on else "없음(가치 팩터 제외)"),
        "method": (
            "모멘텀30/가치25/유동성25/사이즈20 + 기술적 가점"
            if value_on else
            "모멘텀55/유동성30/사이즈15 + 기술적 가점 (가치 미포함)"
        ),
        "dart_factors": ("성장성/안정성 가점 적용(매출·영업익 성장률, ROE, 부채비율; 금융·보험은 부채 감점 면제)" if fundamentals else "없음"),
        "sector_source": ("DART 기업개황 induty_code(KSIC) 버킷" if sectors else "없음"),
        "disclosure_source": ("OpenDART 공시검색 최근 30일 (강한 악재=신규후보 제외, 중간 악재=감점, 호재=가점)"
                              if disclosure_map else "없음"),
        "news_source": ("Google News RSS 종목명 검색, 최근 7일 기사 수" if news_count_map else "없음"),
        "macro": macro,
        "macro_note": "KODEX200 등 지수상품 보유 판단은 개별종목 공시/뉴스보다 이 매크로 지표(미국10년물·환율·코스피추세·외국인수급)가 더 설명력 있음",
        "kodex200_holding": kodex200_holding,
        "disclaimer": "투자 자문 아님. 공개데이터 기반 단순 스크리닝. 투자 판단·손익 책임은 사용자.",
        "recommendations": recs,
    }
    with open(os.path.join(OUT_DIR, "kospi200_screen.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("저장 완료 -> kospi200_screen.json")
    dump = json.dumps(out, ensure_ascii=False, indent=2)
    try:
        print(dump)
    except UnicodeEncodeError:
        # 콘솔 코드페이지(cp949 등)가 표현 못 하는 문자가 있어도 저장은 끝났으니 죽지 않게 처리.
        print(dump.encode("ascii", errors="backslashreplace").decode("ascii"))


if __name__ == "__main__":
    main()
