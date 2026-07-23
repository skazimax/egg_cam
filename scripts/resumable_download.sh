#!/usr/bin/env bash

set -u

if [[ $# -ne 2 ]]; then
  echo "usage: $0 URL OUTPUT" >&2
  exit 2
fi

url=$1
output=$2
mkdir -p "$(dirname "$output")"

until curl --fail --location --continue-at - --silent --show-error \
  "$url" --output "$output"; do
  echo "Download interrupted; resuming in 2 seconds..." >&2
  sleep 2
done
