#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
validator="$script_dir/workflow_contract.py"
gate="$script_dir/check_workflow_gates.sh"
export PYTHONDONTWRITEBYTECODE=1

tmp_dir=$(mktemp -d)
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT HUP INT TERM

source_pdf="$tmp_dir/source.pdf"
printf '%%PDF-1.7\nPAGES=1\nworkflow fixture\n' >"$source_pdf"
fake_bin="$tmp_dir/fake-bin"
mkdir -p "$fake_bin"
cat >"$fake_bin/pdfinfo" <<'PY'
#!/usr/bin/env python3
import pathlib
import re
import sys

data = pathlib.Path(sys.argv[-1]).read_text(encoding="utf-8", errors="replace")
match = re.search(r"^PAGES=([0-9]+)$", data, re.MULTILINE)
if match is None:
    raise SystemExit(1)
print(f"Pages: {match.group(1)}")
PY
chmod 755 "$fake_bin/pdfinfo"
PATH="$fake_bin:$PATH"
export PATH
source_sha=$(python3 - "$source_pdf" <<'PY'
import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
source_size=$(python3 - "$source_pdf" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).stat().st_size)
PY
)

fail() {
  printf 'Workflow contract test failed: %s\n' "$*" >&2
  exit 1
}

expect_status() {
  expected=$1
  shift
  set +e
  "$@" >"$tmp_dir/last.stdout" 2>"$tmp_dir/last.stderr"
  actual=$?
  set -e
  if [ "$actual" -ne "$expected" ]; then
    sed -n '1,120p' "$tmp_dir/last.stdout" >&2
    sed -n '1,160p' "$tmp_dir/last.stderr" >&2
    fail "expected exit $expected, received $actual from $*"
  fi
}

write_record_file() {
  path=$1
  status=$2
  {
    printf '# Workflow Record\n\n'
    printf '### Record: coverage\n'
    printf 'Status: %s\n' "$status"
    printf 'Compile check: pass\n'
    printf 'Visual review: not-applicable\n'
    printf 'Reason:\n'
    printf 'Next action: None; record is current.\n'
  } >"$path"
}

