# -*- coding: utf-8 -*-
"""Knowledge Growth Engine — 기업별 장기 누적 데이터(knowledge/company/{code}/) 생성 파이프라인.

각 Processor 는 독립 실행 가능(`python -m krxfree.processors.<name> <종목코드>`)하며,
registry.py 에 등록돼 pipeline.py 가 고정 순서로 묶어 실행한다.
브리핑(results/)과 Knowledge(knowledge/)는 분리 — Knowledge 는 매일 덮어쓰지 않고 증분 누적한다.
"""
