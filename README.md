# krxbrief — KRX 모닝 브리핑 & 코스피200 스크리너

`pykrx` 에 의존하지 않고, 자체 클라이언트로 KRX·Naver·OpenDART 데이터를 직접 호출해
**한국 주식 모닝 브리핑 데이터**와 **코스피200 추천 스크리너**를 JSON 으로 생성하는 파이프라인.
산출 JSON 은 AI(Claude 등)가 읽어 장 시작 전 브리핑을 작성하는 입력으로 쓴다.

> ⚠️ **면책**: 투자 자문이 아니다. 공개 데이터 기반 단순 스크리닝이며, 모든 투자 판단·손익 책임은 사용자에게 있다.
>
> 설계 원칙·판단 기준·의사결정 근거는 [docs/DESIGN.md](docs/DESIGN.md) 참조. 출력 수치는 **실측값(또는 보편식 파생)만** 쓰고 추측·근사는 넣지 않는다.

---

## 주요 기능

1. **모닝 브리핑** — `python -m krxfree.briefing` → `results/briefing_data.json`
   - 보유종목 현재가·등락률·RSI·이동평균·피벗·평가손익 + KOSPI/KOSDAQ 지수 + 미국 종목
   - 보유종목은 `portfolio.json` 에서 읽음(무로그인: Naver·KRX OpenAPI·yfinance)
2. **코스피200 스크리너** — `python -m krxfree.screener` → `results/kospi200_screen.json`
   - 다중 팩터(모멘텀·가치·유동성·사이즈) 점수화 + 기술적·재무 가점으로 추천
   - 유니버스: KRX 로그인 시 코스피200 구성종목 **자동 조회**, 아니면 시총 상위 200 근사
3. **무인 자동화** — `automation/` (Windows 작업 스케줄러, 매 영업일 08:05)

---

## 필요 정보 (`.env`)

저장소 루트에 `.env` 생성. 양식은 [`.env.example`](.env.example) 참고.

```
KRX_ID=<KRX 로그인 ID>            # 스크리너 PER/PBR·구성종목 자동조회용 (브리핑엔 불필요)
KRX_PW=<KRX 로그인 PW>
KRX_API=<KRX OpenAPI 인증키>     # https://openapi.krx.co.kr
DART_API=<OpenDART 인증키>       # https://opendart.fss.or.kr
```

- **브리핑만** 돌릴 거면 `KRX_API` 만 있으면 됨(로그인 불필요).
- **스크리너**는 PER/PBR(가치 팩터)·구성종목 자동조회 위해 `KRX_ID`/`KRX_PW`, 재무 가점 위해 `DART_API` 필요.
- `.env` 는 평문 저장 → **git 커밋 금지**(`.gitignore` 등록됨).
- KRX OpenAPI 는 서비스별 **이용신청** 필요, 인증키 최대 12개월 후 만료. DART 는 키 1개로 전체 접근.

---

## 설치

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

## 사용 방법

저장소 루트에서:

```bash
python -m krxfree.briefing     # -> results/briefing_data.json (무로그인)
python -m krxfree.screener     # -> results/kospi200_screen.json (KRX 로그인 + DART)
```

### 보유 포트폴리오 (`portfolio.json`, 선택)

보유종목·평단은 코드가 아니라 루트의 `portfolio.json` 에서 읽는다(개인정보 분리, git 제외). 없으면 브리핑은 지수만 산출. 양식은 [`portfolio.json.example`](portfolio.json.example) 참고.

```json
{
  "holdings": [
    {"market": "KR", "name": "삼성전자", "code": "005930", "shares": 10, "avg": 70000},
    {"market": "US", "name": "엔비디아", "ticker": "NVDA", "shares": 1, "avg": 100},
    {"code": "000660"},
    {"ticker": "AAPL"}
  ]
}
```
- **최소 입력**: 국내는 `code`(6자리), 미국은 `ticker`(yfinance 심볼) **하나만** 있으면 된다(위 3·4번째). 나머지(`name`/`shares`/`avg`/`market`)는 생략 가능.
- `shares`+`avg`(평단) 있으면 평가손익 계산(KR `pnl_krw` / US `pnl`), 없으면 시세·지표만 표기.
- `name` 생략 시 코드/티커로 대체. `market` 생략 시 `ticker` 있으면 US, 없으면 KR 자동 판정.

### 자동화 (Windows 작업 스케줄러)

```bat
:: automation\register_krx_task.bat 더블클릭 → UAC 승인 (월~금 08:05 등록)
schtasks /query /tn KRX_Morning_Data /v /fo LIST  :: 확인
schtasks /delete /tn KRX_Morning_Data /f          :: 삭제
```
- `automation/register_krx_task.ps1` 이 배터리 무관 시작·절전 깨우기(`WakeToRun`)·놓친 실행 따라잡기(`StartWhenAvailable`)까지 설정해 등록(`.bat` 은 관리자 권한 자가승격 런처).
- `automation/run_morning.ps1` 이 루트의 venv 로 `python -m krxfree.briefing` → `krxfree.screener` 를 일괄 실행.
- 08:05 = KRX 가 당일 데이터를 오전 8시부터 제공 → 5분 여유. 절전이면 깨워 실행, 꺼져 있었으면 켜고 로그인 시 따라잡기(로그인 상태 필요). 노트북은 전원옵션의 *절전 해제 타이머 허용* 이 꺼져 있으면 등록 스크립트가 동의받아 켠다.

---

## 파일 구성