create_state_project() {
  project=$1
  operation=$2
  source_kind=$3
  traits=$4
  delivery=$5
  execution=$6
  verification=$7
  outcome=$8

  mkdir -p "$project"
  final_status=pending
  compile_check=not-run
  visual_review=not-run
  source_fidelity=in-progress
  previous_delivery=
  downgrade_approval=
  if [ "$outcome" = complete ] || [ "$outcome" = downgraded ]; then
    final_status=reviewed
    compile_check=pass
    if [ "$verification" = source-aware ]; then
      visual_review=pass
      source_fidelity=verified
    else
      if [ "$delivery" = publication-polish ]; then
        visual_review=pass
      else
        visual_review=not-applicable
      fi
      source_fidelity=not-verified-by-scope
    fi
  fi
  if [ "$outcome" = downgraded ]; then
    previous_delivery=publication-polish
    downgrade_approval='User approved clean-semantic delivery.'
  fi

  "$validator" required-files \
    --operation "$operation" \
    --source-kind "$source_kind" \
    --traits "$traits" \
    --delivery-level "$delivery" \
    --execution-mode "$execution" \
    --verification-scope "$verification" |
  while IFS= read -r relative; do
    mkdir -p "$(dirname -- "$project/$relative")"
    case "$relative" in
      main.tex)
        printf '%s\n' '\documentclass{article}\begin{document}Test\end{document}' >"$project/$relative"
        ;;
      conversion-state.md|conversion-notes.md)
        ;;
      *)
        write_record_file "$project/$relative" "$final_status"
        ;;
    esac
  done

  {
    printf '# Conversion Notes\n\n'
    printf 'State schema: 2\n'
    printf 'Skill version: 1.0.0\n'
    printf 'Contract version: 1\n'
    printf 'Source PDF: %s\n' "$source_pdf"
    printf 'Operation: %s\n' "$operation"
    printf 'Source kind: %s\n' "$source_kind"
    printf 'Document traits: %s\n' "$traits"
    printf 'Delivery level: %s\n' "$delivery"
    printf 'Execution mode: %s\n' "$execution"
    printf 'Verification scope: %s\n' "$verification"
    printf 'Outcome: %s\n' "$outcome"
    printf '\n## Notes\n\nFixture notes.\n'
  } >"$project/conversion-notes.md"

  {
    printf '# Conversion State\n\n'
    printf 'State schema: 2\n'
    printf 'Skill version: 1.0.0\n'
    printf 'Contract version: 1\n'
    printf 'Source PDF: %s\n' "$source_pdf"
    printf 'Source PDF SHA-256: %s\n' "$source_sha"
    printf 'Source PDF size bytes: %s\n' "$source_size"
    printf 'Source PDF page count: 1\n'
    printf 'Operation: %s\n' "$operation"
    printf 'Source kind: %s\n' "$source_kind"
    printf 'Document traits: %s\n' "$traits"
    printf 'Delivery level: %s\n' "$delivery"
    printf 'Execution mode: %s\n' "$execution"
    printf 'Verification scope: %s\n' "$verification"
    printf 'Outcome: %s\n' "$outcome"
    printf 'Compile check: %s\n' "$compile_check"
    printf 'Visual review: %s\n' "$visual_review"
    printf 'Source fidelity: %s\n' "$source_fidelity"
    printf 'Previous delivery level: %s\n' "$previous_delivery"
    printf 'Downgrade approval: %s\n' "$downgrade_approval"
    printf 'Next action: None; fixture workflow has reached its recorded outcome.\n'
    printf '\n## Required Gates\n\n'
    if [ "$final_status" = reviewed ]; then
      "$validator" render-gates \
        --operation "$operation" \
        --source-kind "$source_kind" \
        --traits "$traits" \
        --delivery-level "$delivery" \
        --execution-mode "$execution" \
        --verification-scope "$verification" |
        sed 's/^Status: pending$/Status: reviewed/'
    else
      "$validator" render-gates \
        --operation "$operation" \
        --source-kind "$source_kind" \
        --traits "$traits" \
        --delivery-level "$delivery" \
        --execution-mode "$execution" \
        --verification-scope "$verification"
    fi
    if [ "$outcome" = blocked ]; then
      printf '\n### Blocker: unreadable-source-region\n'
      printf 'Status: blocked\n'
      printf 'Reason: Source page 1 is unreadable.\n'
      printf 'Next action: Request a clearer source page.\n'
    fi
  } >"$project/conversion-state.md"
}

"$validator" validate-contract >/dev/null
contract_path="$script_dir/../references/workflow-contract.json"
stateful_gates=$("$validator" required-gates \
  --operation convert \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware)
for required_gate in workflow-setup build-verification final-state-review; do
  printf '%s\n' "$stateful_gates" | grep -Fxq "$required_gate" || fail "stateful workflow omitted $required_gate"
done
math_files=$("$validator" required-files \
  --operation refine \
  --source-kind digital \
  --traits math-heavy \
  --delivery-level clean-semantic \
  --execution-mode resumable \
  --verification-scope source-aware)
for required_file in object-inventory.md math-inventory.md glyph-map.md; do
  printf '%s\n' "$math_files" | grep -Fxq "$required_file" || fail "math workflow omitted $required_file"
done

bad_contract="$tmp_dir/bad-contract.json"
python3 - "$contract_path" "$bad_contract" <<'PY'
import json
import pathlib
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
contract = json.loads(source.read_text(encoding="utf-8"))
del contract["constraints"]["delivery_rank"]
destination.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
PY
expect_status 1 "$validator" --contract "$bad_contract" validate-contract

