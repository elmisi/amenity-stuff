from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class TaxonomyCategory:
    name: str
    description: str = ""
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class Taxonomy:
    categories: tuple[TaxonomyCategory, ...]

    @property
    def allowed_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.categories)


DEFAULT_TAXONOMY_LINES: tuple[str, ...] = (
    "house | Home, property, rent, utilities, household paperwork | rent; lease; condominium; property tax; utility bill; electricity; gas; water; internet; home insurance; maintenance",
    "purchases | Purchases and subscriptions | receipt; order confirmation; subscription; e-commerce; warranty; invoice for goods/services",
    "travel | Travel and transportation | flight; hotel; booking; ticket; itinerary; car rental; travel insurance",
    "tax | Taxes and public administration | F24; tax return; agency letter; payment notice; PagoPA; municipality tax",
    "banking | Banking and payments (generic) | bank statement; transfer; card statement; account; payment receipt",
    "legal | Legal documents and compliance | contract; terms; privacy policy; legal letter; complaint; power of attorney",
    "work | Employment and professional documents | payslip; payroll; timesheet; employment agreement; HR",
    "personal | Personal documents, IDs, letters, handwritten notes | identity card; passport; driving licence; certificate; personal letter; handwritten note; notes; song lyrics; poem",
    "medical | Health and medical records | medical report; prescription; lab results; vaccination; invoice medical",
    "edu | Education and training | certificate; transcript; diploma; course material; thesis; enrollment",
    "media | Media and content | ebook; article; photo; screenshot; scan of photo; audio; video",
    "tech | Technical docs | manual; datasheet; spec; API documentation; architecture; configuration; logs",
    "unknown | Unclassified / skipped |",
)


_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


def parse_taxonomy_lines(lines: Iterable[str]) -> tuple[Taxonomy, tuple[str, ...]]:
    """Parse user-editable taxonomy lines.

    Grammar (one per line):
      name | description | example1; example2; ...

    Returns: (taxonomy, errors)
    """

    errors: list[str] = []
    categories: list[TaxonomyCategory] = []

    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split("|")]
        name = parts[0].strip().lower() if parts else ""
        if not name:
            errors.append(f"Line {idx}: missing category name")
            continue
        if not _NAME_RE.fullmatch(name):
            errors.append(
                f"Line {idx}: invalid category name '{name}' (use: a-z, 0-9, '_' or '-', 2-64 chars)"
            )
            continue
        if name == "analysis" or name == "pending":
            errors.append(f"Line {idx}: reserved category name '{name}'")
            continue

        description = parts[1] if len(parts) >= 2 else ""
        examples_raw = parts[2] if len(parts) >= 3 else ""
        examples: tuple[str, ...] = ()
        if examples_raw.strip():
            ex = [e.strip() for e in examples_raw.split(";") if e.strip()]
            examples = tuple(ex[:12])

        categories.append(TaxonomyCategory(name=name, description=description, examples=examples))

    names = [c.name for c in categories]
    if "unknown" not in names:
        categories.append(TaxonomyCategory(name="unknown", description="Unclassified / skipped", examples=()))

    # De-duplicate keeping first occurrence.
    seen: set[str] = set()
    deduped: list[TaxonomyCategory] = []
    for c in categories:
        if c.name in seen:
            continue
        seen.add(c.name)
        deduped.append(c)

    if not deduped:
        errors.append("No valid categories found")
        deduped = [TaxonomyCategory(name="unknown", description="Unclassified / skipped", examples=())]

    return Taxonomy(categories=tuple(deduped)), tuple(errors)


def taxonomy_to_prompt_block(taxonomy: Taxonomy) -> str:
    lines: list[str] = []
    for c in taxonomy.categories:
        ex = ""
        if c.examples:
            ex = " Examples: " + "; ".join(c.examples)
        desc = (c.description or "").strip()
        if desc:
            lines.append(f"- {c.name}: {desc}{ex}".strip())
        else:
            lines.append(f"- {c.name}:{ex}".strip())
    return "\n".join(lines)
