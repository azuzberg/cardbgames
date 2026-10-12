#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  task_python="${PYTHON_BIN:-python3.13}"
  if ! command -v "$task_python" >/dev/null 2>&1; then
    task_python=python3
  fi
  "$task_python" -c 'import sys; assert sys.version_info[:3] == (3, 13, 3), "Установите Python 3.13.3 или задайте PYTHON_BIN — путь к нему."'
  "$task_python" -m venv .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info[:3] == (3, 13, 3), "Для проекта нужен Python 3.13.3; пересоздайте .venv с этой версией."'
.venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r requirements.txt
exec .venv/bin/python app.py