bad_math_contract="$tmp_dir/bad-math-contract.json"
python3 - "$contract_path" "$bad_math_contract" <<'PY'
import json
import pathlib
import sys

contract = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
for rule in contract["path_rules"]:
    if rule["id"] == "math-model":
        rule["require_files"] = ["object-inventory.md"]
        break
pathlib.Path(sys.argv[2]).write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
PY
expect_status 1 "$validator" --contract "$bad_math_contract" validate-contract
grep -Fq 'path_rules rule math-model outputs do not match schema 2' "$tmp_dir/last.stderr" || fail 'math-model semantic mutation was not diagnosed'

bad_gate_contract="$tmp_dir/bad-gate-contract.json"
python3 - "$contract_path" "$bad_gate_contract" <<'PY'
import json
import pathlib
import sys

contract = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
for rule in contract["gate_rules"]:
    if rule["id"] == "stateful-base":
        rule["require_gates"] = ["workflow-setup"]
        break
pathlib.Path(sys.argv[2]).write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
PY
expect_status 1 "$validator" --contract "$bad_gate_contract" validate-contract
grep -Fq 'gate_rules rule stateful-base outputs do not match schema 2' "$tmp_dir/last.stderr" || fail 'stateful-base semantic mutation was not diagnosed'

rm -rf "$script_dir/__pycache__"
"$validator" validate-package "$script_dir/.." >/dev/null

missing_goal_skill="$tmp_dir/missing-goal-skill"
cp -R "$script_dir/.." "$missing_goal_skill"
rm "$missing_goal_skill/references/goal-mode.md"
expect_status 1 "$validator" validate-package "$missing_goal_skill"
grep -Fq 'Missing package file: references/goal-mode.md' "$tmp_dir/last.stderr" || fail 'package validation accepted a missing Goal reference'

missing_goal_policy_skill="$tmp_dir/missing-goal-policy-skill"
cp -R "$script_dir/.." "$missing_goal_policy_skill"
python3 - "$missing_goal_policy_skill/SKILL.md" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace("never block on Goal startup", "optionally wait for Goal startup")
text = text.replace("use `resumable` by default", "prefer goal-backed by default")
text = text.replace("Never block on Goal startup", "Optionally wait for Goal startup")
text = text.replace("references/goal-mode.md", "references/pdf-analysis.md")
path.write_text(text, encoding="utf-8")
PY
expect_status 1 "$validator" validate-package "$missing_goal_policy_skill"
grep -Fq 'SKILL.md must reference references/goal-mode.md' "$tmp_dir/last.stderr" || fail 'package validation accepted a missing Goal reference route'
grep -Fq 'SKILL.md must never block on Goal startup' "$tmp_dir/last.stderr" || fail 'package validation accepted a missing never-block-on-Goal policy'

missing_run_to_completion_skill="$tmp_dir/missing-run-to-completion-skill"
cp -R "$script_dir/.." "$missing_run_to_completion_skill"
python3 - "$missing_run_to_completion_skill/SKILL.md" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = re.sub(r"run-to-completion", "run-in-stages", text, flags=re.IGNORECASE)
text = text.replace("Never ask the user whether to continue", "Optionally ask the user whether to continue")
text = text.replace(
    "never ask the user whether to continue",
    "optionally ask the user whether to continue",
)
text = text.replace("是否继续", "optional-continue-token")
path.write_text(text, encoding="utf-8")
PY
expect_status 1 "$validator" validate-package "$missing_run_to_completion_skill"
grep -Fq 'SKILL.md must declare run-to-completion as the hard default' "$tmp_dir/last.stderr" || fail 'package validation accepted missing run-to-completion default'
grep -Fq 'SKILL.md must forbid asking the user whether to continue ordinary reconstruction' "$tmp_dir/last.stderr" || fail 'package validation accepted continue-prompt permission'
grep -Fq 'SKILL.md must explicitly ban 是否继续 continue-prompts' "$tmp_dir/last.stderr" || fail 'package validation accepted missing 是否继续 ban'

