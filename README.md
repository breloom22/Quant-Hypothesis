# Quant Hypothesis Framework

트레이딩 직관을 체계적인 퀀트 가설로 구조화하고, 다단계 검증 파이프라인을 거쳐 실제 운용 가능한 전략으로 정제하는 프레임워크.

**Claude Sonnet 4.6**(추론/해석) + **DeepSeek V3.2**(코드 생성/정형 분석) + **Python**(결정적 계산) 하이브리드 구조.

---

## 요구 사항

- Python 3.10+
- Anthropic API 키 (Claude Sonnet 4.6)
- DeepSeek API 키

---

## 설치

```bash
# 1. 저장소 클론
git clone <repo-url>
cd Quant_Hypothesis

# 2. 가상환경 생성 (권장)
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate      # Windows

# 3. 의존성 설치
pip install -r requirements.txt
```

### 의존성 목록

| 패키지 | 용도 |
|--------|------|
| `anthropic` | Claude API 클라이언트 |
| `openai` | DeepSeek API 클라이언트 (OpenAI 호환) |
| `ccxt` | 거래소 데이터 수집 |
| `pandas` | 데이터 처리 |
| `numpy` | 수치 계산 |
| `pyarrow` | Parquet 캐시 저장 |
| `pyyaml` | 설정/가설 파일 파싱 |
| `python-dotenv` | 환경 변수 로딩 |

---

## 환경 변수 설정

프로젝트 루트에 `.env` 파일을 생성한다:

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
DEEPSEEK_API_KEY=sk-...
```


API 키 발급처:
- Anthropic: https://console.anthropic.com/
- DeepSeek: https://platform.deepseek.com/

---

## 설정 (`config.yaml`)

```yaml
llm:
  anthropic:
    api_key: "${ANTHROPIC_API_KEY}"    # .env에서 자동 로드
    model: "claude-sonnet-4-6"
    max_tokens: 16384
  deepseek:
    api_key: "${DEEPSEEK_API_KEY}"
    model: "deepseek-chat"
    base_url: "https://api.deepseek.com"
    max_tokens: 8192

defaults:
  backtest:
    initial_capital: 10000        # 초기 자본 ($)
    fee_rate: 0.0004              # 수수료율 (0.04%)
    slippage: 0.0001              # 슬리피지 (0.01%)
  validation:
    monte_carlo_sims: 10000       # MC 시뮬레이션 횟수
    walk_forward_folds: 3         # WF 폴드 수
    min_signal_count: 50          # 최소 트레이드 수
  data:
    cache_ttl_hours: 24           # 캐시 유효 시간
    default_exchange: "binanceusdm"
```

---

## 사용법

### 전체 워크플로우

```
Phase 0      Phase 1        Phase 2       Phase 3          Phase 4
직관 입력 → 가설 구조화 → 테스트/정제 → 검증 파이프라인 → 보고서
  new       structure     test/refine     validate         report

         ┌─────────────────────────────────────────────┐
         │  run [--auto]  : Phase 1~4 일괄 실행        │
         └─────────────────────────────────────────────┘
```

### End-to-End 실행 (`run`)

Phase 0 입력 후 Phase 1~4를 한번에 실행한다. 두 가지 모드를 지원한다.

**Interactive 모드** (기본) — 각 phase 완료 시 요약을 보고 다음 행동을 선택:

```bash
python cli.py run my_strategy
```

각 phase 완료 후 프롬프트:
- `n` — 다음 phase로 진행
- `r` — 현재 phase 재실행
- `a` — 파이프라인 중단

**Auto 모드** — 인간 개입 없이 Phase 1~4 자동 완주:

```bash
python cli.py run my_strategy --auto
```

Auto 모드 동작:
- Phase 1: Sonnet 첫 번째 구조화 제안 자동 수락
- Phase 2: 분리 테스트/가설 수정 자동 승인, 전체 통과 또는 최대 정제 횟수(3)까지 반복
- Phase 3: 검증 단계 실패 시 자동 계속
- Phase 4: 보고서 생성 (원래 인간 개입 없음)

---

### 개별 Phase 실행

각 phase를 별도로 실행할 수도 있다.

### Phase 0: 새 전략 생성

```bash
python cli.py new my_strategy
```

대화형으로 직관을 입력한다:
- **관찰**: 어떤 패턴/현상을 관찰했는가
- **기대**: 그 패턴이 어떤 결과를 만들 것으로 예상하는가
- **빈도**: 얼마나 자주 발생하는가
- **대상 시장**: 거래소, 종목, 타임프레임

결과: `strategies/my_strategy/hypothesis.yaml` 생성.


### Phase 1: 가설 구조화

```bash
python cli.py structure my_strategy
```

Sonnet이 직관을 분석하여 다음을 생성한다:
- **변수 분해**: 독립 변수 추출 + 초기 구현 + 개선 후보
- **메커니즘 가설**: 인과 체인, 전제 조건, 반증 조건
- **검증 가능한 예측**: 테스트 가능한 예측 3~5개

대화형 승인 루프:
- `a` — 수락
- `e` — 수정 요청 (피드백 입력)
- `r` — 완전히 재생성

승인 후 DeepSeek이 `signals.py`와 테스트 코드를 자동 생성한다.

### Phase 2: 테스트 및 정제

```bash
# 전체 예측 테스트
python cli.py test my_strategy

# 특정 예측만 테스트
python cli.py test my_strategy --pred P01

