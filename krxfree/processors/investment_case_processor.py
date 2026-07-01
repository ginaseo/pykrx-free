#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""장기 투자 Thesis를 Investment Case 단위로 관리(예: "HBM 성장", "AI Memory").

Case 정의(name/keywords/importance)는 오직 manual.json 에서만 온다 — 자동으로 테마를
지어내지 않는다(추측 금지 원칙). merged.json 의 timeline 에서 keyword 매칭된 이벤트만
근거로 status/trend/reason 을 규칙 기반 계산(LLM 추론 없음).

status: 매칭 이벤트 impact_score 합산 -> Thesis 5단계와 동일한 임계치로 매핑.
trend: 최근 30일 내 매칭 이벤트가 있고 점수가 양/음이면 UP/DOWN, 아니면 FLAT.
case_status(ACTIVE/INACTIVE): 마지막 매칭 이벤트가 365일 이상 지나면 INACTIVE
(삭제 대신 상태 변경 — point 14 원칙).

독립 실행: python -m krxfree.processors.investment_case_processor <종목코드>
"""
import sys
import json
import datetime

from . import knowledge_io
from .registry import register
from .tags import match_tags


def _status_from_score(score):
    if score >= 5:
        return "STRONGLY_STRENGTHENED"
    if score >= 2:
        return "STRENGTHENED"
    if score >= -1:
        return "MAINTAINED"
    if score >= -4:
        return "WEAKENED"
    return "BROKEN"


def _compute_case(cdef, timeline, today):
    name = cdef.get("name")
    keywords = cdef.get("keywords") or []
    importance = cdef.get("importance", 50)
    # 구분자 없이 이어붙이면 두 필드 경계에서 키워드가 우연히 생겨 오탐될 수 있음 -> "\n" 로 분리.
    matched = [e for e in timeline
               if any(kw in ((e.get("reason") or "") + "\n" + (e.get("report_nm") or "")) for kw in keywords)]
    if not matched:
        return {"name": name, "status": "MAINTAINED", "importance": importance, "trend": "FLAT",
                "reason": None, "last_updated": None, "case_status": "ACTIVE",
                "tags": match_tags(name + " " + " ".join(keywords))}

    score = sum(e.get("impact_score") or 0 for e in matched)
    status = _status_from_score(score)
    latest_dt = max((e.get("date") for e in matched if e.get("date")), default=None)
    days_ago = (today - datetime.datetime.strptime(latest_dt, "%Y%m%d")).days if latest_dt else None
    if days_ago is not None and days_ago <= 30 and score > 0:
        trend = "UP"
    elif days_ago is not None and days_ago <= 30 and score < 0:
        trend = "DOWN"
    else:
        trend = "FLAT"
    case_status = "INACTIVE" if (days_ago is not None and days_ago > 365) else "ACTIVE"
    reasons = list(dict.fromkeys(e.get("reason") for e in matched if e.get("reason")))[:3]
    tags = match_tags(name + " " + " ".join(keywords))
    return {
        "name": name, "status": status, "importance": importance, "trend": trend,
        "reason": ", ".join(reasons) if reasons else None,
        "last_updated": f"{latest_dt[:4]}-{latest_dt[4:6]}-{latest_dt[6:]}" if latest_dt else None,
        "case_status": case_status, "tags": tags,
    }


@register("investment_case")
def process(code):
    """manual.json 에 investment_cases(name/keywords/importance) 정의가 없으면 빈 리스트 반환
    (임의로 테마를 만들지 않음). merged.json 의 investment_cases 를 갱신해 저장.
    merged.json 이 있는데 파싱 실패하면 knowledge_io.load 가 예외를 던진다 — 빈 값으로
    덮어써 knowledge_merge_processor 가 채운 timeline/digest 등을 지우지 않기 위함."""
    manual = knowledge_io.load(code, "manual.json")
    merged = knowledge_io.load(code, "merged.json")
    case_defs = manual.get("investment_cases") or []
    timeline = merged.get("timeline", [])
    today = datetime.datetime.now()

    out = [_compute_case(cdef, timeline, today) for cdef in case_defs if cdef.get("name") and cdef.get("keywords")]

    merged["investment_cases"] = out
    # 회사 단위 태그 = 모든 case 태그의 합집합. Context Builder(보류) 의 입력값 준비 단계.
    merged["tags"] = sorted({t for c in out for t in c.get("tags", [])})
    knowledge_io.save(code, "merged.json", merged)
    return out


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    print(json.dumps(process(code), ensure_ascii=False, indent=2))
