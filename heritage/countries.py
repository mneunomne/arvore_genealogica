"""Birth countries: apply reviewed birthplaces and presumed countries.

Input: research/countries/out/*.json, one object per person (see research/countries/BRIEF.md).
- kind "recorded": the birth (BIRT) or baptism (CHR) place is written into the tree, with source,
  quote and QUAY, and a note saying when and why.
- kind "presumed" / "unknown": stored in research/countries/presumed.json, which the viewer reads
  to show a half-transparent flag (null country = do not presume).
"""
import glob
import json
import os

from . import viewer
from .research import TODAY
from .tree import to_gedcom_date

QUAY = {'proven': 3, 'probable': 2, 'possible': 1}


def apply(tree, paths, dry_run=False):
    folder = os.path.join(paths.research, 'countries')
    items = []
    for path in sorted(glob.glob(os.path.join(folder, 'out', '*.json'))):
        with open(path, encoding='utf-8') as f:
            items += json.load(f)
    presumed_path = os.path.join(folder, 'presumed.json')
    presumed = {}
    if os.path.exists(presumed_path):
        with open(presumed_path, encoding='utf-8') as f:
            presumed = json.load(f)
    log, problems, written = [], [], 0
    for it in items:
        i, kind, code = it.get('id'), it.get('kind'), it.get('country')
        if i not in tree.indi:
            problems.append(f'{i}: not in the tree')
            continue
        who = f'{tree.name(i)} [{i}]'
        if code and code not in viewer.COUNTRIES:
            problems.append(f'{who}: country {code} has no flag yet (add it to viewer.COUNTRIES)')
            continue
        if kind == 'recorded':
            node, tag, place = tree.indi[i], it.get('event') or 'BIRT', (it.get('place') or '').strip()
            got = viewer.place_country(place) if place else None
            if tag not in ('BIRT', 'CHR') or not place or got != code or not it.get('quote'):
                problems.append(f'{who}: recorded claim incomplete or place "{place}" reads as {got}, not {code}')
                continue
            if viewer._birth_country(node):
                continue            # already has a country (applied before, or fixed by hand)
            old_date = tree.event(node, tag)[0]
            date = None
            if it.get('date') and not old_date:
                try:
                    date = to_gedcom_date(it['date'])
                except ValueError:
                    problems.append(f'{who}: date {it["date"]!r} not understood, place applied without it')
            ch = tree.set_event(node, tag, date, place)
            if not ch:
                continue
            conf = it.get('confidence') if it.get('confidence') in QUAY else 'possible'
            sid = tree.add_source(it.get('source_title') or 'Birthplace research', it.get('source_url'),
                                  note=f'Accessed {TODAY} while filling in missing birth countries.')
            tree.cite(node, sid, quay=QUAY[conf], page=it.get('source_url'), text=it['quote'].strip())
            word = 'Birthplace' if tag == 'BIRT' else 'Baptism place'
            node.add_text('NOTE', f'{word} added by research on {TODAY} (birth-country review), '
                                  f'confidence {conf}: {place}. Source: {it.get("source_title") or "?"}.')
            presumed.pop(i, None)
            written += 1
            log.append(f'{who}: {ch}')
        elif kind in ('presumed', 'unknown'):
            if viewer._birth_country(tree.indi[i]):
                presumed.pop(i, None)
                continue
            entry = {'country': code if kind == 'presumed' else None, 'why': (it.get('reason') or '').strip()}
            if presumed.get(i) != entry:
                presumed[i] = entry
                if kind == 'presumed':
                    log.append(f'{who}: presumed {code} ({entry["why"]})')
        else:
            problems.append(f'{who}: unknown kind {kind!r}')
    if not dry_run:
        if written:
            tree.save()
        with open(presumed_path, 'w', encoding='utf-8') as f:
            json.dump(dict(sorted(presumed.items())), f, ensure_ascii=False, indent=1)
            f.write('\n')
    return log, problems
