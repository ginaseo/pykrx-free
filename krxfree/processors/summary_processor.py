#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SummaryProcessor — 자연어 요약이 아니라 Timeline 을 재현 가능한 "Digest"(기간별 이벤트
목록)로 압축한다. 규칙은 config/digest_rules.json 에서 읽는다(하드코딩 안 함).

Digest 항목: {"period": "YYYY-MM", "events": ["유상증자", ...]}.
기간 안의 event id 집합이 이전 실행과 동일하면 그 기간은 재계산하지 않고 그대로 재사용
(Incremental Update — Timeline 이 안 바뀐 기간까지 매번 다시 만들지 않음).

파이프라인 마지막 단계(timeline -> knowledge_merge -> investment_case -> summary)로 실행 —
manual.json 이 향후 timeline 을 보완하게 되더라도(현재는 안 함) merged.json 의 최종 timeline
을 기준으로 Digest 를 만들도록, generated.json 이 아니라 **merged.json** 의 timeline 을 읽는다.
증분 판단용 상태(`_source_ids`)는 generated.json 에 보관하고, 최종 Digest 는 merged.json 에도
반영한다(investment_case_processor 와 동일하게 마지막 단계가 merged.json 을 갱신).

자연어 문장 생성·LLM 호출 없음. 브리핑 작성 단계에서 이 Digest 를 읽어 LLM 이 설명을 만든다.

독립 실행: python -m krxfree.processors.summary_processor <종목코드>
"""
import sys
import os
import json

from ..paths import ROOT
from . import knowledge_io
from .registry import register

_RULES_PATH = os.path.join(ROOT, "config", "digest_rules.json")
_DEFAULT_RULES = {
    "period_unit": "month",          # month | quarter | year
    "max_events_per_period": 5,
    "include_event_types": None,     # None=전체 허용, 아니면 화이트리스트
    "exclude_event_types": [],
    "sort": "desc",                  # desc=최신순
}


def _load_rules():
    rules = dict(_DEFAULT_RULES)
    try:
        with open(_RULES_PATH, encoding="utf-8") as f:
            rules.update(json.load(f))
    except Exception:
        pass   # 설정 파일 없거나 깨져도 기본값으로 동작(코드 수정 없이 재현 가능해야 함)
    return rules


def _period_key(date_str, unit):
    if not date_str or len(date_str) < 6:
        return None
    y, m = date_str[:4], date_str[4:6]
    if unit == "year":
        return y
    if unit == "quarter":
        q = (int(m) - 1) // 3 + 1
        return f"{y}-Q{q}"
    return f"{y}-{m}"


def _event_id(e):
    return e.get("rcept_no") or f"{e.get('event_type')}|{e.get('date')}|{e.get('reason')}"


@register("summary")
def process(code):
    """merged.json 의 timeline -> digest 재계산(변경 없는 기간은 재사용).
    _source_ids 상태는 generated.json 에, 최종 결과는 merged.json 에도 반영. 반환: digest 리스트.
    generated.json 이 있는데 파싱 실패하면 knowledge_io.load 가 예외를 던진다 — 빈 값으로
    덮어써 timeline 등 다른 필드를 지우지 않기 위함(merged.json 은 원래 없을 수도 있어 default={})."""
    generated = knowledge_io.load(code, "generated.json", {"timeline": [], "digest": []})
    merged = knowledge_io.load(code, "merged.json")
    timeline = merged.get("timeline") or generated.get("timeline", [])
    rules = _load_rules()
    unit = rules.get("period_unit", "month")
    include = rules.get("include_event_types")
    exclude = set(rules.get("exclude_event_types") or [])
    max_n = rules.get("max_events_per_period", 5)
    # 규칙 자체가 바뀌면(기간단위/필터/최대개수 등) 기존 기간도 재계산해야 함 -> ids 와 별개로
    # rules 스냅샷도 비교 대상에 포함(참조 재현 가능해야 한다는 원칙).
    rules_key = json.dumps(rules, sort_keys=True, ensure_ascii=False)

    filtered = [e for e in timeline
                if (include is None or e.get("event_type") in include) and e.get("event_type") not in exclude]

    groups = {}
    for e in filtered:
        pk = _period_key(e.get("date"), unit)
        if pk:
            groups.setdefault(pk, []).append(e)

    prev_digest = {d["period"]: d for d in generated.get("digest", [])}
    new_digest = []
    for period, events in groups.items():
        ids = sorted({_event_id(e) for e in events})
        prev = prev_digest.get(period)
        if prev and prev.get("_source_ids") == ids and prev.get("_rules_key") == rules_key:
            new_digest.append(prev)   # 이 기간·규칙 둘 다 안 바뀜 -> 그대로 재사용(재계산 안 함)
            continue
        reasons = list(dict.fromkeys(e.get("reason") for e in events if e.get("reason")))[:max_n]
        new_digest.append({"period": period, "events": reasons, "_source_ids": ids, "_rules_key": rules_key})

    reverse = rules.get("sort", "desc") == "desc"
    new_digest.sort(key=lambda d: d["period"], reverse=reverse)

    generated["digest"] = new_digest
    generated["digest_rules_applied"] = rules
    knowledge_io.save(code, "generated.json", generated)

    if merged:   # knowledge_merge 가 아직 안 돌았으면(독립 실행 등) merged.json 없을 수 있음
        merged["digest"] = [{k: v for k, v in d.items() if not k.startswith("_")} for d in new_digest]
        merged["digest_rules_applied"] = rules
        knowledge_io.save(code, "merged.json", merged)
    return new_digest


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    print(json.dumps(process(code), ensure_ascii=False, indent=2))
