#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
init="$script_dir/init_latex_project.sh"
ensure="$script_dir/ensure_latex_project.sh"
gate="$script_dir/check_workflow_gates.sh"
umask 022
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/pdf-to-latex-scaffold.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM
export PYTHONDONTWRITEBYTECODE=1

fail() {
  printf 'Project scaffold test failed: %s\n' "$*" >&2
  exit 1
}

assert_file() {
  [[ -f "$1" ]] || fail "expected file: $1"
}

assert_dir() {
  [[ -d "$1" ]] || fail "expected directory: $1"
}

assert_absent() {
  [[ ! -e "$1" ]] || fail "expected path to be absent: $1"
}

expect_failure() {
  if "$@" >"$tmp_dir/last.stdout" 2>"$tmp_dir/last.stderr"; then
    fail "expected command to fail: $*"
  fi
}

make_pdf() {
  local destination=$1
  local pages=$2
  local token=$3
  printf '%%PDF-1.7\nPAGES=%s\nTOKEN=%s\n' "$pages" "$token" >"$destination"
}

fake_bin="$tmp_dir/fake-bin"
mkdir -p "$fake_bin"
cat >"$fake_bin/pdfinfo" <<'PY'
#!/usr/bin/env python3
import pathlib
import re
import sys
import os

path = pathlib.Path(sys.argv[-1])
data = path.read_text(encoding="utf-8", errors="replace")
if not data.startswith("%PDF-"):
    raise SystemExit(1)
match = re.search(r"^PAGES=([0-9]+)$", data, re.MULTILINE)
if match is None:
    raise SystemExit(1)
counter_path = os.environ.get("PDFINFO_COUNTER")
if counter_path:
    counter = pathlib.Path(counter_path)
    count = int(counter.read_text(encoding="utf-8")) + 1 if counter.exists() else 1
    counter.write_text(str(count), encoding="utf-8")
    mutate_on = int(os.environ.get("PDFINFO_MUTATE_ON", "0"))
    if count == mutate_on:
        path.write_text(data + "MUTATED\n", encoding="utf-8")
print(f"Pages: {match.group(1)}")
if os.environ.get("PDFINFO_INVALID_PAGE_SIZE") == "1":
    sys.stdout.flush()
    sys.stdout.buffer.write(b"Page size: 612 x 792 pts \xff\n")
else:
    print("Page size: 612 x 792 pts (letter)")
PY
chmod 755 "$fake_bin/pdfinfo"
PATH="$fake_bin:$PATH"
export PATH

source_pdf="$tmp_dir/source.pdf"
make_pdf "$source_pdf" 3 original

unsafe_placeholder_pdf="$tmp_dir/source{{TARGET_DIR}}.pdf"
unsafe_comment_pdf="$tmp_dir/source<!--comment-->.pdf"
unsafe_newline_pdf="$tmp_dir/"$'source\nnewline.pdf'
unsafe_separator_pdf="$tmp_dir/$(printf 'source\342\200\250separator.pdf')"
make_pdf "$unsafe_placeholder_pdf" 1 unsafe-placeholder
make_pdf "$unsafe_comment_pdf" 1 unsafe-comment
make_pdf "$unsafe_newline_pdf" 1 unsafe-newline
make_pdf "$unsafe_separator_pdf" 1 unsafe-separator
unsafe_index=0
for unsafe_pdf in \
  "$unsafe_placeholder_pdf" \
  "$unsafe_comment_pdf" \
  "$unsafe_newline_pdf" \
  "$unsafe_separator_pdf"; do
  unsafe_index=$((unsafe_index + 1))
  unsafe_target="$tmp_dir/unsafe-source-project-$unsafe_index"
  expect_failure "$init" "$unsafe_pdf" "$unsafe_target" \
    --operation convert \
    --source-kind digital \
    --traits none \
    --delivery-level clean-semantic \
    --execution-mode resumable \
    --verification-scope source-aware
  assert_absent "$unsafe_target"
done

invalid_page_size_pdf="$tmp_dir/invalid-page-size.pdf"
invalid_page_size_project="$tmp_dir/invalid-page-size-project"
make_pdf "$invalid_page_size_pdf" 1 invalid-page-size
PDFINFO_INVALID_PAGE_SIZE=1 "$init" "$invalid_page_size_pdf" "$invalid_page_size_project" \
  --operation convert \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