# 변수 격리 테스트
python cli.py test my_strategy --isolation funding_rate_sign_change

# 정제 루프 1회 (실패 해석 → 메커니즘 수정)
python cli.py refine my_strategy
```

정제 루프 동작:
1. 실패한 예측 식별
2. DeepSeek이 pass/fail 판정
3. Sonnet이 실패 원인 해석
4. 메커니즘 수정 + 새 예측 도출
5. 사람 승인 후 저장

최대 3회 정제. 그 이상이면 가설 폐기 권고.

### Phase 3: 검증 파이프라인

```bash
# 전체 파이프라인 순차 실행
python cli.py validate my_strategy

# 특정 단계만 실행
python cli.py validate my_strategy --step walk_forward
```

13단계 검증:

| # | 단계 | 목적 |
|---|------|------|
| 1 | `crude_signal` | 가장 단순한 형태로 베이스라인 측정 |
| 2 | `signal_refinement` | 변수 교체/조합 테스트 |
| 3 | `variant_selection` | 최적 변형 선택 |
| 4 | `monte_carlo` | 무작위 대비 통계적 유의성 |
| 5 | `param_optimize` | 파라미터 최적화 |
| 6 | `walk_forward` | 시간대 교차검증 |
| 7 | `execution_tuning` | TP/SL 최적화 |
| 8 | `domain_expansion` | 타임프레임/보유기간 확장 |
| 9 | `universe_expansion` | 종목 확장 |
| 10 | `regime_filter` | 시장 국면 필터 |
| 11 | `failure_analysis` | 손실 트레이드 심층 분석 |
| 12 | `cross_validation` | 교차 검증 |
| 13 | `paper_deployment` | 페이퍼 트레이딩 |

각 단계 실패 시 계속 진행 여부를 묻는다.

### Phase 4: 보고서 생성

```bash
python cli.py report my_strategy
```

출력 파일:
- `strategies/my_strategy/log.md` — 전체 리서치 로그
- `strategies/my_strategy/summary.md` — 핵심 수치 요약본

### 유틸리티

```bash
# 전략 목록
python cli.py list

# 전략 상태 확인
python cli.py status my_strategy

# LLM 비용 확인
python cli.py cost my_strategy

# 데이터 미리 보기
python cli.py data fetch BTC/USDT:USDT 8h 30
```

---

## 전략 파일 구조

`python cli.py new my_strategy` 실행 후 생성되는 구조:

```
strategies/my_strategy/
├── hypothesis.yaml      # 전 단계 결과 기록 (Phase 0~4)
├── signals.py           # 신호 생성 코드 (Phase 1에서 자동 생성)
├── tests/               # 예측 테스트 코드 (Phase 1에서 자동 생성)
│   ├── test_P01.py
│   ├── test_P02.py
│   └── ...
├── results/             # 검증 결과 저장
├── log.md               # Phase 4 리서치 로그
└── summary.md           # Phase 4 요약본
```

### `signals.py` 규약

모든 전략의 `signals.py`는 다음 인터페이스를 따른다:

```python
def generate_signals(
    df: pd.DataFrame,           # columns: timestamp, open, high, low, close, volume, [+ 추가]
    overrides: dict | None,     # 변수별 교체 함수 {"변수명": callable}
    hold_bars: int = 3,         # 포지션 보유 봉 수
) -> pd.Series:                 # 1=롱, -1=숏, 0=플랫
```

`overrides` 패턴으로 변수 격리 테스트가 가능하다:

```python
# 기본 신호
signals = generate_signals(df)

# 특정 변수만 교체
signals = generate_signals(df, overrides={
    "funding_rate_sign_change": my_custom_function
})
```

---

## 데이터 캐싱

ccxt로 가져온 데이터는 `data/cache/`에 Parquet 형식으로 캐싱된다.

- 캐시 키: `MD5(exchange:symbol:timeframe:days)`
- TTL: `config.yaml`의 `cache_ttl_hours` (기본 24시간)
- 수동 초기화: `data/cache/` 디렉토리 내 `.parquet` 파일 삭제

---

## LLM 비용

| 모델 | 역할 | Input $/M tokens | Output $/M tokens |
|------|------|-------------------|---------------------|
| Claude Sonnet 4.6 | 추론, 해석, 메커니즘 수정 | $3 | $15 |
| DeepSeek V3.2 | 코드 생성, 정형 분석 | $0.28 | $0.42 |

전략 1개 전체 파이프라인 예상 비용: **$1~3** (Sonnet ~10회 호출, DeepSeek ~20회 호출 기준).

---

## 프로젝트 구조

```
Quant_Hypothesis/
├── .env                    # API 키 (git 제외)
├── config.yaml             # 중앙 설정
├── cli.py                  # CLI 인터페이스
├── requirements.txt        # Python 의존성
├── README.md               # ← 이 문서
├── PROJECT_OVERVIEW.md     # 프로젝트 전체 개요 + 최종 전략 상세
├── framework/              # 핵심 프레임워크
│   ├── schema.py
│   ├── hypothesis_manager.py
│   ├── backtest_engine.py
│   ├── test_runner.py
│   ├── refinement_loop.py
│   ├── validation_pipeline.py
│   ├── report_generator.py
│   ├── data/
│   │   └── fetchers.py
│   └── llm/
│       ├── client.py
│       ├── router.py
│       └── prompts/
├── strategies/             # 전략별 디렉토리
│   └── fr_flip/
└── data/
    └── cache/              # Parquet 캐시
```
