"""Family-tree view on top of the lossless GEDCOM document.

Ids are used without the surrounding @ signs everywhere ("I500001", "F12").
"""
import datetime
import difflib
import os
import re
import shutil
import unicodedata

from . import gedcom

MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
GED_DATE = re.compile(
    r'^(?:(?:ABT|EST|CAL|BEF|AFT) )?(?:(?:\d{1,2} )?(?:%s) )?\d{3,4}$'
    r'|^BET \d{3,4} AND \d{3,4}$' % '|'.join(MONTHS))
PARTICLES = {'de', 'da', 'do', 'dos', 'das', 'e', 'd', 'di', 'del', 'la', 'le', 'von', 'van', 'der'}
SUFFIXES = {'filho', 'junior', 'jr', 'neto', 'sobrinho', 'senior', 'sr'}


# --- dates -------------------------------------------------------------------
def year_of(date):
    m = re.search(r'(?<!\d)(\d{3,4})(?!\d)', date or '')
    return int(m.group(1)) if m else None


def is_exact(date):
    return bool(re.fullmatch(r'\d{1,2} [A-Z]{3} \d{3,4}', date or ''))


def to_gedcom_date(s):
    """Normalise the date spellings a researcher is likely to write."""
    s = (s or '').strip()
    if not s:
        return None
    up = s.upper().replace('.', '')
    if GED_DATE.match(up):
        return up
    qual = ''
    m = re.match(r'^(c|ca|circa|cerca de|por volta de|abt|about|~|est)\s*', s, re.I)
    if m:
        qual, s = 'ABT ', s[m.end():]
    else:
        m = re.match(r'^(before|antes de|bef|<)\s*', s, re.I)
        if m:
            qual, s = 'BEF ', s[m.end():]
        else:
            m = re.match(r'^(after|depois de|aft|>)\s*', s, re.I)
            if m:
                qual, s = 'AFT ', s[m.end():]
    s = s.strip().rstrip('?').strip()
    m = re.fullmatch(r'(\d{3,4})-(\d{1,2})-(\d{1,2})', s)
    if m:
        return f'{qual}{int(m.group(3))} {MONTHS[int(m.group(2)) - 1]} {m.group(1)}'
    m = re.fullmatch(r'(\d{3,4})-(\d{1,2})', s)
    if m:
        return f'{qual}{MONTHS[int(m.group(2)) - 1]} {m.group(1)}'
    m = re.fullmatch(r'(\d{1,2})[/.](\d{1,2})[/.](\d{3,4})', s)   # dd/mm/yyyy
    if m:
        return f'{qual}{int(m.group(1))} {MONTHS[int(m.group(2)) - 1]} {m.group(3)}'
    m = re.fullmatch(r'\d{3,4}', s)
    if m:
        return f'{qual}{s}'
    up = (qual + s).upper()
    if GED_DATE.match(up):
        return up
    raise ValueError(f'date not understood: {s!r} (use e.g. "12 MAR 1801", "ABT 1740", "1801-03-12")')


# --- names -------------------------------------------------------------------
def _norm_token(t):
    t = unicodedata.normalize('NFD', t.lower())
    t = ''.join(c for c in t if 'a' <= c <= 'z')
    for a, b in (('ph', 'f'), ('th', 't'), ('ch', 'c'), ('gn', 'n'), ('oe', 'ue'),
                 ('y', 'i'), ('z', 's'), ('w', 'v'), ('k', 'c')):
        t = t.replace(a, b)
    return re.sub(r'(.)\1+', r'\1', t)


def name_tokens(name):
    """Spelling-tolerant tokens: Ignacia=Inácia, Luiz=Luís, Roza=Rosa, Manoel=Manuel."""
    raw = re.split(r"[\s/,.'`´-]+", name or '')
    toks = [_norm_token(t) for t in raw]
    return [t for t in toks if t and t not in PARTICLES and t not in SUFFIXES]