```
krxfree/                     패키지
├─ paths.py                  루트·결과·.env 경로
├─ loaders.py                portfolio.json / kospi200_members.json 로더
├─ briefing.py               모닝 브리핑 진입점 (python -m krxfree.briefing)
├─ screener.py               코스피200 스크리너 진입점 (python -m krxfree.screener)
└─ clients/
   ├─ naver.py               Naver OHLCV (무인증)
   ├─ openapi.py             KRX 공식 OpenAPI — 지수·전종목 시세 (인증키)
   ├─ login.py               KRX 로그인 — PER/PBR·지수구성종목 (로그인)
   └─ dart.py                OpenDART — 성장률/ROE/부채/업종 (인증키)
automation/                  run_morning.ps1 · register_krx_task.ps1 / .bat
docs/DESIGN.md               설계 원칙·판단요소·의사결정 기록
results/                     산출 JSON (자동 생성, 내용물 gitignore)
portfolio.json[.example]     보유종목 입력(.example=양식). 입력은 gitignore
.env[.example]               자격증명·인증키(.example=양식). .env 커밋 금지
requirements.txt             의존 패키지
corp_map.json / sector_map.json   DART 캐시 (자동 생성, gitignore)
```

**의존 패키지** (`requirements.txt`): `pandas` · `numpy` · `requests` · `python-dotenv` · `yfinance`(미국 시세, 미설치 시 해당 항목 생략). 그 외는 표준 라이브러리.

**호출량(1회)**: KRX OpenAPI 2~5콜 · KRX 로그인 1회(PER/PBR+구성종목) · Naver ~25콜 · DART ~25콜(캐시) · company.json ~25콜(업종, 캐시).

---

## AI 브리핑 활용법

`results/` 의 JSON 파일을 Claude(또는 다른 AI)에 첨부해 아침 브리핑을 받는 것이 주 사용 방식이다.

### 파일별 용도

| 파일 | 내용 | AI 활용 |
|------|------|---------|
| `briefing_data.json` | 보유종목 시세·손익·기술적 지표 + 지수 | 내 포트폴리오 현황 브리핑 |
| `kospi200_screen.json` | 코스피200 팩터 스코어 + 추천 종목 | 오늘 주목할 종목 분석 |

### 프롬프트 예시

**모닝 브리핑** (briefing_data.json 첨부 후):
```text
첨부한 JSON은 오늘 아침 내 포트폴리오 데이터야.
보유종목별 등락률·평가손익 요약하고,
RSI·이동평균 기준으로 주의가 필요한 종목 있으면 짚어줘.
```

**스크리너 분석** (kospi200_screen.json 첨부 후):
```text
첨부한 JSON은 오늘 코스피200 스크리닝 결과야.
상위 종목 중 팩터 균형이 좋은 것 위주로 설명해줘.
특히 가치(PER/PBR)와 모멘텀이 함께 좋은 종목 있으면 강조해줘.
```

**공시/뉴스/매크로 반영 분석** (kospi200_screen.json 첨부 후, Phase1~3 필드 활용):
```text
첨부한 JSON은 오늘 코스피200 스크리닝 결과야. 각 종목의 momentum_label, disclosure,
thesis_status, news_count_7d, 최상위 macro 섹션을 참고해서 다음을 알려줘.

1. momentum_label이 "원인 불명 변동성"이거나 "재료 미확인 상승"인 종목은 따로 모아서
   왜 그런지(뉴스 적음/실적 근거 없음) 짚어줘. 추격 매수 주의 종목으로 표시해줘.
2. disclosure에 hard_negative/soft_negative/dilution(특히 제3자배정·일반공모)이 있는
   종목은 경고로 따로 알려줘.
3. held=true 종목 중 thesis_status가 "주의"나 "재검토 필요"인 게 있으면
   투자 논리가 깨졌는지 설명해줘.
4. kodex200_holding 섹션(보유 중이면 존재)이 있으면 close/nav/fluc_rt/momentum_pct를
   macro 섹션(us10y, usdkrw, kospi, foreign_netflow_7d_won)과 같이 보고 지금 환경이
   KODEX200 같은 지수상품 보유에 우호적인지 비우호적인지 한 줄로 평가해줘
   (개별 공시·뉴스는 ETF엔 적용 안 됨, macro로만 판단).
```

**두 파일 동시 활용**:
```
briefing_data.json = 내 현재 포트폴리오
kospi200_screen.json = 오늘 스크리닝 추천 종목

내 보유종목이 추천 목록에 있는지 확인하고,
추천 종목 중 내가 안 들고 있는 것 중 주목할 만한 것 알려줘.
```

### 자동 브리핑 (Claude Cowork 반복 작업 예약)

매일 08:15, Claude Cowork의 **반복 작업 예약하기** 기능으로
`briefing_data.json` + `kospi200_screen.json` 을 자동 분석하도록 설정 가능.

- 08:05 스케줄러가 JSON 생성 완료
- 08:15 Claude Cowork 예약 브리핑 실행

> ⚠️ AI 분석은 참고용이며 매수·매도 지시가 아니다. 투자 판단·손익 책임은 사용자에게 있다.

---

## 더 읽기

- [docs/DESIGN.md](docs/DESIGN.md) — 데이터 원칙(사실 기반), 가치 판단요소(스크리너 방법론), 데이터 접근 방식 의사결정 기록, 한계/확장 여지
- [docs/API_LIMITS.md](docs/API_LIMITS.md) — 각 API 일일 한도 · 데이터 반영 시점 정리
