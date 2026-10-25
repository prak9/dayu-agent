TICKER="${1:?用法: $0 <TICKER>}"
shift 1

python -m alpha.cli write \
  --ticker "$TICKER" \
  --enable-tool-trace \
  "$@"