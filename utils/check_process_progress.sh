#!/bin/zsh
sudo -v || { echo "❌ 无法获取 sudo 权限"; return 1; }

OUTPUT_DIR="$1"

pgrep -f 'ython -m alpha.cli process --ci' | while read -r pid; do
  if [[ -n "$OUTPUT_DIR" ]]; then
    log_file="${OUTPUT_DIR}/process_${pid}_profile.log"
  else
    log_file="workspace/tmp/process_${pid}_profile.log"
    mkdir -p "workspace/tmp"
  fi
  echo "正在分析进程 PID: $pid | log: $log_file"
  sudo py-spy dump --pid "$pid" --locals > "$log_file" 2>&1
done