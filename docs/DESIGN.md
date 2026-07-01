# 가치 판단요소 · 의사결정 기록

이 문서는 **첫 사용엔 필요 없는** 설계 원칙·판단 기준·의사결정 근거를 모은 것이다. 설치/사용법은 [../README.md](../README.md) 참조.

---

## 데이터 원칙 (사실 기반)

주식 데이터인 만큼 **사실(실측) 기반이 필수**다. 출력에 추측·예측·근사로 만들어 낸 수치를 넣지 않는다.

**원칙**
1. 출력 수치는 **실측값**(API·로그인으로 가져온 값)이거나, **보편 공식으로 계산한 파생지표**만 쓴다.
2. 계산을 쓰는 경우는 둘 중 하나일 때만:
   - **(a)** 원천이 제공하지 않는 파생지표라 계산이 유일 경로 — RSI·이동평균·피벗·수익률·평가손익·ROE·부채비율·성장률 등(보편식, 대조 대상 자체가 없음). 원천 raw 값(종가·재무수치)에서 계산.
   - **(b)** 가져온 값과 비교 가능한 지표라면, **실측값과 100% 일치할 때만** 사용. 일치 보장 못 하면 계산값을 쓰지 않는다.
3. 가져올 수도 계산할 수도 없으면 **`null`(데이터 없음)** 로 둔다. 0·근사·추측으로 채우지 않는다.
4. **추측·예측성 기능**(목표가·밸류 추정·시세 예보 등)은 본 파이프라인에 섞지 않고 **별도 기능/모듈로 분리** 구현한다.

**변경 이유**: 주식은 사실 기반이 필수. 잘못된 수치가 브리핑에 섞이면 판단을 오도한다. 추측·예측이 필요한 영역은 사실 데이터와 명확히 분리해야 신뢰할 수 있다.

**트레이드오프(사실성 우선 → 완전성 일부 포기)**
- 우선주 PER/PBR: KRX 공식 표가 공란(NaN) → `null`. (pykrx 는 0 으로 채우나, 0 은 "PER 0" 오독 소지라 채택 안 함.) 가격비례 환산 등 계산 대체도 **금지**(실측 소스 없음).
- 지수 등락률(`FLUC_RT`) 결측·전일 종가 없음 → `0`(변동 없음) 대신 `null`.
- DART 재무로 PER/PBR 을 *계산*하는 경로(`krxfree.clients.dart.per_pbr`)는 코드에 있으나 **출력에 사용 안 함**(근사라 위 (b) 불충족). PER/PBR 은 KRX 공식값만.
- 결과적으로 일부 칸이 비지만, 채워진 값은 전부 실측/실측기반이다.

---

## 왜 만들었나

