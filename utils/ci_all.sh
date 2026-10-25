#!/bin/zsh
OUTPUT_DIR="$1"
BASE_DIR="workspace"
PORTFOLIO_DIR="${BASE_DIR}/portfolio"
if [[ -n "$OUTPUT_DIR" ]]; then
  REPORT_DIR="${OUTPUT_DIR}/score_ci_reports"
  LOG_DIR="${OUTPUT_DIR}/score_ci_logs"
else
  REPORT_DIR="${BASE_DIR}/score_ci_reports"
  LOG_DIR="${BASE_DIR}/score_ci_logs"
fi

FORMS=(
  "10-K"
  "10-Q"
  "20-F"
  "6-K"
  "8-K"
  "SC 13G"
  "DEF 14A"
)

if [[ ! -d "$PORTFOLIO_DIR" ]]; then
  echo "[score-ci] 未找到目录: $PORTFOLIO_DIR" >&2
  exit 1
fi

mkdir -p "$REPORT_DIR" "$LOG_DIR"

tickers_csv=$(ls -1 "$PORTFOLIO_DIR" | tr '\n' ',' | sed 's/,$//')
tickers=(${(s:,:)tickers_csv})
if (( ${#tickers[@]} == 0 )); then
  echo "[score-ci] $PORTFOLIO_DIR 下没有 ticker 目录，脚本结束"
  exit 0
fi

TICKERS="$tickers_csv"
total_start_ts=$(date +%s)
overall_exit_code=0

sum=${#FORMS[@]}
i=0

for form in "${FORMS[@]}"; do
  ((i++))

  form_start_ts=$(date +%s)
  form_slug=${form:l}
  form_slug=${form_slug// /}
  form_slug=${form_slug//-/}

  log_file="${LOG_DIR}/${form_slug}_score.log"
  json_file="${REPORT_DIR}/score_${form_slug}_ci.json"
  md_file="${REPORT_DIR}/score_${form_slug}_ci.md"

  echo "[score-ci][$i/$sum][$form]"

  python -m alpha.fins.score_sec_ci \
    --form "$form" \
    --base "$BASE_DIR" \
    --tickers "$TICKERS" \
    --output-json "$json_file" \
    --output-md "$md_file" \
    >"$log_file" 2>&1
  exit_code=$?

  form_end_ts=$(date +%s)
  echo "[score-ci][$i/$sum][$form] 耗时: $((form_end_ts - form_start_ts))s, exit=$exit_code | json=$json_file | md=$md_file | log=$log_file"

  if (( exit_code != 0 )); then
    overall_exit_code=$exit_code
  fi
done

total_end_ts=$(date +%s)
echo "[score-ci] 总耗时: $((total_end_ts - total_start_ts))s, overall_exit=$overall_exit_code"