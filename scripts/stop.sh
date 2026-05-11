#!/bin/zsh

echo "=============================="
echo "Crucible 종료 중..."
echo "=============================="

tmux kill-session -t crucible_claude 2>/dev/null && echo "[종료] crucible_claude" || echo "[스킵] crucible_claude 없음"
tmux kill-session -t crucible_gemini 2>/dev/null && echo "[종료] crucible_gemini" || echo "[스킵] crucible_gemini 없음"
tmux kill-session -t crucible_codex  2>/dev/null && echo "[종료] crucible_codex"  || echo "[스킵] crucible_codex 없음"

rm -f ~/crucible_e/tmp/*.txt
rm -f ~/crucible_e/tmp/responses/*
echo "[정리] tmp 파일 삭제"

echo "=============================="
echo "종료 완료"
echo "=============================="
