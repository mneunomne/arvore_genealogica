# Heritage — family tree research system

An automated loop that finds the open ends of the family tree, sends research agents
online to look for the missing parents, checks what they bring back, and writes the
results into the GEDCOM file with sources and quotes.

```
tree/tree.ged ──► frontier ──► brief ──► research agent ──► findings/<id>.json
      ▲                                                          │
      └──────────── apply (checks evidence, adds people) ◄── check
```

## The web version and what is in git

`web/index.html` is the tree as one self-contained page: no other file is needed to show it,
and the only links in it go to the sources' own web addresses. Publish that folder (or just
that file) with any static host. `python3 -m heritage report` rebuilds it.

Git holds the web version and what it is built from, and nothing else:

| In git | Why |
|---|---|
| `web/index.html` | The page to publish. |
| `heritage/`, `heritage.json` | The code and settings that build it. |
| `tree/tree.ged` | The tree it is built from. |
| `research/countries/presumed.json` | The reviewed countries for people without a recorded birthplace. |

Everything else stays on this computer and is listed in `.gitignore`: the research working
files (`research/pages/`, `findings/`, `briefs/`, `dossiers/`, `outreach/`, the logs, reports
and `research/arvore.html`), `documents/`, `tree/history/`, `tools/`, `.claude/` and
`antonio/`. A clone can rebuild the web version but does not have the research behind it.

## Folder layout

| Path | What it is |
|---|---|
| `tree/tree.ged` | **The working tree.** Every change goes here; import it back into MyHeritage when you like. |
| `tree/history/` | A copy of the tree before every change (undo = copy one back). |
| `documents/certificates/` | CIL certificate 38995/2021 (Luciano Harres Braga). |
| `documents/charts/` | Pedigree chart: Alberto Salgado Harres line to the Azores. |
| `documents/exports/` | Place for original MyHeritage GEDCOM exports. The November 2026 exports all include Antonio's line, so they are kept in `antonio/documents/exports/`. |
| `web/index.html` | **The web version**: interactive tree (pedigree, sources, quotes, open ends). Rebuilt by `report`. |
| `research/arvore.html` | The same viewer for use on this computer; it also links each researched person to their dossier. Rebuilt by `report`. |
| `research/REPORT.md` | **Start here.** State of the tree, what was found, what waits for your decision, next targets. |
| `research/dossiers/` | One page per researched ancestor: every round, sources, quotes, leads, queries tried. |
| `research/outreach/` | Ready-to-send e-mail drafts (archives, parishes, tree owners). Fill in your name and send. |
| `research/findings/` | Raw research results waiting to be applied; `archive/` keeps them all after applying. |
| `research/briefs/` | The instructions each research agent received. |
| `research/pages/` | Saved copies of web pages the agents relied on. |
| `research/log.jsonl`, `connections.jsonl` | Machine-readable research log and possible identities between people. |
| `heritage/` | The Python code (standard library only, Python 3.10+). |
| `heritage.json` | Settings: tree path, root people, minimum confidence, living-person cutoff. |
| `tools/myheritage/` | Browser helper that saves MyHeritage pages from your own login, for the agents to read. |
| `antonio/` | **Antonio's branch, kept out of git** (listed in `.gitignore`). A workspace of its own with the same layout; see below. |

## Running a research round

In Claude Code, in this folder, type:

    /research            # picks the best 8 open ends
    /research I500024 I1 # or name the people

That generates briefs, runs one agent per person in parallel, checks and applies the
findings, and rewrites `research/REPORT.md`.

