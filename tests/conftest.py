import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Services aren't installed packages; import them from their folders
sys.path[:0] = [str(REPO / "mcp-servers" / d) for d in ("filesystem", "rag", "triage", "memory", "calendar", "web")] + [str(REPO / d) for d in ("agent", "pipelines", "serving", "voice")]