missing_slash_command_skill="$tmp_dir/missing-slash-command-skill"
cp -R "$script_dir/.." "$missing_slash_command_skill"
python3 - "$missing_slash_command_skill/SKILL.md" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
path.write_text(text.replace("/pdf-to-latex", "pdf-to-latex"), encoding="utf-8")
PY
expect_status 1 "$validator" validate-package "$missing_slash_command_skill"
grep -Fq 'SKILL.md description must advertise the /pdf-to-latex slash command' "$tmp_dir/last.stderr" || fail 'package validation accepted a description without /pdf-to-latex'

codex_residue_skill="$tmp_dir/codex-residue-skill"
cp -R "$script_dir/.." "$codex_residue_skill"
python3 - "$codex_residue_skill/SKILL.md" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
path.write_text(text.replace("Grok performs the reconstruction.", "Codex performs the reconstruction."), encoding="utf-8")
PY
expect_status 1 "$validator" validate-package "$codex_residue_skill"
grep -Fq 'SKILL.md must not reference Codex or $pdf-to-latex' "$tmp_dir/last.stderr" || fail 'package validation accepted Codex residue in SKILL.md'

incomplete_goal_reference_skill="$tmp_dir/incomplete-goal-reference-skill"
cp -R "$script_dir/.." "$incomplete_goal_reference_skill"
printf '%s\n' '# Continuity' >"$incomplete_goal_reference_skill/references/goal-mode.md"
expect_status 1 "$validator" validate-package "$incomplete_goal_reference_skill"
grep -Fq 'references/goal-mode.md is missing required rule: never block on Goal startup' "$tmp_dir/last.stderr" || fail 'package validation accepted an incomplete Goal reference'

missing_goal_runtime_rules_skill="$tmp_dir/missing-goal-runtime-rules-skill"
cp -R "$script_dir/.." "$missing_goal_runtime_rules_skill"
python3 - "$missing_goal_runtime_rules_skill/references/goal-mode.md" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
replacements = {
    "Check current Goal state": "Observe Goal availability",
    "Do not set a token budget unless the user explicitly requested one": "Choose a suitable token budget",
    "Mark a matching Goal complete only after": "Conclude a matching Goal when",
    "blocker threshold": "blocking policy",
    "Never block on Goal startup": "Prefer waiting for Goal startup",
    "use `resumable` by default": "use goal-backed by default",
}
for old, new in replacements.items():
    text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
PY
expect_status 1 "$validator" validate-package "$missing_goal_runtime_rules_skill"
grep -Fq 'missing required rule: existing Goal inspection' "$tmp_dir/last.stderr" || fail 'package validation accepted Goal startup without existing-state inspection'
grep -Fq 'missing required rule: explicit token-budget authority' "$tmp_dir/last.stderr" || fail 'package validation accepted implicit Goal token budgets'
grep -Fq 'missing required rule: terminal completion validation' "$tmp_dir/last.stderr" || fail 'package validation accepted weak Goal completion rules'
grep -Fq 'missing required rule: Goal blocker-threshold handling' "$tmp_dir/last.stderr" || fail 'package validation accepted weak Goal blocker handling'
grep -Fq 'missing required rule: never block on Goal startup' "$tmp_dir/last.stderr" || fail 'package validation accepted hard-wait Goal policy'

missing_self_updater_skill="$tmp_dir/missing-self-updater-skill"
cp -R "$script_dir/.." "$missing_self_updater_skill"
rm "$missing_self_updater_skill/scripts/update_installed_skill.sh"
expect_status 1 "$validator" validate-package "$missing_self_updater_skill"
grep -Fq 'Missing package file: scripts/update_installed_skill.sh' "$tmp_dir/last.stderr" || fail 'package validation accepted a missing self-updater'

