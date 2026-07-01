# ARCHITECTURE — 시스템 전체 구조

이 문서는 "지금 뭐가 어디 있고 왜 그렇게 나뉘어 있는지"를 몇 분 안에 파악하기 위한 기준 문서다.
설치·사용법은 [README.md](README.md), 개별 의사결정 근거·트레이드오프는 [docs/DESIGN.md](docs/DESIGN.md) 참조.

---

## 전체 데이터 흐름

```
Market Data (KRX·Naver·DART·Google뉴스RSS·FRED)
        ↓
Collection Layer      (krxfree/clients/*)
        ↓
Thesis Engine         (krxfree/screener.py — 보유종목 today/rolling_30d/rolling_365d 점수·state)
        ↓
Knowledge Engine       (krxfree/processors/* → knowledge/company/{code}/*.json)
        ↓
Portfolio Intelligence Engine   ← 예정(Phase2.5, 미구현)
        ↓
Briefing Generator             ← 예정(Phase3, 미구현 — 지금은 AI가 JSON을 직접 읽어 브리핑 작성)
        ↓
Slack / Web / Mobile           ← 예정(미구현)
```

**지금 실제로 도는 것은 위쪽 3단(Collection → Thesis → Knowledge)까지다.** Portfolio Intelligence
이후는 로드맵이고 아직 코드가 없다 — 이 문서에서 "예정"이라고 명시한 부분은 존재하지 않는 것으로
간주할 것.

---

## Layer 별 역할

