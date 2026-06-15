# pykrx-free — KRX 모닝 브리핑 & 코스피200 스크리너

`pykrx` 에 의존하지 않고, 자체 클라이언트로 KRX·Naver·OpenDART 데이터를 직접 호출해
**한국 주식 모닝 브리핑 데이터**와 **코스피200 추천 스크리너**를 JSON 으로 생성하는 파이프라인.

산출 JSON 은 AI(Claude 등)가 읽어 장 시작 전 브리핑을 작성하는 입력으로 쓴다.

> ⚠️ **면책**: 투자 자문이 아니다. 공개 데이터 기반 단순 스크리닝이며, 모든 투자 판단·손익 책임은 사용자에게 있다.

---

## 왜 만들었나

1. 장 시작 전 AI 로 브리핑을 받으려면 **전날 시세·재무 데이터**가 필요했다.
2. 한국 주식 데이터로 `pykrx` 를 쓰려 했으나, 일부 데이터(PER/PBR 등)는 **KRX 계정 로그인이 필수**였다.
3. 쓰다 보니 잦은 로그인으로 **KRX 계정이 잠겼다.**
4. 조사 결과 KRX 가 **로그인 없이 인증키(API key)** 로 접근 가능한 공식 OpenAPI 를 제공함을 확인.
5. **로그인 없이 API 키만으로** 모든 데이터를 받도록 직접 구현하기로 결정.
6. 거의 다 구현했으나, **PER/PBR 한 가지만 무로그인으로 획득 불가**(공식 OpenAPI 미제공, 무로그인 다운로드 경로는 2026-06 기준 차단됨)였고, DART 재무로 계산하는 근사값은 일부 종목에서 정확도가 떨어졌다.
7. 정확도를 위해 **PER/PBR 만 KRX 로그인 방식으로 원복**(일 1회 호출이라 계정 잠금 위험 낮음). 나머지는 전부 무로그인 API. **무로그인 전환 방법은 계속 찾는 중**이며, 코드는 양쪽(로그인 / DART 계산)을 모두 보유.

