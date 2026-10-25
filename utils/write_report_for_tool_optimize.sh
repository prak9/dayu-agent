TICKER="${1:?用法: $0 <TICKER>}"
shift 1

log_dir="./workspace/tool_optimize/new_round/log/${TICKER}"
draft_dir="./workspace/tool_optimize/new_round/draft/${TICKER}"
mkdir -p "$log_dir"
mkdir -p "$draft_dir"
python -m alpha.cli write \
  --ticker "$TICKER" \
  --enable-tool-trace \
  --tool-trace-dir "$log_dir" \
  --output "$draft_dir" \
  "$@" 2>&1 | tee -a "${log_dir}/write_${TICKER}.log"