missing_self_update_route_skill="$tmp_dir/missing-self-update-route-skill"
cp -R "$script_dir/.." "$missing_self_update_route_skill"
python3 - "$missing_self_update_route_skill/SKILL.md" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace(
    "update skill https://github.com/zuchengchen/pdf-to-latex-grok.git",
    "refresh the installed package",
)
text = text.replace(
    "更新skill https://github.com/zuchengchen/pdf-to-latex-grok.git",
    "刷新已安装包",
)
text = text.replace(
    "install skill https://github.com/zuchengchen/pdf-to-latex-grok.git",
    "bootstrap the package",
)
text = text.replace(
    "安装skill https://github.com/zuchengchen/pdf-to-latex-grok.git",
    "引导安装包",
)
text = text.replace("scripts/update_installed_skill.sh", "scripts/check_environment.sh")
text = text.replace(
    "Only enter this route when the trimmed request matches exactly",
    "Enter this route for related requests",
)
path.write_text(text, encoding="utf-8")
PY
expect_status 1 "$validator" validate-package "$missing_self_update_route_skill"
grep -Fq 'description must advertise the update skill https://github.com/zuchengchen/pdf-to-latex-grok.git trigger' "$tmp_dir/last.stderr" || fail 'package validation accepted a missing English self-update trigger'
grep -Fq 'description must advertise the 更新skill https://github.com/zuchengchen/pdf-to-latex-grok.git trigger' "$tmp_dir/last.stderr" || fail 'package validation accepted a missing Chinese self-update trigger'
grep -Fq 'description must advertise the install skill https://github.com/zuchengchen/pdf-to-latex-grok.git trigger' "$tmp_dir/last.stderr" || fail 'package validation accepted a missing English install trigger'
grep -Fq 'description must advertise the 安装skill https://github.com/zuchengchen/pdf-to-latex-grok.git trigger' "$tmp_dir/last.stderr" || fail 'package validation accepted a missing Chinese install trigger'
grep -Fq 'SKILL.md must reference scripts/update_installed_skill.sh' "$tmp_dir/last.stderr" || fail 'package validation accepted a missing self-update route'
grep -Fq 'SKILL.md must invoke the self-updater through Bash' "$tmp_dir/last.stderr" || fail 'package validation accepted a non-portable self-update invocation'
grep -Fq 'SKILL.md must restrict self-update to exact command forms' "$tmp_dir/last.stderr" || fail 'package validation accepted broad self-update routing'

mutated_skill="$tmp_dir/mutated-skill"
cp -R "$script_dir/.." "$mutated_skill"
python3 - "$mutated_skill/references/workflow-contract.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
contract = json.loads(path.read_text(encoding="utf-8"))
for rule in contract["gate_rules"]:
    if rule["id"] == "stateful-base":
        rule["require_gates"] = ["workflow-setup"]
        break
path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
PY
expect_status 1 "$validator" validate-package "$mutated_skill"
grep -Fq 'gate_rules rule stateful-base outputs do not match schema 2' "$tmp_dir/last.stderr" || fail 'package validation accepted a semantic rule mutation'

convert_project="$tmp_dir/convert"
create_state_project "$convert_project" convert digital none rough-draft one-turn source-aware complete
expect_status 0 "$gate" "$convert_project"

resume_project="$tmp_dir/resume-book"
create_state_project "$resume_project" resume digital book clean-semantic resumable source-aware complete
if [ -e "$resume_project/math-inventory.md" ]; then
  fail 'book trait must not imply math-inventory.md'
fi
expect_status 0 "$gate" "$resume_project"

refine_project="$tmp_dir/refine-publication"
create_state_project "$refine_project" refine mixed visual-complex publication-polish goal-backed source-aware complete
expect_status 0 "$gate" "$refine_project"

repair_project="$tmp_dir/repair-math"
create_state_project "$repair_project" repair unknown math-heavy clean-semantic resumable project-only complete
expect_status 0 "$gate" "$repair_project"
rm "$repair_project/math-inventory.md"
expect_status 1 "$gate" "$repair_project"