자세한 의사결정 기록은 아래 [데이터 접근 방식](#데이터-접근-방식-의사결정-기록) 참조.

---

## 구현 기능

### 1. 모닝 브리핑 — `krx_briefing_fetch.py`
관심/보유 종목 + 지수 + 해외종목을 모아 `briefing_data.json` 생성.

- **종목별**: 현재가·등락률, RSI(14), 이동평균(5/20/50/200), 피벗(S1/P/R1), 평단 대비 수익률·평가손익
- **지수**: KOSPI / KOSDAQ 종합지수 스냅샷 (KRX OpenAPI, 무로그인)
- **해외**: NVDA (yfinance, 무로그인)
- 관심 종목은 스크립트 상단 `HOLDINGS` 리스트로 지정 (`name`/`code`/`shares`/`avg`)

### 2. 코스피200 스크리너 — `krx_screener_api.py`
KOSPI 시총 상위 200 유니버스에서 다중 팩터로 점수화해 추천 → `kospi200_screen.json` 생성.

- **스코어**: 모멘텀 30 / 가치(PER·PBR) 25 / 유동성 25 / 사이즈 20
- **가점**: 기술적(이평 정배열·RSI 40~70·MA20 상회) + DART(영업익·매출 성장 / ROE≥8 / 고부채 감점)
- **2단계**: 1차 벌크 스코어 → 상위 ~25 후보만 OHLCV(Naver)·DART 정밀 보정

---

## 파일 구성

| 파일 | 역할 | 비고 |
|------|------|------|
| `krx_naver.py` | 자체 Naver OHLCV 클라이언트 | **무인증** |
| `krx_openapi.py` | KRX 공식 OpenAPI 클라 (지수·전종목 시세) | 인증키 `KRX_API` |
| `krx_login.py` | KRX 로그인 PER/PBR 클라 (공식값) | 로그인 `KRX_ID`/`KRX_PW`, 일 1회 |
| `krx_dart.py` | OpenDART 클라 (성장률/ROE/부채비율) | 인증키 `DART_API` |
| `krx_briefing_fetch.py` | **브리핑 생성** 진입점 → `briefing_data.json` | |
| `krx_screener_api.py` | **스크리너 생성** 진입점 → `kospi200_screen.json` | |
| `corp_map.json` | DART 종목코드→corp_code 캐시 | 자동 생성 (gitignore) |
| `.env` | 자격증명/인증키 | **git 제외, 커밋 금지** |
| `.env.example` | `.env` 양식 | |

**기능별 필요 파일**
- **브리핑만**: `krx_naver.py` + `krx_openapi.py` + `krx_briefing_fetch.py` (PER/PBR 불필요 → 무로그인으로 충분)
- **스크리너**: 위 + `krx_login.py` + `krx_dart.py` (`krx_screener_api.py` 가 모두 사용)

> 산출 JSON 은 스크립트 폴더의 **상위 디렉터리**에 기록된다(`krx_briefing_fetch.py:21` 의 `OUT_DIR`). 출력 위치를 바꾸려면 해당 상수를 수정.

---

## 인증 / 데이터 소스

| 데이터 | 소스 | 인증 |
|--------|------|------|
| 보유종목 OHLCV / 이평 / RSI | `krx_naver.py` (Naver 직접) | **무인증** |
| 지수(KOSPI/KOSDAQ), 전종목 일별 시세 | `krx_openapi.py` (KRX OpenAPI) | `KRX_API` 인증키 |
| PER / PBR / 배당수익률 | `krx_login.py` (KRX 공식값) | **KRX 로그인 1회** (`KRX_ID`/`KRX_PW`) |
| 매출·영업익 성장률 / ROE / 부채비율 | `krx_dart.py` (OpenDART) | `DART_API` 인증키 |
| NVDA (해외) | yfinance | 무인증 |

### `.env` (이 폴더에 생성)
```
KRX_ID=<KRX 로그인 ID>
KRX_PW=<KRX 로그인 PW>
KRX_API=<KRX OpenAPI 인증키>     # https://openapi.krx.co.kr
DART_API=<OpenDART 인증키>       # https://opendart.fss.or.kr
```

> **주의**: `.env` 는 비밀번호·키를 평문 저장한다. git 에 절대 커밋하지 말 것 (`.gitignore` 등록됨).
> KRX OpenAPI 는 서비스(엔드포인트)별 **이용신청** 필요(유가증권/지수 일별시세, 종목기본정보, ETF 등).
> DART 는 키 1개로 모든 API 접근(서비스별 신청 불필요).

---

## 설치 & 실행

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt

# 브리핑 생성 (무로그인)
python krx_briefing_fetch.py

# 스크리너 생성 (KRX 로그인 1회 + DART)
python krx_screener_api.py
```

---

## 스크리너 방법론

- **유니버스**: KOSPI 시총 상위 200 (코스피200 근사. KRX OpenAPI 에 정확한 구성종목 명단 없음)
- **스코어**: 모멘텀 30 / 가치(PER·PBR) 25 / 유동성 25 / 사이즈 20
- **가점**: 기술적(이평 정배열·RSI 40~70·MA20 상회) + DART(영업익 성장 / 매출 성장 / ROE≥8 / 고부채 감점)
- **2단계**: 1차 벌크 스코어 → 상위 ~25 후보만 OHLCV(Naver)·DART 호출로 정밀 보정

### 호출량 (1회 실행)
- KRX OpenAPI: 스냅샷 2~5콜 · KRX 로그인: 1회(PER/PBR) · Naver OHLCV: ~25콜 · DART: ~25콜(corp_map 캐시)

---

## 데이터 접근 방식 의사결정 기록 (2026-06)

### KRX 데이터 접근 경로 3가지
| 경로 | 정체 | PER/PBR | 인증(2026) |
|------|------|---------|-----------|
| ① 공식 OpenAPI (`openapi.krx`, `/svc/apis`) | 거래소 정식 개방. `krx_openapi.py` | ❌ 엔드포인트 없음 | 인증키 |
| ② 내부 AJAX (`getJsonData.cmd`) | 사이트 화면용 내부 API 스크래핑 = pykrx, `krx_login.py` | ✅ MDCSTAT03501 | **로그인 필요** |
| ③ OTP 다운로드 (`comm/fileDn`) | 사이트 다운로드 버튼 스크래핑 = 옛 블로그/quant_cookbook | ✅ | **로그인 필요** |

### 검증 결과
- **무로그인 OTP 다운로드(③)** 는 2026-06 현재 **로그인 차단**됨(테스트 3회 모두 실패: GET→403, GET+워밍업→LOGOUT, POST→403).
- **공식 OpenAPI(①)** 는 시세·매매정보·지수만 제공, **PER/PBR 없음.**
- 결론: **무로그인으로 KRX 공식 PER/PBR 획득 불가.** 선택지는 (L) 로그인 스크래핑 또는 (N) DART 재무로 직접 계산(근사).
- DART 근사 검증: 단순 사업구조는 KRX와 거의 일치(±0~7%), 지주사·소수지분·보험(TTM/연결 기준)은 ±10~22% 잔차.

#### DART 계산 PER/PBR vs KRX 공식값 실측 (2026-06-12, DART 2025 사업보고서·지배주주 기준)
| 종목 | PER(KRX) | PER(DART) | PERΔ | PBR(KRX) | PBR(DART) | PBRΔ |
|------|---------:|----------:|-----:|---------:|----------:|-----:|
| 기아 | 8.6 | 8.6 | 0.0% | 1.06 | 1.06 | 0.0% |
| SK스퀘어 | 20.4 | 20.3 | -0.5% | 6.48 | 6.48 | 0.0% |
| SK하이닉스 | 34.6 | 35.7 | +3.2% | 12.52 | 12.71 | +1.5% |
| NAVER | 19.0 | 19.8 | +4.2% | 1.34 | 1.40 | +4.5% |
| KB금융 | 10.5 | 9.8 | -6.7% | 0.98 | 0.97 | -1.0% |
| 신한지주 | 10.2 | 9.5 | -6.9% | 0.82 | 0.82 | 0.0% |
| 삼성생명 | 30.1 | 33.5 | +11.3% | 1.10 | 1.23 | +11.8% |
| 삼성전자 | 48.8 | 42.6 | -12.7% | 5.04 | 4.44 | -11.9% |
| 현대차 | 16.8 | 13.2 | -21.4% | 1.38 | 1.08 | -21.7% |

→ 9종목 중 6개 ±7% 이내, 3개(삼성전자·삼성생명·현대차) ±10~22% 잔차. 가치 팩터는 상대순위 정규화라 스크리너 랭킹 영향은 미미.

### 트레이드오프와 결정
| 안 | PER/PBR | 로그인 | pykrx | 정확도 |
|----|---------|--------|-------|--------|
| **N. 무로그인/API only** | DART 계산 | 0 | 0 | 근사 (일부 ±10~20%) |
| **L. 자체 KRX 로그인** (`krx_login.py`) | KRX 공식값 | 1회/실행 | 0 | 정확 |

**→ 결정: L 선택.** 정확도를 위해 PER/PBR 만 로그인 방식 채택. 로그인은 일 1회뿐이라 계정 잠금 위험이 낮다.
`pykrx` 의존은 제거하고, 자체 클라이언트(`krx_login.py`)로 `getJsonData.cmd` 를 직접 호출한다.
**무로그인 전환을 원하면 언제든 N(DART 계산)으로 스위치 가능**(코드는 양쪽 다 보유).

---

## 한계 / 확장 여지

- **코스피200 정확 명단** 미제공 → 시총 상위 200 근사 사용
- **업종 분류** 없음(KRX OpenAPI 미제공). 보험사 등 고부채 업종은 부채 감점이 다소 불리
- **수정주가**: Naver 기간조회는 수정주가 적용 → 과거 분할 종목은 KRX 원시값과 과거 구간 상이 가능(현재가는 동일)
- **무로그인 완전 전환**: DART 로 PER/PBR 대체 시 KRX 로그인 제거 가능하나, 종목당 재무 호출+근사 계산이라 정확도 트레이드오프 존재. 더 나은 무로그인 경로를 계속 탐색 중.