assert_file "$invalid_page_size_project/conversion-state.md"

not_pdf="$tmp_dir/not-pdf.pdf"
printf 'not a PDF\n' >"$not_pdf"
expect_failure "$init" "$not_pdf" "$tmp_dir/not-pdf-project" \
  --operation convert \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware

unrelated="$tmp_dir/unrelated"
mkdir -p "$unrelated"
printf 'user data\n' >"$unrelated/notes.txt"
expect_failure "$init" "$source_pdf" "$unrelated" \
  --operation convert \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware

expect_failure "$init" "$source_pdf" "$tmp_dir/review-init" \
  --operation review \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode one-turn \
  --verification-scope source-aware

expect_failure "$init" "$source_pdf" "$tmp_dir/resume-init" \
  --operation resume \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware

expect_failure "$init" "$source_pdf" "$tmp_dir/project-only-init" \
  --operation convert \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope project-only

changing_pdf="$tmp_dir/changing.pdf"
changing_project="$tmp_dir/changing-project"
make_pdf "$changing_pdf" 1 changing
expect_failure env PDFINFO_COUNTER="$tmp_dir/pdfinfo-count" PDFINFO_MUTATE_ON=2 \
  "$init" "$changing_pdf" "$changing_project" \
  --operation convert \
  --source-kind digital \
  --traits book \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware
assert_absent "$changing_project"

project="$tmp_dir/project"
"$init" "$source_pdf" "$project" \
  --operation convert \
  --source-kind mixed \
  --traits book,math-heavy,cjk \
  --delivery-level publication-polish \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null

for relative in \
  main.tex \
  conversion-state.md \
  conversion-notes.md \
  page-manifest.md \
  object-inventory.md \
  style-profile.md \
  document-ir.md \
  math-inventory.md \
  glyph-map.md \
  batch-manifest.json; do
  assert_file "$project/$relative"
done
for relative in \
  logs \
  chapters \
  frontmatter \
  backmatter \
  figures \
  tables \
  evidence/source-pages \
  evidence/rebuilt-pages \
  evidence/text-layer \
  evidence/crops \
  work/shards \
  work/merged \
  work/review-findings; do
  assert_dir "$project/$relative"
done
assert_absent "$project/goal-objective.md"

grep -Fq 'State schema: 2' "$project/conversion-state.md" || fail 'state schema was not rendered'
grep -Fq 'Skill version: 1.0.0' "$project/conversion-state.md" || fail 'skill version was not rendered'
grep -Fq 'Document traits: book,math-heavy,cjk' "$project/conversion-state.md" || fail 'traits were not rendered'
grep -Fq 'Source page size: 612 x 792 pts (letter)' "$project/style-profile.md" || fail 'page size was not recorded'
if grep -R -E '\{\{[A-Z0-9_]+\}\}' "$project" >/dev/null 2>&1; then
  fail 'scaffold contains unresolved placeholders'
