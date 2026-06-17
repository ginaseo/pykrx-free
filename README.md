# pykrx-free — KRX 모닝 브리핑 & 코스피200 스크리너

`pykrx` 에 의존하지 않고, 자체 클라이언트로 KRX·Naver·OpenDART 데이터를 직접 호출해
**한국 주식 모닝 브리핑 데이터**와 **코스피200 추천 스크리너**를 JSON 으로 생성하는 파이프라인.
산출 JSON 은 AI(Claude 등)가 읽어 장 시작 전 브리핑을 작성하는 입력으로 쓴다.

> ⚠️ **면책**: 투자 자문이 아니다. 공개 데이터 기반 단순 스크리닝이며, 모든 투자 판단·손익 책임은 사용자에게 있다.
>
> 설계 원칙·판단 기준·의사결정 근거는 [DESIGN.md](DESIGN.md) 참조. 출력 수치는 **실측값(또는 보편식 파생)만** 쓰고 추측·근사는 넣지 않는다.

---

## 주요 기능

1. **모닝 브리핑** (`krx_briefing_fetch.py`) → `results/briefing_data.json`
   - 보유종목 현재가·등락률·RSI·이동평균·피벗·평가손익 + KOSPI/KOSDAQ 지수 + 해외(미국) 종목
   - 보유종목은 `portfolio.json` 에서 읽음(무로그인: Naver·KRX OpenAPI·yfinance)
2. **코스피200 스크리너** (`krx_screener_api.py`) → `results/kospi200_screen.json`
   - 다중 팩터(모멘텀·가치·유동성·사이즈) 점수화 + 기술적·재무 가점으로 추천
3. **무인 자동화** (`run_morning.ps1` + `register_krx_task.bat`)
   - Windows 작업 스케줄러로 매 영업일 08:05 자동 실행

---

## 필요 정보 (`.env`)

이 폴더에 `.env` 생성. 양식은 [`.env.example`](.env.example) 참고.

```
KRX_ID=<KRX 로그인 ID>            # 스크리너 PER/PBR 용 (브리핑엔 불필요)
KRX_PW=<KRX 로그인 PW>
KRX_API=<KRX OpenAPI 인증키>     # https://openapi.krx.co.kr
DART_API=<OpenDART 인증키>       # https://opendart.fss.or.kr
```

- **브리핑만** 돌릴 거면 `KRX_API` 만 있으면 됨(로그인 불필요).
- **스크리너**는 PER/PBR(가치 팩터) 위해 `KRX_ID`/`KRX_PW`, 재무 가점 위해 `DART_API` 필요.
- `.env` 는 평문 비밀번호·키 저장 → **git 커밋 금지**(`.gitignore` 등록됨).
- KRX OpenAPI 는 서비스별 **이용신청** 필요(일별시세·종목기본정보 등), 인증키 **최대 12개월** 후 만료(만료 30일 전 갱신). DART 는 키 1개로 전체 접근.

---

## 설치

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install pandas numpy requests python-dotenv yfinance
```

| 패키지 | 용도 |
|--------|------|
| `pandas` / `numpy` | 시세·재무 처리, 팩터 계산 |
| `requests` | KRX / Naver / DART HTTP 호출 |
| `python-dotenv` | `.env` 로드 |
| `yfinance` | 해외 종목 시세(브리핑 전용, 미설치 시 해당 항목 생략) |

> 그 외는 파이썬 표준 라이브러리라 추가 설치 불필요.

---

## 사용 방법

```bash
# 브리핑 생성 (무로그인)
python krx_briefing_fetch.py        # -> results/briefing_data.json

