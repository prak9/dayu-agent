PROMPT="${1:?用法: $0 <TICKER> <PROMPT> [额外参数...]}"
shift 1
python -m alpha.cli prompt \
  "$PROMPT" \
  --enable-tool-trace \
  "$@"
