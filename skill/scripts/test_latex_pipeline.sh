#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s [--portable|--integration] [--require-tools]\n' "$0" >&2
}

require_tools=false
mode=auto
while [[ $# -gt 0 ]]; do
  case "$1" in
    --portable|--integration)
      if [[ "$mode" != auto ]]; then
        usage
        exit 2
      fi
      mode=${1#--}
      ;;
    --require-tools)
      require_tools=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
  shift
done

if [[ "$mode" == portable && "$require_tools" == true ]]; then
  usage
  exit 2
fi

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
tmp_dir=$(mktemp -d)
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT HUP INT TERM
export PYTHONDONTWRITEBYTECODE=1

if ! command -v python3 >/dev/null 2>&1; then
  printf 'Missing required test tool: python3\n' >&2
  exit 1
fi

python3 - "$script_dir" "$tmp_dir" <<'PY'
import os
import pathlib
import sys

sys.path.insert(0, sys.argv[1])
from latex_pipeline import clean_environment

root = pathlib.Path(sys.argv[2])
untrusted = root / "untrusted-bin"
untrusted.mkdir()
home = root / "clean-home"
environment = clean_environment(
    {
        "PATH": os.pathsep.join((str(untrusted), "/usr/bin", "/bin")),
        "HOME": "/untrusted/home",
        "LATEXMKRC": "/untrusted/latexmkrc",
        "PERL5OPT": "-MInjected",
        "LD_PRELOAD": "/untrusted/preload.so",
        "DYLD_INSERT_LIBRARIES": "/untrusted/inject.dylib",
        "BASH_FUNC_python3%%": "() { touch /untrusted/bash-function; }",
        "PYTHONPATH": "/untrusted/python",
        "TEXINPUTS": "/untrusted/tex",
        "openin_any": "a",
        "openout_any": "a",
    },
    home=home,
)
assert str(untrusted) not in environment["PATH"].split(os.pathsep)
assert environment["HOME"] == str(home)
assert environment["TEXMFHOME"] == str(home / "texmf")
assert environment["TMPDIR"] == str(home / "tmp")
assert environment["openin_any"] == "p"
assert environment["openout_any"] == "p"
for name in (
    "LATEXMKRC",
    "PERL5OPT",
    "LD_PRELOAD",
    "DYLD_INSERT_LIBRARIES",
    "BASH_FUNC_python3%%",
    "PYTHONPATH",
    "TEXINPUTS",
):
    assert name not in environment

declared_tool = untrusted / "latexmk"
declared_tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
declared_tool.chmod(0o755)
declared = clean_environment(
    {"PATH": os.pathsep.join((str(untrusted), "/usr/bin", "/bin"))}
)
assert str(untrusted) in declared["PATH"].split(os.pathsep)

launcher = root / "launcher"
relative_tools = launcher / "tools"
relative_tools.mkdir(parents=True)
relative_latexmk = relative_tools / "latexmk"
relative_latexmk.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
relative_latexmk.chmod(0o755)
previous_cwd = pathlib.Path.cwd()
try:
    os.chdir(launcher)
    relative = clean_environment({"PATH": os.pathsep.join(("tools", "/usr/bin", "/bin"))})
finally:
    os.chdir(previous_cwd)
path_entries = relative["PATH"].split(os.pathsep)
assert str(relative_tools.resolve()) in path_entries
assert all(pathlib.Path(entry).is_absolute() for entry in path_entries)
PY

relative_launcher="$tmp_dir/relative-launcher"
relative_project="$tmp_dir/relative-path-project"
trusted_marker="$tmp_dir/trusted-tool-ran"
malicious_marker="$tmp_dir/project-tool-ran"
mkdir -p "$relative_launcher/tools" "$relative_project/tools"
cat >"$relative_launcher/tools/latexmk" <<'SH'
#!/usr/bin/env bash
touch "$TRUSTED_MARKER"
exit 17
SH
cat >"$relative_launcher/tools/xelatex" <<'SH'
#!/usr/bin/env bash
exit 17
SH
cat >"$relative_project/tools/latexmk" <<'SH'
#!/usr/bin/env bash
touch "$MALICIOUS_MARKER"
exit 0
SH
chmod 755 \
  "$relative_launcher/tools/latexmk" \
  "$relative_launcher/tools/xelatex" \
  "$relative_project/tools/latexmk"
printf '%s\n' '\documentclass{article}\begin{document}Relative PATH\end{document}' >"$relative_project/main.tex"
if (
  cd "$relative_launcher"
  TRUSTED_MARKER="$trusted_marker" MALICIOUS_MARKER="$malicious_marker" \
    PATH="tools:/usr/bin:/bin" "$script_dir/latex_healthcheck.sh" \
    "$relative_project" main.tex >/dev/null 2>&1
); then
  printf 'Expected trusted relative tool fixture to report its injected failure.\n' >&2
  exit 1
fi
if [[ ! -e "$trusted_marker" || -e "$malicious_marker" ]]; then
  printf 'Relative PATH was reinterpreted under the project directory.\n' >&2
  exit 1
fi

python3 - "$script_dir" "$tmp_dir" <<'PY'
import os
import pathlib
import sys

sys.path.insert(0, sys.argv[1])
from latex_pipeline import classify_dependencies, system_roots

root = pathlib.Path(sys.argv[2])
project = root / "dependency-project"
external = root / "external-texmf"
project.mkdir()
external.mkdir()
external_input = external / "secret.sty"
external_input.write_text("external dependency\n", encoding="utf-8")
fls = project / "main.fls"
fls.write_text(f"INPUT {external_input}\n", encoding="utf-8")
environment = os.environ.copy()
environment["TEXMFLOCAL"] = str(external)
report = classify_dependencies(fls, project, environment=environment)
assert str(external_input.resolve()) in report["external"]
assert str(external_input.resolve()) not in report["system"]
external_bib = external / "references.bib"
external_bib.write_text("@book{x,title={External}}\n", encoding="utf-8")
(project / "main.blg").write_text(
    f"Database file #1: {external_bib}\n", encoding="utf-8"
)
aux_report = classify_dependencies(fls, project, environment=os.environ.copy())
assert str(external_bib.resolve()) in aux_report["external"]
nested_log = project / "chapters" / "one.blg"
nested_log.parent.mkdir()
nested_log.write_text(f"Database file #1: {external_bib}\n", encoding="utf-8")
nested_report = classify_dependencies(fls, project, environment=os.environ.copy())
assert str(external_bib.resolve()) in nested_report["external"]

system_one = root / "system-texmf-one"
system_two = root / "system-texmf-two"
probe_bin = root / "probe-bin"
system_one.mkdir()
system_two.mkdir()
probe_bin.mkdir()
kpsewhich = probe_bin / "kpsewhich"
kpsewhich.write_text(
    f"#!/bin/sh\nprintf '%s\\n' '{system_one}:{system_two}'\n",
    encoding="utf-8",
)
kpsewhich.chmod(0o755)
roots = system_roots(
    {"PATH": os.pathsep.join((str(probe_bin), "/usr/bin", "/bin"))}
)
assert system_one.resolve() in roots
assert system_two.resolve() in roots
host_file = pathlib.Path("/etc/hostname")
if host_file.exists():
    fls.write_text(f"INPUT {host_file}\n", encoding="utf-8")
    host_report = classify_dependencies(fls, project, environment=os.environ.copy())
    assert str(host_file.resolve()) in host_report["external"]
PY

artifact_project="$tmp_dir/logs/artifact"
mkdir -p "$artifact_project/chapters"
printf '\\documentclass{article}\\begin{document}Clean\\end{document}\n' >"$artifact_project/main.tex"
"$script_dir/check_latex_artifacts.sh" "$artifact_project" >/dev/null
printf '\\pdfglyph{unresolved}\n' >"$artifact_project/chapters/content.tex"
if "$script_dir/check_latex_artifacts.sh" "$artifact_project" >/dev/null 2>&1; then
  printf 'Expected artifact scan to reject unresolved glyph markers.\n' >&2
  exit 1
fi

nested_artifact_project="$tmp_dir/nested-artifact"
mkdir -p "$nested_artifact_project/chapters/logs"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  '\input{chapters/logs/content}' \
  '\end{document}' >"$nested_artifact_project/main.tex"
printf 'TODO math\n' >"$nested_artifact_project/chapters/logs/content.tex"
if "$script_dir/check_latex_artifacts.sh" "$nested_artifact_project" >/dev/null 2>&1; then
  printf 'Expected nested logs directory source to remain in the artifact scan.\n' >&2
  exit 1
fi

inc_artifact_project="$tmp_dir/inc-artifact"
mkdir -p "$inc_artifact_project"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  '\input{content.inc}' \
  '\end{document}' >"$inc_artifact_project/main.tex"
printf 'TODO math\n' >"$inc_artifact_project/content.inc"
if "$script_dir/check_latex_artifacts.sh" "$inc_artifact_project" >/dev/null 2>&1; then
  printf 'Expected .inc LaTeX inputs to remain in the artifact scan.\n' >&2
  exit 1
fi

external_source="$tmp_dir/external-source.tex"
printf 'External source\n' >"$external_source"
external_project="$tmp_dir/logs/external-project"
mkdir -p "$external_project"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  "\\input{$external_source}" \
  '\end{document}' >"$external_project/main.tex"
if "$script_dir/latex_healthcheck.sh" "$external_project" main.tex >/dev/null 2>&1; then
  printf 'Expected healthcheck to reject project-external input paths.\n' >&2
  exit 1
fi

external_ltx_project="$tmp_dir/external-ltx-project"
mkdir -p "$external_ltx_project"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  "\\input{$external_source}" \
  '\end{document}' >"$external_ltx_project/main.ltx"
if "$script_dir/latex_healthcheck.sh" "$external_ltx_project" main.ltx >/dev/null 2>&1; then
  printf 'Expected non-.tex main source to receive the same external-input preflight.\n' >&2
  exit 1
fi

outside_log="$tmp_dir/outside-log.txt"
printf 'preserve external log\n' >"$outside_log"
unsafe_log_project="$tmp_dir/unsafe-log-project"
mkdir -p "$unsafe_log_project"
printf '%s\n' '\documentclass{article}\begin{document}Unsafe log\end{document}' >"$unsafe_log_project/main.tex"
ln -s "$outside_log" "$unsafe_log_project/logs"
if "$script_dir/publication_gate.sh" "$unsafe_log_project" main.tex >/dev/null 2>&1; then
  printf 'Expected publication gate to reject a logs symlink.\n' >&2
  exit 1
fi
if [[ $(cat "$outside_log") != 'preserve external log' ]]; then
  printf 'Publication gate wrote through a logs symlink.\n' >&2
  exit 1
fi

outside_finding="$tmp_dir/outside-finding.txt"
printf 'preserve external finding\n' >"$outside_finding"
unsafe_finding_project="$tmp_dir/unsafe-finding-project"
mkdir -p "$unsafe_finding_project/logs"
printf '%s\n' '\documentclass{article}\begin{document}Unsafe finding\end{document}' >"$unsafe_finding_project/main.tex"
ln -s "$outside_finding" "$unsafe_finding_project/logs/latex_healthcheck_findings.txt"
if "$script_dir/latex_healthcheck.sh" "$unsafe_finding_project" main.tex >/dev/null 2>&1; then
  printf 'Expected healthcheck to reject a findings symlink.\n' >&2
  exit 1
fi
if [[ $(cat "$outside_finding") != 'preserve external finding' ]]; then
  printf 'Healthcheck wrote through a findings symlink.\n' >&2
  exit 1
fi

unsafe_aux_project="$tmp_dir/unsafe-aux-project"
mkdir -p "$unsafe_aux_project"
printf '%s\n' '\documentclass{article}\begin{document}Preserve source\end{document}' >"$unsafe_aux_project/main.tex"
source_hash=$(python3 - "$unsafe_aux_project/main.tex" <<'PY'
import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
ln -s "$unsafe_aux_project/main.tex" "$unsafe_aux_project/main.aux"
if "$script_dir/latex_healthcheck.sh" "$unsafe_aux_project" main.tex >/dev/null 2>&1; then
  printf 'Expected healthcheck to reject an auxiliary-file symlink.\n' >&2
  exit 1
fi
new_source_hash=$(python3 - "$unsafe_aux_project/main.tex" <<'PY'
import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
[[ "$source_hash" == "$new_source_hash" ]] || {
  printf 'Healthcheck auxiliary output overwrote project source.\n' >&2
  exit 1
}

hardlink_project="$tmp_dir/hardlink-project"
hardlink_outside="$tmp_dir/hardlink-outside.nav"
mkdir -p "$hardlink_project"
printf '%s\n' '\documentclass{article}\begin{document}Hard link\end{document}' >"$hardlink_project/main.tex"
printf 'preserve external hard link\n' >"$hardlink_outside"
ln "$hardlink_outside" "$hardlink_project/main.nav"
if "$script_dir/latex_healthcheck.sh" "$hardlink_project" main.tex >/dev/null 2>&1; then
  printf 'Expected healthcheck to reject project files with multiple hard links.\n' >&2
  exit 1
fi

internal_symlink_project="$tmp_dir/internal-symlink-project"
mkdir -p "$internal_symlink_project"
printf '%s\n' '\documentclass{article}\begin{document}Internal symlink\end{document}' >"$internal_symlink_project/main.tex"
printf 'preserve internal target\n' >"$internal_symlink_project/victim.tex"
ln -s victim.tex "$internal_symlink_project/main.nav"
if "$script_dir/latex_healthcheck.sh" "$internal_symlink_project" main.tex >/dev/null 2>&1; then
  printf 'Expected healthcheck to reject internal project symlinks.\n' >&2
  exit 1
fi
if [[ $(cat "$internal_symlink_project/victim.tex") != 'preserve internal target' ]]; then
  printf 'Healthcheck modified an internal symlink target.\n' >&2
  exit 1
fi

special_file_project="$tmp_dir/special-file-project"
mkdir -p "$special_file_project"
printf '%s\n' '\documentclass{article}\begin{document}Special file\end{document}' >"$special_file_project/main.tex"
mkfifo "$special_file_project/unused.fifo"
if "$script_dir/latex_healthcheck.sh" "$special_file_project" main.tex >/dev/null 2>&1; then
  printf 'Expected healthcheck to reject non-regular project entries.\n' >&2
  exit 1
fi
if [[ $(cat "$hardlink_outside") != 'preserve external hard link' ]]; then
  printf 'Healthcheck modified an external hard-linked file.\n' >&2
  exit 1
fi

timeout_bin="$tmp_dir/timeout-bin"
timeout_project="$tmp_dir/timeout-project"
mkdir -p "$timeout_bin" "$timeout_project"
cat >"$timeout_bin/latexmk" <<'SH'
#!/usr/bin/env bash
sleep 10
SH
cat >"$timeout_bin/xelatex" <<'SH'
#!/usr/bin/env bash
sleep 10
SH
chmod 755 "$timeout_bin/latexmk" "$timeout_bin/xelatex"
printf '%s\n' '\documentclass{article}\begin{document}Timeout\end{document}' >"$timeout_project/main.tex"
if PATH="$timeout_bin:$PATH" "$script_dir/latex_healthcheck.sh" \
  "$timeout_project" main.tex --build-timeout 1 >/dev/null 2>&1; then
  printf 'Expected the build timeout to terminate a non-responsive compiler.\n' >&2
  exit 1
fi

descendant_bin="$tmp_dir/descendant-bin"
descendant_project="$tmp_dir/descendant-project"
descendant_pid_file="$tmp_dir/descendant.pid"
mkdir -p "$descendant_bin" "$descendant_project"
cat >"$descendant_bin/latexmk" <<'SH'
#!/usr/bin/env bash
(
  trap '' TERM
  sleep 30
) &
printf '%s\n' "$!" >"$DESCENDANT_PID_FILE"
exit 0
SH
cat >"$descendant_bin/xelatex" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod 755 "$descendant_bin/latexmk" "$descendant_bin/xelatex"
printf '%s\n' '\documentclass{article}\begin{document}Descendant timeout\end{document}' >"$descendant_project/main.tex"
descendant_start=$(date +%s)
if DESCENDANT_PID_FILE="$descendant_pid_file" PATH="$descendant_bin:$PATH" \
  "$script_dir/latex_healthcheck.sh" "$descendant_project" main.tex \
  --build-timeout 1 >/dev/null 2>&1; then
  printf 'Expected a compiler descendant holding stdout to time out.\n' >&2
  exit 1
fi
descendant_elapsed=$(($(date +%s) - descendant_start))
if [[ $descendant_elapsed -gt 8 ]]; then
  printf 'Compiler timeout exceeded the process-group grace period.\n' >&2
  exit 1
fi
if [[ ! -s "$descendant_pid_file" ]]; then
  printf 'Compiler descendant did not record its PID.\n' >&2
  exit 1
fi
sleep 1
if kill -0 "$(cat "$descendant_pid_file")" 2>/dev/null; then
  printf 'Compiler descendant survived process-group termination.\n' >&2
  exit 1
fi

python3 - "$script_dir" "$tmp_dir" <<'PY'
import os
import pathlib
import sys

sys.path.insert(0, sys.argv[1])
import latex_pipeline

root = pathlib.Path(sys.argv[2])
log_path = root / "bounded-compiler.log"
latex_pipeline.MAX_COMPILE_LOG_BYTES = 1024
returncode, timed_out, truncated = latex_pipeline.run_streamed_command(
    [sys.executable, "-c", "import os; os.write(1, b'x' * 4096)"],
    root,
    log_path,
    env=latex_pipeline.clean_environment(),
    timeout=5,
)
assert returncode == 0
assert not timed_out
assert truncated
assert log_path.stat().st_size < 1400
assert b"was truncated" in log_path.read_bytes()
PY

if [[ "$mode" == portable ]]; then
  printf 'Portable LaTeX pipeline tests passed.\n'
  exit 0
fi

if ! command -v xelatex >/dev/null 2>&1 \
  || ! command -v latexmk >/dev/null 2>&1 \
  || ! command -v pdfinfo >/dev/null 2>&1 \
  || ! command -v pdftotext >/dev/null 2>&1 \
  || { ! command -v pdftoppm >/dev/null 2>&1 && ! command -v mutool >/dev/null 2>&1; }; then
  if [[ "$require_tools" == true ]]; then
    printf 'Integration tools are required but unavailable.\n' >&2
    exit 1
  fi
  printf 'Skipping XeLaTeX integration tests because the full core toolchain is unavailable.\n'
  exit 0
fi

simple_project="$tmp_dir/simple"
mkdir -p "$simple_project"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  'Safe publication text.' \
  '\end{document}' >"$simple_project/main.tex"
"$script_dir/latex_healthcheck.sh" "$simple_project" main.tex >/dev/null

reserved_name_project="$tmp_dir/reserved-name-source"
mkdir -p "$reserved_name_project"
printf 'Checked-in reserved-prefix source.\n' >"$reserved_name_project/publication_gate_content"
printf 'OUTPUT main.tex\n' >"$reserved_name_project/.no-trusted-recorder.fls"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  '\input{publication_gate_content}' \
  '\end{document}' >"$reserved_name_project/main.tex"
"$script_dir/latex_healthcheck.sh" "$reserved_name_project" main.tex >/dev/null

if "$script_dir/publication_gate.sh" "$inc_artifact_project" main.tex \
  --render-dpi 72 >/dev/null 2>&1; then
  printf 'Expected recorder-discovered .inc artifacts to fail the publication gate.\n' >&2
  exit 1
fi

in_project_write_project="$tmp_dir/in-project-write"
mkdir -p "$in_project_write_project"
printf 'Original protected source.\n' >"$in_project_write_project/victim.tex"
printf '%s\n' \
  '\documentclass{article}' \
  '\newwrite\victimfile' \
  '\begin{document}' \
  '\input{victim.tex}' \
  '\immediate\openout\victimfile=victim.tex' \
  '\immediate\write\victimfile{CLOBBERED PROJECT SOURCE}' \
  '\immediate\closeout\victimfile' \
  '\end{document}' >"$in_project_write_project/main.tex"
"$script_dir/latex_healthcheck.sh" "$in_project_write_project" main.tex >/dev/null
if [[ $(cat "$in_project_write_project/victim.tex") != 'Original protected source.' ]]; then
  printf 'Staged healthcheck allowed TeX to modify an original project source.\n' >&2
  exit 1
fi

openout_project="$tmp_dir/openout-project"
openout_external="$tmp_dir/openout-external.txt"
mkdir -p "$openout_project"
printf 'preserve external output\n' >"$openout_external"
printf '%s\n' \
  '\documentclass{article}' \
  '\newwrite\outsidefile' \
  '\begin{document}' \
  "\\immediate\\openout\\outsidefile=$openout_external" \
  '\immediate\write\outsidefile{overwritten}' \
  '\immediate\closeout\outsidefile' \
  'External output test.' \
  '\end{document}' >"$openout_project/main.tex"
if openout_any=a "$script_dir/latex_healthcheck.sh" "$openout_project" main.tex >/dev/null 2>&1; then
  printf 'Expected safe Kpathsea output policy to reject an external write.\n' >&2
  exit 1
fi
if [[ $(cat "$openout_external") != 'preserve external output' ]]; then
  printf 'XeLaTeX overwrote a project-external file through openout_any.\n' >&2
  exit 1
fi

perl_inject_dir="$tmp_dir/perl-inject"
perl_inject_marker="$tmp_dir/perl-inject-executed"
mkdir -p "$perl_inject_dir"
cat >"$perl_inject_dir/Inject.pm" <<'PERL'
package Inject;
BEGIN {
    open my $fh, '>', $ENV{PERL_INJECT_MARKER} or die $!;
    print {$fh} "executed\n";
    close $fh;
}
1;
PERL
PERL5OPT="-I$perl_inject_dir -MInject" PERL_INJECT_MARKER="$perl_inject_marker" \
  "$script_dir/latex_healthcheck.sh" "$simple_project" main.tex >/dev/null
if [[ -e "$perl_inject_marker" ]]; then
  printf 'latexmk loaded ambient PERL5OPT startup code.\n' >&2
  exit 1
fi

poisoned_texmf="$tmp_dir/poisoned-texmf"
poisoned_project="$tmp_dir/poisoned-project"
mkdir -p "$poisoned_texmf" "$poisoned_project"
cat >"$poisoned_texmf/externalonly.sty" <<'TEX'
\ProvidesPackage{externalonly}
\newcommand{\externalonly}{environment-only package}
TEX
printf '%s\n' \
  '\documentclass{article}' \
  '\usepackage{externalonly}' \
  '\begin{document}\externalonly\end{document}' >"$poisoned_project/main.tex"
if TEXINPUTS="$poisoned_texmf//:" "$script_dir/latex_healthcheck.sh" \
  "$poisoned_project" main.tex >/dev/null 2>&1; then
  printf 'Expected healthcheck to ignore TEXINPUTS environment injection.\n' >&2
  exit 1
fi

rc_marker="$tmp_dir/project-rc-executed"
# The dollar-prefixed names below belong to Perl.
# shellcheck disable=SC2016
printf 'open my $fh, q{>}, q{%s} or die $!; print {$fh} q{executed}; close $fh;\n' "$rc_marker" >"$simple_project/.latexmkrc"
"$script_dir/latex_healthcheck.sh" "$simple_project" main.tex >/dev/null
if [[ -e "$rc_marker" ]]; then
  printf 'Project .latexmkrc executed without explicit approval.\n' >&2
  exit 1
fi

shell_project="$tmp_dir/shell-escape"
mkdir -p "$shell_project"
shell_marker="$tmp_dir/shell-escape-executed"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  "\\immediate\\write18{touch $shell_marker}" \
  '\end{document}' >"$shell_project/main.tex"
if "$script_dir/latex_healthcheck.sh" "$shell_project" main.tex >/dev/null 2>&1; then
  printf 'Expected shell-escape source to require explicit approval.\n' >&2
  exit 1
fi
if [[ -e "$shell_marker" ]]; then
  printf 'Shell escape executed despite the safe default.\n' >&2
  exit 1
fi

missing_glyph_project="$tmp_dir/missing-glyph"
mkdir -p "$missing_glyph_project"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  '\font\badfont=cmr10 \badfont\char"4E2D' \
  '\end{document}' >"$missing_glyph_project/main.tex"
if "$script_dir/latex_healthcheck.sh" "$missing_glyph_project" main.tex --fail-on-findings >/dev/null 2>&1; then
  printf 'Expected a missing glyph to fail strict healthcheck findings.\n' >&2
  exit 1
fi
if ! grep -Fq 'ERROR missing-character:' "$missing_glyph_project/logs/latex_healthcheck_findings.txt"; then
  printf 'Missing-glyph finding was not classified correctly.\n' >&2
  exit 1
fi

rm -f "$simple_project/.latexmkrc"
"$script_dir/publication_gate.sh" "$simple_project" main.tex --render-dpi 72 >/dev/null
if ! grep -Fq 'PASS: Publication gate' "$simple_project/logs/publication_gate_summary.txt"; then
  printf 'Expected the default publication gate to run to completion.\n' >&2
  exit 1
fi
if [[ ! -s "$simple_project/logs/publication_primary_dependencies.txt" \
  || ! -s "$simple_project/logs/publication_clean_dependencies.txt" ]]; then
  printf 'Expected publication gate to preserve primary and clean dependency reports.\n' >&2
  exit 1
fi
if [[ ! -s "$simple_project/logs/publication_clean_output.txt" ]]; then
  printf 'Expected publication gate to preserve clean-build text evidence.\n' >&2
  exit 1
fi

nested_pdf_project="$tmp_dir/nested-main-pdf"
mkdir -p "$nested_pdf_project/assets"
cp "$simple_project/main.pdf" "$nested_pdf_project/assets/main.pdf"
printf '%s\n' \
  '\documentclass{article}' \
  '\usepackage{graphicx}' \
  '\begin{document}' \
  'Embedded project asset.' \
  '\includegraphics[width=0.2\linewidth]{assets/main.pdf}' \
  '\end{document}' >"$nested_pdf_project/main.tex"
"$script_dir/publication_gate.sh" "$nested_pdf_project" main.tex --render-dpi 72 >/dev/null

nested_aux_source_project="$tmp_dir/nested-aux-source"
mkdir -p "$nested_aux_source_project/assets"
printf 'Checked-in auxiliary-suffix source.\n' >"$nested_aux_source_project/assets/content.out"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  '\input{assets/content.out}' \
  '\end{document}' >"$nested_aux_source_project/main.tex"
"$script_dir/publication_gate.sh" "$nested_aux_source_project" main.tex --render-dpi 72 >/dev/null

top_level_aux_source_project="$tmp_dir/top-level-aux-source"
mkdir -p "$top_level_aux_source_project"
printf 'Checked-in top-level auxiliary-suffix source.\n' >"$top_level_aux_source_project/main.out"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  '\input{main.out}' \
  '\end{document}' >"$top_level_aux_source_project/main.tex"
"$script_dir/publication_gate.sh" "$top_level_aux_source_project" main.tex --render-dpi 72 >/dev/null

frozen_bbl_project="$tmp_dir/frozen-bbl"
mkdir -p "$frozen_bbl_project"
printf 'Frozen same-jobname bibliography content.\n' >"$frozen_bbl_project/main.bbl"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  '\input{main.bbl}' \
  '\end{document}' >"$frozen_bbl_project/main.tex"
"$script_dir/publication_gate.sh" "$frozen_bbl_project" main.tex --render-dpi 72 >/dev/null
grep -Fq 'Frozen same-jobname bibliography content.' \
  "$frozen_bbl_project/logs/publication_gate_output.txt" || {
  printf 'Frozen same-jobname BBL content is missing from the primary output.\n' >&2
  exit 1
}
grep -Fq 'Frozen same-jobname bibliography content.' \
  "$frozen_bbl_project/logs/publication_clean_output.txt" || {
  printf 'Frozen same-jobname BBL content is missing from the clean output.\n' >&2
  exit 1
}

if command -v bibtex >/dev/null 2>&1; then
  conditional_bibtex_project="$tmp_dir/conditional-bibtex"
  mkdir -p "$conditional_bibtex_project"
  printf '%s\n' \
    '\documentclass{article}' \
    '\begin{document}' \
    'Conditional citation~\cite{conditional2026}.' \
    '\bibliographystyle{plain}' \
    '\bibliography{references}' \
    '\end{document}' >"$conditional_bibtex_project/main.tex"
  printf '%s\n' \
    '@book{conditional2026,' \
    '  author = {Example, Ada},' \
    '  title = {Conditional BibTeX Entry},' \
    '  year = {2026}' \
    '}' >"$conditional_bibtex_project/references.bib"
  "$script_dir/latex_healthcheck.sh" "$conditional_bibtex_project" main.tex \
    --require-latexmk --fail-on-findings >/dev/null
  pdftotext "$conditional_bibtex_project/main.pdf" \
    "$conditional_bibtex_project/output.txt"
  grep -Fq 'Conditional BibTeX Entry' "$conditional_bibtex_project/output.txt" || {
    printf 'Conditional BibTeX mode did not build the real bibliography.\n' >&2
    exit 1
  }
fi

stale_project="$tmp_dir/stale-xdv-project"
evil_xdv_project="$tmp_dir/evil-xdv-project"
mkdir -p "$stale_project" "$evil_xdv_project"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  'GOOD PRIMARY CONTENT' \
  '\end{document}' >"$stale_project/main.tex"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  'EVIL PRIMARY CONTENT' \
  '\end{document}' >"$evil_xdv_project/main.tex"
(
  cd "$evil_xdv_project"
  xelatex -no-pdf -interaction=nonstopmode -halt-on-error main.tex >/dev/null
)
cp "$evil_xdv_project/main.xdv" "$stale_project/main.xdv"
python3 - "$stale_project/main.xdv" <<'PY'
import os
import pathlib
import sys
import time

path = pathlib.Path(sys.argv[1])
future = time.time() + 3600
os.utime(path, (future, future))
PY
"$script_dir/publication_gate.sh" "$stale_project" main.tex --render-dpi 72 >/dev/null
if ! grep -Fq 'GOOD PRIMARY CONTENT' "$stale_project/logs/publication_gate_output.txt" \
  || grep -Fq 'EVIL PRIMARY CONTENT' "$stale_project/logs/publication_gate_output.txt"; then
  printf 'Publication gate reused a stale primary XDV artifact.\n' >&2
  exit 1
fi

white_project="$tmp_dir/white-on-white"
mkdir -p "$white_project"
printf '%s\n' \
  '\documentclass{article}' \
  '\usepackage{xcolor}' \
  '\begin{document}' \
  '\color{white}Text exists but is not visible.' \
  '\end{document}' >"$white_project/main.tex"
if "$script_dir/publication_gate.sh" "$white_project" main.tex --render-dpi 72 >/dev/null 2>&1; then
  printf 'Expected visually blank white-on-white output to fail publication verification.\n' >&2
  exit 1
fi

if command -v bibtex >/dev/null 2>&1 \
  && [[ -n $(kpsewhich chapterbib.sty 2>/dev/null) ]]; then
  chapterbib_project="$tmp_dir/chapterbib-project"
  chapterbib_external="$tmp_dir/chapterbib-external.bib"
  mkdir -p "$chapterbib_project/chapters"
  printf '%s\n' '@book{external,title={External bibliography},author={Example},year={2026}}' >"$chapterbib_external"
  printf '%s\n' \
    '\documentclass{article}' \
    '\usepackage{chapterbib}' \
    '\begin{document}' \
    '\include{chapters/one}' \
    '\end{document}' >"$chapterbib_project/main.tex"
  printf '%s\n' \
    "\\newcommand{\\externalbib}{${chapterbib_external%.bib}}" \
    'External citation: \cite{external}.' \
    '\bibliographystyle{plain}' \
    '\bibliography{\externalbib}' >"$chapterbib_project/chapters/one.tex"
  if "$script_dir/publication_gate.sh" "$chapterbib_project" main.tex \
    --render-dpi 72 >/dev/null 2>&1; then
    printf 'Expected nested chapter bibliography logs to expose the external dependency.\n' >&2
    exit 1
  fi
  if ! grep -Fq "$chapterbib_external" \
    "$chapterbib_project/logs/publication_primary_dependencies.txt"; then
    printf 'Nested chapter bibliography dependency was omitted from the report.\n' >&2
    exit 1
  fi
fi

if [[ -r /etc/hostname ]]; then
  host_read_project="$tmp_dir/host-read-project"
  mkdir -p "$host_read_project"
  cat >"$host_read_project/main.tex" <<'TEX'
\documentclass{article}
\newread\hostfile
\begin{document}
\openin\hostfile=/etc/hostname
\read\hostfile to \hostline
\closein\hostfile
Host value: \texttt{\hostline}
\end{document}
TEX
  if "$script_dir/publication_gate.sh" "$host_read_project" main.tex \
    --render-dpi 72 >/dev/null 2>&1; then
    printf 'Expected publication gate to reject arbitrary /etc input.\n' >&2
    exit 1
  fi
fi

set +e
"$script_dir/publication_gate.sh" "$simple_project" main.tex --skip-clean --render-dpi 72 >/dev/null 2>&1
skip_status=$?
set -e
if [[ $skip_status -ne 2 ]]; then
  printf 'Expected --skip-clean to return incomplete status 2, got %s.\n' "$skip_status" >&2
  exit 1
fi
if ! grep -Fq 'INCOMPLETE: Clean-room XeLaTeX rebuild was skipped' "$simple_project/logs/publication_gate_summary.txt"; then
  printf 'Expected skipped clean-room work to be recorded as incomplete.\n' >&2
  exit 1
fi

reference_project="$tmp_dir/undefined-reference"
mkdir -p "$reference_project"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  'Missing reference: \ref{not-defined}.' \
  '\end{document}' >"$reference_project/main.tex"
if "$script_dir/publication_gate.sh" "$reference_project" main.tex --render-dpi 72 >/dev/null 2>&1; then
  printf 'Expected unresolved references to fail the default publication gate.\n' >&2
  exit 1
fi

set +e
"$script_dir/publication_gate.sh" "$reference_project" main.tex --allow-findings --render-dpi 72 >/dev/null 2>&1
allowed_status=$?
set -e
if [[ $allowed_status -ne 2 ]]; then
  printf 'Expected --allow-findings to return incomplete status 2, got %s.\n' "$allowed_status" >&2
  exit 1
fi

blank_project="$tmp_dir/blank"
mkdir -p "$blank_project"
printf '%s\n' \
  '\documentclass{article}' \
  '\begin{document}' \
  '\pagestyle{empty}' \
  '\null' \
  '\end{document}' >"$blank_project/main.tex"
if "$script_dir/publication_gate.sh" "$blank_project" main.tex --render-dpi 72 >/dev/null 2>&1; then
  printf 'Expected empty extracted text to fail the publication gate.\n' >&2
  exit 1
fi

printf 'LaTeX pipeline tests passed.\n'
