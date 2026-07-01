# Hermes Integration Contract — 설계만, 구현 없음

Hermes 는 Engine 이 아니라 **Integration Layer**다. Portfolio Intelligence Engine 과
Briefing Generator(둘 다 구현 완료 — `krxfree.portfolio_engine`/`krxfree.briefing_generator`)
를 연결하는 가장 마지막 단계에서 만든다.

이 문서는 그때 구현할 API 의 **입출력 계약만** 지금 고정해 둔다 — Hermes 자체 코드는 아직
없다(이 계약이 기준으로 삼는 `build_schema()`/`build_snapshot()` 등은 이미 구현·검증됨).
나중에 내부 구현(Search backend, Portfolio 계산식, Briefing Generator)이 바뀌어도 이 계약은
바뀌지 않는 것이 목표다.

---

## API 목록

| 함수 | 반환 | 지금 있는 소스 |
|---|---|---|
| `get_portfolio_health()` | `{score, holdings_checked, strengthened_count, weakened_count, broken_count, top_sector_concentration_pct}` | `results/kospi200_screen.json.portfolio_health` (향후: 최신 `portfolio_snapshot` 기준으로 교체) |
| `get_daily_briefing()` | `results/briefing_schema.json` 그대로(LLM 이 이걸 읽어 최종 문장 생성) | `krxfree.briefing_generator.build_schema()` |
| `search_knowledge(query, filters=None, top_k=10)` | `[chunk, ...]` | `krxfree.search.engine.SearchEngine.search()` 그대로 |
| `get_company_thesis(company_code)` | thesis dict | `results/kospi200_screen.json.recommendations[].thesis` |
| `get_investment_cases(company_code)` | `[investment_case, ...]` | Search Layer 경유(`company_code` + `chunk_type=investment_case` 필터) |
| `get_portfolio_risk()` | risk dict | `krxfree.portfolio_engine.build_snapshot()["risk"]` |
| `get_portfolio_actions()` | `[action, ...]` | `build_snapshot()["action_items"]` |
| `get_portfolio_snapshot(date)` | snapshot dict \| None | `results/portfolio_snapshot/{date}.json` |
| `compare_portfolio_snapshot(date1, date2)` | diff dict | 두 스냅샷의 숫자 필드 delta(`portfolio_engine._delta` 와 동일 로직) |

## 원칙

- 전부 **읽기 전용** — Hermes 는 Knowledge/Thesis/Portfolio 어느 것도 쓰지 않는다.
- 내부 구현(Search backend 교체, Portfolio 계산식 변경)이 바뀌어도 이 계약은 그대로 유지.
- **지금은 구현하지 않는다** — Portfolio Intelligence Engine + Briefing Generator 완성 이후 착수.
