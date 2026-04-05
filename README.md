# Quant Hypothesis Framework

A framework for structuring trading intuitions into systematic quant hypotheses, refining them through a multi-stage validation pipeline, and producing deployment-ready strategies.

**Claude Sonnet 4.6** (reasoning/interpretation) + **DeepSeek V3.2** (code generation/structured analysis) + **Python** (deterministic computation) hybrid architecture.

---

## Requirements

- Python 3.10+
- Anthropic API key (Claude Sonnet 4.6)
- DeepSeek API key

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd Quant_Hypothesis

# 2. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate      # Windows

# 3. Install dependencies
pip install -r requirements.txt
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `anthropic` | Claude API client |
| `openai` | DeepSeek API client (OpenAI-compatible) |
| `ccxt` | Exchange data collection |
| `pandas` | Data processing |
| `numpy` | Numerical computation |
| `pyarrow` | Parquet cache storage |
| `pyyaml` | Config/hypothesis file parsing |
| `python-dotenv` | Environment variable loading |

---

## Environment Variables

Create a `.env` file in the project root:

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
DEEPSEEK_API_KEY=sk-...
```

API key sources:
- Anthropic: https://console.anthropic.com/
- DeepSeek: https://platform.deepseek.com/

---

## Configuration (`config.yaml`)

```yaml
llm:
  anthropic:
    api_key: "${ANTHROPIC_API_KEY}"    # Auto-loaded from .env
    model: "claude-sonnet-4-6"
    max_tokens: 16384
  deepseek:
    api_key: "${DEEPSEEK_API_KEY}"
    model: "deepseek-chat"
    base_url: "https://api.deepseek.com"
    max_tokens: 8192

defaults:
  backtest:
    initial_capital: 10000        # Initial capital ($)
    fee_rate: 0.0004              # Fee rate (0.04%)
    slippage: 0.0001              # Slippage (0.01%)
  validation:
    monte_carlo_sims: 10000       # MC simulation count
    walk_forward_folds: 3         # WF fold count
    min_signal_count: 50          # Minimum trade count
  data:
    cache_ttl_hours: 24           # Cache TTL
    default_exchange: "binanceusdm"
```

---

## Usage

### Full Workflow

```
Phase 0      Phase 1        Phase 2       Phase 3          Phase 4
Intuition -> Structuring -> Test/Refine -> Validation   -> Report
  new       structure     test/refine     validate         report

         ┌─────────────────────────────────────────────┐
         │  run [--auto]  : Run Phase 1~4 end-to-end   │
         └─────────────────────────────────────────────┘
```

### End-to-End Run (`run`)

Runs Phase 1~4 sequentially after Phase 0 input. Two modes are supported.

**Interactive mode** (default) -- review summary after each phase and choose the next action:

```bash
python cli.py run my_strategy
```

Prompt after each phase:
- `n` -- proceed to next phase
- `r` -- re-run current phase
- `a` -- abort pipeline

**Auto mode** -- complete Phase 1~4 without human intervention:

```bash
python cli.py run my_strategy --auto
```

Auto mode behavior:
- Phase 1: Auto-accepts Sonnet's first structuring proposal
- Phase 2: Auto-approves isolation tests/hypothesis refinements; repeats until all pass or max refinement count (3)
- Phase 3: Continues automatically on validation step failure
- Phase 4: Report generation (no human intervention needed)

---

### Individual Phase Execution

Each phase can also be run independently.

### Phase 0: Create New Strategy

```bash
python cli.py new my_strategy
```

Interactively input your intuition:
- **Observation**: What pattern/phenomenon did you observe?
- **Expectation**: What outcome do you expect from this pattern?
- **Frequency**: How often does it occur?
- **Target market**: Exchange, instrument, timeframe

Output: `strategies/my_strategy/hypothesis.yaml`

### Phase 1: Hypothesis Structuring

```bash
python cli.py structure my_strategy
```

Sonnet analyzes your intuition and generates:
- **Variable decomposition**: Independent variable extraction + initial implementation + improvement candidates
- **Mechanism hypothesis**: Causal chain, preconditions, falsification conditions
- **Testable predictions**: 3~5 testable predictions

Interactive approval loop:
- `a` -- accept
- `e` -- request edits (enter feedback)
- `r` -- fully regenerate

After approval, DeepSeek auto-generates `signals.py` and test code.

### Phase 2: Test & Refine

```bash
# Test all predictions
python cli.py test my_strategy

# Test a specific prediction
python cli.py test my_strategy --pred P01

