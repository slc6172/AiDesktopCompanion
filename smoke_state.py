"""Manual check against the real Gemini API: does she keep her state tags honest?

    python smoke_state.py            # needs GEMINI_API_KEY; 20 short conversations, about a minute
    python smoke_state.py --offline  # no network: a stand-in model, only to see what the report looks like
    python smoke_state.py --pause 8  # seconds between calls (default 5): a busy free plan answers 429 if pushed

Target: at least 90% on both "declares when something changed" and "does not make things up".
If it falls short, paste the whole output back into the conversation before deciding anything.
"""
import sys

from companion.statesmoke import OracleLLM, evaluate, run_all


def main():
    if "--offline" in sys.argv:
        llm, persona = OracleLLM(), "(offline)"
    else:
        from companion.gemini_llm import GeminiLLM

        try:
            persona = open("persona.md", encoding="utf-8").read()
        except FileNotFoundError:
            raise SystemExit("找不到 persona.md。請把 persona.example.md 複製一份,命名為 persona.md。")
        llm = GeminiLLM()
    pause = float(sys.argv[sys.argv.index("--pause") + 1]) if "--pause" in sys.argv else 5.0
    report = evaluate(run_all(llm, persona, pause_s=0.0 if "--offline" in sys.argv else pause))
    print(report.text())
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