one_turn_repair="$tmp_dir/one-turn-repair"
mkdir -p "$one_turn_repair"
printf '%s\n' '\documentclass{article}\begin{document}Repair\end{document}' >"$one_turn_repair/main.tex"
expect_status 0 "$gate" "$one_turn_repair" \
  --operation repair \
  --source-kind unknown \
  --traits math-heavy \
  --delivery-level clean-semantic \
  --execution-mode one-turn \
  --verification-scope project-only \
  --outcome complete \
  --compile-check pass \
  --visual-review not-applicable \
  --source-fidelity not-verified-by-scope \
  --next-action 'None; repair is complete.'
if [ -e "$one_turn_repair/conversion-state.md" ] || [ -e "$one_turn_repair/math-inventory.md" ]; then
  fail 'one-turn non-publication repair must remain stateless and minimal'
fi

one_turn_publication="$tmp_dir/one-turn-publication"
mkdir -p "$one_turn_publication"
printf '%s\n' '\documentclass{article}\begin{document}Publication repair\end{document}' >"$one_turn_publication/main.tex"
expect_status 1 "$gate" "$one_turn_publication" \
  --operation repair \
  --source-kind unknown \
  --traits none \
  --delivery-level publication-polish \
  --execution-mode one-turn \
  --verification-scope project-only \
  --outcome complete \
  --compile-check pass \
  --visual-review not-applicable \
  --source-fidelity not-verified-by-scope \
  --next-action 'None; repair is complete.'

stateful_one_turn_publication="$tmp_dir/stateful-one-turn-publication"
create_state_project "$stateful_one_turn_publication" repair unknown none publication-polish one-turn project-only complete
expect_status 0 "$gate" "$stateful_one_turn_publication"

stateful_publication_math="$tmp_dir/stateful-publication-math"
create_state_project "$stateful_publication_math" repair digital math-heavy publication-polish one-turn source-aware complete
expect_status 0 "$gate" "$stateful_publication_math"
grep -Fq '### Gate: source-fidelity-review' "$stateful_publication_math/conversion-state.md" || fail 'source-aware publication repair gate is missing'
grep -Fq '### Gate: math-object-review' "$stateful_publication_math/conversion-state.md" || fail 'math publication repair gate is missing'

review_project="$tmp_dir/review"
mkdir -p "$review_project"
printf '%s\n' '\documentclass{article}\begin{document}Review\end{document}' >"$review_project/main.tex"
expect_status 0 "$gate" "$review_project" \
  --operation review \
  --source-kind digital \
  --traits none \
  --delivery-level clean-semantic \
  --execution-mode one-turn \
  --verification-scope project-only \
  --outcome complete \
  --compile-check pass \
  --visual-review pass \
  --source-fidelity not-verified-by-scope \
  --next-action 'None; review is complete.'
if [ -e "$review_project/conversion-state.md" ]; then
  fail 'review validation must not create conversion-state.md'
fi

publication_review="$tmp_dir/publication-review"
mkdir -p "$publication_review"
printf '%s\n' '\documentclass{article}\begin{document}Publication review\end{document}' >"$publication_review/main.tex"
expect_status 1 "$gate" "$publication_review" \
  --operation review \
  --source-kind digital \
  --traits none \
  --delivery-level publication-polish \
  --execution-mode one-turn \
  --verification-scope project-only \
  --outcome complete \
  --compile-check pass \
  --visual-review pass \
  --source-fidelity not-verified-by-scope \
  --next-action 'None; publication review is complete.'
expect_status 0 "$gate" "$publication_review" \
  --operation review \
  --source-kind digital \
  --traits none \
  --delivery-level publication-polish \
  --execution-mode one-turn \
  --verification-scope project-only \
  --outcome complete \
  --compile-check pass \
  --visual-review pass \
  --source-fidelity not-verified-by-scope \
  --next-action 'None; publication review is complete.' \
  --gate artifact-scan reviewed \
  --gate clean-room-build reviewed \
  --gate publication-review reviewed

