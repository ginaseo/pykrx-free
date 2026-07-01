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
import sys
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
from . import state as briefing_state
try:
    from .processors import pipeline as knowledge_pipeline
except Exception as _e:
    print(f"[knowledge] pipeline import 실패, Knowledge 갱신 비활성화: {_e}", file=sys.stderr)
    knowledge_pipeline = None

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

    # === 5-b) DART 성장성/안정성 가점 + 공시 이벤트 분류 (pool ∪ 보유종목, 키 있을 때만) ===
    # 공시는 보유종목도 포함해서 본다 — 신규 후보 거를 때뿐 아니라 Thesis Impact Engine 용.
    # 보유종목은 365일(rolling_365d 계산용), 그 외 후보는 30일만 조회(비용 절감).
    fundamentals = {}
    sectors = {}          # {종목코드: 업종버킷} — 부채 감점 면제 판정 + 출력용
    disclosure_map = {}   # {종목코드: {"dart": {event_type:[...]}, "krx": {event_type:[...]}}}
    excluded = set()      # HARD_EXCLUDE_TYPES 공시 -> 신규 후보만 제외, 보유종목은 Thesis 경고로 유지
    dart_codes = sorted(set(pool.index) | (HELD & set(cur.index)))
    # today_dt 는 DART 유무와 무관하게 이후 Thesis 섹션(5-c')에서 항상 쓰임 -> if 블록 밖에서 계산.
    today_dt = datetime.datetime.strptime(today, "%Y%m%d")
    if dart is not None:
        try:
            cmap = dart.load_corp_map()
        except Exception:
            cmap = {}
        try:
            sectors = dart.sectors_for(dart_codes, cmap)  # company.json, 캐시
        except Exception:
            sectors = {}
        disc_bgn_pool = (today_dt - datetime.timedelta(days=30)).strftime("%Y%m%d")
        disc_bgn_held = (today_dt - datetime.timedelta(days=365)).strftime("%Y%m%d")
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

            disc_bgn = disc_bgn_held if code in HELD else disc_bgn_pool
            try:
                flags = dart.disclosure_flags(cc, disc_bgn, today)
            except Exception:
                flags = None
            disclosure_map[code] = flags   # None = 조회 실패(모름). "공시 없음"과 절대 혼동 금지.
            if flags is not None and fin:
                # 재무제표 기반 Thesis 이벤트(ROE 개선/부채 감소) -> 공시와 동일한 dart 버킷에 편입
                # (rcept_no 없어 dedup·오늘 신규 판정 대상은 아니고, 날짜 기반 rolling 집계에만 반영).
                for fe in dart.fin_events(fin):
                    flags["dart"].setdefault(fe["event_type"], []).append(fe)
            if flags is not None:
                types_present = dart.event_types_present(flags)
                hard_present = bool(types_present & dart.HARD_EXCLUDE_TYPES)
                if hard_present:
                    if "unfaithful_disclosure" in types_present:
                        hist_bgn = (today_dt - datetime.timedelta(days=365 * 5)).strftime("%Y%m%d")
                        try:
                            flags["unfaithful_repeat_5y"] = dart.unfaithful_repeat_count(cc, hist_bgn, today)
                        except Exception:
                            flags["unfaithful_repeat_5y"] = None
                    if code not in HELD:
                        excluded.add(code)
                if types_present & dart.SOFT_PENALTY_TYPES:
                    # hard_negative 와 별개로 항상 확인 -> 보유종목이 불성실공시+유상증자를 동시에
                    # 안고 있어도 희석률 상세가 Thesis 엔진에서 누락되지 않게(예: 한화솔루션 실측).
                    if types_present & {"capital_increase", "cb_issue"}:
                        # 정정공시는 조회기간 안에 보여도 원결정(배정방식·희석률)은 그보다 훨씬
                        # 전일 수 있음(유상증자는 결정->효력발생까지 수개월) -> 1년 범위로 재조회.
                        dil_bgn = (today_dt - datetime.timedelta(days=365)).strftime("%Y%m%d")
                        try:
                            dil = dart.dilution_flags(cc, dil_bgn, today)
                        except Exception:
                            dil = None
                        if dil is not None:
                            if dil["capital_increase"] or dil["convertible_bond"]:
                                flags["dilution"] = dil
                            b += dart.dilution_severity(dil)
                            if dil.get("capital_increase"):
                                # 희석률 구간별 추가 감점 -> "유상증자"와 별개 항목으로 contributors 에 노출
                                max_pct = max((ci.get("dilution_pct") or 0) for ci in dil["capital_increase"])
                                extra = dart.dilution_extra_penalty(max_pct)
                                if extra != 0:
                                    ci_dates = [it.get("rcept_dt")
                                                for it in flags["dart"].get("capital_increase", [])]
                                    latest_dt = max(ci_dates) if ci_dates else today
                                    flags["dart"].setdefault("dilution_penalty", []).append({
                                        "report_nm": f"유상증자 희석률 {max_pct:.0f}%", "rcept_dt": latest_dt,
                                        "rcept_no": None, "dart_link": None, "event_type": "dilution_penalty",
                                        "level": "A", "confidence": "HIGH", "classification": "DART",
                                        "severity": 2, "impact_score": extra, "reason": f"희석률 {max_pct:.0f}%",
                                    })
                        # dil 조회 실패면 감점 보류(모르는 걸 페널티로 단정 안 함)
                    else:
                        b -= 0.05  # BW/최대주주변경 등 세부 조회 없는 SOFT_PENALTY 는 기존 고정 감점
                if types_present & dart.POSITIVE_BONUS_TYPES:
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

    # === 5-c') 공시 이력 비교 + Thesis Impact Score (보유종목 전용) ===
    # "어제 대비 무엇이 달라졌는지"(신규/후속 공시 판정) + Thesis 오늘/30일/1년 누적 점수.
    prev_state = briefing_state.load()
    prev_disclosures = prev_state.get("disclosures") or {}
    new_state_disclosures = {}
    new_state_thesis = {}
    thesis_map = {}   # {종목코드: Thesis dict} — 보유종목만 채움
    d30 = (today_dt - datetime.timedelta(days=30)).strftime("%Y%m%d")
    d365 = (today_dt - datetime.timedelta(days=365)).strftime("%Y%m%d")

    _STATE_TEXT = {  # 브리핑 변환용(이모지) — 원문은 영문 enum, 표시만 여기서 매핑
        "STRONGLY_STRENGTHENED": "🟢 크게 강화", "STRENGTHENED": "🟢 강화",
        "MAINTAINED": "🔵 유지", "WEAKENED": "🟡 약화", "BROKEN": "🔴 훼손",
        "UNCONFIRMED": "⚪ 확인 불가",
    }
    _SUMMARY_LEAD = {
        "STRONGLY_STRENGTHENED": "투자 논리가 크게 강화되었습니다",
        "STRENGTHENED": "투자 논리가 강화되었습니다",
        "MAINTAINED": "투자 논리에 특별한 변화가 없습니다",
        "WEAKENED": "투자 논리가 약화되었습니다",
        "BROKEN": "투자 논리가 크게 훼손되었습니다",
        "UNCONFIRMED": "공시 확인이 되지 않아 투자 논리를 판단할 근거가 부족합니다",
    }

    def _thesis_state(score):
        if score >= 5:
            return "STRONGLY_STRENGTHENED"
        if score >= 2:
            return "STRENGTHENED"
        if score >= -1:
            return "MAINTAINED"
        if score >= -4:
            return "WEAKENED"
        return "BROKEN"

    def _thesis_action(state, has_dilution):
        if state == "BROKEN":
            return {"level": "CRITICAL",
                    "items": ["후속 공시 확인", "IR 자료 확인", "경영진 설명 확인", "자금 사용 목적 확인"]}
        if state == "WEAKENED":
            items = ["후속 공시 확인"]
            if has_dilution:
                items.append("자금 사용 목적 확인")
            return {"level": "WARNING", "items": items}
        if state in ("STRENGTHENED", "STRONGLY_STRENGTHENED"):
            return {"level": "WATCH", "items": ["다음 실적 확인", "신규 계약 진행 확인"]}
        return {"level": "INFO", "items": []}

    def _buffett_lens(today_score, rolling_30d, reasons):
        """규칙 기반(LLM 생성 아님). 부정 분기는 신뢰도/자본배분 우선점검, 긍정 분기는 근거(주주환원/
        자본배분 개선)에 따라 세분화. 경제적해자/현금창출력/안전마진 등은 FCF·내재가치 데이터가 없어
        이번 버전에서 규칙화 보류(DESIGN.md 참조) — 근거 없는 문구를 강제로 만들지 않는다."""
        if today_score <= -5 or rolling_30d <= -8:
            return "경영진 신뢰도와 자본배분 정책을 우선 점검하세요."
        if rolling_30d >= 8:
            shareholder_return = any("자사주" in r for r in reasons)
            capital_alloc = any(r in ("부채 감소", "ROE 개선") for r in reasons)
            if shareholder_return and capital_alloc:
                return "주주환원과 자본배분이 함께 개선되고 있습니다 — 경제적 해자가 유지되는지 계속 확인하세요."
            if shareholder_return:
                return "자사주 매입·소각 등 주주환원이 강화되고 있습니다 — 장기 경쟁우위 유지 여부를 지속 확인하세요."
            if capital_alloc:
                return "부채 감소·ROE 개선 등 자본배분이 개선되고 있습니다 — 실적 개선 지속 여부를 확인하세요."
            return "주주환원 정책과 경제적 해자가 유지되는지 확인하세요."
        return None

    _STATE_RANK = {"BROKEN": 0, "WEAKENED": 1, "MAINTAINED": 2, "STRENGTHENED": 3, "STRONGLY_STRENGTHENED": 4}

    def _thesis_change(prev_thesis_entry, new_state):
        """전일 state 대비 변화 감지. UNCONFIRMED 가 얽히면 방향 판단 보류(모르는 걸 개선/악화로 단정 안 함)."""
        prev_state_str = (prev_thesis_entry or {}).get("state")
        if not prev_state_str or prev_state_str == "UNCONFIRMED" or new_state == "UNCONFIRMED":
            return {"prev_state": prev_state_str, "changed": False, "direction": None, "alert": None}
        changed = prev_state_str != new_state
        direction = alert = None
        if changed:
            pr, nr = _STATE_RANK.get(prev_state_str), _STATE_RANK.get(new_state)
            if pr is not None and nr is not None:
                if nr > pr:
                    direction, alert = "IMPROVED", "✅ 투자 Thesis 개선"
                elif nr < pr:
                    direction, alert = "WORSENED", "🚨 투자 Thesis 변경"
        return {"prev_state": prev_state_str, "changed": changed, "direction": direction, "alert": alert}

    def _trend_arrow(score):
        if score >= 2:
            return "↗ 강화"
        if score <= -2:
            return "↘ 약화"
        return "→ 유지"

    def _decay_weight(days_ago):
        """30일=100%/90일=70%/180일=40%/365일=20% — 오래된 이벤트일수록 rolling_365d 기여도 감소."""
        if days_ago is None:
            return 0.0
        if days_ago <= 30:
            return 1.0
        if days_ago <= 90:
            return 0.7
        if days_ago <= 180:
            return 0.4
        if days_ago <= 365:
            return 0.2
        return 0.0

    def _fmt_date(yyyymmdd):
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}" if yyyymmdd else None

    def _thesis_summary(state, reasons, buffett_lens):
        lead = _SUMMARY_LEAD[state]
        if reasons:
            lead += f"({', '.join(reasons[:3])})"
        return f"{lead}. {buffett_lens}" if buffett_lens else f"{lead}."

    for code in dart_codes:
        flags = disclosure_map.get(code)
        if code not in HELD:
            continue
        if flags is None:
            # 공시 조회 자체 실패 -> "유지"로 단정 금지. 별도 상태로 구분.
            thesis_map[code] = {
                "score": {"today": None, "rolling_30d": None, "rolling_365d": None},
                "state": "UNCONFIRMED", "state_label": _STATE_TEXT["UNCONFIRMED"],
                "reasons": ["공시 조회 실패(원문 직접 확인 필요)"], "contributors": [],
                "action": {"level": "WARNING", "items": ["원문 직접 확인"]},
                "buffett_lens": None, "confidence": 0.0, "low_confidence": True,
                "last_changed": None, "last_changed_days_ago": None, "timeline": [],
                "summary": _SUMMARY_LEAD["UNCONFIRMED"] + ".",
                "change": _thesis_change((prev_state.get("thesis") or {}).get(code), "UNCONFIRMED"),
                "trend": {"30d": None, "365d": None}, "investment_case": [],
            }
            continue

        all_events = [it for items in flags.get("dart", {}).values() for it in items] + \
                     [it for items in flags.get("krx", {}).values() for it in items]
        if all_events:
            # dedup 판정은 seen_ids(넉넉한 상한, 365일 조회범위 커버)로 하고, recent(5건)는
            # 사람이 보는 요약 스냅샷일 뿐 dedup 기준으로 쓰지 않는다 — recent 만 기준으로 삼으면
            # 5건 넘게 쌓인 종목에서 오래된 이벤트가 매번 "new" 로 되살아나는 버그가 생김.
            prev_seen_ids = set((prev_disclosures.get(code) or {}).get("seen_ids") or [])
            for it in all_events:
                it["new"] = bool(it.get("rcept_no")) and it.get("rcept_no") not in prev_seen_ids
            sorted_desc = sorted(all_events, key=lambda it: it.get("rcept_no") or "", reverse=True)
            all_ids = sorted({it.get("rcept_no") for it in all_events if it.get("rcept_no")} | prev_seen_ids,
                              reverse=True)[:300]
            new_state_disclosures[code] = {
                "recent": [{"rcept_no": it.get("rcept_no"), "reason": it.get("reason"), "rcept_dt": it.get("rcept_dt")}
                           for it in sorted_desc[:5]],
                "seen_ids": all_ids,
            }

        if knowledge_pipeline is not None:
            # Knowledge(knowledge/company/{code}/) 증분 업데이트 — 실패해도 브리핑 생성은 계속되도록 격리.
            try:
                knowledge_pipeline.run(code, all_events)
            except Exception as e:
                print(f"[knowledge] {code} 갱신 실패(브리핑은 계속 진행): {e}", file=sys.stderr)

        a_events = dart.level_a_events(flags)
        scored = [e for e in a_events if e.get("impact_score") is not None]
        # 이벤트별 경과일수 -> decay weight. rcept_dt 없으면(이론상 없음) weight 0(반영 안 함).
        for e in scored:
            rd = e.get("rcept_dt")
            days_ago = (today_dt - datetime.datetime.strptime(rd, "%Y%m%d")).days if rd else None
            e["_days_ago"] = days_ago
            e["_weighted_impact"] = round(e["impact_score"] * _decay_weight(days_ago), 2)

        today_events = [e for e in scored if e.get("new")]
        d30_events = [e for e in scored if (e.get("_days_ago") or 9999) <= 30]
        d365_events = [e for e in scored if (e.get("_days_ago") or 9999) <= 365]
        today_score = sum(e["impact_score"] for e in today_events)          # 신규 이벤트는 decay 미적용(방금 인지)
        rolling_30d = sum(e["impact_score"] for e in d30_events)            # 30일 이내는 weight=1.0 이라 raw 합과 동일
        rolling_365d = round(sum(e["_weighted_impact"] for e in d365_events), 2)   # decay 적용된 누적

        # Thesis State: today 우선 -> 없으면(0) rolling_30d -> 없으면(0) rolling_365d(decay 반영)
        cascade_score = today_score or rolling_30d or rolling_365d
        cascade_events = today_events if today_score else (d30_events if rolling_30d else d365_events)
        state = _thesis_state(cascade_score)
        reasons = list(dict.fromkeys(e["reason"] for e in cascade_events))[:5]

        use_weighted = cascade_events is d365_events   # 30일 이내는 weight=1.0 이라 raw 와 동일
        contrib_agg = {}
        for e in cascade_events:
            val = e["_weighted_impact"] if use_weighted else e["impact_score"]
            contrib_agg[e["reason"]] = contrib_agg.get(e["reason"], 0) + val
        contributors = [{"reason": r, "impact_score": round(v, 2)}
                        for r, v in sorted(contrib_agg.items(), key=lambda kv: -abs(kv[1]))]

        last_evt_dt = max((e["rcept_dt"] for e in scored if e.get("rcept_dt")), default=None)
        last_changed_days_ago = (today_dt - datetime.datetime.strptime(last_evt_dt, "%Y%m%d")).days \
            if last_evt_dt else None

        seen_pairs = set()
        timeline = []
        for e in sorted(scored, key=lambda e: e.get("rcept_dt") or "", reverse=True):
            key = (e.get("rcept_dt"), e["reason"])
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            timeline.append({"date": _fmt_date(e.get("rcept_dt")), "reason": e["reason"]})
            if len(timeline) >= 10:
                break

        has_krx_a = any(it.get("level") == "A" for items in flags.get("krx", {}).values() for it in items)
        has_dart_a = any(it.get("level") == "A" for items in flags.get("dart", {}).values() for it in items)
        has_fin = code in fundamentals
        if has_krx_a and has_dart_a and has_fin:
            confidence = 0.95
        elif (has_dart_a or has_krx_a) and has_fin:
            confidence = 0.75
        elif has_fin:
            confidence = 0.50
        elif code in news_count_map:
            confidence = 0.40
        else:
            confidence = 0.20

        buffett_lens = _buffett_lens(today_score, rolling_30d, reasons)
        thesis_map[code] = {
            "score": {"today": today_score, "rolling_30d": rolling_30d, "rolling_365d": rolling_365d},
            "state": state, "state_label": _STATE_TEXT[state], "reasons": reasons, "contributors": contributors,
            "action": _thesis_action(state, bool(flags.get("dilution"))),
            "buffett_lens": buffett_lens, "confidence": confidence, "low_confidence": confidence < 0.5,
            "last_changed": _fmt_date(last_evt_dt), "last_changed_days_ago": last_changed_days_ago,
            "timeline": timeline, "summary": _thesis_summary(state, reasons, buffett_lens),
            "change": _thesis_change((prev_state.get("thesis") or {}).get(code), state),
            "trend": {"30d": _trend_arrow(rolling_30d), "365d": _trend_arrow(rolling_365d)},
            "investment_case": [],  # 스키마만 준비(향후 종목별 투자 근거별 강화/유지/약화 평가 추가 예정)
        }
        new_state_thesis[code] = {"today": today_score, "rolling_30d": rolling_30d, "rolling_365d": rolling_365d,
                                   "state": state}

    briefing_state.save({
        **prev_state,
        "disclosures": {**prev_disclosures, **new_state_disclosures},
        "thesis": {**(prev_state.get("thesis") or {}), **new_state_thesis},
    })

    # === Portfolio Health (보유종목 Thesis 분포 + 업종 집중도) ===
    # ponytail: ETF 비중/현금 비중은 portfolio.json 의 평가금액(briefing_data.json 소관) 이 있어야
    # 계산 가능 -> 이 스크립트(kospi200_screen.json) 만으로는 불가, 이번 버전 제외(향후 두 산출물
    # 합산 스크립트 필요). 아래는 Thesis 상태 분포 + 업종 집중도만(이 파일 데이터로 재현 가능한 것만).
    _confirmed = {c: t for c, t in thesis_map.items() if t.get("state") != "UNCONFIRMED"}
    if _confirmed:
        n = len(_confirmed)
        strengthened = sum(1 for t in _confirmed.values()
                            if t["state"] in ("STRENGTHENED", "STRONGLY_STRENGTHENED"))
        weakened = sum(1 for t in _confirmed.values() if t["state"] == "WEAKENED")
        broken = sum(1 for t in _confirmed.values() if t["state"] == "BROKEN")
        health_score = max(0, min(100, 100 - broken * 25 - weakened * 10 + strengthened * 5))
        sector_counts = {}
        for c in _confirmed:
            s = sectors.get(c)
            if s:
                sector_counts[s] = sector_counts.get(s, 0) + 1
        top_sector_pct = (round(max(sector_counts.values()) / sum(sector_counts.values()) * 100, 1)
                           if sector_counts else None)
        portfolio_health = {
            "score": health_score, "holdings_checked": n,
            "strengthened_count": strengthened, "weakened_count": weakened, "broken_count": broken,
            "top_sector_concentration_pct": top_sector_pct,
            "note": "ETF·현금 비중은 이 산출물(kospi200_screen.json)만으로 계산 불가 -> 미포함",
        }
    else:
        portfolio_health = None

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
        if dart is not None and dart.event_types_present(disclosure_map.get(code) or {}) & dart.POSITIVE_BONUS_TYPES:
            return "공시 모멘텀"
        nc = news_count_map.get(code)
        if nc is not None and nc <= NEWS_LOW_THRESHOLD:
            return "원인 불명 변동성"
        return "재료 미확인 상승"

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
    def _disclosure_out(code):
        """disclosure_map[code] -> 출력용 dict. dart/krx 는 반드시 분리 유지, 빈 카테고리는 제거.
        unfaithful_repeat_5y=0은 보존(0도 유의미 - "이번 건 제외 과거 반복 없음"). 내용 없으면 None.
        `_days_ago`/`_weighted_impact` 등 내부 계산용 필드(밑줄 접두)는 공개 출력에서 제외."""
        d = disclosure_map.get(code) or {}
        out = {k: v for k, v in d.items() if k not in ("unfaithful_repeat_5y",) and v}
        for cat in ("dart", "krx"):
            if cat in out:
                out[cat] = {et: [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]
                            for et, items in out[cat].items()}
        if d.get("unfaithful_repeat_5y") is not None:
            out["unfaithful_repeat_5y"] = d["unfaithful_repeat_5y"]
        return out or None

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
            "disclosure": _disclosure_out(code),
            "disclosure_checked": disclosure_map.get(code) is not None,
            "thesis": (thesis_map.get(code) if code in HELD else None),
            "news_count_7d": news_count_map.get(code),
        })

    out = {
        "generated": now.strftime("%Y-%m-%d %H:%M KST"),
        "schema_version": "2.0",          # JSON 구조 버전. 필드 구조 변경 시에만 증가.
        "thesis_engine_version": "3.0",   # Thesis 점수 계산 규칙 버전. 산정 방식 변경 시에만 증가.
        "portfolio_health": portfolio_health,
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
