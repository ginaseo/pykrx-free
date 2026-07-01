#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4계층 병합: manual.json(사용자 입력, 최우선) > dart.json(공식 데이터) > generated.json(계산 결과)
-> merged.json(브리핑에서 참조하는 최종 산출물).

dart.json 은 아직 만드는 Processor 가 없어(CompanyProfileProcessor, Phase2-3 예정) 대개 비어
있음 — 있으면 반영, 없으면 그냥 스킵(추측으로 채우지 않음).

timeline 은 (event_type, date, rcept_no|reason) 기준 dedup 후 최신순 정렬.

독립 실행: python -m krxfree.processors.knowledge_merge_processor <종목코드>
"""
import sys
import json
import datetime

from . import knowledge_io
from .registry import register


def _dedup_timeline(timeline):
    seen = set()
    out = []
    for e in timeline:
        rn = e.get("rcept_no")
        k = ("id", rn) if rn else ("synthetic", e.get("event_type"), e.get("date"), e.get("reason"))
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return sorted(out, key=lambda e: e.get("date") or "", reverse=True)


@register("knowledge_merge")
def process(code):
    """manual.json/dart.json 이 있는데 파싱 실패하면 knowledge_io.load 가 예외를 던진다(빈 값
    취급 금지 — 사용자가 채운 값이나 공식 데이터를 조용히 없는 것처럼 취급하면 안 됨). 셋 다
    없는 건 정상(아직 미작성)."""
    manual = knowledge_io.load(code, "manual.json")
    dart_layer = knowledge_io.load(code, "dart.json")
    generated = knowledge_io.load(code, "generated.json", {"timeline": [], "digest": [], "investment_cases": []})

    merged = {}
    merged.update(generated)   # 1) 계산 결과
    merged.update(dart_layer)  # 2) 공식 데이터 — generated 보다 우선(문서/README 명시 순서)
    # 3) 사용자 입력은 값이 채워진 필드만 최우선 반영(빈 값으로 덮어써 기존 정보 지우지 않음)
    EMPTY = (None, [], {}, "")
    merged.update({k: v for k, v in manual.items() if v not in EMPTY and k != "investment_cases"})

    merged["timeline"] = _dedup_timeline(generated.get("timeline", []))
    # digest 는 파이프라인상 summary_processor 가 이 다음 단계에서 채운다(merged.json 기준으로
    # 재계산). 아직 안 돌았을 독립 실행 대비 폴백만 유지(내부 변경감지용 _source_ids 는 제외).
    merged.setdefault("digest", [{k: v for k, v in d.items() if not k.startswith("_")}
                                  for d in generated.get("digest", [])])
    merged.setdefault("investment_cases", generated.get("investment_cases", []))
    merged.setdefault("version", "1.0")

    knowledge_io.save(code, "merged.json", merged)
    return merged


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    print(json.dumps(process(code), ensure_ascii=False, indent=2))