source_review="$tmp_dir/source-review"
mkdir -p "$source_review"
printf '%s\n' '\documentclass{article}\begin{document}Source review\end{document}' >"$source_review/main.tex"
expect_status 0 "$gate" "$source_review" \
  --operation review \
  --source-kind digital \
  --traits book,math-heavy \
  --delivery-level clean-semantic \
  --execution-mode one-turn \
  --verification-scope source-aware \
  --outcome complete \
  --compile-check pass \
  --visual-review pass \
  --source-fidelity verified \
  --next-action 'None; source review is complete.' \
  --source-pdf "$source_pdf" \
  --source-sha256 "$source_sha" \
  --source-size-bytes "$source_size" \
  --source-page-count 1 \
  --gate source-fidelity-review reviewed \
  --gate book-structure-review reviewed \
  --gate math-object-review reviewed

downgraded_project="$tmp_dir/downgraded"
create_state_project "$downgraded_project" repair unknown cjk clean-semantic resumable project-only downgraded
expect_status 0 "$gate" "$downgraded_project"

blocked_project="$tmp_dir/blocked"
create_state_project "$blocked_project" repair unknown none clean-semantic resumable project-only blocked
expect_status 2 "$gate" "$blocked_project"

in_progress_project="$tmp_dir/in-progress"
create_state_project "$in_progress_project" repair unknown none clean-semantic resumable project-only in-progress
expect_status 1 "$gate" "$in_progress_project"

missing_field_project="$tmp_dir/missing-field"
cp -R "$convert_project" "$missing_field_project"
sed '/^Delivery level:/d' "$missing_field_project/conversion-state.md" >"$missing_field_project/state.tmp"
mv "$missing_field_project/state.tmp" "$missing_field_project/conversion-state.md"
expect_status 1 "$gate" "$missing_field_project"

bad_blocker_project="$tmp_dir/bad-blocker"
cp -R "$blocked_project" "$bad_blocker_project"
sed 's/^Reason: Source page 1 is unreadable\.$/Reason:/' "$bad_blocker_project/conversion-state.md" >"$bad_blocker_project/state.tmp"
mv "$bad_blocker_project/state.tmp" "$bad_blocker_project/conversion-state.md"
expect_status 1 "$gate" "$bad_blocker_project"

bad_status_project="$tmp_dir/bad-status"
create_state_project "$bad_status_project" repair unknown cjk clean-semantic resumable project-only complete
awk '
  !changed && $0 == "Status: reviewed" { print "Status: compiled"; changed = 1; next }
  { print }
' "$bad_status_project/style-profile.md" >"$bad_status_project/style.tmp"
mv "$bad_status_project/style.tmp" "$bad_status_project/style-profile.md"
expect_status 1 "$gate" "$bad_status_project"

legacy_project="$tmp_dir/legacy-profile"
cp -R "$convert_project" "$legacy_project"
awk '
  $0 ~ /^Operation:/ { print "Task profile: standard" }
  { print }
' "$legacy_project/conversion-state.md" >"$legacy_project/state.tmp"
mv "$legacy_project/state.tmp" "$legacy_project/conversion-state.md"
expect_status 1 "$gate" "$legacy_project"

tampered_identity="$tmp_dir/tampered-identity"
cp -R "$convert_project" "$tampered_identity"
sed 's/^Source PDF SHA-256:.*/Source PDF SHA-256: 0000000000000000000000000000000000000000000000000000000000000000/' \
  "$tampered_identity/conversion-state.md" >"$tampered_identity/state.tmp"
mv "$tampered_identity/state.tmp" "$tampered_identity/conversion-state.md"
expect_status 1 "$gate" "$tampered_identity"

