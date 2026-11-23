"""Consistency checks on the tree: things that cannot be true or that look like slips.

Read-only. `python3 -m heritage audit` prints the list; the report includes it as
"Things that do not add up". Every line names the people by id so they can be looked up
with `python3 -m heritage show <id>`.
"""
import re

from . import tree as T

# (section title, explanation) in the order they are reported
SECTIONS = [
    ('impossible', 'Cannot be true as recorded'),
    ('unlikely', 'Possible, but worth a second look'),
    ('entry', 'Entry slips (names, dates typed in the wrong place)'),
    ('links', 'Broken or odd links'),
]
TITLES = re.compile(r'^(Sr|Sra|Dr|Dra|Dona|Capitão|Capitao|Coronel|Major|Tenente)\b\.?', re.I)


def run(tree, roots=()):
    """[(section key, text)] for everything that fails a check."""
    out = []
    add = lambda key, text: out.append((key, text))
    L = tree.label

    # --- links ---------------------------------------------------------------
    for i, n in tree.indi.items():
        famc = tree._ids(n, 'FAMC')
        if len([f for f in famc if f in tree.fam]) > 1:
            add('links', f'{L(i)} is a child in more than one family: {", ".join(famc)}')
        for tag in ('FAMC', 'FAMS'):
            for f in tree._ids(n, tag):
                if f not in tree.fam:
                    add('links', f'{L(i)} points to family {f}, which does not exist')
                elif tag == 'FAMC' and i not in tree.fam_children(f):
                    add('links', f'{L(i)} names {f} as parents, but the family does not list the child')
                elif tag == 'FAMS' and i not in tree._ids(tree.fam[f], 'HUSB') + tree._ids(tree.fam[f], 'WIFE'):
                    add('links', f'{L(i)} names {f} as own family, but is not a spouse in it')
    couples = {}
    for f, n in tree.fam.items():
        hs, ws, cs = tree._ids(n, 'HUSB'), tree._ids(n, 'WIFE'), tree._ids(n, 'CHIL')
        for x in hs + ws + cs:
            if x not in tree.indi:
                add('links', f'Family {f} refers to {x}, who does not exist')
        people = [x for x in hs + ws + cs if x in tree.indi]
        if len(people) <= 1:
            add('links', f'Family {f} has a single member: {", ".join(L(x) for x in people) or "nobody"}')
        for x in hs:
            if x in tree.indi and tree.sex(x) == 'F':
                add('links', f'{L(x)} is recorded as female but is the husband in {f}')
        for x in ws:
            if x in tree.indi and tree.sex(x) == 'M':
                add('links', f'{L(x)} is recorded as male but is the wife in {f}')
        h, w = tree.fam_parents(f)
        if h and w:
            couples.setdefault((h, w), []).append(f)
    for (h, w), fs in couples.items():
        if len(fs) > 1:
            add('links', f'{L(h)} and {L(w)} are a couple in several families: {", ".join(fs)}')
    for i in tree.indi:
        seen, stack = set(), [p for p in tree.parents(i) if p]
        while stack:
            x = stack.pop()
            if x == i:
                add('impossible', f'{L(i)} is their own ancestor')
                break
            if x not in seen:
                seen.add(x)
                stack.extend(p for p in tree.parents(x) if p)
    if roots:
        comp, stack = set(), [r for r in roots if r in tree.indi]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            stack.extend(p for p in tree.parents(x) if p)
            stack.extend(tree.children(x))
            stack.extend(s for _, s in tree.spouses(x) if s)
        for i in tree.indi:
            if i not in comp:
                add('links', f'{L(i)} is not connected to the pedigree of any root person')

    # --- one person's own dates ----------------------------------------------
    year = lambda node, *tags: T.year_of(tree.event(node, *tags)[0])
    for i, n in tree.indi.items():
        for tag in ('BIRT', 'CHR', 'BAPM', 'DEAT', 'BURI'):
            for e in n.all(tag):
                d = e.val('DATE')
                if d and not T.GED_DATE.match(d) and not re.match(r'^(FROM|TO|BET|AFT|BEF) ', d):
                    add('entry', f'{L(i)}: the {tag} date reads "{d}"')
        b, d = year(n, 'BIRT'), year(n, 'DEAT')
        c = year(n, 'CHR', 'BAPM')
        if b and d and d < b:
            add('impossible', f'{L(i)} died before being born')
        elif b and d and d - b > 105:
            add('unlikely', f'{L(i)} would have lived {d - b} years')
        if b and c and c < b:
            add('impossible', f'{L(i)} was baptised ({c}) before the recorded birth ({b})')

        by = tree.birth_year(i)
        fa, mo = tree.parents(i)
        for p, role, lo, hi, grace in ((fa, 'father', 14, 75, 1), (mo, 'mother', 13, 52, 0)):
            if not p or not by:
                continue
            pb, pd = tree.birth_year(p), tree.death_year(p)
            if pb and by - pb < lo:
                add('impossible', f'{L(i)}: {role} {L(p)} would have been {by - pb} at the birth')
            elif pb and by - pb > hi:
                add('impossible' if role == 'mother' or by - pb > 90 else 'unlikely',
                    f'{L(i)}: {role} {L(p)} would have been {by - pb} at the birth')
            if pd and by > pd + grace:
                add('impossible', f'{L(i)} was born in {by}, after the {role} {L(p)} died ({pd})')

        name = tree.name(i)
        words = name.split()
        if any(a.lower() == b_.lower() and len(a) > 2 for a, b_ in zip(words, words[1:])):
            add('entry', f'{L(i)}: a word is repeated in the name')
        if name == '(unnamed)':
            add('entry', f'{L(i)} has no name')
        elif TITLES.search(name) or re.search(r'[`?()]', name):
            add('entry', f'{L(i)}: the name contains a title, a bracket or a stray character')

    # --- marriages -------------------------------------------------------------
    for f, n in tree.fam.items():
        my = T.year_of(n.val('MARR', 'DATE'))
        h, w = tree.fam_parents(f)
        for x in (h, w):
            if not x or not my:
                continue
            xb, xd = tree.birth_year(x), tree.death_year(x)
            if xb and my - xb < 12:
                add('impossible', f'{L(x)} would have been {my - xb} at the marriage in {my} ({f})')
            if xd and my > xd:
                add('impossible', f'{L(x)} died in {xd}, before the marriage dated {my} ({f})')
        kids = sorted((tree.birth_year(c), c) for c in tree.fam_children(f) if tree.birth_year(c))
        if kids and my and kids[0][0] < my - 1:
            add('unlikely', f'{L(kids[0][1])} was born {my - kids[0][0]} years before the parents\' marriage dated {my} ({f})')
        if len(kids) > 1 and kids[-1][0] - kids[0][0] > 32:
            add('unlikely', f'Children of {f} were born over {kids[-1][0] - kids[0][0]} years ({kids[0][0]}-{kids[-1][0]})')
    return out


def text(tree, roots=()):
    found = run(tree, roots)
    lines = []
    for key, title in SECTIONS:
        items = [t for k, t in found if k == key]
        if items:
            lines += [f'{title} ({len(items)}):'] + [f'  {t}' for t in items] + ['']
    return '\n'.join(lines) or 'Nothing found.'