# 스크리너 생성 (KRX 로그인 1회 + DART)
python krx_screener_api.py          # -> results/kospi200_screen.json
```

### 입력 파일 (선택, git 제외)

**`portfolio.json`** — 보유종목·평단(브리핑용). 없으면 브리핑은 지수만 산출. 국내·해외를 한 `holdings` 리스트에 담고 `market` 으로 구분. 양식은 [`portfolio.json.example`](portfolio.json.example) 참고(값은 더미).
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
- **최소 입력**: 국내는 `code`(6자리), 해외는 `ticker`(yfinance 심볼) **하나만** 있으면 된다 — 위 3·4번째 항목처럼. 나머지(`name`/`shares`/`avg`/`market`)는 생략 가능.
- `shares`+`avg`(평단) 있으면 평가손익 계산(KR `pnl_krw` / US `pnl`), 없으면 **시세·지표만** 표기.
- `name` 생략 시 코드/티커로 대체. `market` 생략 시 `ticker` 있으면 US, 없으면 KR 로 자동 판정.

**`kospi200_members.json`** — 코스피200 실제 구성종목(스크리너용, **선택**). KRX 로그인이 되면 구성종목을 **자동 조회**(MDCSTAT00601)하므로 보통 불필요하다. 로그인을 안 쓰거나 자동 조회 실패 시의 **수동 폴백**으로만 쓴다(이마저 없으면 시총 상위 200 근사). 코드 배열 / 객체 배열 / `{코드:이름}` 중 아무 형태나 가능(각 항목에서 6자리 코드만 추출):
```json
["005930", "000660", "..."]
```
> 유니버스 우선순위: **KRX 자동(로그인)** → 수동 `kospi200_members.json` → 시총 상위 200 근사.

### 자동화 (Windows 작업 스케줄러)

```bat
:: register_krx_task.bat 더블클릭 → UAC 승인 (월~금 08:05 등록)
schtasks /query /tn KRX_Morning_Data /v /fo LIST  :: 확인
schtasks /delete /tn KRX_Morning_Data /f          :: 삭제
```
- `register_krx_task.ps1` 이 배터리 무관 시작·절전 깨우기(`WakeToRun`)·놓친 실행 따라잡기(`StartWhenAvailable`)까지 설정해 등록(`.bat` 은 관리자 권한 자가승격 런처).
- 08:05 = KRX 가 당일 데이터를 오전 8시부터 제공 → 5분 여유.
- 절전이면 깨워 실행, 꺼져 있었으면 켜고 로그인 시 따라잡기 실행(로그인 상태 필요). 노트북은 전원옵션의 *절전 해제 타이머 허용* 이 꺼져 있으면 등록 스크립트가 동의받아 켠다.

---

## 파일 구성

| 파일 | 역할 | 비고 |
|------|------|------|
| `krx_naver.py` | Naver OHLCV 클라 | 무인증 |
| `krx_openapi.py` | KRX 공식 OpenAPI 클라 (지수·전종목 시세) | 인증키 `KRX_API` |
| `krx_login.py` | KRX 로그인 PER/PBR 클라 (공식값) | 로그인, 일 1회 |
| `krx_dart.py` | OpenDART 클라 (성장률/ROE/부채/업종) | 인증키 `DART_API` |
| `krx_briefing_fetch.py` | 브리핑 진입점 → `results/briefing_data.json` | |
| `krx_screener_api.py` | 스크리너 진입점 → `results/kospi200_screen.json` | |
| `run_morning.ps1` | 작업 스케줄러 진입점 (브리핑+스크리너) | |
| `register_krx_task.ps1` / `.bat` | 작업 등록 본체 / 자가승격 런처 | |
| `results/` | 산출 JSON 출력 폴더 | 자동 생성, 내용물 gitignore |
| `corp_map.json` / `sector_map.json` | DART corp_code / 업종 캐시 | 자동 생성, gitignore |
| `portfolio.json` / `kospi200_members.json` | 사용자 입력(위 참조) | gitignore |
| `.env` / `.env.example` | 자격증명·인증키 / 양식 | `.env` 커밋 금지 |

**호출량(1회)**: KRX OpenAPI 2~5콜 · KRX 로그인 1회 · Naver ~25콜 · DART ~25콜(캐시) · company.json ~25콜(업종, 캐시).

---

## 더 읽기

- [DESIGN.md](DESIGN.md) — 데이터 원칙(사실 기반), 가치 판단요소(스크리너 방법론), 데이터 접근 방식 의사결정 기록, 한계/확장 여지