fi
python3 - "$project/batch-manifest.json" "$source_pdf" <<'PY'
import hashlib
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
source = pathlib.Path(sys.argv[2]).resolve()
assert manifest["schema_version"] == 1
assert manifest["source"]["path"] == str(source)
assert manifest["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
assert manifest["source"]["page_count"] == 3
assert manifest["batches"] == []
PY

set +e
"$gate" "$project" >/dev/null 2>&1
gate_status=$?
set -e
if [[ $gate_status -ne 1 ]]; then
  fail "unfinished scaffold should validate as in-progress, got exit $gate_status"
fi

printf 'preserve this source\n' >>"$project/main.tex"
main_hash=$(python3 - "$project/main.tex" <<'PY'
import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
"$init" "$source_pdf" "$project" \
  --operation convert \
  --source-kind mixed \
  --traits book,math-heavy,cjk \
  --delivery-level publication-polish \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
new_main_hash=$(python3 - "$project/main.tex" <<'PY'
import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
[[ "$main_hash" == "$new_main_hash" ]] || fail 'matching reinitialization overwrote main.tex'

for inactive_kind in comment indented duplicate invalid-utf8 missing-outcome; do
  inactive_project="$tmp_dir/inactive-$inactive_kind"
  cp -R "$project" "$inactive_project"
  case "$inactive_kind" in
    comment)
      {
        printf '<!--\n'
        cat "$inactive_project/conversion-state.md"
        printf '%s\n' '-->'
      } >"$inactive_project/state.tmp"
      ;;
    indented)
      python3 - "$inactive_project/conversion-state.md" "$inactive_project/state.tmp" <<'PY'
import pathlib
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
destination.write_text(
    "".join(" \t" + line for line in source.read_text(encoding="utf-8").splitlines(keepends=True)),
    encoding="utf-8",
)
PY
      ;;
    duplicate)
      awk '
        !added && /^## / { print "Operation: convert"; added = 1 }
        { print }
      ' "$inactive_project/conversion-state.md" >"$inactive_project/state.tmp"
      ;;
    invalid-utf8)
      cp "$inactive_project/conversion-state.md" "$inactive_project/state.tmp"
      printf '\377' >>"$inactive_project/state.tmp"
      ;;
    missing-outcome)
      sed '/^Outcome:/d' "$inactive_project/conversion-state.md" >"$inactive_project/state.tmp"
      ;;
  esac
  mv "$inactive_project/state.tmp" "$inactive_project/conversion-state.md"
  expect_failure "$init" "$source_pdf" "$inactive_project" \
    --operation convert \
    --source-kind mixed \
    --traits book,math-heavy,cjk \
    --delivery-level publication-polish \
    --execution-mode resumable \
    --verification-scope source-aware
done

python3 - "$source_pdf" "$project" <<'PY'
import hashlib
import json
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).resolve()
project = pathlib.Path(sys.argv[2])
digest = hashlib.sha256(source.read_bytes()).hexdigest()
size = source.stat().st_size
generated = "2026-01-01T00:00:00Z"

