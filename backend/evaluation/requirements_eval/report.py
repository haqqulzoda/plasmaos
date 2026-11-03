"""Markdown rendering of score and scope-check results."""

from __future__ import annotations


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _ci(value: tuple[float, float] | list | None) -> str:
    return "n/a" if not value else f"{value[0]:.1%} to {value[1]:.1%}"


def render_score(payload: dict) -> str:
    meta = payload["meta"]
    lines = [
        f"# Requirement extraction score: {meta['run_label']}", "",
        f"Dataset `{meta['dataset_id']}` (status **{meta['dataset_status']}**), outputs from `{meta['outputs']}`.",
        f"Scored {meta['documents_with_output']} of {meta['documents']} documents that have stored outputs.", "",
    ]
    if meta["dataset_status"].startswith("DRAFT"):
        lines += [
            "> The labels are a draft that a procurement expert has not reviewed. Numbers below describe agreement "
            "with draft labels, not validated accuracy.", "",
        ]
    o = payload["overall"]
    lines += [
        "## Overall", "",
        "| Recall | Precision | F1 | Mandatory agreement | Unlocated quotes |", "| ---: | ---: | ---: | ---: | ---: |",
        f"| {_pct(o['recall'])} | {_pct(o['precision'])} | {_pct(o['f1'])} | {_pct(o['mandatory_agreement'])} | {_pct(o['unlocated_rate'])} |",
        "",
    ]
    for grouping in payload["groups"]:
        lines += [
            f"## By {grouping['grouping']}" + (f" (reference: {grouping['reference']})" if grouping["reference"] else ""), "",
            "| Group | Docs | Required items | Recall | Recall 95% CI | Gap vs reference | Gap 95% CI | Precision | Mandatory agreement | Sufficient data |",
            "| --- | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: | --- |",
        ]
        for value, entry in grouping["groups"].items():
            gap = entry.get("recall_gap_vs_reference")
            lines.append(
                f"| {value} | {entry['documents_with_required_items']} | {entry['counts'].get('required', 0)} | "
                f"{_pct(entry['recall'])} | {_ci(entry.get('recall_ci95'))} | "
                f"{'—' if gap is None else f'{gap:+.1%}'} | {_ci(entry.get('recall_gap_ci95'))} | "
                f"{_pct(entry['precision'])} | {_pct(entry['mandatory_agreement'])} | "
                f"{'no' if entry['insufficient'] else 'yes'} |"
            )
        lines.append("")
    lines += [
        "A group marked \"no\" has fewer than 10 documents or 30 required items: report it, but do not use it to "
        "claim or rule out a difference. A gap whose interval includes 0 is not evidence of a difference.", "",
    ]
    return "\n".join(lines)


def render_scope_check(payload: dict) -> str:
    lines = ["# Scope-classifier language check (offline, no model)", "", payload["method"], ""]
    for key, groups in payload["by"].items():
        lines += [
            f"## By {key}", "",
            "| Group | Docs | Items | Marked bid-blocking | Share | 95% CI | Needs review | Scopes |",
            "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |",
        ]
        for value, entry in groups.items():
            scopes = ", ".join(f"{scope} {count}" for scope, count in sorted(entry["scopes"].items()))
            lines.append(
                f"| {value} | {entry['documents']} | {entry['items']} | {entry['blocking']} | "
                f"{_pct(entry['blocking_share'])} | {_ci(entry['blocking_share_ci95'])} | {entry['needs_review']} | {scopes} |"
            )
        lines.append("")
    lines += ["## Keyword lists by language", "", "| List | " + " | ".join(("en", "ru", "uz-Latn", "uz-Cyrl")) + " |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for name, counts in payload["lexicon"].items():
        lines.append(f"| {name} | " + " | ".join(str(counts.get(k, 0)) for k in ("en", "ru", "uz-Latn", "uz-Cyrl")) + " |")
    lines.append("")
    return "\n".join(lines)
