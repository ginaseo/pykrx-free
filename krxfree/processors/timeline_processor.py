#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""기업 이벤트를 시간순으로 누적(증분 업데이트, append-only).

기존 generated.json 을 먼저 로드하고, 신규 이벤트만 추가한다. 삭제 없음(point 14 원칙).
동일 이벤트 dedup: rcept_no 있으면 그 값, 없으면(재무 이벤트 등 합성 이벤트)
(event_type, date, reason) 조합으로 판정.

독립 실행: python -m krxfree.processors.timeline_processor <종목코드>
"""
import sys
import json

from . import knowledge_io
from .registry import register

_DEFAULT = {"timeline": [], "investment_cases": [], "version": "1.0"}


def _event_key(ev):
    rn = ev.get("rcept_no")
    return ("id", rn) if rn else ("synthetic", ev.get("event_type"), ev.get("rcept_dt") or ev.get("date"),
                                   ev.get("reason"))


@register("timeline")
def process(code, events):
    """events: dart.classify_event() 계열 dict 리스트(report_nm/rcept_dt/rcept_no/event_type/
    reason/impact_score 등). 기존 timeline 에 신규만 추가 -> 최신순 정렬 -> 저장.
    반환: 갱신된(또는 기존) generated.json 내용. generated.json 이 있는데 파싱 실패하면
    knowledge_io.load 가 예외를 던진다 — 빈 값으로 덮어써 기존 이력을 지우지 않기 위함."""
    data = knowledge_io.load(code, "generated.json", _DEFAULT)
    existing_keys = {_event_key(e) for e in data.get("timeline", [])}
    added = 0
    for ev in events or []:
        k = _event_key(ev)
        if k in existing_keys:
            continue
        data.setdefault("timeline", []).append({
            "date": ev.get("rcept_dt"), "reason": ev.get("reason"), "event_type": ev.get("event_type"),
            "rcept_no": ev.get("rcept_no"), "impact_score": ev.get("impact_score"),
            "report_nm": ev.get("report_nm"),
        })
        existing_keys.add(k)
        added += 1
    data["timeline"] = sorted(data.get("timeline", []), key=lambda e: e.get("date") or "", reverse=True)
    if added:
        knowledge_io.save(code, "generated.json", data)
    return data


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    print(json.dumps(process(code, []), ensure_ascii=False, indent=2))
