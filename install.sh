#!/usr/bin/env sh
set -eu

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Create/update the MeshBridge Python virtual environment and install
dependencies for a fresh VM checkout.

Options:
  --dev             also install requirements-dev.txt
  --config PATH     config file to validate if present (default: config.hjson)
  --no-check        skip config validation
  -h, --help        show this help

Notes:
  - This script does not install OS packages.
  - This script does not overwrite an existing config.hjson.
  - If config.hjson is missing, it copies docs/sample.config.hjson as a starter.
EOF
}

dev_install=0
check_config=1
config_path="config.hjson"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dev)
      dev_install=1
      ;;
    --config)
      shift
      if [ "$#" -eq 0 ]; then
        echo "error: --config requires a path" >&2
        exit 2
      fi
      config_path="$1"
      ;;
    --no-check)
      check_config=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [ ! -f "requirements.txt" ] || [ ! -f "main.py" ]; then
  echo "error: run this script from the MeshBridge repository root" >&2
  exit 1
fi

python_bin="${PYTHON:-python3}"

if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "error: Python interpreter not found: $python_bin" >&2
  echo "Install Python 3.10+ and python3-venv, then rerun this script." >&2
  exit 1
fi

python_version="$("$python_bin" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
python_ok="$("$python_bin" -c 'import sys; print(int(sys.version_info >= (3, 10)))')"

if [ "$python_ok" != "1" ]; then
  echo "error: Python 3.10+ is required; found $python_version" >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment with $python_bin..."
  "$python_bin" -m venv .venv
else
  echo "Using existing .venv..."
fi

venv_python=".venv/bin/python"
venv_pip=".venv/bin/pip"

echo "Upgrading pip tooling..."
"$venv_python" -m pip install --upgrade pip setuptools wheel

echo "Installing MeshBridge dependencies..."
"$venv_pip" install -r requirements.txt

if [ "$dev_install" -eq 1 ]; then
  echo "Installing development dependencies..."
  "$venv_pip" install -r requirements-dev.txt
fi

if [ ! -f "$config_path" ] && [ "$config_path" = "config.hjson" ]; then
  echo "Creating starter config.hjson from docs/sample.config.hjson..."
  cp docs/sample.config.hjson "$config_path"
  echo "Edit $config_path with Discord, MeshCore, and route settings before running the bridge."
fi

if [ "$check_config" -eq 1 ]; then
  if [ -f "$config_path" ]; then
    echo "Validating config: $config_path"
    "$venv_python" main.py --config "$config_path" --check-config
  else
    echo "Skipping config validation; config file does not exist: $config_path"
  fi
fi

cat <<EOF

Install complete.

Run manually:
  .venv/bin/python main.py --config $config_path --log-level INFO

Or:
  ./startbridge.sh

For systemd, edit systemd/meshbridge.service for the VM path/user, then copy it
to /etc/systemd/system/meshbridge.service and enable it.
EOF
