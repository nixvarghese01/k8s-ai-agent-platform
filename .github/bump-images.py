"""Point the manifests at the images CI just pushed (build.yml, job "bump").

    python3 .github/bump-images.py <prefix> <tag> <digests-dir>

<prefix> is ghcr.io/<owner>/local-ai-; <digests-dir> holds one {"name", "digest"} JSON per image.
Every container using local-ai/<name>:dev (a local build) or an earlier <prefix><name> reference
becomes <prefix><name>:<tag>@<digest>, pulled once (IfNotPresent) instead of Never.
"""

import json
import pathlib
import re
import sys

prefix, tag, digests_dir = sys.argv[1:4]
digests = {}
for f in pathlib.Path(digests_dir).glob("*.json"):
    d = json.loads(f.read_text())
    digests[d["name"]] = d["digest"]

changed = []
for path in sorted(pathlib.Path("infra/k3s").rglob("*.yaml")):
    text = path.read_text(encoding="utf-8")
    new = text
    for name, digest in digests.items():
        ref = f"{prefix}{name}:{tag}@{digest}"
        pattern = re.compile(
            r"(image: )(?:local-ai/" + re.escape(name) + r":dev|" + re.escape(prefix + name) + r"[:@][^\s#]+)"
            r"(\s*\n(\s*)imagePullPolicy: )\w+"
        )
        # an image reference and the imagePullPolicy line right after it; a reference that
        # already has this digest stays as it is (a new tag alone would restart the pods)
        def repl(m):
            if m.group(0).find(f"@{digest}") != -1:
                return m.group(0)
            return f"{m.group(1)}{ref}{m.group(2)}IfNotPresent"

        new = pattern.sub(repl, new)
    if new != text:
        path.write_text(new, encoding="utf-8")
        changed.append(str(path))

print("updated:", ", ".join(changed) if changed else "nothing")