# Variable isolation test
python cli.py test my_strategy --isolation funding_rate_sign_change

# Run one refinement loop (failure interpretation -> mechanism revision)
python cli.py refine my_strategy
```

Refinement loop behavior:
1. Identify failed predictions
2. DeepSeek issues pass/fail judgments
3. Sonnet interprets failure causes
4. Revise mechanism + derive new predictions
5. Save after human approval

Maximum 3 refinement iterations. Beyond that, hypothesis retirement is recommended.

### Phase 3: Validation Pipeline

```bash
# Run full pipeline sequentially
python cli.py validate my_strategy

# Run a specific step only
python cli.py validate my_strategy --step walk_forward
```

13-step validation:

| # | Step | Purpose |
|---|------|---------|
| 1 | `crude_signal` | Baseline measurement in simplest form |
| 2 | `signal_refinement` | Variable substitution/combination testing |
| 3 | `variant_selection` | Select optimal variant |
| 4 | `monte_carlo` | Statistical significance vs. randomness |
| 5 | `param_optimize` | Parameter optimization |
| 6 | `walk_forward` | Time-series cross-validation |
| 7 | `execution_tuning` | TP/SL optimization |
| 8 | `domain_expansion` | Timeframe/holding period expansion |
| 9 | `universe_expansion` | Instrument expansion |
| 10 | `regime_filter` | Market regime filtering |
| 11 | `failure_analysis` | Deep analysis of losing trades |
| 12 | `cross_validation` | Cross-validation |
| 13 | `paper_deployment` | Paper trading |

Each step prompts whether to continue on failure.

### Phase 4: Report Generation

```bash
python cli.py report my_strategy
```

Output files:
- `strategies/my_strategy/log.md` -- Full research log
- `strategies/my_strategy/summary.md` -- Key metrics summary

### Utilities

```bash
# List strategies
python cli.py list

# Check strategy status
python cli.py status my_strategy

# Check LLM costs
python cli.py cost my_strategy

# Preview data
python cli.py data fetch BTC/USDT:USDT 8h 30
```

---

## Strategy File Structure

Generated after running `python cli.py new my_strategy`:

```
strategies/my_strategy/
├── hypothesis.yaml      # All phase results (Phase 0~4)
├── signals.py           # Signal generation code (auto-generated in Phase 1)
├── tests/               # Prediction test code (auto-generated in Phase 1)
│   ├── test_P01.py
│   ├── test_P02.py
│   └── ...
├── results/             # Validation results
├── log.md               # Phase 4 research log
└── summary.md           # Phase 4 summary
```

### `signals.py` Convention

Every strategy's `signals.py` follows this interface:

```python
def generate_signals(
    df: pd.DataFrame,           # columns: timestamp, open, high, low, close, volume, [+ extras]
    overrides: dict | None,     # per-variable replacement functions {"var_name": callable}
    hold_bars: int = 3,         # position holding period in bars
) -> pd.Series:                 # 1=long, -1=short, 0=flat
```

The `overrides` pattern enables variable isolation testing:

```python
# Default signal
signals = generate_signals(df)

# Replace a specific variable
signals = generate_signals(df, overrides={
    "funding_rate_sign_change": my_custom_function
})
```

---

## Data Caching

Data fetched via ccxt is cached in `data/cache/` as Parquet files.

- Cache key: `MD5(exchange:symbol:timeframe:days)`
- TTL: `cache_ttl_hours` in `config.yaml` (default 24h)
- Manual reset: delete `.parquet` files in `data/cache/`

---

## LLM Cost

| Model | Role | Input $/M tokens | Output $/M tokens |
|-------|------|-------------------|---------------------|
| Claude Sonnet 4.6 | Reasoning, interpretation, mechanism revision | $3 | $15 |
| DeepSeek V3.2 | Code generation, structured analysis | $0.28 | $0.42 |

Estimated cost per full strategy pipeline: **$1~3** (based on ~10 Sonnet calls, ~20 DeepSeek calls).

---

## Project Structure

```
Quant_Hypothesis/
├── .env                    # API keys (git-ignored)
├── config.yaml             # Central configuration
├── cli.py                  # CLI interface
├── requirements.txt        # Python dependencies
├── README.md
├── PROJECT_OVERVIEW.md     # Project overview + final strategy details
├── framework/              # Core framework
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
├── strategies/             # Per-strategy directories
│   └── fr_flip/
└── data/
    └── cache/              # Parquet cache
```
