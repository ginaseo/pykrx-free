#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Portfolio Intelligence Engine — 종목 개별이 아니라 포트폴리오 전체 관점의 진단.

새 데이터를 수집하지 않는다. 이미 만든 산출물만 조합한다:
- results/kospi200_screen.json (Thesis Engine — 보유종목 thesis/sector/PER/PBR/DIV 등)
- results/briefing_data.json  (Collection Layer — 포지션 시세·평가금액)
- Search Layer(krxfree.search) — Knowledge(태그) 조회. **Knowledge 파일을 직접 읽지 않고
  반드시 Search Layer 를 거친다**(Portfolio 와 Knowledge 를 직접 결합하지 않는다는 원칙).

[실행] python -m krxfree.portfolio_engine
[결과] results/portfolio_snapshot/YYYY-MM-DD.json — 하루 1회, 기존 스냅샷은 삭제하지 않고 누적.

[의도적으로 계산하지 않는 것 — 데이터 없이 추측 금지]
- 현금 비중: portfolio.json 에 현금 잔고 필드 자체가 없음.
- 보유종목 간 Correlation: 가격 시계열을 전 종목 다시 받아야 하는 별도 계산이라 범위 밖
  (필요성이 확인되면 추가 — 지금은 HHI 기반 집중도로 분산도만 근사).
