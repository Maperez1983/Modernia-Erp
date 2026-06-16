#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_DIR="$ROOT/.git/hooks"
HOOK_PATH="$HOOK_DIR/pre-push"

mkdir -p "$HOOK_DIR"

cat > "$HOOK_PATH" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
python3 scripts/ollama_diff_review.py --staged --fail-on-review --json >/tmp/modernia-pre-push-review.json || {
  echo "Pre-push bloqueado: revisar /tmp/modernia-pre-push-review.json"
  exit 1
}
EOF

chmod +x "$HOOK_PATH"
echo "Hook instalado en $HOOK_PATH"
