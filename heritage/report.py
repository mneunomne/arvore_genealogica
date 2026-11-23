"""research/REPORT.md: one page with the state of the tree and the research."""
import os
from collections import Counter

from . import audit, connect, research


def build(tree, cfg, paths, root):
    rs = [r for r in cfg['roots'] if r['id'] in tree.indi]
    ids = [r['id'] for r in rs]
    out = ['# Family research report', '',
           f'_Generated {research.TODAY} from `{cfg["tree"]}`: {len(tree.indi)} people, '
           f'{len(tree.fam)} families, {len(tree.sour)} sources._', '']

    out += ['## Pedigrees', '', '| Root person | Ancestors | Generations | Complete generations |', '|---|---|---|---|']
    for r in rs:
        anc = tree.ancestors(r['id'])
        per = Counter(anc.values())
        complete = max((g for g in per if all(per.get(k, 0) == 2 ** k for k in range(g + 1))), default=0)
        out.append(f'| {r["label"]} | {len(anc) - 1} | {max(anc.values())} | {complete} |')
    out.append('')

    research_ids = [i for i in cfg.get('research_roots', ids) if i in tree.indi]
    if research_ids != ids:
        out += ['Research focus: ' + ', '.join(tree.name(i) for i in research_ids) + '.', '']

    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            ca = connect.common_ancestors(tree, a, b)
            if ca:
                out += [f'## How {tree.name(a)} and {tree.name(b)} connect', '']
                for i, ga, gb in ca[:4]:
                    out.append(f'- {tree.label(i)} — {connect.kinship(ga, gb)}')
                out.append('')

    log = research.read_jsonl(paths.log)
    if log:
        out += ['## Research rounds', '', '| Date | Person | Result | Changes applied | Held for review |',
                '|---|---|---|---|---|']
        for e in log[-60:][::-1]:
            name = tree.label(e['target']) if e['target'] in tree.indi else e['target']
            dossier = [f for f in os.listdir(paths.dossiers) if f.startswith(e['target'] + '-')]
            if dossier:
                name = f'[{name}](dossiers/{dossier[0]})'
            out.append(f'| {e["date"]} | {name} | {e["status"]} | {e["applied"]} | {e["held"]} |')
        out.append('')

    held = []
    for f in sorted(os.listdir(paths.archive)):
        if not f.endswith('.json'):
            continue
        import json
        data = json.load(open(os.path.join(paths.archive, f), encoding='utf-8'))
        for k, c in enumerate(data.get('claims', [])):
            if c.get('_decision') == 'hold' and not c.get('_applied') and not c.get('_superseded_by'):
                held.append((f, k, c))
    if held:
        out += ['## Waiting for your decision', '',
                'Accept a claim with `python3 -m heritage apply research/findings/archive/<file> --accept <n>`.', '']
        for f, k, c in held:
            out.append(f'- `{f}` claim {k} ({c.get("type")}, {c.get("confidence")}): {c.get("reasoning", "")[:300]} '
                       f'— _{"; ".join(c.get("_reasons", []))}_')
        out.append('')

    conns = [c for c in research.read_jsonl(paths.connections) if c.get('status') == 'open']
    if conns:
        out += ['## Possible identities to check', '']
        for c in conns:
            la = tree.label(c['a']) if c['a'] in tree.indi else c['a']
            lb = tree.label(c['b']) if c['b'] in tree.indi else c['b']
            out.append(f'- {la} = {lb}? ({c.get("confidence")}) {c.get("reasoning", "")}')
        out.append('')

    dups = connect.duplicates(tree)
    if dups:
        out += ['## Possible duplicate entries', '']
        out += [f'- {tree.label(x)} and {tree.label(y)}' for _, x, y in dups[:20]]
        out.append('')

    found = audit.run(tree, ids)
    if found:
        out += ['## Things that do not add up', '',
                'From `python3 -m heritage audit`. Most come from the imported MyHeritage trees and need a record to settle.', '']
        for key, title in audit.SECTIONS:
            items = [t for k, t in found if k == key]
            if items:
                out += [f'**{title}**', ''] + [f'- {t}' for t in items] + ['']

    drafts = sorted(f for f in os.listdir(paths.outreach) if f.endswith('.md'))
    if drafts:
        out += ['## E-mail drafts ready to send', '']
        out += [f'- [{f}](outreach/{f})' for f in drafts]
        out.append('')

    fr = research.frontier(tree, research_ids, paths)
    out += ['## Next research targets', '', '| Score | Person | Generation | Missing | Last research |', '|---|---|---|---|---|']
    for t in fr[:20]:
        out.append(f'| {t["score"]} | {tree.label(t["id"])} | {t["gen"]} | {", ".join(t["missing"])} | {t["last"] or "-"} |')
    out.append('')

    path = os.path.join(paths.research, 'REPORT.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    return os.path.relpath(path, root)
