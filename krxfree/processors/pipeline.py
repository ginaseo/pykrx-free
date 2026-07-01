#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Knowledge 생성 파이프라인 — 순서 고정: Timeline -> KnowledgeMerge -> InvestmentCase -> Summary(Digest).

Summary 를 마지막에 두는 이유: Digest 는 "최종 Knowledge 상태"(manual.json 반영분 +
investment_case 계산까지 끝난 merged.json)를 기준으로 만드는 게 장기적으로 일관성이 높음
(현재는 manual.json 이 timeline 에 기여하지 않아 순서를 바꿔도 값 자체는 동일하지만, 향후
manual.json 이 timeline 을 보완하게 되면 순서가 실제로 결과에 영향을 준다 — 지금 순서를
그 방향으로 맞춰 둠).

새 Processor 추가 시 이 PIPELINE 리스트에 이름만 추가하면 된다(registry 에 @register 만
해두면 개별 배선 코드 수정 불필요). Phase2-3(CompanyProfile/Wiki/Alias/RelatedCompany),
Phase2-4(Event Importance), Phase2-5(Portfolio Intelligence) 도 같은 방식으로 확장 예정.
ContextProcessor 는 이번 단계에서 보류(Dynamic Context 는 Knowledge 가 아니라 향후
"Context Builder"에서 뉴스·매크로와 함께 브리핑 생성 시점에 만들 예정 — DESIGN.md 참조).
"""
# 아래 import 는 registry 등록(@register) 부작용을 위한 것 — 직접 호출은 registry.get() 으로.
from . import timeline_processor, summary_processor, knowledge_merge_processor, investment_case_processor  # noqa: F401
from . import registry

PIPELINE = ["knowledge_merge", "investment_case", "summary"]   # "timeline" 은 events 인자가 달라 별도 호출


def run(code, events):
    """code 종목의 Knowledge 를 이번 실행에서 확인된 events 로 증분 업데이트.
    실패해도 예외를 그대로 던진다 — 호출부(screener.py)가 try/except 로 감싸
    Knowledge 문제가 브리핑 생성 자체를 막지 않도록 한다."""
    registry.get("timeline")(code, events)
    result = None
    for name in PIPELINE:
        result = registry.get(name)(code)
    return result
