"""Command line for the heritage research system.  Run `python3 -m heritage -h`."""
import argparse
import datetime
import json
import os
import shutil
import sys

from . import connect, research
from .tree import Tree, slug

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The workspace: the folder holding heritage.json, tree/ and research/.  It is this project
# folder unless --home (or HERITAGE_HOME) names another one, e.g. `--home antonio`.
ROOT = CODE


def config():
    with open(os.path.join(ROOT, 'heritage.json'), encoding='utf-8') as f:
        return json.load(f)


def load():
    cfg = config()
    tree = Tree(os.path.join(ROOT, cfg['tree']), cfg.get('living_years', 110))
    return cfg, tree, research.Paths(ROOT)


def roots(cfg, tree):
    configured = cfg.get('research_roots', [r['id'] for r in cfg['roots']])
    return [i for i in configured if i in tree.indi]


# --- commands ----------------------------------------------------------------
def cmd_status(a):
    cfg, tree, paths = load()
    print(f'Tree: {cfg["tree"]} — {len(tree.indi)} people, {len(tree.fam)} families, {len(tree.sour)} sources')
    for r in cfg['roots']:
        anc = tree.ancestors(r['id'])
        print(f'  {r["label"]}: {len(anc) - 1} ancestors, {max(anc.values())} generations deep')
    fr = research.frontier(tree, roots(cfg, tree), paths)
    print(f'Open ends (ancestors with a missing parent): {len(fr)}')
    log = research.read_jsonl(paths.log)
    if log:
        print(f'Research rounds: {len(log)}, last {log[-1]["date"]}')
    pending = [f for f in os.listdir(paths.findings) if f.endswith('.json')]
    if pending:
        print(f'Findings waiting to be applied: {", ".join(sorted(pending))}')
    conns = [c for c in research.read_jsonl(paths.connections) if c.get('status') == 'open']
    if conns:
        print(f'Open possible identities to review: {len(conns)} (research/connections.jsonl)')


def cmd_frontier(a):
    cfg, tree, paths = load()
    fr = research.frontier(tree, roots(cfg, tree), paths, a.all)
    for t in fr[:a.n]:
        print(f'{t["score"]:4d}  {t["id"]:>9}  gen {t["gen"]:>2}  {t["name"]} '
              f'(~{t["year"] or "?"}, {t["place"] or "no place"}) missing {"+".join(t["missing"])}'
              + (f'  [last: {t["last"]}]' if t['last'] else ''))
    if a.json:
        print(json.dumps(fr[:a.n], ensure_ascii=False))


def cmd_brief(a):
    cfg, tree, paths = load()
    text = research.brief(tree, a.id, paths, roots(cfg, tree))
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(text)
        print(a.out)
    else:
        print(text)


def _load_findings(paths, ident):
    p = ident if ident.endswith('.json') else paths.finding(ident)
    with open(p, encoding='utf-8') as f:
        return p, json.load(f)


def _report(checker):
    for p in checker.problems:
        print(f'  PROBLEM  {p}')
    for n, c in enumerate(checker.f.get('claims', [])):
        what = {'parents': lambda c: f'parents of {c.get("child")}: {c.get("father")} + {c.get("mother")}',
                'fact': lambda c: f'{c.get("event")} of {c.get("person")}: {c.get("date") or ""} {c.get("place") or ""}',
                'spouse': lambda c: f'spouse of {c.get("person")}: {c.get("spouse")}',
                'note': lambda c: f'note on {c.get("person")}',
                'same_person': lambda c: f'{c.get("a")} = {c.get("b")}?'}.get(c.get('type'), lambda c: c.get('type'))(c)
        print(f'  [{n}] {c.get("_decision", "?").upper():7} {c.get("confidence", "?"):11} {what}')
        for r in c.get('_reasons', []):
            print(f'               - {r}')


def cmd_check(a):
    cfg, tree, paths = load()
    _, f = _load_findings(paths, a.id)
    ch = research.Checker(tree, f, a.min or cfg.get('min_confidence', 'probable'))
    ch.run()
    _report(ch)
    sys.exit(1 if ch.problems else 0)