source_dir = project / "evidence" / "source-pages"
(source_dir / "page-001.png").write_bytes(b"PNG evidence\n")
(source_dir / "manifest.json").write_text(
    json.dumps(
        {
            "schema_version": 1,
            "evidence_kind": "source-pages",
            "source_path": str(source),
            "source_sha256": digest,
            "source_size_bytes": size,
            "page_count": 3,
            "pages": [1],
            "page_records": {
                "1": {
                    "png": "page-001.png",
                    "dpi": 90,
                    "renderer": "pdftoppm",
                    "generated_at": generated,
                }
            },
            "generated_at": generated,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

text_dir = project / "evidence" / "text-layer"
(text_dir / "page-001.txt").write_text("text evidence\n", encoding="utf-8")
(text_dir / "manifest.json").write_text(
    json.dumps(
        {
            "schema_version": 1,
            "evidence_kind": "text-layer",
            "source_path": str(source),
            "source_sha256": digest,
            "source_size_bytes": size,
            "page_count": 3,
            "pages": [1],
            "page_records": {
                "1": {
                    "text": "page-001.txt",
                    "extractor": "pdftotext",
                    "layout": True,
                    "generated_at": generated,
                }
            },
            "generated_at": generated,
            "extractor": "pdftotext",
            "layout": True,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

page_index = project / "work" / "page-index.json"
page_index.write_text(
    json.dumps(
        {
            "schema_version": 1,
            "kind": "page-complexity-index",
            "source": {
                "path": str(source),
                "sha256": digest,
                "size_bytes": size,
                "page_count": 3,
            },
            "policy": {
                "source_kind": "mixed",
                "traits": ["book"],
                "batch_sizes": {"low": 30, "medium": 10, "high": 5, "critical": 1},
                "worker_output": "compact-summary-with-detail-artifact",
                "evidence": "local-text-triage-before-rendered-page-escalation",
            },
            "pages": [
                {
                    "page": page,
                    "text_chars": 0,
                    "complexity": "critical",
                    "route": "visual-transcription",
                    "recommended_batch_size": 1,
                }
                for page in (1, 2, 3)
            ],
            "batches": [
                {
                    "batch_id": "plan-001",
                    "owned_pages": [1],
                    "context_pages": [2],
                    "complexity": "critical",
                    "route": "visual-transcription",
                    "worker_mode": "single-page",
                    "detail_policy": "summary-first",
                }
            ],
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY

moved_pdf="$tmp_dir/moved.pdf"
mv "$source_pdf" "$moved_pdf"
"$init" "$moved_pdf" "$project" \
  --operation convert \
  --source-kind mixed \
  --traits book,math-heavy,cjk \
  --delivery-level publication-polish \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
expected_source=$(python3 - "$moved_pdf" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve())
PY
)
for relative in \
  conversion-state.md \
  conversion-notes.md \
  page-manifest.md \
  object-inventory.md \
  style-profile.md \
  document-ir.md \
  math-inventory.md \
  glyph-map.md; do
  grep -Fq "Source PDF: $expected_source" "$project/$relative" || fail "moved source path was not refreshed in $relative"
done
python3 - "$project" "$expected_source" <<'PY'
import json
import pathlib
import sys

project = pathlib.Path(sys.argv[1])
expected = sys.argv[2]
for relative in (
    "evidence/source-pages/manifest.json",
    "evidence/text-layer/manifest.json",
    "batch-manifest.json",
    "work/page-index.json",
):
    manifest = json.loads((project / relative).read_text(encoding="utf-8"))
    if relative.startswith("evidence/"):
        actual = manifest["source_path"]
    else:
        actual = manifest["source"]["path"]
    if actual != expected:
        raise SystemExit(f"moved source path was not refreshed in {relative}")
PY

make_pdf "$moved_pdf" 3 replacement
expect_failure "$init" "$moved_pdf" "$project" \
  --operation convert \
  --source-kind mixed \
  --traits book,math-heavy,cjk \
  --delivery-level publication-polish \
  --execution-mode resumable \
  --verification-scope source-aware

book_pdf="$tmp_dir/book.pdf"
book_project="$tmp_dir/book-project"
make_pdf "$book_pdf" 2 book
"$init" "$book_pdf" "$book_project" \
  --operation convert \
  --source-kind digital \
  --traits book \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
assert_absent "$book_project/math-inventory.md"
assert_absent "$book_project/glyph-map.md"

repair_project="$tmp_dir/one-turn-repair"
mkdir -p "$repair_project"
printf '%s\n' '\documentclass{article}\begin{document}Repair\end{document}' >"$repair_project/main.tex"
"$ensure" "$repair_project" \
  --operation repair \
  --source-kind unknown \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode one-turn \
  --verification-scope project-only >/dev/null
assert_absent "$repair_project/conversion-state.md"
assert_absent "$repair_project/conversion-notes.md"

publication_repair="$tmp_dir/publication-repair"
mkdir -p "$publication_repair"
printf '%s\n' '\documentclass{article}\begin{document}Publication repair\end{document}' >"$publication_repair/main.tex"
"$ensure" "$publication_repair" \
  --operation repair \
  --source-kind unknown \
  --traits none \
  --delivery-level publication-polish \
  --execution-mode one-turn \
  --verification-scope project-only >/dev/null
assert_file "$publication_repair/conversion-state.md"
assert_file "$publication_repair/conversion-notes.md"
assert_file "$publication_repair/style-profile.md"
grep -Fq '### Gate: publication-review' "$publication_repair/conversion-state.md" || fail 'publication repair gate was not rendered'

refine_project="$tmp_dir/project-only-refine"
mkdir -p "$refine_project"
printf '%s\n' '\documentclass{article}\begin{document}Refine\end{document}' >"$refine_project/main.tex"
"$ensure" "$refine_project" \
  --operation refine \
  --source-kind unknown \
  --traits cjk \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope project-only >/dev/null
assert_file "$refine_project/conversion-state.md"
assert_file "$refine_project/conversion-notes.md"
assert_file "$refine_project/style-profile.md"
assert_absent "$refine_project/batch-manifest.json"
grep -Fq 'Source PDF: unavailable' "$refine_project/conversion-state.md" || fail 'project-only state should record unavailable source'

printf 'preserve ensure content\n' >>"$refine_project/main.tex"
expect_failure "$ensure" "$refine_project" \
  --operation resume \
  --source-kind unknown \
  --traits cjk \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope project-only
grep -Fq 'preserve ensure content' "$refine_project/main.tex" || fail 'failed ensure changed main.tex'

source_aware_project="$tmp_dir/source-aware-ensure"
mkdir -p "$source_aware_project"
printf '%s\n' '\documentclass{article}\begin{document}Resume\end{document}' >"$source_aware_project/main.tex"
expect_failure "$ensure" "$source_aware_project" \
  --operation resume \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware

ordered_pdf="$tmp_dir/ordered.pdf"
ordered_project="$tmp_dir/ordered-project"
make_pdf "$ordered_pdf" 1 ordered
"$init" "$ordered_pdf" "$ordered_project" \
  --operation convert \
  --source-kind digital \
  --traits cjk,book \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
grep -Fq 'Document traits: book,cjk' "$ordered_project/conversion-state.md" || fail 'traits were not canonicalized'
"$init" "$ordered_pdf" "$ordered_project" \
  --operation convert \
  --source-kind digital \
  --traits book,cjk \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
assert_dir "$ordered_project/frontmatter"

relative_pdf="$tmp_dir/relative-source.pdf"
relative_project="$tmp_dir/relative-project"
make_pdf "$relative_pdf" 1 relative
"$init" "$relative_pdf" "$relative_project" \
  --operation convert \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
cp "$relative_pdf" "$relative_project/relative-source.pdf"
python3 - "$relative_project/conversion-state.md" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
updated = []
for line in lines:
    if line.startswith("Source PDF:"):
        updated.append("Source PDF: relative-source.pdf")
    elif line.startswith("Source PDF SHA-256:"):
        label, value = line.split(": ", 1)
        updated.append(f"{label}: {value.upper()}")
    else:
        updated.append(line)
path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
rm "$relative_project/conversion-notes.md"
"$ensure" "$relative_project" \
  --operation convert \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
expected_relative_source=$(python3 - "$relative_project/relative-source.pdf" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve())
PY
)
for provenance_file in conversion-state.md conversion-notes.md; do
  grep -Fq "Source PDF: $expected_relative_source" "$relative_project/$provenance_file" || fail "relative source was not rebound consistently in $provenance_file"
done

resume_pdf="$tmp_dir/resume-source.pdf"
resume_project="$tmp_dir/resume-project"
make_pdf "$resume_pdf" 2 resume
"$init" "$resume_pdf" "$resume_project" \
  --operation convert \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
sed 's/^Operation: convert$/Operation: resume/' "$resume_project/conversion-state.md" >"$resume_project/state.tmp"
mv "$resume_project/state.tmp" "$resume_project/conversion-state.md"
sed 's/^Operation: convert$/Operation: resume/' "$resume_project/conversion-notes.md" >"$resume_project/notes.tmp"
mv "$resume_project/notes.tmp" "$resume_project/conversion-notes.md"
for provenance_file in conversion-state.md conversion-notes.md; do
  {
    printf '%s\n' '<!-- Source PDF: /hidden/decoy.pdf -->'
    cat "$resume_project/$provenance_file"
  } >"$resume_project/provenance.tmp"
  mv "$resume_project/provenance.tmp" "$resume_project/$provenance_file"
done
chmod 640 "$resume_project/conversion-state.md"
rm "$resume_project/object-inventory.md"
moved_resume_pdf="$tmp_dir/moved-resume-source.pdf"
mv "$resume_pdf" "$moved_resume_pdf"
"$ensure" "$resume_project" \
  --source-pdf "$moved_resume_pdf" \
  --operation resume \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
assert_file "$resume_project/object-inventory.md"
expected_resume_source=$(python3 - "$moved_resume_pdf" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve())
PY
)
for provenance_file in conversion-state.md conversion-notes.md; do
  grep -Fq "Source PDF: $expected_resume_source" "$resume_project/$provenance_file" || fail "ensure did not rebind a moved resume source in $provenance_file"
  grep -Fq '<!-- Source PDF: /hidden/decoy.pdf -->' "$resume_project/$provenance_file" || fail "source rebind changed hidden metadata in $provenance_file"
done
python3 - "$resume_project" <<'PY'
import pathlib
import stat
import sys

project = pathlib.Path(sys.argv[1])
if stat.S_IMODE(project.joinpath("conversion-state.md").stat().st_mode) != 0o640:
    raise SystemExit("source rebind did not preserve the existing state-file mode")
if stat.S_IMODE(project.joinpath("object-inventory.md").stat().st_mode) != 0o644:
    raise SystemExit("new scaffold files did not honor umask 022")
PY

symlink_pdf="$tmp_dir/symlink-source.pdf"
symlink_project="$tmp_dir/symlink-evidence-project"
symlink_outside="$tmp_dir/symlink-evidence-outside"
make_pdf "$symlink_pdf" 1 symlink-source
"$init" "$symlink_pdf" "$symlink_project" \
  --operation convert \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware >/dev/null
sed 's/^Operation: convert$/Operation: refine/' "$symlink_project/conversion-state.md" >"$symlink_project/state.tmp"
mv "$symlink_project/state.tmp" "$symlink_project/conversion-state.md"
sed 's/^Operation: convert$/Operation: refine/' "$symlink_project/conversion-notes.md" >"$symlink_project/notes.tmp"
mv "$symlink_project/notes.tmp" "$symlink_project/conversion-notes.md"
rm -rf "$symlink_project/evidence"
mkdir -p "$symlink_outside/source-pages"
python3 - "$symlink_pdf" "$symlink_outside/source-pages" <<'PY'
import hashlib
import json
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).resolve()
out_dir = pathlib.Path(sys.argv[2])
out_dir.joinpath("page-001.png").write_bytes(b"PNG evidence\n")
out_dir.joinpath("manifest.json").write_text(
    json.dumps(
        {
            "schema_version": 1,
            "evidence_kind": "source-pages",
            "source_path": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_size_bytes": source.stat().st_size,
            "page_count": 1,
            "pages": [1],
            "page_records": {
                "1": {
                    "png": "page-001.png",
                    "dpi": 90,
                    "renderer": "pdftoppm",
                    "generated_at": "2026-01-01T00:00:00Z",
                }
            },
            "generated_at": "2026-01-01T00:00:00Z",
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY
ln -s "$symlink_outside" "$symlink_project/evidence"
moved_symlink_pdf="$tmp_dir/moved-symlink-source.pdf"
mv "$symlink_pdf" "$moved_symlink_pdf"
expect_failure "$ensure" "$symlink_project" \
  --source-pdf "$moved_symlink_pdf" \
  --operation refine \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware
python3 - "$symlink_outside/source-pages/manifest.json" "$symlink_project/conversion-state.md" "$symlink_pdf" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
state = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
original = str(pathlib.Path(sys.argv[3]).resolve(strict=False))
if manifest["source_path"] != original or f"Source PDF: {original}" not in state:
    raise SystemExit("rejected evidence symlink still changed project provenance")
PY

collision_project="$tmp_dir/collision-project"
collision_outside="$tmp_dir/collision-outside"
mkdir -p "$collision_project" "$collision_outside"
printf '%s\n' '\documentclass{article}\begin{document}Collision\end{document}' >"$collision_project/main.tex"
ln -s "$collision_outside/created.md" "$collision_project/style-profile.md"
expect_failure "$ensure" "$collision_project" \
  --operation refine \
  --source-kind unknown \
  --traits cjk \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope project-only
assert_absent "$collision_outside/created.md"
assert_absent "$collision_project/conversion-state.md"

logs_symlink_project="$tmp_dir/logs-symlink-project"
logs_outside="$tmp_dir/logs-outside"
mkdir -p "$logs_symlink_project" "$logs_outside"
printf '%s\n' '\documentclass{article}\begin{document}Logs\end{document}' >"$logs_symlink_project/main.tex"
ln -s "$logs_outside" "$logs_symlink_project/logs"
expect_failure "$ensure" "$logs_symlink_project" \
  --operation repair \
  --source-kind unknown \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode one-turn \
  --verification-scope project-only
if find "$logs_outside" -mindepth 1 -print -quit | grep -q .; then
  fail 'logs symlink allowed scaffold writes outside the project'
fi

legacy_state_project="$tmp_dir/legacy-state-project"
mkdir -p "$legacy_state_project"
printf '%s\n' '\documentclass{article}\begin{document}Legacy\end{document}' >"$legacy_state_project/main.tex"
printf '%s\n' '# Legacy State' 'Operation: refine' >"$legacy_state_project/conversion-state.md"
expect_failure "$ensure" "$legacy_state_project" \
  --operation refine \
  --source-kind unknown \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope project-only
assert_absent "$legacy_state_project/style-profile.md"

for invalid_state_kind in empty comment-only; do
  invalid_state_project="$tmp_dir/$invalid_state_kind-state-project"
  mkdir -p "$invalid_state_project"
  printf '%s\n' '\documentclass{article}\begin{document}Invalid state\end{document}' >"$invalid_state_project/main.tex"
  if [[ "$invalid_state_kind" == empty ]]; then
    : >"$invalid_state_project/conversion-state.md"
  else
    printf '%s\n' '<!-- Operation: refine -->' >"$invalid_state_project/conversion-state.md"
  fi
  expect_failure "$ensure" "$invalid_state_project" \
    --operation refine \
    --source-kind unknown \
    --traits none \
    --delivery-level clean-semantic \
    --execution-mode resumable \
    --verification-scope project-only
  assert_absent "$invalid_state_project/conversion-notes.md"
  assert_absent "$invalid_state_project/style-profile.md"
done

python3 - "$script_dir/project_scaffold.py" "$tmp_dir" <<'PY'
import importlib.util
import os
import pathlib
import stat
import sys
from unittest import mock

script = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2]) / "transaction-tests"
root.mkdir()
sys.path.insert(0, str(script.parent))
spec = importlib.util.spec_from_file_location("project_scaffold_test", script)
if spec is None or spec.loader is None:
    raise SystemExit("could not load project_scaffold.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

mode_file = root / "mode.md"
mode_file.write_text("old\n", encoding="utf-8")
mode_file.chmod(0o640)
module.commit_file_updates(root, {mode_file: b"new\n"})
if mode_file.read_bytes() != b"new\n" or stat.S_IMODE(mode_file.stat().st_mode) != 0o640:
    raise SystemExit("transactional update did not preserve file content and mode")

fsync_file = root / "fsync.md"
fsync_file.write_text("old\n", encoding="utf-8")
with mock.patch.object(module.os, "fsync", side_effect=OSError("injected fsync failure")):
    try:
        module.commit_file_updates(root, {fsync_file: b"new\n"})
    except module.ScaffoldError:
        pass
    else:
        raise SystemExit("injected fsync failure unexpectedly succeeded")
if fsync_file.read_bytes() != b"old\n":
    raise SystemExit("fsync failure changed the original file")
if list(root.glob(".fsync.md.*")) or list(root.glob(".scaffold-rebind-*")):
    raise SystemExit("fsync failure leaked a temporary file or backup directory")

restore_file = root / "restore.md"
restore_file.write_text("old\n", encoding="utf-8")
real_replace = os.replace
replace_calls = 0

def fail_install_and_restore(source, destination):
    global replace_calls
    replace_calls += 1
    if replace_calls in {2, 3}:
        raise OSError(f"injected replace failure {replace_calls}")
    return real_replace(source, destination)

with mock.patch.object(module.os, "replace", side_effect=fail_install_and_restore):
    try:
        module.commit_file_updates(root, {restore_file: b"new\n"})
    except module.ScaffoldError as exc:
        message = str(exc)
    else:
        raise SystemExit("injected install and restore failures unexpectedly succeeded")
backups = list(root.glob(".scaffold-rebind-*"))
if len(backups) != 1 or str(backups[0]) not in message:
    raise SystemExit("incomplete recovery did not retain and report its backup directory")
backup_files = list(backups[0].iterdir())
if restore_file.exists() or len(backup_files) != 1 or backup_files[0].read_bytes() != b"old\n":
    raise SystemExit("incomplete recovery did not retain the original file")
PY

printf 'Project scaffold tests passed.\n'
