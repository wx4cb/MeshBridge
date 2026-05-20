#!/usr/bin/env sh
set -eu

exec .venv/bin/python main.py --config config.hjson --log-level DEBUG
