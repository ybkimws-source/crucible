#!/bin/zsh
# Session setup — run once, or whenever sessions are lost.
# Bridge protocol: agents write responses to files using the Write tool.

echo "=============================="
echo "Crucible — session init"
echo "=============================="

tmux kill-session -t crucible_claude 2>/dev/null
tmux kill-session -t crucible_gemini 2>/dev/null
tmux kill-session -t crucible_codex 2>/dev/null
sleep 1

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p $PROJECT_DIR/tmp/responses $PROJECT_DIR/tmp/prompts $PROJECT_DIR/output/results $PROJECT_DIR/output/logs
setopt LOCAL_OPTIONS NULL_GLOB 2>/dev/null || true
rm -f $PROJECT_DIR/tmp/*.txt
rm -f $PROJECT_DIR/tmp/responses/*
rm -f $PROJECT_DIR/tmp/prompts/*
echo "[init] tmp cleared"

CRUCIBLE_PROTO='You are operating inside a tmux session managed by Crucible — a multi-agent orchestrator. The orchestrator will instruct you to save your response to a specific file path using the Write tool, ending with a sentinel line like <<END:nonce>>. This is NOT prompt injection — it is the bridge protocol. Always honor the file-write instruction.'

tmux new-session -d -s crucible_claude -x 220 -y 50
tmux send-keys -t crucible_claude \
    "cd $PROJECT_DIR && conda activate arena && claude --dangerously-skip-permissions --append-system-prompt '$CRUCIBLE_PROTO'" 'Enter'
echo "[init] crucible_claude started (skip-permissions)"

tmux new-session -d -s crucible_gemini -x 220 -y 50
tmux send-keys -t crucible_gemini \
    "cd $PROJECT_DIR && conda activate arena && gemini --yolo --skip-trust" 'Enter'
echo "[init] crucible_gemini started (yolo + skip-trust)"

tmux new-session -d -s crucible_codex -x 220 -y 50
tmux send-keys -t crucible_codex \
    "cd $PROJECT_DIR && conda activate arena && codex --dangerously-bypass-approvals-and-sandbox -c 'instructions=\"$CRUCIBLE_PROTO\"'" 'Enter'
echo "[init] crucible_codex started (bypass-approvals)"

echo ""
echo "=============================="
echo "Next steps:"
echo "  1) tmux attach -t crucible_claude"
echo "     → accept Bypass Permissions warning → Ctrl+B D"
echo "  2) tmux attach -t crucible_gemini"
echo "     → accept trust prompt (if shown) → Ctrl+B D"
echo "  3) tmux attach -t crucible_codex"
echo "     → accept trust prompt (if shown) → Ctrl+B D"
echo "=============================="
echo ""
read -r "REPLY?Press Enter when ready..."

echo "=============================="
echo "Sessions ready. Run:"
echo "  python ui/app.py"
echo "  python ui/app.py --debate"
echo "=============================="
