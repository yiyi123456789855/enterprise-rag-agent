#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required."
  exit 1
fi

if [[ ! -f .env.direct ]]; then
  bash deploy/init_direct_env.sh
fi

if [[ ! -x .venv-server/bin/python ]]; then
  python3 -m venv .venv-server
fi

if ! .venv-server/bin/python -m pip --version >/dev/null 2>&1; then
  echo "pip is missing from .venv-server; trying ensurepip."
  if ! .venv-server/bin/python -m ensurepip --upgrade; then
    echo "ensurepip is unavailable; bootstrapping pip from bootstrap.pypa.io."
    bootstrap_file="$(mktemp)"
    curl --fail --show-error --silent https://bootstrap.pypa.io/get-pip.py -o "$bootstrap_file"
    .venv-server/bin/python "$bootstrap_file"
    rm -f "$bootstrap_file"
  fi
fi

.venv-server/bin/python -m pip install --upgrade pip setuptools wheel
.venv-server/bin/python -m pip install \
  --index-url https://download.pytorch.org/whl/cu124 \
  "torch==2.6.0"
.venv-server/bin/python -m pip install -e ".[server]"

.venv-server/bin/python -c \
  "import torch; print('torch=', torch.__version__); print('cuda_available=', torch.cuda.is_available()); print('gpu=', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"

echo "Direct GPU environment is ready. Start with: bash deploy/start_direct.sh"
