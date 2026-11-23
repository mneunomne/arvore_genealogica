"""Finding connections: duplicates, relationship paths, shared ancestors,
and surname/place overlaps between the pedigrees of different root people."""
from collections import defaultdict

from .tree import name_similarity, name_tokens


def duplicates(tree, min_score=0.85):
    """Pairs of people who look like the same person recorded twice."""
    ids = list(tree.indi)
    toks = {i: set(name_tokens(tree.name(i))) for i in ids}
    out = []
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            if len(toks[a] & toks[b]) < 1 or len(toks[a]) < 2 or len(toks[b]) < 2:
                continue
            s = name_similarity(tree.name(a), tree.name(b))
            if s < min_score:
                continue
            if 'U' not in (tree.sex(a), tree.sex(b)) and tree.sex(a) != tree.sex(b):
                continue
            ya, yb = tree.est_year(a), tree.est_year(b)
            if ya and yb and abs(ya - yb) > 12:
                continue
            if b in tree.parents(a) or a in tree.parents(b) or b in tree.siblings(a):
                continue
            out.append((s, a, b))
    return sorted(out, reverse=True)


def path(tree, a, b):
    """Shortest chain of parent/child/spouse steps from a to b: [(relation, id)]."""
    prev, queue = {a: None}, [a]
    while queue:
        i = queue.pop(0)
        if i == b:
            break
        father, mother = tree.parents(i)
        steps = [('father', father), ('mother', mother)]
        steps += [('child', c) for c in tree.children(i)]
        steps += [('spouse', s) for _, s in tree.spouses(i)]
        for rel, j in steps:
            if j and j not in prev:
                prev[j] = (rel, i)
                queue.append(j)
    if b not in prev:
        return None
    chain, i = [], b
    while prev[i]:
        rel, j = prev[i]
        chain.append((rel, i))
        i = j
    return [('start', a)] + chain[::-1]


def common_ancestors(tree, a, b):
    """[(id, generations from a, generations from b)], nearest first, couples' own ancestors dropped."""
    ga, gb = tree.ancestors(a), tree.ancestors(b)
    shared = set(ga) & set(gb)
    # keep only the most recent ones: drop anyone who is an ancestor of another shared person
    covered = set()
    for i in shared:
        covered |= set(tree.ancestors(i)) - {i}
    return sorted(((i, ga[i], gb[i]) for i in shared - covered), key=lambda t: t[1] + t[2])


def kinship(ga, gb):
    """English name of the relationship given generations to the common ancestor."""
    if ga == 0 or gb == 0:
        n = max(ga, gb)
        names = {0: 'same person', 1: 'parent/child', 2: 'grandparent/grandchild'}
        return names.get(n, f'{n - 2}x great-grandparent/descendant')
    if ga == 1 and gb == 1:
        return 'siblings'
    if min(ga, gb) == 1:
        n = max(ga, gb) - 2
        return 'uncle/aunt – nephew/niece' if n == 0 else f'{n}x great-uncle/aunt'
    degree, removed = min(ga, gb) - 1, abs(ga - gb)
    suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(degree if degree < 20 else degree % 10, 'th')
    return f'{degree}{suffix} cousins' + (f' {removed}x removed' if removed else '')


# devotional surnames shared by thousands of unrelated people: useless as a clue
COMMON = {'jesus', 'conceicao', 'silva', 'santos', 'espirito', 'santo', 'anjos', 'assuncao', 'nascimento',
          'rosario', 'luz', 'trindade', 'nunes', 'pereira', 'oliveira', 'sousa', 'souza', 'roza', 'rosa',
          'maria', 'martins', 'goncalves', 'fernandes', 'rodrigues', 'alves', 'costa'}


def surname_key(tree, i):
    toks = name_tokens(tree.name(i))
    if len(toks) < 2:
        return None
    for t in reversed(toks[1:]):
        if t not in {name_tokens(x)[0] for x in COMMON if name_tokens(x)}:
            return t
    return None


def overlaps(tree, root_a, root_b, window=80):
    """Surnames that occur in both pedigrees (outside the already shared ancestors) in
    overlapping periods: places to look for a further link between the two families."""
    ga, gb = tree.ancestors(root_a), tree.ancestors(root_b)
    shared = set(ga) & set(gb)
    groups = {}
    for side, anc in (('a', ga), ('b', gb)):
        g = defaultdict(list)
        for i in anc:
            if i in shared:
                continue
            k = surname_key(tree, i)
            if k:
                g[k].append(i)
        groups[side] = g
    out = []
    for k in set(groups['a']) & set(groups['b']):
        ya = [tree.est_year(i) for i in groups['a'][k] if tree.est_year(i)]
        yb = [tree.est_year(i) for i in groups['b'][k] if tree.est_year(i)]
        gap = None
        if ya and yb:
            gap = max(0, max(min(ya), min(yb)) - min(max(ya), max(yb)))
            if gap > window:
                continue
        out.append({'surname': k, 'gap_years': gap, 'a': groups['a'][k], 'b': groups['b'][k]})
    return sorted(out, key=lambda o: (o['gap_years'] is None, o['gap_years'] or 0, -len(o['a']) - len(o['b'])))


def brick_wall_surnames(tree, frontier_ids):
    """Frontier people whose surname also belongs to someone elsewhere in the tree."""
    by = defaultdict(list)
    for i in tree.indi:
        k = surname_key(tree, i)
        if k:
            by[k].append(i)
    out = []
    for i in frontier_ids:
        k = surname_key(tree, i)
        if not k:
            continue
        related = set(tree.ancestors(i)) | tree.descendants(i) | set(tree.siblings(i)) | {i}
        others = [j for j in by[k] if j not in related
                  and not (set(tree.ancestors(j)) & related) and tree.est_year(j) and tree.est_year(i)
                  and abs(tree.est_year(j) - tree.est_year(i)) <= 90]
        if others:
            out.append((i, others))
    return out
