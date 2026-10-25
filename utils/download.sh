TICKER="${1:?用法: $0 <TICKER> [额外参数...]}"
shift
python -m alpha.cli download --ticker "$TICKER" "$@"