## Commands

    python3 -m heritage status                 # overview
    python3 -m heritage frontier -n 30         # open ends, best targets first
    python3 -m heritage show "Theodora"        # look someone up (name or id)
    python3 -m heritage path I500001 I24       # how two people connect
    python3 -m heritage connections            # shared ancestors, duplicates, surname overlaps
    python3 -m heritage brief I500032          # research brief for one person
    python3 -m heritage check I500032          # validate research/findings/I500032.json
    python3 -m heritage apply I500032          # ...and apply what passes
    python3 -m heritage apply research/findings/archive/<file>.json --accept 3,4   # accept held claims
    python3 -m heritage merge I500080 I500112  # merge a duplicate into another person
    python3 -m heritage import new-export.ged  # make a fresh MyHeritage export the working tree
    python3 -m heritage report                 # rewrite research/REPORT.md, research/arvore.html and web/index.html
    python3 -m heritage audit                  # dates, links and names that do not add up (also in the report)
    python3 -m heritage countries              # apply research/countries/out/*.json: birthplaces into the
                                               # tree, presumed countries into research/countries/presumed.json

## How findings are judged

Each claim carries a confidence, and the code checks it against the evidence:

| Confidence | Meaning | GEDCOM QUAY |
|---|---|---|
| proven | a record states it directly (needs a record source + quote) | 3 |
| probable | good published genealogy, or several consistent indications (needs a quote) | 2 |
| possible | plausible, single weaker source; claims resting only on member trees end here | 1 |
| speculative | a hunch; recorded in the dossier, not put in the tree | 0 |

With `"min_confidence": "possible"` (the current, generous setting) everything from
*possible* up is applied. Every added person gets a note with how and why they were
added, and every link carries its source, quote and QUAY, so weak branches stay visible.
Raise it to `"probable"` in `heritage.json` for a stricter tree.

`"roots"` in `heritage.json` lists the people whose pedigrees the report and viewer show;
`"research_roots"` (optional) narrows research targets and open ends to some of them.

## Antonio's branch (`antonio/`, not in git)

The tree used to hold two pedigrees, Alberto's and Antonio's, which meet in a group of
shared 18th-century ancestors. On 23 Nov 2026 Antonio's branch was separated so that this
folder can be committed without it:

- **This folder** keeps Alberto's pedigree, including the 54 ancestors the two share (with
  their sources, dossiers and saved pages). Antonio, his relatives and the 254 people who
  are only on his side are no longer in `tree/tree.ged`.
- **`antonio/`** is a complete workspace for his pedigree: `heritage.json`, `tree/tree.ged`
  (his 254 people plus a copy of the 54 shared ancestors, same ids), `research/` (dossiers,
  briefs, findings, saved pages, outreach drafts, log, report, viewer) and `documents/`
  (his CIL certificate, the Abraham Seneor chart, the MyHeritage exports).
- **`antonio/before-split/`** holds what existed before the separation: the combined tree
  (`tree-combined.ged`), every earlier tree snapshot (`tree-history/`) and the combined
  versions of the files that were split. To undo the separation, copy `tree-combined.ged`
  back to `tree/tree.ged` and restore the roots in `heritage.json`.

Every command works on his workspace with `--home antonio`:

    python3 -m heritage --home antonio status
    python3 -m heritage --home antonio frontier -n 30
    python3 -m heritage --home antonio report      # antonio/research/REPORT.md, arvore.html and antonio/web/index.html

The two trees now grow separately. A shared ancestor researched in one is not updated in the
other, and people added to each get ids from the same sequence, so do not merge the two
files back together without checking for id clashes.

Claims are **held for your decision** (listed in the report) when they would:
contradict a date already in the tree, give someone a second father or mother, or add
a person who seems to be in the tree already. They are **rejected** when impossible
(a parent born after the child, a parent who died long before the birth, a person who
would become their own ancestor).

## Privacy

Agents only research deceased people; anyone who may be alive (no death recorded and
born less than 110 years ago) is excluded from briefs and searches. The root people are
never searched for.

## Sources worth remembering

- Hemeroteca Digital Brasileira — https://memoria.bn.gov.br/hdb/ — Brazilian newspapers;
  good for Rio Pardo and the rest of Rio Grande do Sul (obituaries, marriages, inventories).
- FamilySearch catalogue: Rio Grande do Sul Catholic church records and civil registration.
- CCA Açores digitised parish registers; tombo.pt; repositoriohistorico.pt (Inquisition).
- carneirodafontoura.com, sanguepalmeiro.blogspot.com, geneaminas.com.br.