commented_state="$tmp_dir/commented-state"
cp -R "$convert_project" "$commented_state"
{
  printf '<!--\n'
  cat "$commented_state/conversion-state.md"
  printf '%s\n' '-->'
} >"$commented_state/state.tmp"
mv "$commented_state/state.tmp" "$commented_state/conversion-state.md"
expect_status 1 "$gate" "$commented_state"

indented_state="$tmp_dir/indented-state"
cp -R "$convert_project" "$indented_state"
sed 's/^/    /' "$indented_state/conversion-state.md" >"$indented_state/state.tmp"
mv "$indented_state/state.tmp" "$indented_state/conversion-state.md"
expect_status 1 "$gate" "$indented_state"

python3 - "$convert_project" "$tmp_dir" <<'PY'
import pathlib
import shutil
import sys

source = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
for name, prefix in (
    ("space-tab-state", " \t"),
    ("two-space-tab-state", "  \t"),
    ("three-space-tab-state", "   \t"),
    ("tab-state", "\t"),
):
    destination = root / name
    shutil.copytree(source, destination)
    state = destination / "conversion-state.md"
    lines = state.read_text(encoding="utf-8").splitlines(keepends=True)
    state.write_text("".join(prefix + line for line in lines), encoding="utf-8")
PY
for mixed_indent_project in \
  "$tmp_dir/space-tab-state" \
  "$tmp_dir/two-space-tab-state" \
  "$tmp_dir/three-space-tab-state" \
  "$tmp_dir/tab-state"; do
  expect_status 1 "$gate" "$mixed_indent_project"
done

python3 - "$convert_project" "$tmp_dir" <<'PY'
import pathlib
import shutil
import sys

source = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
prefixes = {
    "fenced-comment-state": "```text\n<!-- literal comment opener\n```\n",
    "long-fence-comment-state": "````text\n``` shorter literal fence\n````\n",
    "fence-info-closing-state": "````text\n```` not a closing fence\n````\n",
    "indented-comment-state": "    <!-- literal comment opener\n",
    "inline-comment-state": "`<!-- literal comment opener`\n",
    "multiline-inline-comment-state": "`multiline code span\n<!-- literal comment opener\nclosing delimiter`\n",
}
for name, prefix in prefixes.items():
    destination = root / name
    shutil.copytree(source, destination)
    with destination.joinpath("page-manifest.md").open("a", encoding="utf-8") as handle:
        handle.write("\n" + prefix)
        handle.write("\n### Page: visible-after-code\n")
        handle.write("Status: pending\n")
        handle.write("Reason:\n")
        handle.write("Next action: Review this visible record.\n")
PY
for comment_code_project in \
  "$tmp_dir/fenced-comment-state" \
  "$tmp_dir/long-fence-comment-state" \
  "$tmp_dir/fence-info-closing-state" \
  "$tmp_dir/indented-comment-state" \
  "$tmp_dir/inline-comment-state" \
  "$tmp_dir/multiline-inline-comment-state"; do
  expect_status 1 "$gate" "$comment_code_project"
done

realigned_field_project="$tmp_dir/realigned-inline-field"
cp -R "$convert_project" "$realigned_field_project"
awk '
  !changed && $0 == "Status: reviewed" { print "`literal`Status: reviewed"; changed = 1; next }
  { print }
' "$realigned_field_project/conversion-state.md" >"$realigned_field_project/state.tmp"
mv "$realigned_field_project/state.tmp" "$realigned_field_project/conversion-state.md"
expect_status 1 "$gate" "$realigned_field_project"

statusless_record="$tmp_dir/statusless-record"
cp -R "$convert_project" "$statusless_record"
{
  printf '\n### Page: statusless\n'
  printf 'Reason: This visible lifecycle record intentionally lacks Status.\n'
  printf 'Next action: Add the required lifecycle status.\n'
} >>"$statusless_record/page-manifest.md"
expect_status 1 "$gate" "$statusless_record"

printf 'Workflow contract tests passed.\n'
