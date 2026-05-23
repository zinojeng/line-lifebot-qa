# Generic LLM Wiki Markdown Normalizer

`scripts/llm_wiki_markdown_normalizer.py` is a reusable Markdown audit and
low-risk normalization tool for LLM Wiki-style projects.

This is the generic cross-project tool. The ADA/KDIGO LINE QA project also has
a domain-specific wrapper, `scripts/normalize_wiki_markdown.py`, which is what
`scripts/wiki_ops.py md-audit` and `scripts/wiki_ops.py md-normalize` call for
that medical wiki. Use the generic tool for other projects; use `wiki_ops.py`
only when working on the ADA/KDIGO LINE QA wiki workflow.

It is intentionally conservative:

- audit-only by default;
- small batch writes only when `--apply` is used;
- source-like folders such as `raw/`, `sources/`, `archive/`, and `originals/`
  are not auto-fixed unless `--include-sources` is explicit;
- high-risk content is reported for source-aware review instead of rewritten.

## Basic Usage

On this Mac, the source copy currently lives at:

```bash
python3 scripts/llm_wiki_markdown_normalizer.py \
  --root /path/to/project \
  --profile generic
```

For portable use in another project, copy the script into that project's
`scripts/` folder and call it with a relative path:

```bash
cp /path/to/line-lifebot-qa/scripts/llm_wiki_markdown_normalizer.py \
  /path/to/project/scripts/llm_wiki_markdown_normalizer.py

cd /path/to/project
python3 scripts/llm_wiki_markdown_normalizer.py --root . --profile generic
```

Apply only three low-risk fixes:

```bash
python3 scripts/llm_wiki_markdown_normalizer.py \
  --root . \
  --profile generic \
  --apply \
  --max-files 3
```

The default report is written to:

```text
reports/markdown-normalization-audit.md
```

## Which Tool Should I Use?

Use the generic tool for other projects:

```bash
cd /path/to/other/project
python3 scripts/llm_wiki_markdown_normalizer.py --root . --profile generic
```

Use the ADA/KDIGO project-specific workflow only inside the LINE QA medical
guideline project:

```bash
cd /path/to/line-lifebot-qa
python3 scripts/wiki_ops.py md-audit
python3 scripts/wiki_ops.py md-normalize --max-files 3
```

The project-specific workflow has medical guideline assumptions. The generic
tool does not depend on ADA/KDIGO paths or claim-card conventions.

## Profiles

- `generic`: title, summary, type, status, dates, tags, aliases, sources,
  related, confidence, and last_verified.
- `obsidian`: generic plus `obsidian_type`; also checks weak wikilinks.
- `project`: generic plus owner/write-policy fields.
- `research`: generic plus source_type, provenance, and open_questions.
- `medical`: generic plus evidence_level, clinical_use, contested, and
  review_cycle_days. This profile treats content as high-risk and reports it
  for source-aware review rather than blind auto-fix.

## Hermes Prompt

```text
Use the generic LLM Wiki Markdown normalizer.

First run audit-only:
python3 scripts/llm_wiki_markdown_normalizer.py --root . --profile <PROFILE>

Read reports/markdown-normalization-audit.md.
If the report shows low-risk auto-fixable pages, apply only a small batch:
python3 scripts/llm_wiki_markdown_normalizer.py --root . --profile <PROFILE> --apply --max-files 3

Do not change source/raw files unless explicitly allowed.
Do not invent facts, sources, claims, grades, thresholds, or safety language.
After each batch, run the project's tests or review gate and report:
- pages scanned
- pages changed
- pages skipped
- items needing human/source review
- next recommended batch
```

## Recommended Project Integration

For long-term reuse, add a small wrapper script inside each target project:

```bash
#!/usr/bin/env bash
set -euo pipefail

python3 scripts/llm_wiki_markdown_normalizer.py \
  --root "$(pwd)" \
  --profile generic \
  "$@"
```

Then use:

```bash
./scripts/normalize_markdown.sh
./scripts/normalize_markdown.sh --apply --max-files 3
```
