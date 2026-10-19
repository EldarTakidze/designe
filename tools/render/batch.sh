#!/bin/bash
# Чистовые рендеры: python3 tools/render/batch.sh "warm japandi mix" "kl_entry kl_kitchen kl_window"
cd "$(dirname "$0")/../.."
for view in $2; do
  for st in $1; do
    out=renders/${st}_${view}.png
    python3 tools/render/scene.py --variant B --style $st --view $view --out $out --samples ${SAMPLES:-64} --res ${RES:-1440x900} 2>&1 | grep -E "^saved|Error|Traceback"
  done
done