def cmd_apply(a):
    cfg, tree, paths = load()
    path, f = _load_findings(paths, a.id)
    accept = [int(x) for x in (a.accept or '').split(',') if x.strip()]
    ch = research.Checker(tree, f, a.min or cfg.get('min_confidence', 'probable'), accept)
    if not ch.run():
        _report(ch)
        print('Not applied: fix the problems above in the findings file first.')
        sys.exit(1)
    changes = research.apply(tree, ch, paths)
    _report(ch)
    if a.dry_run:
        print('\n'.join(['Would change:'] + [f'  {c}' for c in changes]))
        return
    if changes:
        tree.save()
    reviewed = '_reviewed' in f
    research.write_dossier(tree, f, changes, paths, review=reviewed)
    if not reviewed:
        research.append_jsonl(paths.log, {'date': research.TODAY, 'target': f['target'], 'status': f.get('status'),
                                          'applied': len(changes),
                                          'held': sum(c.get('_decision') == 'hold' for c in f.get('claims', []))})
    # keep the finding (with decisions) in the archive; held claims can be accepted later
    f['_reviewed'] = research.TODAY
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    in_archive = os.path.dirname(os.path.abspath(path)) == os.path.abspath(paths.archive)
    dest = path if in_archive else os.path.join(paths.archive, f'{f["target"]}-{stamp}.json')
    with open(dest, 'w', encoding='utf-8') as out:
        json.dump(f, out, ensure_ascii=False, indent=2)
    if os.path.dirname(os.path.abspath(path)) == os.path.abspath(paths.findings):
        os.remove(path)
    print('\n'.join(['Changes:'] + [f'  {c}' for c in changes] if changes else ['No changes to the tree.']))
    print(f'Archived as {os.path.relpath(dest, ROOT)}')


def cmd_show(a):
    cfg, tree, paths = load()
    ids = tree.find(a.query)
    for i in ids[:a.n]:
        f, m = tree.parents(i)
        print(tree.label(i))
        for p in tree.places(i)[:3]:
            print(f'    place: {p}')
        print(f'    father: {tree.label(f) if f else "-"}\n    mother: {tree.label(m) if m else "-"}')
        for fam, s in tree.spouses(i):
            print(f'    spouse: {tree.label(s) if s else "?"} ({fam}); children: '
                  + ', '.join(tree.name(c) for c in tree.fam_children(fam)))
    if not ids:
        print('nobody found')


def cmd_path(a):
    cfg, tree, paths = load()
    p = connect.path(tree, a.a, a.b)
    if not p:
        print('No connection in the tree.')
        return
    for rel, i in p:
        print(f'  {rel:>7} -> {tree.label(i)}')
    for i, ga, gb in connect.common_ancestors(tree, a.a, a.b)[:4]:
        print(f'Common ancestor {tree.label(i)}: {ga} / {gb} generations — {connect.kinship(ga, gb)}')


def cmd_connections(a):
    cfg, tree, paths = load()
    rs = roots(cfg, tree)
    print('== Possible duplicates (same person entered twice)')
    for s, x, y in connect.duplicates(tree)[:a.n]:
        print(f'  {s:.2f}  {tree.label(x)}  <->  {tree.label(y)}')
    for n, x in enumerate(rs):
        for y in rs[n + 1:]:
            print(f'\n== {x} and {y}')
            for i, ga, gb in connect.common_ancestors(tree, x, y)[:6]:
                print(f'  common ancestor {tree.label(i)} — {connect.kinship(ga, gb)}')
            print('  Surnames in both pedigrees (possible further links):')
            for o in connect.overlaps(tree, x, y)[:a.n]:
                print(f'    {o["surname"]}: ' + '; '.join(tree.label(i) for i in o['a'][:3]) + '  |  '
                      + '; '.join(tree.label(i) for i in o['b'][:3]))
    print('\n== Open ends sharing a surname with other branches')
    fr = [t['id'] for t in research.frontier(tree, rs, paths, True)]
    for i, others in connect.brick_wall_surnames(tree, fr)[:a.n]:
        print(f'  {tree.label(i)}: ' + '; '.join(tree.label(j) for j in others[:4]))


