#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Briefing Generator — Rule Engine 이 규칙 기반 Briefing Schema(JSON)를 만들고,
LLM 은 이 JSON 만 읽어 문장을 쓴다. **LLM 은 여기서 아무것도 계산하지 않는다.**

[실행] python -m krxfree.briefing_generator
[결과] results/briefing_schema.json

Rule Engine 우선순위(고정 — LLM 판단에 맡기지 않음):
1. Thesis BROKEN 종목은 반드시 top_changes 상위 3개 안에 포함.
2. Portfolio Health 는 schema 의 portfolio 섹션 맨 앞(첫 필드)에 위치.
3. 전일 대비 Risk Score(100=안전)가 유의미하게 나빠지면(5점 이상 하락) headline 으로 승격.
4. 오늘 신규 이벤트(thesis.score.today != 0)가 있는 종목은 top_changes 후보.
5. WARNING/CRITICAL action 이 있는 종목은 필터링 없이 반드시 actions 에 포함.

새 계산은 하지 않는다 — results/kospi200_screen.json(Thesis Engine)과
results/briefing_data.json(Collection Layer), results/portfolio_snapshot/(Portfolio
Intelligence Engine)의 최신 스냅샷만 조합한다.
"""
import os
import json
import datetime

from .paths import RESULTS_DIR

SNAPSHOT_DIR = os.path.join(RESULTS_DIR, "portfolio_snapshot")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _latest_snapshot():
    if not os.path.isdir(SNAPSHOT_DIR):
        return None
    files = sorted(f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json"))
    if not files:
        return None
    return _load_json(os.path.join(SNAPSHOT_DIR, files[-1]))


def _snapshot_meta(snapshot):
    """스냅샷 신선도. portfolio/risk 섹션이 오늘 데이터가 아닐 수 있음을 명시(추측 방지)."""
    if not snapshot:
        return {"date": None, "age_days": None, "stale": True, "note": "포트폴리오 스냅샷 없음"}
    snap_date = snapshot.get("snapshot_date")
    try:
        age = (datetime.datetime.now() - datetime.datetime.strptime(snap_date, "%Y-%m-%d")).days
    except Exception:
        age = None
    return {"date": snap_date, "age_days": age, "stale": bool(age and age >= 1),
            "note": None if not age else f"{age}일 지난 스냅샷 — portfolio/risk 섹션이 오늘 기준이 아닐 수 있음"}


def _headline(snapshot):
    """규칙 3: Risk Score 유의미한 악화(5점↑ 하락) 최우선. 그 다음 Portfolio Health 변화."""
    if not snapshot:
        return None
    chg = snapshot.get("change_vs_prev") or {}
    risk_delta = chg.get("risk_score_delta")
    if risk_delta is not None and risk_delta <= -5:
        return {"type": "risk_worsened",
                "text": f"포트폴리오 리스크 점수 {abs(risk_delta)}점 하락(전일 대비, 100=안전)"}
    health_delta = chg.get("portfolio_health_delta")
    if health_delta:
        direction = "개선" if health_delta > 0 else "악화"
        return {"type": "portfolio_health_change",
                "text": f"Portfolio Health {direction} {abs(health_delta)}점(전일 대비)"}
    return None


def _entry(r):
    t = r.get("thesis") or {}
    return {"code": r["code"], "name": r.get("name"), "state": t.get("state"),
            "today_score": (t.get("score") or {}).get("today"), "reasons": t.get("reasons")}


def _top_changes(screen, max_n=5):
    """규칙 1+4: BROKEN 종목 최우선(최대 3개 보장) -> 오늘 신규 이벤트 있는 종목 순."""
    held = [r for r in screen.get("recommendations", []) if r.get("held")]
    broken = [r for r in held if (r.get("thesis") or {}).get("state") == "BROKEN"]
    broken_codes = {r["code"] for r in broken}
    others_new = [r for r in held
                  if r["code"] not in broken_codes and ((r.get("thesis") or {}).get("score") or {}).get("today")]

    out, seen = [], set()
    for r in broken[:3] + others_new:
        if r["code"] in seen:
            continue
        seen.add(r["code"])
        out.append(_entry(r))
        if len(out) >= max_n:
            break
    return out


def _actions(screen):
    """규칙 5: WARNING/CRITICAL action 은 필터링 없이 전부 포함."""
    out = []
    for r in screen.get("recommendations", []):
        if not r.get("held"):
            continue
        action = (r.get("thesis") or {}).get("action") or {}
        if action.get("level") in ("WARNING", "CRITICAL") and action.get("items"):
            out.append({"code": r["code"], "name": r.get("name"), "level": action["level"],
                        "items": action["items"]})
    return out


def _companies(screen):
    out = []
    for r in screen.get("recommendations", []):
        if not r.get("held"):
            continue
        t = r.get("thesis") or {}
        out.append({
            "code": r["code"], "name": r.get("name"), "sector": r.get("sector"),
            "close": r.get("close"), "momentum_pct": r.get("momentum_pct"),
            "thesis_state": t.get("state"), "thesis_summary": t.get("summary"),
            "buffett_lens": t.get("buffett_lens"),
        })
    return out


def _watchlist(screen, max_n=5):
    return [{"code": r["code"], "name": r.get("name"), "score": r.get("score"), "sector": r.get("sector")}
            for r in screen.get("recommendations", []) if not r.get("held")][:max_n]


def build_schema():
    screen = _load_json(os.path.join(RESULTS_DIR, "kospi200_screen.json"))
    if screen is None:
        raise RuntimeError("results/kospi200_screen.json 없음 — 먼저 `python -m krxfree.screener` 실행 필요.")
    briefing = _load_json(os.path.join(RESULTS_DIR, "briefing_data.json")) or {}
    snapshot = _latest_snapshot()

    schema = {
        "schema_version": "1.0",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "headline": _headline(snapshot),   # 규칙 2: portfolio 섹션보다 먼저 노출되는 최우선 한 줄
        "snapshot_meta": _snapshot_meta(snapshot),   # portfolio/risk 섹션 신선도(며칠 지난 데이터인지)
        "market": {"indices": briefing.get("indices"), "macro": screen.get("macro")},
        "portfolio": {   # 규칙 2: health 를 이 섹션의 첫 필드로
            "health": (snapshot or {}).get("portfolio_health") or screen.get("portfolio_health"),
            "sector_allocation": (snapshot or {}).get("sector_allocation"),
            "theme_exposure": (snapshot or {}).get("theme_exposure"),
            "thesis_distribution": (snapshot or {}).get("thesis_distribution"),
        },
        "risk": {
            "score": (snapshot or {}).get("risk_score"),
            "contributors": ((snapshot or {}).get("risk") or {}).get("contributors"),
            "top_risks": (snapshot or {}).get("top_risks"),
        },
        "top_changes": _top_changes(screen),
        "actions": _actions(screen),
        "companies": _companies(screen),
        "watchlist": _watchlist(screen),
    }

    path = os.path.join(RESULTS_DIR, "briefing_schema.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
    return schema


if __name__ == "__main__":
    s = build_schema()
    print("저장 완료 ->", os.path.join(RESULTS_DIR, "briefing_schema.json"))
    dump = json.dumps(s, ensure_ascii=False, indent=2)
    try:
        print(dump)
    except UnicodeEncodeError:
        print(dump.encode("ascii", errors="backslashreplace").decode("ascii"))