1. 장 시작 전 AI 로 브리핑을 받으려면 **전날 시세·재무 데이터**가 필요했다.
2. 한국 주식 데이터로 [`pykrx`](https://github.com/sharebook-kr/pykrx) 를 쓰려 했으나, 일부 데이터(PER/PBR 등)는 **KRX 계정 로그인이 필수**였다.
3. 쓰다 보니 잦은 로그인으로 **KRX 계정이 잠겼다.**
4. 조사 결과 KRX 가 **로그인 없이 인증키(API key)** 로 접근 가능한 공식 OpenAPI 를 제공함을 확인.
5. **로그인 없이 API 키만으로** 모든 데이터를 받도록 직접 구현하기로 결정.
6. 거의 다 구현했으나, **PER/PBR 한 가지만 무로그인으로 획득 불가**(공식 OpenAPI 미제공, 무로그인 다운로드 경로는 2026-06 기준 차단됨)였고, DART 재무로 계산하는 근사값은 일부 종목에서 정확도가 떨어졌다.
7. 정확도를 위해 **PER/PBR 만 KRX 로그인 방식으로 원복**(일 1회 호출이라 계정 잠금 위험 낮음). 나머지는 전부 무로그인 API. 코드는 양쪽(로그인 / DART 계산)을 모두 보유.
8. 매일 아침 손으로 스크립트를 돌리는 건 결국 안 하게 된다. **장 시작 전에 데이터가 알아서 준비돼 있어야** 브리핑을 바로 받을 수 있다. KRX 가 당일 데이터를 오전 8시부터 제공하므로 **Windows 작업 스케줄러로 매 영업일 08:05 무인 실행**되도록 자동화했다.

---

## 가치 판단요소 (스크리너 방법론)

- **유니버스**: KRX 로그인 시 코스피200 구성종목 **자동 조회**(MDCSTAT00601). 로그인 없으면 수동 `kospi200_members.json`(폴백), 그것도 없으면 KOSPI 시총 상위 200 근사. 150개 미만이면 불완전으로 보고 폴백.
- **스코어**: 모멘텀 30 / 가치(PER·PBR) 25 / 유동성 25 / 사이즈 20 (가치 미산출 시 모멘텀 55 / 유동성 30 / 사이즈 15).
- **가점**: 기술적(이평 정배열·RSI 40~70·MA20 상회) + DART(영업익 성장 / 매출 성장 / ROE≥8 / 고부채 감점).
- **업종 보정**: 금융·보험은 구조적 고부채라 부채비율 감점을 **면제**(업종은 DART `induty_code` KSIC 버킷).
- **2단계**: 1차 벌크 스코어 → 상위 ~25 후보만 OHLCV(Naver)·DART 호출로 정밀 보정.

> 점수 가중치·임계값은 모델 파라미터(상수)다. 시세가 아니라 **랭킹 산출용 판단 기준**이므로 자유롭게 튜닝 가능.

---

## 데이터 접근 방식 의사결정 기록 (2026-06)

### KRX 데이터 접근 경로 3가지
| 경로 | 정체 | PER/PBR | 인증(2026) |
|------|------|---------|-----------|
| ① 공식 OpenAPI (`openapi.krx`, `/svc/apis`) | 거래소 정식 개방. `krx_openapi.py` | ❌ 엔드포인트 없음 | 인증키 |
| ② 내부 AJAX (`getJsonData.cmd`) | 사이트 화면용 내부 API 스크래핑 = pykrx, `krxfree/clients/login.py` | ✅ MDCSTAT03501 | **로그인 필요** |
| ③ OTP 다운로드 (`comm/fileDn`) | 사이트 다운로드 버튼 스크래핑 = 옛 블로그/quant_cookbook | ✅ | **로그인 필요** |

### 검증 결과
- **무로그인 OTP 다운로드(③)** 는 2026-06 현재 **로그인 차단**됨(GET→403, GET+워밍업→LOGOUT, POST→403).
- **공식 OpenAPI(①)** 는 시세·매매정보·지수만 제공, **PER/PBR 없음.**
- 결론: **무로그인으로 KRX 공식 PER/PBR 획득 불가.** 선택지는 (L) 로그인 스크래핑 또는 (N) DART 재무로 직접 계산(근사).

#### 무로그인 ② 재검증 (2026-06-17)
- pykrx 소스는 ②(`getJsonData.cmd` MDCSTAT03501)를 **로그인 없이** 호출한다(과거 KRX 동작 기준). "우리도 무로그인 가능한가?" 확인차 **익명 호출을 직접 테스트**.
- 결과: 워밍업 GET 으로 `JSESSIONID` 쿠키를 받아도, 익명 POST → **`HTTP 400` 본문 `"LOGOUT"`**. ③과 동일하게 차단.
- 해석: **KRX 가 내부 통계 엔드포인트(②)를 회원 로그인 필수로 강화**(대략 2026년). pykrx 의 무로그인 코드는 KRX 변경 *이전* 기준이라 **현재 KRX 상대로는 동일하게 LOGOUT**(소스가 무로그인이라고 현재도 되는 것이 아님).
- 따라서 **무로그인 PER/PBR 은 현재 불가** 재확인. 로그인 방식(L) 유지. 같은 게이트를 쓰는 지수구성종목(MDCSTAT00601)·업종분류(MDCSTAT03901)도 **무로그인 불가**이며, 받으려면 **기존 로그인 세션**으로 호출해야 한다(MDCSTAT00601 = 로그인 세션으로 200종목 정상 응답 확인, 2026-06-17).

#### DART 계산 PER/PBR vs KRX 공식값 실측 (2026-06-12, DART 2025 사업보고서·지배주주 기준)
판정: ✅ 일치(±7% 이내) · ⚠️ 잔차(±10% 이상)

| 종목 | PER(KRX) | PER(DART) | PERΔ | PBR(KRX) | PBR(DART) | PBRΔ | 판정 |
|------|---------:|----------:|-----:|---------:|----------:|-----:|:----:|
| 기아 | 8.6 | 8.6 | 0.0% | 1.06 | 1.06 | 0.0% | ✅ |
| SK스퀘어 | 20.4 | 20.3 | -0.5% | 6.48 | 6.48 | 0.0% | ✅ |
| SK하이닉스 | 34.6 | 35.7 | +3.2% | 12.52 | 12.71 | +1.5% | ✅ |
| NAVER | 19.0 | 19.8 | +4.2% | 1.34 | 1.40 | +4.5% | ✅ |
| KB금융 | 10.5 | 9.8 | -6.7% | 0.98 | 0.97 | -1.0% | ✅ |
| 신한지주 | 10.2 | 9.5 | -6.9% | 0.82 | 0.82 | 0.0% | ✅ |
| 삼성생명 | 30.1 | 33.5 | +11.3% | 1.10 | 1.23 | +11.8% | ⚠️ |
| 삼성전자 | 48.8 | 42.6 | -12.7% | 5.04 | 4.44 | -11.9% | ⚠️ |
| 현대차 | 16.8 | 13.2 | -21.4% | 1.38 | 1.08 | -21.7% | ⚠️ |

→ 9종목 중 6개 ✅ ±7% 이내(단순 사업구조), 3개 ⚠️(지주/소수지분/보험·TTM 차이) ±10~22% 잔차.

### 트레이드오프와 결정
| 안 | PER/PBR | 로그인 | 정확도 |
|----|---------|--------|--------|
| N. 무로그인/API only | DART 계산 | 0 | 근사 (일부 ±10~20%) |
| **L. 자체 KRX 로그인** (`krx_login.py`) | KRX 공식값 | 1회/실행 | 정확 |

**→ 결정: L 선택.** [데이터 원칙](#데이터-원칙-사실-기반)상 PER/PBR 은 실측 공식값만 써야 하고(DART 근사는 100% 불일치라 금지), 정확한 PER/PBR 의 무로그인 경로가 현재 없으므로 로그인이 유일한 사실 기반 경로다. 로그인은 일 1회뿐이라 계정 잠금 위험이 낮다. PER/PBR 이 필요 없으면 로그인을 빼고 가치 팩터를 제외(N)해도 되며 그 경우도 사실성은 유지된다.

---

## 추천 기능 확장 — 공시/뉴스/매크로 (2026-06-21)

스크리너가 점수만 내면 "왜 추천했는지" 설명이 안 됨. 점수 엔진보다 **설명 엔진**으로 가는 방향으로 Phase1~3 추가.

### Phase1 — DART 공시 필터 + 보유종목 경고
- `dart.disclosure_flags()`: 최근 30일 공시(`list.json`)를 제목 키워드로 분류.
  - **강한 악재**(관리종목지정/상장폐지/횡령/배임/회생절차/감자결정/불성실공시법인지정): 신규 후보는 **제외**, 보유종목은 경고만(이미 들고 있는 건 빼지 않음).
  - **중간 악재**(유상증자/CB/교환사채): 감점.
  - **호재**(자사주취득/단일판매공급계약): 소폭 가점.
- 보유종목엔 `thesis_status`(양호/주의/재검토 필요) — "투자 논리가 깨졌는가"를 공시·실적으로 판정.
- `momentum_label`: 모멘텀 15%↑인데 실적 성장 없으면 "재료 미확인 상승"으로 라벨링(자동 배제 아님 — 오탐 위험이 더 큼).

### Phase2 — 배정방식·희석규모 세분화
- `dart.dilution_flags()`: 유상증자결정(`piicDecsn`)·CB발행(`cvbdIsDecsn`) 상세 API로 배정방식(`ic_mthn`)과 희석률(신주/기존주식수) 계산.
  - 제3자배정/일반공모 + 희석 10%↑ → 강한 감점(-0.08). 그 외 희석 10%↑ → -0.05. 소규모 → -0.02.
  - CB는 시총 대비 비율 산출 불가(권면총액만 제공) → 고정 감점(-0.05) 유지.
  - **조회범위는 1년**(disclosure_flags 의 30일과 다름): 정정공시(`[기재정정]`)는 30일 안에 잡혀도
    원결정(배정방식·희석률 필드)은 결정→효력발생까지 수개월 걸려 그보다 훨씬 전일 수 있음
    (한화솔루션 실측 확인, 2026-06-23 — 원결정 4월, 정정만 6월에 반복 노출).
    30일로 좁혀 조회하면 "공시는 잡히는데 배정방식/희석률은 모름" 상태가 됨.
- **단일판매·공급계약체결은 OpenDART에 구조화된 전용 API가 없음**(문서 확인, 2026-06-21) → 계약금액/매출 비율 산출은 **보류**. 공시 제목 키워드 분류(Phase1)만 적용.

### Phase3 — 뉴스 건수 + ETF 매크로
- `clients/news.py`: Google News RSS(`news.google.com/rss/search`, 인증키 불필요)로 종목명 검색, 최근 7일 기사 수만 집계(감성분석 없음).
  - 모멘텀 15%↑ + 실적/호재공시 없음 + 뉴스 2건↓ → `momentum_label = "원인 불명 변동성"`.
  - 네이버는 종목별 RSS 미공개(HTML 스크래핑 필요해 깨지기 쉬움) → 구글뉴스 RSS 채택.
- `clients/macro.py`: **KODEX200 같은 지수상품은 개별종목 뉴스보다 매크로가 설명력이 큼**(우선순위: 미국10년물 > 달러원 > 코스피추세 > 외국인수급. 외국인수급은 KRX 공식 데이터라 품질은 괜찮으나 후순위로 둠).
  - 미국10년물(`DGS10`)·달러원(`DEXKOUS`): FRED 공개 CSV(`fredgraph.csv`, 인증키 불필요) — 키 발급 없이 확보 가능한 가장 안정적인 소스.
  - 코스피추세: 기존 KRX OpenAPI `idx_dd_trd`(이미 이용신청 돼 있어 추가 비용 없음) 재사용.
  - 외국인수급: `getJsonData.cmd`(`MDCSTAT02201`) — **로그인 세션 필요**(익명 호출은 `400 LOGOUT`, 실측 확인). 종목별 아닌 시장 전체 1회 계산이라 계정 잠금 위험 낮음.
  - 출력 최상위 `macro` 섹션(종목별 아님, 1회만 계산)으로 분리.

**변경 이유**: 사용자가 "점수보다 왜 그 점수인지가 중요"하다고 판단. 라벨/경고를 점수와 분리해 설명가능성을 높이고, 추측성 분류(예: 단일판매계약 금액 추정)는 검증 안 된 API 필드를 쓰지 않는 [데이터 원칙](#데이터-원칙-사실-기반)을 그대로 따름.

### Phase4 — 공시 영향 점수·Thesis 방향·이력 관리 (2026-07-01)
- **KRX 시장조치 별도 API 없음 확인**: 공식 OpenAPI 는 시세·지수만 제공(기존 결정 재확인). 불성실공시법인지정 등도 DART `list.json` 제목 키워드 하나로만 잡힘 — "①DART 공시 ②KRX 시장조치 분리 API" 전제는 데이터소스상 불가. 라벨만 구분해 표기하는 수준이 현실적 한계.
- `dart.disclosure_score(cat, report_nm)`: 공시 분류(hard/soft/positive)에 제목 키워드 기반 ★1~5 점수 + 한 줄 사유 부여. **내부 참고용, 매수·매도 신호 아님**. 희석률 등 세부 수치는 반영 안 함(ponytail: 근사치, 정밀화는 필요시 추가).
- `_thesis_direction(code)`: 보유종목 한정, 4단계(강화/유지/약화/훼손). 횡령·배임·상장폐지·관리종목지정·회생절차는 훼손, 그 외 hard_negative(불성실공시 등)·soft_negative(유상증자/CB)는 약화, positive 만 있으면 강화, 없으면 유지. 조회 실패는 "확인 불가"(기존 `thesis_status`와 별개 필드로 병존 — 기존 소비처 안 깨기 위함).
- `_action_needed(code, direction)`: 행동 변화 감지 문구. 훼손="투자 논리 재검토 필요", 약화="자금 사용 목적 확인"(희석 상세 있을 때) 또는 "후속 공시 확인 필요". 강화/유지/확인불가는 None(행동 변화 없음).
- `results/briefing_state.json`: "어제 대비 무엇이 달라졌는지" 비교용 상태 파일. `{generated, disclosures: {종목코드: {last_rcept_no, last_type}}, thesis: {}, behavior: {}}`. 이번 구현은 `disclosures` 만 채움 — 같은 공시를 매일 반복 강조하지 않기 위해 각 공시 항목에 `new`(`rcept_no` > 저장된 `last_rcept_no`) 표시. `thesis`/`behavior` 는 스키마만 마련(향후 Thesis 변화·행동 변화 이력도 같은 파일에서 비교 확장 예정, 지금은 값 채우지 않음).

### Phase5 — Thesis Impact Engine (2026-07-01)
Phase4 의 ★점수/4단계 방향(thesis_status/thesis_direction/action_needed/disclosure.stars) 를
전부 걷어내고 숫자 기반 Thesis 엔진으로 교체. 목적은 "오늘 무슨 공시가 있었나"가 아니라
"오늘 투자 논리가 얼마나 강화/약화됐나"를 하루 5분 안에 보여주는 것.

- **DART/KRX 완전 분리**: `disclosure_flags()` 반환 구조를 `{"dart": {event_type:[...]}, "krx": {event_type:[...]}}`
  로 변경(기존 hard_negative/soft_negative/positive 3버킷 폐기). 두 카테고리는 절대 합치지 않음.
- **이벤트 taxonomy(`dart.py` `_EVENT_RULES`)**: 제목 키워드 매칭마다 `event_type`(유상증자/CB/BW/자기주식취득·소각/
  배당/최대주주변경/횡령/배임/회생절차/감자결정/감사의견 + KRX 불성실공시법인지정/관리종목지정/거래정지/
  상장적격성실질심사/상장폐지), `level`(A/B/C), `confidence`(HIGH/MEDIUM/LOW), `severity`(1~5, 공시 자체 중요도),
  `impact_score`(Thesis 영향도, 방향 불명이면 None), `reason` 한 줄을 함께 부여.
  - **Level A** = 구조화 신뢰(DART 공식 report_nm 카테고리 또는 KRX 시장조치) — Thesis Impact Score 산정 대상.
  - **Level B** = 제목 키워드 참고(공급계약/시설투자/합병/분할/신규사업) — 브리핑엔 표시하되 점수 미반영.
  - **Level C** = 시장경보성(투자주의/투자유의/단기과열/투자경고) — 참고만, 점수 대상 아님(DART list.json 특성상
    실제로는 거의 매치 안 될 가능성 높음 — 정직하게 빈 결과로 남김, 억지 매칭 안 함).
  - ponytail: 감사의견거절/부적정/한정은 title 키워드로 매치 시도하나 DART report_nm 이 통상 "감사보고서제출"
    까지만이라(의견 유형은 본문) 실제 매치는 드묾 — 정직한 한계로 문서화, 향후 본문 파싱 API 확보 시 승격.
  - 배당/무상증자는 방향(확대·축소, 호재 여부) 판단 근거가 title 만으론 불충분 -> `impact_score=None`
    (Thesis 합산에서 자동 제외, 이벤트 존재 자체는 표시). 실적 기반 이벤트(ROIC/FCF/부채감소트렌드/
    대규모고객확보/실적 서프라이즈-컨센서스대비)는 이번 버전 **미구현**(기존 계산 필드로 커버 불가 — 과도한
    근사 대신 range 밖으로 명시적 배제).
- **Thesis Impact Score 계산**: Level A + `impact_score is not None` 인 이벤트만 합산.
  `today`(이번 실행에서 새로 확인된 이벤트만) / `rolling_30d` / `rolling_365d`(둘 다 raw 이벤트 날짜 기준
  매번 새로 합산 — 과거 점수를 누적 저장하지 않고 원본에서 재계산해 드리프트 방지).
  보유종목만 계산(365일 조회), 비보유 후보는 기존처럼 30일만 조회(비용 절감, 랭킹용 가/감점은 별개 로직 유지).
- **상태 5단계**: `+5↑ STRONGLY_STRENGTHENED · +2~+4 STRENGTHENED · -1~+1 MAINTAINED · -2~-4 WEAKENED · -5↓ BROKEN`
  + 조회 실패 전용 `UNCONFIRMED`(6번째, "확인 불가"를 "유지"로 오판 방지 — 기존 thesis_status 의 "확인 불가"와
  동일 원칙). 상태/영문 enum은 데이터 레이어 값이고, 이모지(🟢🔵🟡🔴) 변환은 브리핑 작성 단계(AI) 몫.
- **action(행동 변화 감지)**: `{level: INFO/WARNING/CRITICAL, items: [...]}`. BROKEN→CRITICAL(재검토+자금목적+경영진설명),
  WEAKENED→WARNING(후속공시, 희석 정보 있으면 자금목적 추가), 그 외 INFO+빈 items(변화 없음).
- **buffett_lens**: 규칙 기반(오늘 ≤-5 또는 30일 누적 ≤-8 → 자본배분/신뢰도 점검 문구, 30일 누적 ≥+8 → 경쟁우위 유지 확인
  문구, 그 외 None). LLM 생성 아님.
- **confidence**(이벤트 신뢰도 아니고 Thesis 판단의 데이터 근거 충분도): KRX+DART Level A + 재무데이터 모두 있으면 0.95,
  DART/KRX Level A 단독 0.75, 뉴스만 0.40, 아무 신호 없음 0.20 — spec 예시 구간을 그대로 규칙화.
- **랭킹 점수(스크리너 후보 선정)와 완전 분리**: 기존 후보 제외/가점/감점 로직은 `dart.HARD_EXCLUDE_TYPES`/
  `SOFT_PENALTY_TYPES`/`POSITIVE_BONUS_TYPES` 로 event_type 재매핑만 하고 그대로 유지 — Thesis Impact Score 는
  투자자용 서술 지표, 스크리너 점수는 랭킹용 내부 지표로 서로 건드리지 않음.
- **이력 dedup 버그 수정**: `briefing_state.json.disclosures[code]` 를 `recent`(최근 5건, 사람이 보는 요약 스냅샷)
  만으로 dedup 판정하면 365일 조회 범위 안에 5건 넘게 쌓인 종목(예: 정정공시 반복)에서 6번째 이후로 밀려난
  옛 이벤트가 **매번 "new" 로 되살아나는 버그**가 있었음(실측 확인: 한화솔루션 9건 중 4건이 매 실행마다 재계산).
  `seen_ids`(상한 300, dedup 전용) 를 별도로 둬서 해결 — `recent` 는 표시용, `seen_ids` 는 판정용으로 역할 분리.
- **실측 검증(2026-07-01)**: 한화솔루션 실제 유상증자 반복 정정공시(7건, 각 -2) + 불성실공시법인지정(2건, 각 -4)로
  최초 실행 today=-22(스키마 첫 적용이라 전부 new) → 이후 정상 실행에서 today=0/rolling_30d=-8/rolling_365d=-22,
  state=MAINTAINED(오늘 신규 없음이나 최근 추세는 약화 지속 — buffett_lens 규칙대로 문구 노출 확인).

### Phase6 — Thesis State 자동화·Decay·Timeline 보강 (2026-07-01)
Phase5 실측 후 "state 가 거의 항상 MAINTAINED(오늘 신규 이벤트 없으면 항상 유지로 뜸)" 피드백 반영.
구조(score/state/reasons/action/buffett_lens/confidence)는 유지, 계산 로직만 보완.

- **State cascade**: `today_score`(0 아니면 그대로) → 0이면 `rolling_30d` → 그것도 0이면
  `rolling_365d`(decay 적용값) 순으로 대표 점수를 골라 5단계 상태 산정. 신규 이벤트가 없어도
  최근 추세가 남아 있으면 그 추세로 상태가 매겨짐(기존엔 today_score 만 봐서 거의 늘 MAINTAINED).
  `reasons`/`contributors`/`buffett_lens` 도 이때 선택된 창(today/30d/365d)의 이벤트 기준으로 계산 —
  숫자와 서술이 항상 같은 근거를 가리키도록 함.
- **Score Decay**: `rolling_365d` 는 이벤트 경과일수 가중합(`_decay_weight`: 30일=100%/90일=70%/
  180일=40%/365일=20%)으로 변경 — 오래된 이벤트일수록 기여도 감소. `today_score`/`rolling_30d` 는
  창 자체가 30일 이내(weight 100%)라 수치 변화 없음(기존 raw 합과 동일).
- **contributors**: reason별 기여 점수 합계(사용된 창 기준, 365d 창이면 decay 반영값). "Impact 구성" 표시용.
- **action 5단계**: BROKEN→CRITICAL(4항목, IR자료확인 추가), WEAKENED→WARNING(기존과 동일),
  STRENGTHENED/STRONGLY_STRENGTHENED→**WATCH**(다음 실적 확인/신규 계약 진행 확인, 신규 레벨),
  MAINTAINED→INFO(빈 items).
- **buffett_lens 긍정 분기 세분화**: rolling_30d≥8 이고 reasons 에 "자사주"/"배당" 포함 시 주주환원 특화 문구,
  아니면 일반 문구. 부정 분기는 today≤-5 OR rolling_30d≤-8(기존 유지) — 규칙 기반, LLM 생성 아님.
- **confidence 5단계 갱신**: KRX+DART+실적=0.95, (DART 또는 KRX)+실적=0.75, **실적만=0.50**(신규 구간),
  뉴스만=0.40, 데이터부족=0.20. `low_confidence`(<0.5) 필드 추가 — "데이터 근거 제한" 표시를 LLM 판단이
  아닌 데이터 생성 단계 값으로 고정.
- **last_changed / last_changed_days_ago**: Level A 채점 이벤트 중 가장 최근 `rcept_dt`. 브리핑에서
  "Thesis 변경 N일 전"에 바로 사용(날짜 계산을 LLM에 맡기지 않음).
- **timeline**: 채점 이벤트를 (날짜, reason) 중복 제거 후 최신순 최대 10건. 최근 변화 흐름 표시용.
- **summary**: `state`+상위 3개 `reasons`+`buffett_lens` 조합 템플릿 문자열을 데이터 생성 단계에서 저장
  (LLM 매번 재추론 안 함). 표시용 `state_label`(이모지 매핑)도 같은 이유로 함께 저장.
- **실측 검증**: 삼성전자 자사주취득 3건(경과 67~85일, decay 반영) → `rolling_365d=3.0(decay 전 6)`,
  cascade가 rolling_365d 선택 → `state=STRENGTHENED`(기존엔 today=0이라 MAINTAINED 로 묻혔음).
  현대차는 decay 후 1.4(<2 임계치)라 `MAINTAINED` 유지 — 문턱값 근처에서 decay 가 상태를 가르는 것 확인.
  한화솔루션은 rolling_30d=-8(0 아님)이 cascade 로 선택돼 `state=BROKEN`, `action=CRITICAL`,
  `buffett_lens`/`summary` 정상 생성.

### Phase7 — V3(데이터 모델 마지막 개선): 버전관리·변화감지·희석률·재무이벤트·PortfolioHealth (2026-07-01)
사용자가 "이번을 V3 데이터 모델 기준 버전으로 삼고, 이후엔 구조 변경보다 브리핑 품질에 집중"이라고
못박음. 기존 필드는 유지, 계산 로직·신규 파생 필드만 추가.

- **버전 관리**: 출력 최상위에 `schema_version`("2.0", JSON 구조 버전 — 필드 구조 변경 시만 증가),
  `thesis_engine_version`("3.0", 점수 산정 규칙 버전 — 계산식 변경 시만 증가) 추가.
- **today_score**: 이미 Phase5 부터 "이번 실행에서 새로 확인된 이벤트만" 합산하도록 구현돼 있었음
  (신규 요청 아니라 기존 동작 재확인). 대부분 0으로 보이는 건 버그가 아니라 "오늘 새 공시가 없었다"는
  정상 신호 — Phase6 의 state cascade(today→30d→365d) 가 이 상황에서 추세를 대신 보여줌.
- **Thesis Change 감지**: `thesis.change = {prev_state, changed, direction(IMPROVED/WORSENED),
  alert(✅/🚨 문구)}`. `briefing_state.json.thesis` 에 저장된 전일 state 와 랭크 비교
  (BROKEN<WEAKENED<MAINTAINED<STRENGTHENED<STRONGLY_STRENGTHENED). UNCONFIRMED 가 얽히면 방향
  판단 보류(모르는 걸 개선/악화로 단정 안 함).
- **희석률 티어링**: `dart.dilution_extra_penalty(pct)`(10~20%:-1, 20~30%:-2, 30%↑:-3)를 유상증자
  기본 감점(-2)과 **별개 이벤트**(`event_type=dilution_penalty`, reason=`"희석률 N%"`)로 `flags["dart"]`
  에 추가 — "유상증자"와 "희석률"이 contributors 에 분리된 줄로 보이도록.
  - **버그 발견·수정**: 기존 코드가 `if hard_present: ... elif SOFT_PENALTY_TYPES: ...` 로 갈라져 있어,
    보유종목이 hard_negative(불성실공시 등)와 soft_negative(유상증자)를 **동시에** 안고 있으면 희석률
    상세 조회 자체가 스킵됐음(한화솔루션 실측: 불성실공시+유상증자 동시 보유라 dilution_penalty 가
    전혀 안 붙는 것으로 발견). `elif` → 독립 `if` 로 수정해 hard_negative 여부와 무관하게 항상 확인.
- **재무 기반 긍정 이벤트(ROE 개선/부채 감소)**: `dart.financials()` 가 이미 매 호출마다 받아오던
  frmtrm(전기) 금액을 캡처해(추가 API 호출 없음) `roe_prev_pct`/`debt_ratio_prev_pct` 추가.
  `dart.fin_events(fin)` 가 전기 대비 ROE +1%p↑ → "ROE 개선"(+1), 부채비율 -10%p↓ → "부채 감소"(+2)
  를 이벤트로 만들어 `flags["dart"]` 에 편입. 날짜는 사업연도말(`YYYY1231`)이라 공시 이벤트와 동일한
  decay/timeline 로직을 그대로 탐(별도 코드 경로 불필요). `rcept_no` 가 없어 dedup "new" 판정 대상은
  아니고(항상 False), 30일/365일 rolling 집계에만 반영 — 연차 보고 하나가 매일 "새 이벤트"로
  재카운트되는 것을 방지.
  - **미구현(명시적 보류)**: 배당확대(방향 판단에 원문 파싱 필요, title 만으론 불가) · 실적
    서프라이즈(컨센서스 추정치 소스 없음) · ROIC 개선 · FCF 증가 · 현금흐름 개선(현금흐름표 계정
    매핑 미비 — PER/PBR 근사 실패 전례처럼 어설픈 계정 매칭이 오차 키움) · 신규 대형계약(이미
    Level B "공급계약"으로 존재, 구조화 API 없어 Level A 승격 불가). 근거 있는 것만 우선 반영하고
    나머지는 계정 매핑·API 확보 시 재검토.
- **Buffett Lens 세분화**: 긍정 분기에서 `reasons` 에 "자사주"(주주환원) / "부채 감소"·"ROE 개선"
  (자본배분) 존재 여부로 문구 3갈래 분기. 경제적 해자/현금창출력/안전마진 등은 FCF·내재가치 데이터가
  없어 규칙화 보류(문구만 그럴듯하게 지어내지 않음 — LLM 자유생성 금지 원칙 유지).
- **Confidence**: Phase6 에서 이미 0.95/0.75/0.50/0.40/0.20 5단계로 구현돼 있었음(문서화만 재확인,
  코드 변경 없음).
- **Portfolio Health**: `kospi200_screen.json` 자체 데이터(보유종목 thesis 분포 + 업종 집중도)만으로
  계산 — `100 - 훼손×25 - 약화×10 + 강화×5`(0~100 클램프), `top_sector_concentration_pct`.
  **ETF 비중/현금 비중은 이번에도 미포함** — 포지션 평가금액은 `briefing_data.json`(briefing.py) 쪽
  데이터라 이 스크립트 하나로는 계산 불가(두 산출물을 합치는 별도 스크립트 필요, 향후 검토).
- **Trend**: `thesis.trend = {"30d":, "365d":}` — rolling 점수를 ↗강화/→유지/↘약화 화살표로 변환
  (state 판정과 동일한 ±2 임계치 재사용, 별도 기준 추가 안 함).
- **Investment Case**: `thesis.investment_case: []` — 스키마만 준비(요청대로 값은 비움). 향후 종목별
  투자 근거(AI 메모리/HBM 성장 등)마다 강화/유지/약화 평가를 추가할 자리.
- **실측 검증**: 한화솔루션 rolling_30d -8→**-11**(희석률 -3 반영), contributors 3줄(유상증자 -4,
  불성실공시 -4, 희석률30% -3)로 분리 노출 확인. 삼성전자 rolling_365d 3.0→**3.2**(ROE개선 +0.2 decay
  반영 합류), reasons/timeline 에 "ROE 개선" 추가 확인. `portfolio_health.score=80`(보유 5종목 중 강화1·
  훼손1) 확인.
- **today_score/change "버그" 재확인**: 사용자가 "대부분 0/false 이라 버그 아니냐"고 재차 문의.
  `briefing_state.json` 을 인위 조작(이력 리셋 + 전일 state=MAINTAINED 로 세팅)해 재실행한 결과
  `today=-22`, `change={changed:true, direction:WORSENED, alert:"🚨 투자 Thesis 변경"}` 정확히 산출 →
  버그 아니라 "최근 진짜 신규 이벤트가 없었다"는 정상 신호였음을 실측으로 확인(원상복구 후 정상 재확인).

### Phase8 — Knowledge Growth Engine 뼈대(Registry+Pipeline) + 핵심 3 Processor (2026-07-01)
"이후엔 데이터 구조보다 Knowledge/브리핑 품질에 집중"이라던 V3 선언 이후, 사용자가 별도로 장기
기업 지식 축적 시스템을 요청. 브리핑(`results/`, 매번 덮어씀)과 분리된 `knowledge/`(장기 누적, 삭제 없음)
신설. 9개 Processor 전체가 아니라 **뼈대(Registry+Pipeline) + 핵심 3개**만 이번에 구현(사용자가 직접
범위를 좁혀 확정).

- **차단 이슈 먼저 확인**: WikiEnricher 가 요구한 founder/ceo/website/products/competitors 등은
  DART/KRX/Naver/Google뉴스 어디에도 없는 데이터라, 없이 진행하면 LLM 지어내기나 새 외부 API가
  필요 — 이 프로젝트의 "실측값만, 추측 금지" 원칙과 정면충돌. 사용자에게 확인 후 **DART
  company.json 이 실제 주는 것만 자동 채움, 나머지는 null 유지 + 사용자가 `manual.json` 에 직접
  채우는 4계층 구조**로 확정(WikiEnricher 자체는 "CompanyProfileProcessor" 로 개명 제안됐고
  Phase2-3 로 연기 — 이번엔 미구현).
- **디렉터리**: `knowledge/company/{종목코드}/{manual,dart,generated,merged}.json`.
  `manual.json`(사용자 작성, 최우선) 만 git 추적 — 나머지 3개는 자동 생성 산출물이라 `.gitignore` 등록
  (`results/*.json` 과 동일한 취급 원칙).
- **Registry(`processors/registry.py`)**: `@register("이름")` 데코레이터 하나로 등록. 새 Processor
  추가 시 pipeline.py 리스트에 이름만 넣으면 됨(개별 배선 코드 수정 불필요 — 사용자가 명시적으로
  요청한 "향후 확장 쉬운 구조").
- **Pipeline(`processors/pipeline.py`)**: 순서 고정 `timeline -> knowledge_merge -> investment_case`
  (요청받은 다이어그램 그대로). `run(code, events)` 하나로 3단계 실행.
- **TimelineProcessor**: `generated.json` 의 `timeline` 에 신규 이벤트만 append(삭제 없음).
  dedup 키: `rcept_no` 있으면 그 값, 없으면(재무 이벤트 등 합성) `(event_type, date, reason)`.
  Thesis Engine(Phase5~7)이 이미 만들어 둔 이벤트 dict(report_nm/rcept_dt/rcept_no/event_type/
  impact_score/reason)를 그대로 재사용 — 새 데이터 소스 불필요.
- **KnowledgeMergeProcessor**: `manual.json(최우선) > dart.json(공식, 아직 비어있음) >
  generated.json(계산결과)` 순으로 병합해 `merged.json` 저장. `timeline` 은 여기서 한 번 더
  dedup(같은 이벤트가 여러 경로로 들어와도 하나만).
- **InvestmentCaseProcessor**: Case 정의(name/keywords/importance)는 **오직 `manual.json` 에서만**
  옴(자동으로 테마를 지어내지 않음). `merged.json` 의 timeline 에서 keyword 매칭된 이벤트만 근거로
  `status`(Thesis 5단계 재사용)/`trend`(UP/DOWN/FLAT, 최근 30일 매칭+부호)/`reason`(매칭 이벤트
  reason 상위 3개 그대로)/`case_status`(마지막 매칭 365일 초과 시 INACTIVE — 삭제 대신 상태변경,
  point14 원칙)를 규칙 기반 계산. LLM 은 이 값을 만들 때 관여 안 함(브리핑 작성 시 해석만 담당).
- **screener.py 연동**: 보유종목 Thesis 계산에 쓰던 `all_events` 를 그대로
  `knowledge_pipeline.run(code, all_events)` 에 넘겨 매 실행마다 자동 증분(별도 명령 불필요).
  실패해도 `try/except` 로 격리해 Knowledge 문제가 브리핑 생성을 막지 않게 함(기존 클라이언트
  호출부와 동일한 방어 스타일).
- **실측 검증**: 한화솔루션에 테스트용 `manual.json`(case="테스트-유상증자 리스크",
  keywords=["유상증자","불성실공시"]) 을 임시로 넣고 2회 연속 실행 → `merged.json` 에 timeline 11건
  누적, investment_case 1건(`status=BROKEN, trend=DOWN, case_status=ACTIVE`) 정상 계산, 2회차 실행
  에도 timeline 11건 유지(중복 없음) 확인 후 테스트 파일 정리. 삼성전자 등 실제 보유종목은
  `manual.json` 없이도 timeline 만 정상 누적됨(investment_cases 는 빈 리스트 — 케이스 정의 없으면
  억지로 안 만든다는 원칙대로).

### Phase2-2 — SummaryProcessor(Timeline Digest) + Tag 구조 (2026-07-01)
사용자가 "Summary/ContextProcessor" 를 요청했으나 예시가 자연어 서술문(원인→결과 인과관계
포함)이라 **기존 원칙(LLM이 Knowledge를 생성하지 않는다)과 충돌** — 확인 후 범위 조정.

- **SummaryProcessor 는 자연어 요약이 아니라 "Timeline Digest"**: timeline 을 기간별(월/분기/연)
  로 묶어 `{"period": "2026-06", "events": ["유상증자", "불성실공시법인 지정"]}` 형태로 압축.
  문장 생성 없음 — 이 Digest 를 브리핑 작성 단계에서 LLM 이 읽어 문장을 만든다(Knowledge=사실,
  LLM=해석 분리 유지).
- **규칙은 코드가 아니라 `config/digest_rules.json`**: `period_unit`(month/quarter/year),
  `max_events_per_period`, `include_event_types`/`exclude_event_types`, `sort`. 규칙 변경 시
  코드 수정 불필요.
- **Incremental**: 기간별 이벤트 id 집합(`_source_ids`, rcept_no 있으면 그 값 없으면
  event_type+date+reason)을 저장해두고, 다음 실행에서 그 기간의 id 집합이 그대로면 재계산 없이
  이전 결과를 재사용. `_source_ids` 는 내부 변경감지용이라 `merged.json` 산출 시 제거
  (`knowledge_merge_processor` 가 `_` 접두 키를 걸러냄).
- **ContextProcessor 는 이번 단계 보류**: Context(인과관계·산업 배경)는 기업의 고정 지식이
  아니라 **시장 상황에 따라 계속 바뀌는 동적 정보** — `manual.json` 에 넣으면 금방 낡은 정보가
  됨. 대신 향후 뉴스·매크로 데이터가 준비되면 "Context Builder"(Knowledge + News + Macro + Tags
  -> 브리핑 생성 시점에 조합)로 별도 설계하기로 하고, 이번엔 그 입력값이 될 **Tag 구조만** 준비.
- **Tag 구조(`processors/tags.py`)**: AI/HBM/Memory/Cloud/EV/Battery/Renewable/Semiconductor
  키워드 테이블로 investment_case 이름·키워드에서 규칙 기반 매칭(`match_tags()`). 매칭 없으면
  빈 리스트(테마 억지로 안 만듦). `investment_case_processor` 가 case 별 `tags` +
  회사 단위 `merged.json.tags`(전체 case 태그 합집합)를 계산.
- **pipeline 순서 갱신**: `timeline -> summary -> knowledge_merge -> investment_case`.
- **실측 검증**: 한화솔루션 테스트 케이스로 digest 4개 기간(2026-06/05/04, 2025-12) 정상 생성,
  `tags=["Renewable"]`("태양광 사업" 케이스명 매칭) 확인. 2회 연속 실행으로 digest 안정성(동일
  기간 재계산 없이 유지) 확인 후 테스트 파일 정리.
- **파이프라인 순서 재검토(같은 날 추가 커밋)**: 사용자가 "summary 를 knowledge_merge·
  investment_case 뒤로 옮기는 게 맞지 않냐"고 재확인 요청. 검토 결과 — 지금은 manual.json 이
  timeline 에 아무것도 기여하지 않아 순서를 바꿔도 값은 동일하지만, **향후 manual.json 이
  timeline 을 보완하게 되면 순서가 실제로 결과에 영향**을 준다(Digest 가 "최종 merged 상태"를
  반영 못 하고 뒤처지는 문제 생김). 순서를 `timeline -> knowledge_merge -> investment_case ->
  summary` 로 변경, `summary_processor` 는 `generated.json` 대신 **`merged.json` 의 timeline**
  을 읽도록 수정(증분 판단용 `_source_ids` 상태는 계속 `generated.json` 에 보관, 최종 Digest 는
  `merged.json` 에도 반영 — investment_case_processor 와 동일 패턴). 재실행으로 결과값 동일함
  확인(현재 데이터 기준으로는 순서 무관하게 같은 출력 — 예상대로).

---

## 한계 / 확장 여지

- **코스피200 정확 명단**: KRX OpenAPI 엔 없음 → 로그인 세션 MDCSTAT00601(자동) 우선, 무로그인이면 수동 `kospi200_members.json`(폴백), 둘 다 없으면 시총 상위 200 근사. 구성종목은 연 2회(6·12월) 정기변경 시에만 갱신하면 됨.
- **업종 분류**: KRX OpenAPI 엔 없음 → DART 기업개황 `induty_code`(KSIC)로 업종 버킷 부여(`sector_map.json` 캐시). KSIC 미상 종목은 `기타`.
- **수정주가**: Naver 기간조회는 수정주가 적용 → 과거 분할 종목은 KRX 원시값과 과거 구간 상이 가능(현재가는 동일).
- **무로그인 완전 전환**: 정확 PER/PBR 의 무로그인 경로가 현재 없어 보류. KRX 정책 변경 시 재검토.
