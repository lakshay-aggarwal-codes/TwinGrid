import ast
from collections import defaultdict
from pathlib import Path

directory = Path("alembic/versions")
revisions = defaultdict(list)
parents = {}
errors = []

for path in sorted(directory.glob("*.py")):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        errors.append(f"PARSE ERROR: {path.name}: {exc}")
        continue

    values = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in ("revision", "down_revision"):
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        values[target.id] = "<dynamic>"

    revision = values.get("revision")
    parent = values.get("down_revision")

    if not isinstance(revision, str):
        errors.append(f"MISSING/INVALID REVISION: {path.name}: {revision!r}")
        continue

    revisions[revision].append(path.name)
    parents[revision] = (path.name, parent)

print("=== PARSE / REVISION ERRORS ===")
print("\n".join(errors) if errors else "None")

print("\n=== DUPLICATE REVISION IDS ===")
duplicates = {r: files for r, files in revisions.items() if len(files) > 1}
print(duplicates if duplicates else "None")

print("\n=== MISSING PARENTS ===")
missing = []
for revision, (filename, parent) in parents.items():
    if parent is None:
        continue
    parent_ids = parent if isinstance(parent, tuple) else (parent,)
    for parent_id in parent_ids:
        if isinstance(parent_id, str) and parent_id not in revisions:
            missing.append((filename, parent_id))
print(missing if missing else "None")

print("\n=== REVISION CHAIN ===")
for revision, (filename, parent) in sorted(parents.items()):
    print(f"{revision} <- {parent!r} [{filename}]")

print(f"\nFiles: {sum(map(len, revisions.values()))}")
print(f"Unique revisions: {len(revisions)}")
