TICKER="${1:?用法: $0 <TICKER>}"
CHAPTER="${2:?用法: $0 <TICKER> <CHAPTER>}"
shift 2
python -m alpha.cli write \
  --ticker "$TICKER" \
  --chapter "$CHAPTER" \
  --enable-tool-trace \
  "$@"