def cmd_import(a):
    """Make a new GEDCOM export (e.g. from MyHeritage) the working tree."""
    cfg = config()
    dest = os.path.join(ROOT, cfg['tree'])
    Tree(a.file)  # must parse
    if os.path.exists(dest):
        hist = os.path.join(os.path.dirname(dest), 'history')
        os.makedirs(hist, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        shutil.copy2(dest, os.path.join(hist, f'tree-{stamp}.ged'))
    shutil.copy2(a.file, dest)
    print(f'{a.file} is now {cfg["tree"]} (previous version kept in history/)')


def cmd_merge(a):
    cfg, tree, paths = load()
    for x in (a.keep, a.drop):
        if x not in tree.indi:
            sys.exit(f'{x} is not in the tree')
    print(f'Keeping {tree.label(a.keep)}\nMerging {tree.label(a.drop)}')
    tree.merge(a.keep, a.drop)
    tree.save()
    conns = research.read_jsonl(paths.connections)
    if conns:
        for c in conns:
            if {c.get('a'), c.get('b')} == {a.keep, a.drop}:
                c['status'] = 'merged'
        with open(paths.connections, 'w', encoding='utf-8') as f:
            f.writelines(json.dumps(c, ensure_ascii=False) + '\n' for c in conns)
    print('Done (previous tree kept in tree/history/).')


def cmd_mh_targets(a):
    """Fill tools/myheritage/targets.json with the current open ends."""
    cfg, tree, paths = load()
    path = os.path.join(ROOT, 'tools', 'myheritage', 'targets.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}
    targets = []
    for t in research.frontier(tree, roots(cfg, tree), paths)[:a.n]:
        node = tree.indi[t['id']]
        given = node.val('NAME', 'GIVN') or tree.name(t['id']).split(' ')[0]
        surname = node.val('NAME', 'SURN') or ''
        place = (t['place'] or '').split(',')[0].strip()
        targets.append({'name': slug(tree.name(t['id'])), 'first': given, 'last': surname,
                        'year': str(t['year'] or ''), 'place': place})
    old['searchTemplate'] = old.get('searchTemplate') or 'PASTE-A-SEARCH-URL-HERE'
    old['targets'] = targets
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(old, f, ensure_ascii=False, indent=2)
    print(f'{len(targets)} targets written to {os.path.relpath(path, ROOT)}')


def cmd_countries(a):
    from . import countries
    cfg, tree, paths = load()
    log, problems = countries.apply(tree, paths, dry_run=a.dry_run)
    for line in log:
        print('  ' + line)
    for line in problems:
        print('  ! ' + line)
    print(f'{len(log)} change(s){" (dry run, nothing written)" if a.dry_run else ""}, {len(problems)} problem(s).')
    if not a.dry_run:
        cmd_report(a)


def cmd_audit(a):
    from . import audit
    cfg, tree, paths = load()
    print(audit.text(tree, [r['id'] for r in cfg['roots']]))


def cmd_report(a):
    from . import report, viewer
    cfg, tree, paths = load()
    print(report.build(tree, cfg, paths, ROOT))
    print(viewer.build(tree, cfg, paths, ROOT))


def main(argv=None):
    global ROOT
    p = argparse.ArgumentParser(prog='heritage', description=__doc__)
    p.add_argument('--home', default=os.environ.get('HERITAGE_HOME'),
                   help='workspace folder to work on (default: this project; e.g. --home antonio)')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status', help='overview of the tree and the research').set_defaults(fn=cmd_status)
    s = sub.add_parser('frontier', help='ancestors with missing parents, best research targets first')
    s.add_argument('-n', type=int, default=25)
    s.add_argument('--all', action='store_true', help='do not push down recently researched people')
    s.add_argument('--json', action='store_true')
    s.set_defaults(fn=cmd_frontier)
    s = sub.add_parser('brief', help='research brief for one person (for an agent or by hand)')
    s.add_argument('id')
    s.add_argument('-o', '--out')
    s.set_defaults(fn=cmd_brief)
    for name, fn, h in (('check', cmd_check, 'validate a findings file without changing anything'),
                        ('apply', cmd_apply, 'validate a findings file and apply what passes')):
        s = sub.add_parser(name, help=h)
        s.add_argument('id', help='person id (reads research/findings/<id>.json) or a path to a findings file')
        s.add_argument('--min', choices=list(research.CONF), help='lowest confidence that is applied')
        if name == 'apply':
            s.add_argument('--accept', help='comma-separated claim numbers held for review that you accept')
            s.add_argument('--dry-run', action='store_true')
        s.set_defaults(fn=fn)
    s = sub.add_parser('show', help='look someone up')
    s.add_argument('query')
    s.add_argument('-n', type=int, default=5)
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser('path', help='how two people are connected')
    s.add_argument('a')
    s.add_argument('b')
    s.set_defaults(fn=cmd_path)
    s = sub.add_parser('connections', help='duplicates, shared ancestors and surname overlaps')
    s.add_argument('-n', type=int, default=20)
    s.set_defaults(fn=cmd_connections)
    s = sub.add_parser('import', help='make a new GEDCOM export the working tree')
    s.add_argument('file')
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser('merge', help='merge a duplicate person into another')
    s.add_argument('keep')
    s.add_argument('drop')
    s.set_defaults(fn=cmd_merge)
    s = sub.add_parser('myheritage-targets', help='fill tools/myheritage/targets.json from the open ends')
    s.add_argument('-n', type=int, default=30)
    s.set_defaults(fn=cmd_mh_targets)
    sub.add_parser('report', help='write research/REPORT.md, research/arvore.html and web/index.html').set_defaults(fn=cmd_report)
    sub.add_parser('audit', help='list dates, links and names that do not add up').set_defaults(fn=cmd_audit)
    s = sub.add_parser('countries', help='apply research/countries/out/*.json: birthplaces and presumed countries')
    s.add_argument('--dry-run', action='store_true')
    s.set_defaults(fn=cmd_countries)
    a = p.parse_args(argv)
    if a.home:
        ROOT = os.path.abspath(a.home if os.path.isdir(a.home) else os.path.join(CODE, a.home))
        if not os.path.exists(os.path.join(ROOT, 'heritage.json')):
            sys.exit(f'{ROOT} has no heritage.json')
    a.fn(a)
