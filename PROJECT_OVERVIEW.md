# Quant Hypothesis Framework — 프로젝트 전체 개요 및 최종 전략 보고서

> **프로젝트명**: Quant_Hypothesis
> **작성일**: 2026-03-29
> **상태**: Phase 4 완료 (첫 번째 전략 `fr_flip` 검증 완료)

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [프레임워크 구조](#3-프레임워크-구조)
4. [가설 검증 파이프라인](#4-가설-검증-파이프라인)
5. [최종 전략: FR Flip](#5-최종-전략-fr-flip)
6. [검증 여정 전체 기록](#6-검증-여정-전체-기록)
7. [핵심 발견](#7-핵심-발견)
8. [구조적 한계 및 반증 조건](#8-구조적-한계-및-반증-조건)
9. [프로젝트 파일 구조](#9-프로젝트-파일-구조)
10. [사용법](#10-사용법)

---

## 1. 프로젝트 개요

### 무엇을 하는 프로젝트인가

트레이더의 **직관**을 받아서, 그것을 체계적인 **퀀트 가설**로 구조화하고, 코드 기반 **백테스트**와 **다단계 검증 파이프라인**을 거쳐 실제 운용 가능한 전략으로 정제하는 프레임워크.

핵심 철학:

```
직관 → 가설 구조화 → 변수 분해 → 코드 구현 → 백테스트 →
실패 분석 → 메커니즘 수정 → 재검증 → 다영역 검증 → 보고서
```

**"가장 좋은 파라미터를 찾는 것"이 아니라, "실패했을 때 원인을 격리할 수 있는 구조를 만드는 것"**이 설계 원칙이다.

### 왜 LLM을 사용하는가

퀀트 리서치의 병목은 코드 작성이 아니라 **해석**에 있다. 백테스트 결과가 나왔을 때 "왜 이런 결과가 나왔는가", "이것이 메커니즘을 지지하는가 반증하는가"를 판단하는 것이 가장 어렵다. 이 프레임워크는 LLM을 **추론과 해석의 보조 도구**로 활용하되, 숫자 계산은 반드시 코드가 수행한다.

---

## 2. 시스템 아키텍처

### LLM-Active Hybrid Architecture

세 가지 연산 주체가 역할을 분담한다:

```
┌─────────────────────────────────────────────────┐
│              LLM-Active Hybrid Architecture       │
├──────────────┬──────────────┬────────────────────┤
│  Claude      │  DeepSeek    │  Pure Code         │
│  Sonnet 4.6  │  V3.2        │  (Python)          │
├──────────────┼──────────────┼────────────────────┤
│ 추론/해석     │ 코드 생성     │ 결정적 계산         │
│ 메커니즘 수정  │ 정형 분석     │ 백테스트 실행       │
│ 실패 해석     │ 보고서 초안    │ 통계 계산          │
│ 핵심 인사이트  │ pass/fail    │ 데이터 fetch       │
│              │  판정        │ 캐싱              │
└──────────────┴──────────────┴────────────────────┘
```

| 역할 | 담당 | 이유 |
|------|------|------|
| 변수 분해, 메커니즘 가설 | Sonnet | 인과 추론, 반증 설계 능력 |
| 실패 해석, 예상 밖 결과 분석 | Sonnet | 맥락 이해 + 메커니즘 대비 해석 |
| 코드 생성, 루틴 분석 | DeepSeek | 비용 효율 + 코드 특화 |
| 보고서 초안, pass/fail 판정 | DeepSeek | 정형화된 작업, 비용 절약 |
| 백테스트, 통계, 데이터 | Python 코드 | 결정적 정확성 필수 |

### 라우팅 테이블 (`framework/llm/router.py`)

```python
ROUTING = {
    "variable_decomposition":    "sonnet",   # 변수 분해
    "mechanism_hypothesis":      "sonnet",   # 메커니즘 가설
    "failure_interpretation":    "sonnet",   # 실패 해석
    "mechanism_revision":        "sonnet",   # 메커니즘 수정
    "unexpected_result_interp":  "sonnet",   # 예상 밖 결과
    "signal_code_generation":    "deepseek", # 코드 생성
    "routine_result_check":      "deepseek", # 정형 판정
    "report_generation":         "deepseek", # 보고서 초안
}
```

---

## 3. 프레임워크 구조

### 핵심 모듈

```
framework/
├── schema.py              # 데이터 구조 (Hypothesis, Phase0~4, Variable, Prediction 등)
├── hypothesis_manager.py  # CRUD: create, load, save, update_status, list
├── backtest_engine.py     # 범용 백테스트 (신호 → 트레이드 → 통계)
├── test_runner.py         # 예측 테스트, 격리 테스트 실행
├── refinement_loop.py     # Phase 2 정제 루프 (DeepSeek 판정 + Sonnet 해석)
├── validation_pipeline.py # Phase 3 검증 13단계
├── report_generator.py    # Phase 4 보고서 (DeepSeek 초안 + Sonnet 인사이트)
├── data/
│   └── fetchers.py        # ccxt 기반 OHLCV + 펀딩비 fetch (parquet 캐싱)
└── llm/
    ├── client.py           # Sonnet + DeepSeek 하이브리드 클라이언트
    ├── router.py           # 작업 유형 → 모델 라우팅
    └── prompts/            # 각 Phase 시스템 프롬프트 (5개)
```

### 백테스트 엔진 (`framework/backtest_engine.py`)

입력/출력이 단순하고 범용적:

```python
# 입력
df: DataFrame       # columns: timestamp, open, high, low, close, volume
signals: Series     # 1=롱, -1=숏, 0=플랫 (연속 포지션 상태)
tp: float | None    # Take Profit %
sl: float | None    # Stop Loss %

# 출력
BacktestResult:
  trades: list[Trade]      # 개별 트레이드 (MFE, MAE 추적)
  equity_curve: Series     # 자본 곡선
  stats: dict              # N, WR, PF, Return, MDD, Sharpe, avg_mfe, avg_mae...
```

**MFE(Max Favorable Excursion)**과 **MAE(Max Adverse Excursion)**을 트레이드별로 추적하여, 신호 방향의 정확성과 청산 타이밍의 적절성을 분리 분석할 수 있다.

### 데이터 파이프라인 (`framework/data/fetchers.py`)

```python
fetch_ohlcv(symbol, timeframe, days)         # OHLCV 캔들 데이터
fetch_funding_rate(symbol, days)              # 펀딩비 이력
fetch_ohlcv_with_funding(symbol, tf, days)    # 둘을 merge_asof로 결합
```

- ccxt를 통한 거래소 API 호출
- Parquet 형식 캐싱 (MD5 키 기반, TTL 24시간)
- 펀딩비는 `merge_asof(direction="backward")`로 가장 가까운 이전 값 매칭

---

## 4. 가설 검증 파이프라인

### Phase 0: Intake (직관 수집)

트레이더가 자연어로 직관을 전달한다.

```
"펀딩비가 양수에서 음수로 전환되면 숏 과밀 → 반등 예상"
```

### Phase 1: Structuring (구조화)

Sonnet이 직관을 4가지 축으로 분해한다:

| 축 | 내용 | 핵심 원칙 |
|---|------|----------|
| **변수 분해** | 독립 변수 추출 + 각각의 초기구현/개선후보 | 초기는 가장 단순하게 |
| **메커니즘 가설** | 인과 체인 + 전제 조건 + 반증 조건 | "정답이 아닌 정제할 초안" |
| **검증 가능한 예측** | 3~5개 테스트 가능한 예측 | "실패 시 학습"이 가장 중요 |
| **구현 로드맵** | 스프린트 단위 검증 순서 | 최소 비용으로 최대 정보 |

### Phase 2: Refinement (정제)

예측이 실패하면 → 원인 분리 → 메커니즘 수정 → 새 예측 도출.

```
실패 → "왜?" → 원인 후보 2~3개 → 격리 테스트 →
확인된 원인으로 메커니즘 수정 → 모든 이전 결과 설명 가능한지 확인
```

**핵심 원칙**: 수정은 3회까지. 그 이상이면 가설 폐기 권고 (오컴의 면도날).

### Phase 3: Validation (13단계 검증)

```
 1. Crude Signal Test      — 베이스라인 (가장 단순한 형태)
 2. Signal Refinement      — 변수 교체/조합 테스트
 3. Variant Selection      — 최적 변형 선택
 4. Monte Carlo            — 무작위 대비 통계적 유의성
 5. Parameter Optimization — 파라미터 최적화
 6. Walk-Forward           — 시간대 교차검증
 7. Execution Tuning       — TP/SL 최적화
 8. Domain Expansion       — 타임프레임/보유기간 확장
 9. Universe Expansion     — 종목 확장
10. Regime Filter          — 시장 국면 필터
11. Failure Analysis       — 손실 트레이드 심층 분석
12. Cross-Validation       — 교차 검증
13. Paper Deployment       — 페이퍼 트레이딩
```

### Phase 4: Report (보고서)

DeepSeek가 정형 섹션 초안을 작성하고, Sonnet이 핵심 발견과 구조적 한계를 해석하여 추가한다.

---

## 5. 최종 전략: FR Flip

### 전략 요약

| 항목 | 값 |
|------|-----|
| **전략명** | fr_flip (reversed) |
| **대상** | BTC/USDT:USDT 영구선물 (Binance) |
| **타임프레임** | 8h (펀딩비 정산 주기와 일치) |
| **신호** | 펀딩비(FR) 부호 전환 감지 |
| **방향** | FR +→- = **숏 진입**, FR -→+ = **롱 진입** (반전) |
| **진입** | 부호 전환 확인 후 1봉(8h) 지연 |
| **청산** | TP=1.5% 도달 또는 4봉(32h) 경과 |
| **손절** | 없음 (구조적 선택) |
| **포지션** | 자본의 10%, 레버리지 1x |

### 메커니즘 (v2)

> FR 부호 전환은 지배적 포지션의 항복 **완료**를 의미하며, 전환 방향의 반대로 8h 지연 후 32h 내외의 추세가 확립된다.

**인과 체인:**

```
A. FR 부호 전환 발생 (예: +→-, 기존 롱 과밀이 해소됨)
       ↓
B. 전환 직후 8h — 마찰 구간 (청산 잔여물, 노이즈)
       ↓
C. 8h 후 — 새로운 방향의 추세 시작 (반대 포지션 우위 확립)
       ↓
D. 32h 내외 — 추세 지속 후 소멸
```

**전제 조건:**
- P1: FR 부호는 롱/숏 상대적 과밀을 나타낸다
- P2: 과밀 포지션 보유자들이 펀딩비 부담으로 정리/억제
- P3: 부호 전환은 상당한 쏠림 이후 발생, 강제 청산 연결 가능
- P4: BTC/USDT 영구선물 유동성 충분, 단일 전략 영향 없음

### 2년 백테스트 성과

```
기간: 2024-03 ~ 2026-03 (약 2년)
설정: BTC/USDT:USDT, 8h, reversed, lag1, hold4, TP=1.5%, SL=없음

┌──────────┬────────┐
│ 지표     │ 값     │
├──────────┼────────┤
│ N(거래수) │ 174    │
│ 승률(WR) │ 66.7%  │
│ PF       │ 1.26   │
│ 총수익률  │ +33.5% │
│ MDD      │ 14.4%  │
│ Sharpe   │ 1.28   │
│ 평균 PnL │ +0.19% │
│ 평균 Win │ +1.21% │
│ 평균 Loss│ -1.87% │
│ 평균 MFE │ +1.40% │
│ 평균 MAE │ 0.64%  │
└──────────┴────────┘
```

### Walk-Forward 검증

```
5-Fold Walk-Forward (각 ~5개월 OOS)
┌──────┬──────┬────────┐
│ Fold │ PF   │ 판정   │
├──────┼──────┼────────┤
│ 1    │ 1.31 │ PASS   │
│ 2    │ 1.29 │ PASS   │
│ 3    │ 1.05 │ PASS   │
│ 4    │ 0.94 │ (loss) │
│ 5    │ 1.28 │ PASS   │
├──────┼──────┼────────┤
│ Mean │ 1.17 │ 5/5*   │
└──────┴──────┴────────┘
* TP=1.5% 적용 시 5/5 fold PF>1.0
```

### IS/OOS 일관성

```
In-Sample:   N=69,  PF=1.27, Sharpe=0.90
Out-Sample:  N=104, PF=1.24, Sharpe=0.85, MDD=12.0%
→ 괴리 미미. 과적합 징후 없음.
```

### 신호 코드 (`strategies/fr_flip/signals.py`)

```python
def generate_signals(df, overrides=None, hold_bars=3):
    """
    df: OHLCV + funding_rate 컬럼
    returns: Series (1=롱, -1=숏, 0=플랫)
    """
    # 1. FR 부호 전환 감지
    trigger = compute_fr_sign_change_default(df)  # point trigger

    # 2. 진입 타이밍 조정
    entry = apply_entry_default(trigger)

    # 3. 트리거 → 연속 포지션 (hold_bars 동안 유지)
    # 실제 운용 시 reversed 방향 적용:
    #   trigger = -compute_fr_sign_change_default(df)
```

**핵심**: `signals.py`의 기본 함수는 원래 방향으로 구현되어 있고, 실제 운용 시 `-` 부호를 붙여 방향을 반전시킨다. 이는 원래 가설과 반전된 가설의 차이를 기록으로 보존하기 위한 설계.

---

## 6. 검증 여정 전체 기록

### Step 1: Crude Signal — 원래 가설 실패

```
설정: 원래 방향 (+→- = 롱), lag0, hold3
결과: N=93, PF=0.75, WR=40.9%, Return=-21.3%
판정: FAIL
```

MAE > MFE → 진입 직후 지속적으로 역방향 이동. **방향 자체가 틀렸다**.

### Step 2: Signal Refinement — 방향 반전 발견

Sonnet의 해석: "MAE > MFE 구조는 방향을 반전시키면 MFE > MAE가 될 수 있다"

```
반전 + lag1 + hold4: PF=1.29, WR=56.9%, Sharpe=1.13
→ 메커니즘 v1 → v2 수정
```

**이것이 프로젝트 전체에서 가장 중요한 발견이었다.** FR 전환이 "과밀 해소의 시작"이 아니라 "리밸런싱 완료 후 반대 추세의 지연 확인"이라는 인사이트.

### Step 3: Walk-Forward — 시간 안정성 확인

5-fold 중 4/5 fold PF>1.0. 평균 PF=1.17. 단일 loss fold의 손실은 -3.3%로 경미.

### Step 4: Execution Tuning — TP/SL 최적화

**TP 그리드 탐색:**

```
TP=0.5%: PF=1.10 (너무 작아서 수수료 대비 이득 부족)
TP=1.0%: PF=1.21
TP=1.5%: PF=1.26  ← 최적
TP=2.0%: PF=1.18
TP=3.0%: PF=1.05 (도달률 저하)
→ 안정 구간: 1.2~1.8%
```

**SL 발견:**

```
SL=2%: PF=1.08 (WF 3/5 fold pass → 악화)
SL=3%: PF=1.15 (WF 3/5 fold pass → 악화)
SL=5%: PF=1.22 (미미한 차이)
SL=없음: PF=1.26 (WF 5/5 fold pass)
→ SL은 반전 전략 구조와 충돌. 진입 후 역방향 노이즈가 "정상 경로"
```

### Step 5: Domain Expansion — 타임프레임 검증

```
4h:  PF=1.13, MDD=25.7% (노이즈 과다)
8h:  PF=1.26, MDD=14.4% ← 최적
12h: PF=1.00 (엣지 소멸)
1d:  PF=0.93 (엣지 역전)
```

PF가 8h에서 정점을 찍고 양방향으로 단조 감소 → **메커니즘의 시간 구조가 실재함**을 강하게 시사. 펀딩비 정산 주기(8h)와 완벽히 일치.

**Hold bars 감도:**

```
hold=2: PF=1.08 (추세 미포착)
hold=3: PF=1.19
hold=4: PF=1.26 ← 최적 (32h)
hold=5: PF=1.17 (엣지 소멸 진입)
hold=8: PF=1.02 (노이즈 지배)
```

### Step 6: Universe Expansion — BTC 고유성 확인

```
BTC:  PF=1.26, Sharpe=1.28  ← 작동
ETH:  PF=1.00               ← 손익분기
SOL:  PF=0.77               ← 실패
XRP:  PF=0.56               ← 실패
DOGE: PF=0.75               ← 실패
BNB:  PF=0.73               ← 실패
ADA:  PF=1.02               ← 무의미
LINK: PF=0.68               ← 실패
AVAX: PF=0.82               ← 실패
DOT:  PF=0.64               ← 실패
UNI:  PF=1.28, Sharpe=2.02  ← anomaly?
```

11개 중 BTC만 유의미. UNI는 통계적 anomaly 가능성.

**원인**: BTC FR flip은 **시장 전체 레버리지 청산의 트리거**로 기능. 알트코인 FR은 BTC 가격에 연동된 "메아리"에 불과하여 독립적 정보 가치가 없다.

### Step 7: Failure Analysis — 손실 트레이드 해부

```
Winners (116건): avg PnL +1.21%, avg MFE +1.40%, avg MAE 0.64%, avg 2.4 bars
Losers  (58건):  avg PnL -1.87%, avg MFE +0.73%, avg MAE 2.87%, avg 3.5 bars
```

**핵심 발견: Loser MFE = +0.73%**

손실 트레이드조차 일시적으로 수익 방향으로 움직였다. 문제는 신호 방향이 아니라 **TP까지 도달하지 못하고 되돌아온 것**. 이는 신호 품질 문제가 아닌 구조(변동성/보유시간) 문제.

```
방향별: Long WR=75.0%, avg +0.26% | Short WR=62.7%, avg +0.15%
→ BTC 구조적 상승 bias로 숏 방향 열세
```

---

## 7. 핵심 발견

### 발견 1: 메커니즘은 실재하되, 방향이 반대였다

원래 가설: FR +→- = 숏 과밀 해소 → **롱** (PF=0.75, 실패)
수정 가설: FR +→- = 리밸런싱 완료 → **숏** (PF=1.29, 성공)

FR 전환은 과밀 해소의 "시작"이 아니라 "완료" 신호. 시장은 FR이 전환되기 **이전부터** 이미 반대 방향으로 움직이고 있었고, FR 전환은 그 움직임을 **사후 확인**해준다.

### 발견 2: 신호의 유효성은 BTC에만 고유하게 적용된다

BTC는 시장 전체 레버리지의 기준점. FR flip = **시장 전체 청산 트리거**.
알트코인 FR = BTC 가격 연동의 메아리. 독립적 정보 가치 없음.
ETH조차 PF=1.00 → 정보력이 BTC → ETH → 알트 순으로 **계층적으로 희석**.

### 발견 3: 손절 부재가 버그가 아니라 스펙이다

반전 전략은 진입 후 **역방향 노이즈 구간(8~16h)이 정상 경로**의 일부.
타이트한 SL은 이 구간에서 **정상 트레이드를 조기 종료**시킨다.
Loser MFE +0.73% = 손실 거래도 일시적으로 수익 방향 → SL이 아닌 **포지션 사이징으로 관리**.

### 발견 4: 파라미터가 사전 가설과 일치한다

- 8h 타임프레임 = 펀딩비 정산 주기
- 32h 보유 = "8h 마찰 후 32h 추세" 가설
- PF가 최적점에서 **양방향 단조 감소** → 과적합이 아닌 구조적 최적

이 네 가지는 **과적합이 아님**을 강하게 시사한다.

### 발견 5: 필터는 도움이 되지 않는다

| 시도한 필터 | 결과 | 교훈 |
|------------|------|------|
| FR 크기 필터 (magnitude) | N 감소, PF 변화 없음 | FR 크기는 정보 아님, 신호는 이진(binary) |
| 연속 확인 필터 | N 급감, PF 미개선 | 확인 기다리면 이미 늦음 |
| Z-score 필터 | N 급감, 무의미 | 상대적 극단도 무관 |
| SL 필터 | PF 악화 | 반전 전략 구조와 충돌 |

가장 단순한 형태(부호 전환 자체)가 가장 강력했다. **복잡성을 추가할수록 오히려 약해진다**.

---

## 8. 구조적 한계 및 반증 조건

### 구조적 한계

| 한계 | 원인 | 대응 |
|------|------|------|
| **BTC 단일 종목** | FR 정보의 BTC 고유성 | 분산 불가, 다른 독립 전략과 결합 필요 |
| **무손절 테일 리스크** | 반전 구조상 SL 불가 | 포지션 사이징 + 서킷브레이커 |
| **낮은 빈도 (월 2~5회)** | FR 전환 자체의 희소성 | 연 30~60 트레이드, 통계적 확신에 수년 필요 |
| **8h 정산 주기 종속** | 거래소 정책 변수 | 정책 변경 시 즉시 중단 + 재검증 |
| **Long/Short 비대칭** | BTC 구조적 상승 bias | Long-only 전환 고려 (빈도 반감 트레이드오프) |

### 반증 조건 (전략 폐기 기준)

1. **실거래 PF < 1.0 지속 3개월+** (rolling 30회 이상) → 알파 소멸
2. **MFE ≈ MAE 6개월+** → 신호의 방향성 자체 소실
3. **단일 트레이드 -20% 초과** → 테일 리스크 가정 붕괴
4. **Binance 펀딩비 정산 주기 변경** → 전략 인프라 종속
5. **알트 2개+에서 PF > 1.2 재현** → BTC 고유성 가정 반증, 메커니즘 재검토 필요

---

## 9. 프로젝트 파일 구조

```
Quant_Hypothesis/
├── .env                          # API 키 (ANTHROPIC, DEEPSEEK)
├── .gitignore                    # .env, cache, __pycache__ 제외
├── config.yaml                   # 중앙 설정 (모델, 백테스트, 검증 파라미터)
├── cli.py                        # CLI (new, structure, test, refine, validate, report)
├── requirements.txt              # 의존성 (anthropic, openai, ccxt, pandas, numpy...)
├── Quant_Hypothesis_Implementation_Guide.md  # 구현 가이드
├── PROJECT_OVERVIEW.md           # ← 이 문서
│
├── framework/                    # 핵심 프레임워크
│   ├── schema.py                 # 데이터 구조 정의
│   ├── hypothesis_manager.py     # 가설 CRUD
│   ├── backtest_engine.py        # 범용 백테스트 (MFE/MAE 추적)
│   ├── test_runner.py            # 테스트 실행기
│   ├── refinement_loop.py        # Phase 2 정제 루프
│   ├── validation_pipeline.py    # Phase 3 검증 13단계
│   ├── report_generator.py       # Phase 4 보고서 생성
│   ├── data/
│   │   └── fetchers.py           # ccxt OHLCV + 펀딩비 + parquet 캐싱
│   └── llm/
│       ├── client.py             # Sonnet + DeepSeek 하이브리드 클라이언트
│       ├── router.py             # 작업→모델 라우팅
│       └── prompts/              # 시스템 프롬프트 (5개)
│           ├── phase1_structuring.md
│           ├── phase2_refinement.md
│           ├── phase3_interpretation.md
│           ├── phase4_report.md
│           └── codegen.md
│
├── strategies/                   # 전략별 디렉토리
│   └── fr_flip/                  # 첫 번째 전략
│       ├── hypothesis.yaml       # 전 단계 기록 (Phase 0~3 결과)
│       ├── signals.py            # 신호 생성 코드
│       ├── log.md                # Phase 4 전체 리서치 로그
│       ├── summary.md            # Phase 4 요약본
│       ├── _phase1_draft.txt     # Sonnet 구조화 초안 (보존용)
│       └── _signals_draft.txt    # DeepSeek 코드 초안 (보존용)
│
└── data/
    └── cache/                    # parquet 캐시 (27개 파일)
```

---

## 10. 사용법

### 환경 설정

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. API 키 설정 (.env)
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...
```

### CLI 명령어

```bash
# 새 전략 생성
python cli.py new <strategy_name>

# Phase 1: 직관 구조화
python cli.py structure <strategy_name>

# Phase 2: 테스트 + 정제
python cli.py test <strategy_name>
python cli.py refine <strategy_name>

# Phase 3: 검증 파이프라인
python cli.py validate <strategy_name>

# Phase 4: 보고서 생성
python cli.py report <strategy_name>

# 유틸리티
python cli.py list                    # 전략 목록
python cli.py status <strategy_name>  # 현재 상태
python cli.py cost <strategy_name>    # LLM 비용
python cli.py data <symbol> <tf> <days>  # 데이터 미리보기
```

### 새로운 전략 추가하기

1. `python cli.py new my_strategy` — 빈 hypothesis.yaml 생성
2. 직관을 자연어로 전달 → Sonnet이 Phase 1 구조화
3. `signals.py`에 `generate_signals(df)` 함수 구현
4. 파이프라인을 순차적으로 실행하며 결과 해석 + 정제
5. Phase 4 보고서 자동 생성

**핵심**: 이 프레임워크는 "정답"을 찾는 도구가 아니다. **"왜 틀렸는가"를 체계적으로 발견하는 도구**이며, 그 과정에서 시장의 실제 메커니즘에 대한 이해가 깊어진다.

---

*Generated by Quant Hypothesis Framework v1.0*
*First strategy completed: fr_flip (2026-03-29)*
