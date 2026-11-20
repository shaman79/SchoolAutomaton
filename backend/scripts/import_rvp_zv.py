"""Import the Czech RVP ZV expected learning outcomes from NPI open data into ``app/data/rvp_zv.json``.

The source is the open dataset "RVP ZV – závazná část a metodická podpora" published by the Národní
pedagogický institut ČR at https://opendata.npi.cz. Its stated terms of use: it contains no copyrighted
works, is not a copyright-protected database and carries no sui generis database right, so the app may
ship (an extract of) it.

Usage, from ``backend/``::

    python -m scripts.import_rvp_zv                  # download DEFAULT_URL
    python -m scripts.import_rvp_zv --file data.json  # a local copy of the dataset at --url
    python -m scripts.import_rvp_zv --url <a newer dataset URL from opendata.npi.cz>

For every expected learning outcome ("očekávaný výsledek učení") of every subject ("vzdělávací obor")
it keeps the code, subject, strand ("tematický okruh"), stage (ZV5 = end of grade 5, ZV9 = end of
grade 9), the statement, and the descriptions of three phases of mastering it ("Na začátku", "Na cestě",
"Splněno") as plain text. Strands that a later amendment removed from the RVP ZV are skipped
(``EXCLUDED_STRANDS``). The output is deterministic (sorted by code), so a re-import diffs cleanly.

After a re-import run the backend tests: ``tests/test_prompt_version.py`` fingerprints this data and
asks for a PROMPT_VERSION bump when it changed.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://opendata.npi.cz/download/rvp/data_final_rvp_zv_full_mp_20251216.json"
OUTPUT = Path(__file__).resolve().parents[1] / "app" / "data" / "rvp_zv.json"

PUBLISHER = "Národní pedagogický institut České republiky (NPI ČR)"
TERMS = (
    "opendata.npi.cz: neobsahuje autorská díla; není autorskoprávně chráněnou databází; "
    "nechráněno zvláštním právem pořizovatele databáze; neobsahuje osobní údaje."
)

# Strand code prefix -> why it is left out. The MŠMT measure of 28 Aug 2026 (MSMT-13279/2026-4,
# in force from 1 Sep 2026) dropped "Zdravotní a aplikovaná tělesná výchova" from the RVP ZV; the
# open dataset of 16 Dec 2025 still lists it.
EXCLUDED_STRANDS: dict[str, str] = {
    "CZB-TEV-003": "Zdravotní a aplikovaná tělesná výchova: removed from the RVP ZV by MSMT-13279/2026-4 "
    "(in force from 1 Sep 2026)",
}

# Dataset phase name -> key in the output.
PHASES: dict[str, str] = {"Na začátku": "start", "Na cestě": "on_the_way", "Splněno": "met"}

_CODE_RE = re.compile(r"^[A-Z]{3}-[A-Z]{3}-\d{3}-(ZV\d)-\d{3}$")


def plain_text(value: str | None) -> str:
    """HTML from the dataset -> one line of plain text (block ends become spaces, entities decoded)."""
    text = re.sub(r"(?i)<br\s*/?>|</(?:p|li|div|h\d)>", " ", value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = unicodedata.normalize("NFC", html.unescape(text))
    return re.sub(r"\s+", " ", text).strip()


def extract(dataset: dict, *, source_url: str) -> dict:
    """The trimmed catalogue (see the module docstring) from the parsed open-data JSON."""
    subjects: dict[str, dict[str, str]] = {}
    outcomes: list[dict] = []
    for area in dataset["vzdelavaciOblasti"]:
        for subject in area["vzdelavaciObory"]:
            subjects[subject["kod"]] = {"name": plain_text(subject["nazev"]), "area": plain_text(area["nazev"])}
            for strand in subject["tematickeOkruhy"]:
                for node in strand["uzloveBody"]:
                    for item in node["ocekavaneVysledkyUceni"]:
                        code = item["kod"].strip()
                        match = _CODE_RE.match(code)
                        if not match:
                            raise ValueError(f"unexpected outcome code {code!r}")
                        if match.group(1) != node["kod"]:
                            raise ValueError(f"{code} sits under nodal point {node['kod']}")
                        if any(code.startswith(prefix) for prefix in EXCLUDED_STRANDS):
                            continue
                        text = plain_text(item["zneni"])
                        if not text:
                            raise ValueError(f"{code} has no statement")
                        phases = {}
                        for level in item.get("urovneMetodickePodpory") or []:
                            key = PHASES.get(plain_text(level.get("nazev")))
                            description = plain_text(level.get("charakteristika"))
                            if key and description:
                                phases[key] = description
                        outcomes.append({
                            "code": code,
                            "subject": subject["kod"],
                            "strand": plain_text(strand["nazev"]),
                            "stage": node["kod"],
                            "text": text,
                            "phases": {key: phases[key] for key in PHASES.values() if key in phases},
                        })
    outcomes.sort(key=lambda o: o["code"])
    codes = [o["code"] for o in outcomes]
    if len(set(codes)) != len(codes):
        raise ValueError("duplicate outcome codes in the dataset")
    return {
        "source": {
            "dataset": "RVP ZV – závazná část a metodická podpora (open data)",
            "url": source_url,
            "publisher": PUBLISHER,
            "terms": TERMS,
            "excluded": EXCLUDED_STRANDS,
        },
        "subjects": dict(sorted(subjects.items())),
        "outcomes": outcomes,
    }


def render(catalogue: dict) -> str:
    return json.dumps(catalogue, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL, help="dataset URL (recorded in the output)")
    parser.add_argument("--file", type=Path, help="read a local copy of --url instead of downloading it")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if args.file:
        raw = args.file.read_bytes()
    else:
        request = urllib.request.Request(args.url, headers={"User-Agent": "SchoolAutomaton RVP import"})
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - fixed https source
            raw = response.read()
    catalogue = extract(json.loads(raw), source_url=args.url)
    args.out.write_text(render(catalogue), encoding="utf-8")
    stages: dict[str, int] = {}
    for outcome in catalogue["outcomes"]:
        stages[outcome["stage"]] = stages.get(outcome["stage"], 0) + 1
    print(f"wrote {len(catalogue['outcomes'])} outcomes {stages} to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
