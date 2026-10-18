#!/usr/bin/env bash
# Daemon entrypoint for Streamlit (see web_extra_daemons in config.yaml).
set -euo pipefail
cd /var/www/html
/var/www/html/.ddev/scripts/ensure-venv.sh
exec /opt/venv/bin/streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.headless true \
  --server.runOnSave true \
  --browser.gatherUsageStats false