def name_similarity(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    left = list(big)
    hits = 0
    for t in small:
        best = max(left, key=lambda x: difflib.SequenceMatcher(None, t, x).ratio(), default=None)
        if best is not None and difflib.SequenceMatcher(None, t, best).ratio() >= 0.84:
            hits += 1
            left.remove(best)
    score = 0.5 * hits / len(small) + 0.5 * hits / len(big)
    if difflib.SequenceMatcher(None, ta[0], tb[0]).ratio() < 0.84:
        score *= 0.5      # different first given name: very unlikely the same person
    return score


def slug(s):
    s = unicodedata.normalize('NFD', s or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:60]


# --- the tree ----------------------------------------------------------------
class Tree:
    def __init__(self, path, living_years=110):
        self.path = path
        self.living_years = living_years
        self.doc = gedcom.load(path)
        self.reindex()

    def reindex(self):
        self.indi, self.fam, self.sour = {}, {}, {}
        for r in self.doc.records:
            if r.xref and r.tag in ('INDI', 'FAM', 'SOUR'):
                {'INDI': self.indi, 'FAM': self.fam, 'SOUR': self.sour}[r.tag][r.xref.strip('@')] = r
        self._est = None

    # --- people ---
    def name(self, i):
        n = self.indi[i].val('NAME') or ''
        return re.sub(r'\s+', ' ', n.replace('/', ' ')).strip() or '(unnamed)'

    def sex(self, i):
        return self.indi[i].val('SEX') or 'U'

    def event(self, node, *tags):
        """(date, place) of the first of the given events that exists."""
        for t in tags:
            e = node.get(t)
            if e is not None and (e.val('DATE') or e.val('PLAC')):
                return e.val('DATE'), e.val('PLAC')
        return None, None

    def birth_year(self, i):
        return year_of(self.event(self.indi[i], 'BIRT')[0]) or year_of(self.event(self.indi[i], 'CHR', 'BAPM')[0])

    def death_year(self, i):
        return year_of(self.event(self.indi[i], 'DEAT')[0]) or year_of(self.event(self.indi[i], 'BURI')[0])

    def lifespan(self, i):
        b, d = self.event(self.indi[i], 'BIRT', 'CHR', 'BAPM')[0], self.event(self.indi[i], 'DEAT', 'BURI')[0]
        if not b and not d:
            y = self.est_year(i)
            return f'~{y}?' if y else '?'
        return f'{b or "?"} – {d or "?"}'

    def label(self, i):
        return f'{self.name(i)} ({self.lifespan(i)}) [{i}]'

    def places(self, i):
        out = []
        for e in self.indi[i].children:
            p = e.val('PLAC')
            if p and p not in out:
                out.append(p)
        return out

    # --- relations ---
    def _ids(self, node, tag):
        return [c.value.strip('@') for c in node.all(tag) if c.value]

    def famc(self, i):
        for f in self._ids(self.indi[i], 'FAMC'):
            if f in self.fam:
                return f
        return None

    def fams(self, i):
        return [f for f in self._ids(self.indi[i], 'FAMS') if f in self.fam]

    def fam_parents(self, f):
        h, w = self._ids(self.fam[f], 'HUSB'), self._ids(self.fam[f], 'WIFE')
        h = [x for x in h if x in self.indi]
        w = [x for x in w if x in self.indi]
        return (h[0] if h else None, w[0] if w else None)

    def fam_children(self, f):
        return [c for c in self._ids(self.fam[f], 'CHIL') if c in self.indi]

    def parents(self, i):
        f = self.famc(i)
        return self.fam_parents(f) if f else (None, None)

    def spouses(self, i):
        """[(family id, spouse id or None)]"""
        out = []
        for f in self.fams(i):
            h, w = self.fam_parents(f)
            out.append((f, w if h == i else h))
        return out

    def children(self, i):
        return [c for f in self.fams(i) for c in self.fam_children(f)]

    def siblings(self, i):
        f = self.famc(i)
        return [c for c in self.fam_children(f) if c != i] if f else []

    def ancestors(self, root):
        """{id: generation}, root is generation 0 (shortest path wins)."""
        seen, queue = {}, [(root, 0)]
        while queue:
            i, g = queue.pop(0)
            if i in seen or i not in self.indi:
                continue
            seen[i] = g
            queue.extend((p, g + 1) for p in self.parents(i) if p)
        return seen

    def descendants(self, i):
        seen, stack = set(), [i]
        while stack:
            for c in self.children(stack.pop()):
                if c not in seen:
                    seen.add(c)
                    stack.append(c)
        return seen

    # --- estimated years and the living-person guard ---
    def est_year(self, i):
        """Birth year, or a rough estimate from relatives (None if hopeless)."""
        if self._est is None:
            est = {p: self.birth_year(p) for p in self.indi if self.birth_year(p)}
            self._propagate(est)
            # a death year is a weak clue: use it only where relatives gave nothing
            for p in self.indi:
                if p not in est and self.death_year(p):
                    est[p] = self.death_year(p) - 60
            self._propagate(est)
            self._est = est
        return self._est.get(i)

    def _propagate(self, est):
        """Fill in years from relatives (children, parents, spouses, marriages), in place."""
        for _ in range(40):
            new = {}
            for p in self.indi:
                if p in est:
                    continue
                kids = [est[c] for c in self.children(p) if c in est]
                guesses = [min(kids) - 28] if kids else []
                guesses += [est[x] + 30 for x in self.parents(p) if x in est]
                guesses += [est[s] for _, s in self.spouses(p) if s in est]
                for m in self.fams(p):
                    y = year_of(self.fam[m].val('MARR', 'DATE'))
                    if y:
                        guesses.append(y - 25)
                if guesses:
                    new[p] = round(sum(guesses) / len(guesses))
            if not new:
                break
            est.update(new)

    def possibly_living(self, i):
        """True unless the person is recorded as dead or born long enough ago."""
        if self.indi[i].get('DEAT') is not None or self.indi[i].get('BURI') is not None:
            return False
        y = self.est_year(i)
        return y is None or y > datetime.date.today().year - self.living_years

    # --- search ---
    def find(self, text):
        if text.strip('@') in self.indi:
            return [text.strip('@')]
        want = name_tokens(text)
        out = []
        for i in self.indi:
            have = name_tokens(self.name(i))
            if want and all(any(h.startswith(w) for h in have) for w in want):
                out.append(i)
        return out

    def similar(self, name, year=None, tol=10, sex=None, min_score=0.8):
        """Existing people who might be the same person as (name, year)."""
        out = []
        for i in self.indi:
            s = name_similarity(name, self.name(i))
            if s < min_score:
                continue
            if sex in ('M', 'F') and self.sex(i) in ('M', 'F') and sex != self.sex(i):
                continue
            y = self.est_year(i)
            if year and y and abs(y - year) > tol:
                continue
            out.append((s, i))
        return [i for s, i in sorted(out, reverse=True)]

    # --- editing ---
    def next_id(self, prefix):
        table = {'I': self.indi, 'F': self.fam, 'S': self.sour}[prefix]
        nums = [int(k[1:]) for k in table if k[0] == prefix and k[1:].isdigit()]
        return f'{prefix}{max(nums + [0]) + 1}'

    def _insert(self, node):
        last = max((n for n, r in enumerate(self.doc.records) if r.tag == node.tag), default=None)
        if last is None:
            self.doc.insert_before_trailer(node)
        else:
            self.doc.records.insert(last + 1, node)
        self.reindex()

    def add_person(self, given, surname, sex='U'):
        i = self.next_id('I')
        n = gedcom.Node('INDI', xref=f'@{i}@')
        full = f'{given or ""} /{surname or ""}/'.strip()
        nm = n.add('NAME', full)
        if given:
            nm.add('GIVN', given)
        if surname:
            nm.add('SURN', surname)
        n.add('SEX', sex if sex in ('M', 'F') else 'U')
        self._insert(n)
        return i

    def add_family(self, husb=None, wife=None):
        f = self.next_id('F')
        n = gedcom.Node('FAM', xref=f'@{f}@')
        self._insert(n)
        if husb:
            self.set_spouse(f, husb, 'HUSB')
        if wife:
            self.set_spouse(f, wife, 'WIFE')
        return f

    def set_spouse(self, f, i, role):
        fam = self.fam[f]
        if fam.get(role) is None:
            fam.children.insert(0, gedcom.Node(role, f'@{i}@'))
        if f not in self._ids(self.indi[i], 'FAMS'):
            self.indi[i].add('FAMS', f'@{f}@')
        self._est = None

    def add_child(self, f, i):
        if i not in self._ids(self.fam[f], 'CHIL'):
            self.fam[f].add('CHIL', f'@{i}@')
        if f not in self._ids(self.indi[i], 'FAMC'):
            self.indi[i].add('FAMC', f'@{f}@')
        self._est = None

    def set_event(self, node, tag, date=None, place=None):
        """Create or complete an event. Returns a description of what changed, or None."""
        e = node.get(tag)
        changed = []
        if e is None:
            e = node.add(tag)
        if e.value == 'Y' and (date or place) and tag != 'DEAT':
            e.value = None
        if date:
            d = e.get('DATE')
            if d is None:
                e.children.insert(0, gedcom.Node('DATE', date))
                changed.append(f'{tag} date {date}')
            elif d.value != date:
                changed.append(f'{tag} date {d.value} -> {date}')
                d.value = date
        if place:
            p = e.get('PLAC')
            if p is None:
                e.add('PLAC', place)
                changed.append(f'{tag} place {place}')
        self._est = None
        return ', '.join(changed) or None

    def add_source(self, title, url=None, author=None, text=None, note=None):
        """Reuse a source with the same URL or title, else create one."""
        for sid, s in self.sour.items():
            if url and url in ((s.val('PUBL') or '') + ' ' + ' '.join(n.text() for n in s.all('NOTE'))):
                return sid
            if not url and (s.val('TITL') or '').strip().lower() == title.strip().lower():
                return sid
        sid = self.next_id('S')
        n = gedcom.Node('SOUR', xref=f'@{sid}@')
        if author:
            n.add('AUTH', author)
        n.add_text('TITL', title[:240])
        if url:
            n.add('PUBL', url)
        if text:
            n.add_text('TEXT', text)
        if note:
            n.add_text('NOTE', note)
        self._insert(n)
        return sid

    def cite(self, node, sid, quay=None, page=None, text=None):
        for c in node.all('SOUR'):
            if c.value == f'@{sid}@':
                return
        c = node.add('SOUR', f'@{sid}@')
        if page:
            c.add('PAGE', page[:240])
        if quay is not None:
            c.add('QUAY', str(quay))
        if text:
            c.add('DATA').add_text('TEXT', text)

    def merge(self, keep, drop):
        """Fold person `drop` into `keep`: links, events, names and citations move over."""
        a, b = self.indi[keep], self.indi[drop]
        ref_old, ref_new = f'@{drop}@', f'@{keep}@'
        for f in list(self.fam.values()):
            for c in f.children:
                if c.tag in ('HUSB', 'WIFE', 'CHIL') and c.value == ref_old:
                    c.value = ref_new
            # the same child listed twice after the merge
            seen = set()
            for c in list(f.children):
                if c.tag == 'CHIL':
                    if c.value in seen:
                        f.remove(c)
                    seen.add(c.value)
        have = {(c.tag, c.value) for c in a.children}
        for c in b.children:
            if c.tag in ('RIN', '_UID', '_UPD'):
                continue
            if c.tag in ('FAMS', 'FAMC', 'SOUR', 'NOTE', 'OBJE') and (c.tag, c.value) in have:
                continue
            if c.tag in ('BIRT', 'DEAT', 'CHR', 'BAPM', 'BURI', 'SEX') and a.get(c.tag) is not None:
                if c.tag != 'SEX':
                    mine = a.get(c.tag)
                    for sub in c.children:      # fill gaps (date/place) only
                        if sub.tag in ('DATE', 'PLAC') and mine.get(sub.tag) is None:
                            mine.add(sub.tag, sub.value)
                continue
            if c.tag == 'NAME':
                if c.value != a.val('NAME'):
                    a.add('NAME', c.value).add('TYPE', 'aka')
                continue
            a.children.append(c)
        a.add('NOTE', f'Merged with duplicate record {drop} on {datetime.date.today().isoformat()}.')
        self.doc.records.remove(b)
        self.reindex()
        self._fold_parent_families(keep)

    def _fold_parent_families(self, i):
        """If i is a child in several families and one's parents are a subset of
        another's (e.g. father-only vs father+mother), drop the poorer link and
        delete that family when it ends up empty."""
        fams = [f for f in self._ids(self.indi[i], 'FAMC') if f in self.fam]
        for f in fams:
            pf = {p for p in self.fam_parents(f) if p}
            for g in fams:
                if g == f or f not in self.fam or g not in self.fam:
                    continue
                pg = {p for p in self.fam_parents(g) if p}
                if pf < pg or (pf == pg and f > g):
                    self.fam[f].children = [c for c in self.fam[f].children
                                            if not (c.tag == 'CHIL' and c.value == f'@{i}@')]
                    self.indi[i].children = [c for c in self.indi[i].children
                                             if not (c.tag == 'FAMC' and c.value == f'@{f}@')]
                    if not self.fam_children(f) and len(pf) <= 1:
                        for p in pf:
                            self.indi[p].children = [c for c in self.indi[p].children
                                                     if not (c.tag == 'FAMS' and c.value == f'@{f}@')]
                        self.doc.records.remove(self.fam[f])
                    self.reindex()
                    break

    # --- saving ---
    def save(self, snapshot=True):
        """Write the tree; keeps a timestamped copy of the previous version first."""
        if snapshot and os.path.exists(self.path):
            hist = os.path.join(os.path.dirname(self.path), 'history')
            os.makedirs(hist, exist_ok=True)
            stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
            shutil.copy2(self.path, os.path.join(hist, f'tree-{stamp}.ged'))
        self.doc.save(self.path)
