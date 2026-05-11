#!/bin/zsh
# 사용법:
#   ./start.sh                        # ko, summary, TUI
#   ./start.sh --lang en              # 영어 모드
#   ./start.sh --lang mixed           # 내부 영어 + 최종 한국어
#   ./start.sh --mode full            # Gemini도 직접 탐색
#   ./start.sh --dir /path/to/project # 분석 디렉토리 지정
#   ./start.sh --cli                  # TUI 대신 CLI 모드
#   ./start.sh --rounds 3             # 라운드 수 지정

LANG_OPT="ko"
MODE_OPT="summary"
DIR_OPT=""
ROUNDS_OPT=""
USE_CLI=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --lang)   LANG_OPT=$2;   shift 2 ;;
        --mode)   MODE_OPT=$2;   shift 2 ;;
        --dir)    DIR_OPT=$2;    shift 2 ;;
        --rounds) ROUNDS_OPT=$2; shift 2 ;;
        --cli)    USE_CLI=true;  shift ;;
        *) echo "알 수 없는 옵션: $1"; exit 1 ;;
    esac
done

# 세션 셋업
source ~/crucible_e/scripts/bringup.sh

# 실행 명령 구성
ARGS="--lang $LANG_OPT --mode $MODE_OPT"
[[ -n "$DIR_OPT" ]]    && ARGS="$ARGS --dir $DIR_OPT"
[[ -n "$ROUNDS_OPT" ]] && ARGS="$ARGS --rounds $ROUNDS_OPT"

if $USE_CLI; then
    CMD="python orchestrator.py $ARGS"
else
    CMD="python ui/app.py $ARGS"
fi

terminator -e "zsh -c 'source ~/.zshrc && conda activate arena && cd ~/crucible_e && $CMD; zsh'" &