"""
import os
import json
import datetime

from .paths import RESULTS_DIR
from .search.engine import default_engine

SNAPSHOT_DIR = os.path.join(RESULTS_DIR, "portfolio_snapshot")
ETF_CODES = {"069500"}   # KODEX200 등 — screener.py 가 다루는 ETF 범위와 동일


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _company_tags(engine, code):
    """Knowledge 태그 조회 — Search Layer 경유(merged.json 직접 읽지 않음)."""
    hits = engine.search("", filters={"company_code": code}, top_k=1)
    return hits[0].get("tags", []) if hits else []


def _position_value(h):
    """포지션 평가금액. current*shares 우선, 시세 없으면 avg*shares(원가) 로 근사."""
    shares = h.get("shares")
    if shares is None:
        return None
    if h.get("current") is not None:
        return h["current"] * shares
    if h.get("avg") is not None:
        return h["avg"] * shares
    return None


def _sector_allocation(screen, briefing):
    """업종/국가/ETF 비중 — 포지션 평가금액 가중. 평가금액 자체가 없으면 None(추측 금지)."""
    rec_by_code = {r["code"]: r for r in screen.get("recommendations", []) if r.get("held")}
    weights, market_of = {}, {}
    total = 0.0
    for h in briefing.get("holdings", []):
        code = h.get("code") or h.get("ticker")
        v = _position_value(h)
        if not code or v is None:
            continue
        weights[code] = v
        market_of[code] = h.get("market") or "KR"
        total += v
    if total <= 0:
        return None

    sector_value, market_value = {}, {}
    for code, v in weights.items():
        sec = (rec_by_code.get(code) or {}).get("sector") or "기타"
        sector_value[sec] = sector_value.get(sec, 0) + v
        market_value[market_of[code]] = market_value.get(market_of[code], 0) + v
    etf_value = sum(v for c, v in weights.items() if c in ETF_CODES)

    return {
        "by_sector_pct": {k: round(v / total * 100, 1) for k, v in sector_value.items()},
        "by_market_pct": {k: round(v / total * 100, 1) for k, v in market_value.items()},
        "etf_pct": round(etf_value / total * 100, 1),
        "cash_pct": None,   # 데이터 없음(portfolio.json 에 현금 필드 없음)
        "total_value": round(total, 0),
    }


def _theme_exposure(screen, engine):
    """산업 테마(Knowledge 태그, Search Layer 경유) + 스타일 태그(PER/PBR/DIV/성장률 — 실측 필드)."""
    theme_codes = {}
    for r in screen.get("recommendations", []):
        if not r.get("held"):
            continue
        code = r["code"]
        tags = set(_company_tags(engine, code))
        div, per, pbr = r.get("DIV"), r.get("PER"), r.get("PBR")
        fin = r.get("fundamentals_dart") or {}
        if div is not None and div >= 2:
            tags.add("배당")
        if (per is not None and per < 10) or (pbr is not None and pbr < 1):
            tags.add("Value")
        if (fin.get("op_growth_pct") or 0) >= 15 or (fin.get("rev_growth_pct") or 0) >= 15:
            tags.add("성장")
        for t in tags:
            theme_codes.setdefault(t, []).append(code)
    return {theme: sorted(codes) for theme, codes in theme_codes.items()}


def _thesis_distribution(screen):
    held = [r for r in screen.get("recommendations", []) if r.get("held")]
    n = len(held)
    counts = {}
    for r in held:
        st = (r.get("thesis") or {}).get("state") or "UNCONFIRMED"
        counts[st] = counts.get(st, 0) + 1
    return {"holdings_checked": n, "counts": counts,
            "pct": ({k: round(v / n * 100, 1) for k, v in counts.items()} if n else {})}


def _portfolio_risk(screen):
    """훼손·약화 종목 비중 기반 내부 참고 지표(매도 신호 아님)."""
    held = [r for r in screen.get("recommendations", []) if r.get("held")]
    flags = []
    for r in held:
        t = r.get("thesis") or {}
        if t.get("state") in ("BROKEN", "WEAKENED"):
            flags.append({"code": r["code"], "name": r.get("name"), "state": t.get("state"),
                          "reasons": t.get("reasons")})
        if (r.get("disclosure") or {}).get("dilution"):
            flags.append({"code": r["code"], "name": r.get("name"), "state": "DILUTION",
                          "reasons": ["희석 진행 중"]})
    n = len(held)
    broken = sum(1 for r in held if (r.get("thesis") or {}).get("state") == "BROKEN")
    weakened = sum(1 for r in held if (r.get("thesis") or {}).get("state") == "WEAKENED")
    risk_score = round((broken * 2 + weakened) / n * 100, 1) if n else None
    return {"risk_score": risk_score, "flags": flags,
            "note": "risk_score 는 훼손·약화 종목 비중 기반 내부 참고 지표(매수·매도 신호 아님)"}


def _diversification(sector_alloc):
    """HHI(허핀달-허쉬만지수) 기반 업종 집중도. 종목간 Correlation 은 범위 밖(모듈 docstring 참조)."""
    if not sector_alloc:
        return None
    pct = sector_alloc["by_sector_pct"]
    hhi = sum((p / 100) ** 2 for p in pct.values())
    return {"sector_hhi": round(hhi, 3), "diversification_score": round((1 - hhi) * 100, 1),
            "note": "업종 HHI 기반 근사치. 종목간 수익률 Correlation 은 이번 버전 미포함"}


def _portfolio_actions(screen):
    out = []
    for r in screen.get("recommendations", []):
        if not r.get("held"):
            continue
        action = (r.get("thesis") or {}).get("action") or {}
        if action.get("level") in ("WARNING", "CRITICAL") and action.get("items"):
            out.append({"code": r["code"], "name": r.get("name"), "level": action["level"],
                        "items": action["items"]})
    return out


def _load_prev_snapshot(today_str):
    if not os.path.isdir(SNAPSHOT_DIR):
        return None
    files = sorted(f for f in os.listdir(SNAPSHOT_DIR)
                   if f.endswith(".json") and f[:-5] < today_str)
    if not files:
        return None
    return _load_json(os.path.join(SNAPSHOT_DIR, files[-1]))


def _get_path(d, path):
    for k in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _delta(prev, cur, path):
    a, b = _get_path(prev, path), _get_path(cur, path)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(b - a, 2)
    return None


def build_snapshot():
    screen = _load_json(os.path.join(RESULTS_DIR, "kospi200_screen.json"))
    if screen is None:
        raise RuntimeError("results/kospi200_screen.json 없음 — 먼저 `python -m krxfree.screener` 실행 필요.")
    briefing = _load_json(os.path.join(RESULTS_DIR, "briefing_data.json")) or {"holdings": []}
    engine = default_engine()

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    sector_alloc = _sector_allocation(screen, briefing)
    snapshot = {
        "snapshot_date": today_str,
        "schema_version": "1.0",
        "portfolio_health": screen.get("portfolio_health"),
        "sector_allocation": sector_alloc,
        "theme_exposure": _theme_exposure(screen, engine),
        "thesis_distribution": _thesis_distribution(screen),
        "risk": _portfolio_risk(screen),
        "diversification": _diversification(sector_alloc),
        "actions": _portfolio_actions(screen),
    }

    prev = _load_prev_snapshot(today_str)
    snapshot["change_vs_prev"] = None if not prev else {
        "prev_date": prev.get("snapshot_date"),
        "portfolio_health_delta": _delta(prev, snapshot, "portfolio_health.score"),
        "risk_score_delta": _delta(prev, snapshot, "risk.risk_score"),
        "diversification_score_delta": _delta(prev, snapshot, "diversification.diversification_score"),
    }

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    path = os.path.join(SNAPSHOT_DIR, f"{today_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return snapshot


if __name__ == "__main__":
    s = build_snapshot()
    print("저장 완료 ->", os.path.join(SNAPSHOT_DIR, f"{s['snapshot_date']}.json"))
    print(json.dumps(s, ensure_ascii=False, indent=2))
