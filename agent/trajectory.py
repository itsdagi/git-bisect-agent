"""Structured, append-only trajectory logging.

Every tool call the agent makes -- its name, input, result, timing, and the
orchestrator's next decision -- is written to a JSONL file as it happens, so
a run's full trajectory is captured even if the process crashes mid-run.
"""
import json
import time
from pathlib import Path


class TrajectoryLogger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self.path, "w")
        self._t0 = time.time()

    def log(self, event_type, **fields):
        record = {
            "t": round(time.time() - self._t0, 3),
            "type": event_type,
            **fields,
        }
        self._f.write(json.dumps(record, default=str) + "\n")
        self._f.flush()
        return record

    def close(self):
        self._f.close()

    def render_markdown(self):
        """Render the JSONL log as a human-readable markdown trajectory."""
        lines = []
        with open(self.path) as f:
            for raw in f:
                rec = json.loads(raw)
                t, typ = rec["t"], rec["type"]
                if typ == "tool_call":
                    lines.append(f"### [{t}s] tool_call: `{rec['tool']}`")
                    lines.append(f"input: `{json.dumps(rec['input'])}`")
                    result = rec.get("result")
                    result_str = json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)
                    if len(result_str) > 2000:
                        result_str = result_str[:2000] + "\n... (truncated)"
                    lines.append(f"result:\n```\n{result_str}\n```")
                elif typ == "decision":
                    lines.append(f"**[{t}s] decision:** {rec['note']}")
                elif typ == "info":
                    lines.append(f"[{t}s] {rec['note']}")
                elif typ == "final":
                    lines.append(f"\n## Final answer\n{rec['note']}")
                lines.append("")
        return "\n".join(lines)
