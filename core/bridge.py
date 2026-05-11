import os
import time
import uuid
import subprocess
import threading
from dataclasses import dataclass
from core.agents import AgentConfig
from core.config import TMP_DIR, RESPONSES_DIR, PROMPTS_DIR, BRIDGE_TIMEOUT

POLL_INTERVAL = 0.1

_INSTR = {
    "ko": (
        "\n\n[OUTPUT INSTRUCTION]\n"
        "이 응답을 화면에 길게 출력하지 말고, 다음 절대경로 파일에 Write 툴로 저장해:\n"
        "  {path}\n"
        "파일 마지막 줄은 정확히 다음 한 줄이어야 해 (응답 종료 sentinel):\n"
        "  {sentinel}\n"
        "파일 작성 완료 후 화면엔 'OK'만 출력해."
    ),
    "en": (
        "\n\n[OUTPUT INSTRUCTION]\n"
        "Do not print your full response to the terminal. Use the Write tool to save it to:\n"
        "  {path}\n"
        "The very last line of that file must be exactly:\n"
        "  {sentinel}\n"
        "After writing, print only 'OK' to the terminal."
    ),
}


@dataclass
class BridgeResult:
    ok: bool
    content: str
    error: str = ""
    elapsed: float = 0.0

    def __bool__(self):
        return self.ok


class CLIBridge:
    def __init__(self, config: AgentConfig, lang: str = "en"):
        self.config = config
        self.name = config.name
        self.session = config.session
        self.lang = "en" if lang == "mixed" else lang
        self._lock = threading.Lock()

    def check_session(self) -> bool:
        result = subprocess.run(
            ["tmux", "has-session", "-t", self.session],
            capture_output=True,
        )
        return result.returncode == 0

    def inject_system_prompt(self) -> bool:
        if not self.config.system_prompt:
            return True
        print(f"[{self.name}] injecting system prompt...")
        result = self._send_and_wait(self.config.system_prompt, timeout=BRIDGE_TIMEOUT)
        if not result.ok:
            print(f"[{self.name}] injection failed: {result.error}")
            return False
        print(f"[{self.name}] ready")
        return True

    def send(self, prompt: str, timeout: int = BRIDGE_TIMEOUT) -> BridgeResult:
        if not self.check_session():
            return BridgeResult(
                ok=False,
                content="",
                error=f"tmux session '{self.session}' not found",
            )
        with self._lock:
            return self._send_and_wait(prompt, timeout)

    def _send_and_wait(self, prompt: str, timeout: int) -> BridgeResult:
        nonce = uuid.uuid4().hex[:8]
        os.makedirs(RESPONSES_DIR, exist_ok=True)
        os.makedirs(PROMPTS_DIR, exist_ok=True)
        out_path = os.path.join(RESPONSES_DIR, f"{self.name}_{nonce}.md")
        prompt_path = os.path.join(PROMPTS_DIR, f"{self.name}_{nonce}.md")
        sentinel = f"<<END:{nonce}>>"
        start = time.monotonic()

        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        instr = _INSTR[self.lang].format(path=out_path, sentinel=sentinel)
        marked = f"@{prompt_path}" + instr

        if os.path.exists(out_path):
            os.remove(out_path)

        self._clear()
        self._paste(marked, f"{self.name}_paste")
        time.sleep(0.3)
        subprocess.run(["tmux", "send-keys", "-t", self.session, "Enter"])

        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                time.sleep(POLL_INTERVAL)
                if not os.path.exists(out_path):
                    continue
                try:
                    with open(out_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except OSError:
                    continue
                tail = content.rstrip().splitlines()
                if tail and tail[-1].strip() == sentinel:
                    body = "\n".join(tail[:-1]).strip()
                    return BridgeResult(
                        ok=True,
                        content=body or "ok",
                        elapsed=time.monotonic() - start,
                    )
        finally:
            try:
                os.remove(prompt_path)
            except OSError:
                pass

        return BridgeResult(
            ok=False,
            content="",
            error=f"timeout — sentinel not detected ({out_path})",
            elapsed=time.monotonic() - start,
        )

    def _clear(self):
        subprocess.run(["tmux", "send-keys", "-t", self.session, "C-u"])
        time.sleep(0.1)

    def _paste(self, text: str, buf_name: str):
        os.makedirs(TMP_DIR, exist_ok=True)
        tmp_file = os.path.join(TMP_DIR, f"{buf_name}.txt")
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(text)
        subprocess.run(
            ["tmux", "load-buffer", "-b", buf_name, tmp_file], check=True
        )
        subprocess.run(["tmux", "paste-buffer", "-b", buf_name, "-t", self.session])
