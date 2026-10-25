#!/bin/zsh

total_start_ts=$(date +%s)
log_root="workspace/tmp/download_logs"
mkdir -p "$log_root"

tickers_csv="${1:?用法: $0 <TICKERS_CSV>  例: $0 'AAPL,MSFT,TSLA'}"
shift
tickers=(${${(s:,:)tickers_csv}// /})
sum=${#tickers[@]}
i=0

for ticker in "${tickers[@]}"; do
  ((i++))
  ticker_start_ts=$(date +%s)
  log_file="${log_root}/${ticker}_download.log"

  echo "[downloading][$i/$sum][$ticker]"

  python -m alpha.cli download --ticker "$ticker" "$@" > "$log_file" 2>&1

  ticker_end_ts=$(date +%s)
  echo "[download][$i/$sum][$ticker] 耗时: $((ticker_end_ts - ticker_start_ts))s | log: $log_file"
done

total_end_ts=$(date +%s)
echo "[download] 总耗时: $((total_end_ts - total_start_ts))s"
