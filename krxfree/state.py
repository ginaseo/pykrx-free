#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""브리핑 상태 저장 — '어제 대비 무엇이 달라졌는지' 비교용(신규/후속 공시 판정).

현재는 disclosures 섹션만 채운다. thesis/behavior 는 스키마만 마련해 두고
값은 비워 둔다(향후 V2 확장: Thesis 변화·행동 변화 이력도 같은 파일에서 비교).
"""

import os
import json
import datetime

from .paths import RESULTS_DIR

_PATH = os.path.join(RESULTS_DIR, "briefing_state.json")


def load() -> dict:
    try:
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(state: dict):
    """임시 파일에 쓴 뒤 os.replace 로 교체 — 쓰는 도중 프로세스가 죽어도 기존 파일이
    반토막 난 채로 남지 않게(반토막 JSON -> load() 실패 -> seen_ids 초기화되는 사고 방지)."""
    state["generated"] = datetime.datetime.now().isoformat(timespec="seconds")
    state.setdefault("disclosures", {})
    state.setdefault("thesis", {})    # 스키마만 유지(추후 확장)
    state.setdefault("behavior", {})  # 스키마만 유지(추후 확장)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    tmp_path = _PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, _PATH)