### 1. Collection Layer (`krxfree/clients/`)
KRX·DART·Naver·뉴스·매크로에서 실측 데이터만 가져온다. 계산·해석은 하지 않음(원칙:
[DESIGN.md 데이터 원칙](docs/DESIGN.md#데이터-원칙-사실-기반)).

| 파일 | 역할 |
|---|---|
| `openapi.py` | KRX 공식 OpenAPI(시세·지수, 무로그인) |
| `login.py` | KRX 로그인 세션(PER/PBR·구성종목, 일 1회) |
| `naver.py` | 국내 종목 OHLCV |
| `dart.py` | OpenDART 공시·재무제표. 공시 이벤트 taxonomy(`classify_event`, Level A/B/C)도 여기 있음 |
| `news.py` | Google News RSS 기사 건수 |
| `macro.py` | 미국10년물·환율·코스피추세·외국인수급(ETF 판단용) |

### 2. Thesis Engine (`krxfree/screener.py`)
보유종목의 "투자 논리가 오늘/30일/1년간 얼마나 강화·약화됐는가"를 계산해
`results/kospi200_screen.json` 의 `recommendations[].thesis` 에 담는다.

- **Score**: Level A 공시 이벤트(`dart.classify_event` 가 매긴 `impact_score`)만 합산.
  `today`(신규 이벤트만) → `rolling_30d` → `rolling_365d`(경과일 decay: 30일100%/90일70%/
  180일40%/365일20%) 순으로 대표 점수를 골라 `state` 산정(cascade).
- **State**: `STRONGLY_STRENGTHENED / STRENGTHENED / MAINTAINED / WEAKENED / BROKEN` (+ 조회
  실패 전용 `UNCONFIRMED`).
- **Contributors / Reasons / Action / Buffett Lens / Confidence / Change / Trend**: 전부
  규칙 기반(LLM 개입 없음), `docs/DESIGN.md` Phase5~7 참조.
- **Portfolio Health**: 보유종목 Thesis 분포 + 업종 집중도(이 스크립트 데이터만으로 계산 가능한
  범위 — ETF·현금 비중은 `briefing_data.json` 쪽 데이터가 필요해 미포함).
- **이력/dedup**: `results/briefing_state.json` 에 종목별 `disclosures`(최근 5건 + dedup 용
  `seen_ids`)와 `thesis`(전일 state, 변화 감지용) 저장.

이 레이어의 산출물(`results/*.json`)은 **매 실행마다 덮어쓴다** — 일회성 브리핑 데이터.

### 3. Knowledge Engine (`krxfree/processors/`)
Thesis Engine 이 계산한 이벤트를 종목별로 **장기 누적**한다. `results/` 와 달리 절대
덮어쓰지 않고 증분만 한다.

```
knowledge/company/{종목코드}/
    manual.json      사용자가 직접 작성(최우선). investment_cases 정의, founder/ceo 등.
    dart.json        (아직 채우는 Processor 없음 — Phase2-3 CompanyProfileProcessor 예정)
    generated.json   Processor 가 계산한 결과(timeline, digest, investment_cases 중간상태)
    merged.json      manual > dart > generated 병합한 최종 산출물(브리핑이 참조하는 파일)
```

**Registry + Pipeline 패턴** (`processors/registry.py`, `processors/pipeline.py`):
```python
@register("이름")
def process(code): ...
```
로 등록만 하면 `pipeline.PIPELINE` 리스트에 이름을 추가하는 것만으로 실행 순서에 끼워 넣을 수
있다. 개별 Processor 파일을 서로 참조하도록 배선할 필요가 없다.

**현재 파이프라인 순서**: `timeline → knowledge_merge → investment_case → summary`

| Processor | 하는 일 |
|---|---|
| `timeline_processor` | 공시 이벤트를 `generated.json.timeline` 에 증분 추가(삭제 없음, dedup) |
| `knowledge_merge_processor` | manual/dart/generated 4계층 병합 → `merged.json` |
| `investment_case_processor` | `manual.json` 에 정의한 case(name/keywords/importance)만 존재 — timeline 에서 keyword 매칭된 이벤트로 status/trend/reason/tags 규칙 계산 |
| `summary_processor` | `merged.json.timeline` 을 월/분기/연 단위로 압축한 **Digest**(자연어 아님) 생성. 규칙은 `config/digest_rules.json` |

`summary` 가 파이프라인 맨 뒤인 이유: Digest 는 manual.json 반영분·investment_case 계산까지 끝난
**최종** timeline 을 기준으로 만드는 게 맞아서(`docs/DESIGN.md` Phase2-2 참조).

**Knowledge 관리 원칙**:
1. 기존 것 먼저 로드, 새 이벤트만 추가(전체 재생성 안 함)
2. 삭제 대신 상태 변경(`case_status: ACTIVE/INACTIVE`)
3. 동일 이벤트는 dedup(`rcept_no`, 없으면 `event_type+date+reason`)
4. **LLM 은 Knowledge 를 쓰지 않는다** — 읽고 해석(브리핑 문장 생성)만 한다. Knowledge 에는
   항상 재현 가능한 Facts 만 저장.

**보류된 것**: `ContextProcessor`(인과관계·산업배경 서술)는 시장 상황 따라 계속 바뀌는
동적 정보라 장기 Knowledge 저장 대상이 아니라고 판단해 미구현. 대신 `processors/tags.py`
(AI/HBM/Memory/... 키워드 매칭)로 investment_case·회사 단위 `tags` 만 준비해 둠 — 나중에
뉴스·매크로 데이터가 갖춰지면 "Context Builder"(Knowledge + News + Macro + Tags → 브리핑
생성 시점에 조합)로 별도 설계 예정.

### 4. Portfolio Intelligence Engine — 예정(Phase2.5)
보유종목 개별이 아니라 포트폴리오 전체(업종 집중도·ETF/현금 비중·Correlation·Diversification)를
분석. 아직 미구현.

### 5. Briefing Generator — 예정(Phase3)
`results/*.json` + `knowledge/company/*/merged.json` + (향후) Portfolio Intelligence 결과를
LLM 이 함께 읽어 최종 브리핑 문장을 생성. 지금은 이 역할을 AI(Claude 등)가 JSON 을 직접
읽어 대체 수행 중(README.md 프롬프트 예시 참조).

---

## 확장 전략

- **새 Processor 추가**: `krxfree/processors/새이름.py` 만들고 `@register("새이름")` 붙인 뒤
  `pipeline.py` 의 `PIPELINE` 리스트에 이름만 추가. 기존 Processor 코드는 건드릴 필요 없음.
- **새 이벤트 taxonomy**: `krxfree/clients/dart.py` 의 `_EVENT_RULES` 테이블에 항목 추가.
- **Digest 규칙 변경**: `config/digest_rules.json` 수정(코드 변경 불필요).
- **JSON 구조는 되도록 안 바꾼다** — V3(Thesis)·Knowledge Engine V1 은 기준 구조로 확정.
  새 기능은 이 구조를 활용해서 구현하는 걸 우선한다(README/DESIGN 개발 원칙 동일).
