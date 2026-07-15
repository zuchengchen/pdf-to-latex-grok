#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s [--require-tools]\n' "$0" >&2
}

require_tools=false
if [[ $# -gt 1 ]]; then
  usage
  exit 2
elif [[ $# -eq 1 ]]; then
  case "$1" in
    --require-tools) require_tools=true ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
fi

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/pdf-to-latex-extended.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM
export PYTHONDONTWRITEBYTECODE=1

fail() {
  printf 'Extended pipeline test failed: %s\n' "$*" >&2
  exit 1
}

missing=
for command_name in xelatex latexmk pdfinfo pdftotext makeindex makeglossaries bibtex fc-match; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    missing="$missing $command_name"
  fi
done
if ! command -v pdftoppm >/dev/null 2>&1 && ! command -v mutool >/dev/null 2>&1; then
  missing="$missing pdftoppm-or-mutool"
fi

biber_available=true
if ! command -v biber >/dev/null 2>&1; then
  biber_available=false
  if [[ "$require_tools" == true ]]; then
    fail 'missing required extended tool: biber'
  fi
  printf 'Skipping the Biber corpus; biber is unavailable.\n'
fi
if [[ -n "$missing" ]]; then
  if [[ "$require_tools" == true ]]; then
    fail "missing required extended tools:$missing"
  fi
  printf 'Skipping extended document corpus; missing tools:%s\n' "$missing"
  exit 0
fi

if ! fc-match -f '%{family}\n' 'Noto Serif CJK SC' | grep -Fq 'Noto Serif CJK SC'; then
  if [[ "$require_tools" == true ]]; then
    fail 'Noto Serif CJK SC is required for the extended CJK corpus'
  fi
  printf 'Skipping extended document corpus; Noto Serif CJK SC is unavailable.\n'
  exit 0
fi

book_project="$tmp_dir/book-cjk-glossary"
mkdir -p "$book_project"
cat >"$book_project/.latexmkrc" <<'PERL'
add_cus_dep('glo', 'gls', 0, 'run_makeglossaries');
sub run_makeglossaries {
  return system('makeglossaries', $_[0]);
}
PERL
cat >"$book_project/main.tex" <<'TEX'
\documentclass{book}
\usepackage{fontspec}
\usepackage{xeCJK}
\usepackage{makeidx}
\usepackage{glossaries}
\setCJKmainfont{Noto Serif CJK SC}
\makeindex
\makeglossaries
\newglossaryentry{workflow}{name={workflow},description={a verified document process}}
\begin{document}
\frontmatter
\tableofcontents
\mainmatter
\chapter{Document Workflow}
This book records a \gls{workflow}. 中文重建测试。\index{workflow}
\chapter{Cross References}
Chapter~\ref{chap:verification} is part of the stable book structure.
\section{Verification}\label{chap:verification}
The generated index and glossary must contain visible entries.
\backmatter
\printglossaries
\printindex
\end{document}
TEX
"$script_dir/latex_healthcheck.sh" "$book_project" main.tex \
  --allow-project-rc --require-latexmk --fail-on-findings >/dev/null
pdftotext "$book_project/main.pdf" "$book_project/output.txt"
grep -Fq 'a verified document process' "$book_project/output.txt" || fail 'glossary output is missing'
grep -Fq 'workflow' "$book_project/output.txt" || fail 'index output is missing'
grep -Fq '中文重建测试' "$book_project/output.txt" || fail 'CJK output is missing'

bibtex_project="$tmp_dir/bibtex"
mkdir -p "$bibtex_project"
cat >"$bibtex_project/main.tex" <<'TEX'
\documentclass{article}
\usepackage{fontspec}
\usepackage[numbers]{natbib}
\begin{document}
Classic BibTeX citation~\citep{lamport1994}.
\bibliographystyle{plainnat}
\bibliography{references}
\end{document}
TEX
cat >"$bibtex_project/references.bib" <<'BIB'
@book{lamport1994,
  author = {Leslie Lamport},
  title = {LaTeX: A Document Preparation System},
  year = {1994},
  publisher = {Addison-Wesley}
}
BIB
"$script_dir/latex_healthcheck.sh" "$bibtex_project" main.tex \
  --require-latexmk --fail-on-findings >/dev/null
pdftotext "$bibtex_project/main.pdf" "$bibtex_project/output.txt"
grep -Fq 'Document Preparation System' "$bibtex_project/output.txt" || fail 'BibTeX bibliography is missing'

biber_project="$tmp_dir/biber"
if [[ "$biber_available" == true ]]; then
  mkdir -p "$biber_project"
  cat >"$biber_project/main.tex" <<'TEX'
\documentclass{article}
\usepackage{fontspec}
\usepackage[backend=biber,style=numeric]{biblatex}
\addbibresource{references.bib}
\begin{document}
Biber citation~\cite{knuth1984}.
\printbibliography
\end{document}
TEX
  cat >"$biber_project/references.bib" <<'BIB'
@book{knuth1984,
  author = {Donald E. Knuth},
  title = {The TeXbook},
  year = {1984},
  publisher = {Addison-Wesley}
}
BIB
  "$script_dir/publication_gate.sh" "$biber_project" main.tex --render-dpi 72 >/dev/null
  grep -Fq 'PASS: Publication gate' "$biber_project/logs/publication_gate_summary.txt" || fail 'Biber publication gate did not pass'
  grep -Fq 'The TeXbook' "$biber_project/logs/publication_gate_output.txt" || fail 'Biber bibliography is missing'
  grep -Fq 'The TeXbook' "$biber_project/logs/publication_clean_output.txt" || fail 'Clean-room Biber bibliography is missing'
fi

forward_skill="$tmp_dir/forward-skill"
cp -R "$script_dir/.." "$forward_skill"
python3 "$forward_skill/scripts/workflow_contract.py" validate-package "$forward_skill" >/dev/null

printf 'Extended pipeline tests passed.\n'
