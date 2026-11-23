"""The tree viewer, a self-contained page (open it in a browser), written twice:

- research/arvore.html: the local copy, where each researched person links to their dossier;
- web/index.html: the copy to publish. It links to nothing outside itself except the sources'
  own web addresses, so it works without the research files, which are not in git.
  For privacy it carries only the names of the root people, their parents and their brothers
  and sisters: no dates, places, notes or sources.
"""
import json
import os
import re
import unicodedata

from . import connect, research

CONF_RE = re.compile(r'confidence (proven|probable|possible|speculative)')
COUNTRIES = {
    'BR': {'name': 'Brasil', 'flag': '🇧🇷', 'color': '#229e69'},
    'PT': {'name': 'Portugal', 'flag': '🇵🇹', 'color': '#cf5361'},
    'DE': {'name': 'Alemanha', 'flag': '🇩🇪', 'color': '#c89524'},
    'FR': {'name': 'França', 'flag': '🇫🇷', 'color': '#537cd3'},
    'ES': {'name': 'Espanha', 'flag': '🇪🇸', 'color': '#d88632'},
    'AR': {'name': 'Argentina', 'flag': '🇦🇷', 'color': '#54a9ce'},
    'AO': {'name': 'Angola', 'flag': '🇦🇴', 'color': '#cf5361'},
    'BE': {'name': 'Bélgica', 'flag': '🇧🇪', 'color': '#c89524'},
    'RU': {'name': 'Rússia', 'flag': '🇷🇺', 'color': '#537cd3'},
    'UY': {'name': 'Uruguai', 'flag': '🇺🇾', 'color': '#54a9ce'},
    'IT': {'name': 'Itália', 'flag': '🇮🇹', 'color': '#229e69'},
    'NL': {'name': 'Países Baixos', 'flag': '🇳🇱', 'color': '#d88632'},
    'GB': {'name': 'Reino Unido', 'flag': '🇬🇧', 'color': '#537cd3'},
    'CH': {'name': 'Suíça', 'flag': '🇨🇭', 'color': '#cf5361'},
    'AT': {'name': 'Áustria', 'flag': '🇦🇹', 'color': '#cf5361'},
    'PY': {'name': 'Paraguai', 'flag': '🇵🇾', 'color': '#54a9ce'},
    'CV': {'name': 'Cabo Verde', 'flag': '🇨🇻', 'color': '#537cd3'},
}
COUNTRY_NAMES = {
    'brasil': 'BR', 'brazil': 'BR', 'portugal': 'PT',
    'deutschland': 'DE', 'germany': 'DE', 'alemanha': 'DE',
    'france': 'FR', 'franca': 'FR', 'espana': 'ES', 'espanha': 'ES', 'spain': 'ES',
    'argentina': 'AR', 'rep. argentina': 'AR', 'republica argentina': 'AR', 'angola': 'AO',
    'belgica': 'BE', 'belgium': 'BE', 'belgique': 'BE', 'russia': 'RU', 'russie': 'RU',
    'uruguai': 'UY', 'uruguay': 'UY', 'italia': 'IT', 'italy': 'IT', 'paises baixos': 'NL', 'holanda': 'NL',
    'netherlands': 'NL', 'nederland': 'NL', 'reino unido': 'GB', 'inglaterra': 'GB', 'england': 'GB',
    'suica': 'CH', 'schweiz': 'CH', 'switzerland': 'CH', 'austria': 'AT', 'osterreich': 'AT',
    'paraguai': 'PY', 'paraguay': 'PY', 'cabo verde': 'CV',
}
# A country name closing a place written without commas ("Abiul- Leiria- Portugal", "Petropolis/Brazil").
COUNTRY_TAIL = re.compile(r'(?:^|[^a-z])(' + '|'.join(sorted(map(re.escape, COUNTRY_NAMES), key=len, reverse=True)) + r')\.?$')
# Fallback when a place does not end in a country: states, regions and cities that pin it down.
# Parts are checked right to left, so "Santa Catarina, Lisboa" is Portugal and "... Lisboa - Desterro-SC" is Brazil.
REGIONS = [
    (re.compile(r'\b(rio grande do sul|santa catarina|sao paulo|minas gerais|parana|bahia|pernambuco|rio de janeiro|'
                r'desterro|florianopolis|niteroi|mage|inhomirim|porto alegre|rio pardo)\b|(^|[^a-z])(rs|sc|sp|rj|mg|pr)([^a-z]|$)'), 'BR'),
    (re.compile(r'\b(acores|azores|acoras|terceira|faial|sao miguel|madeira|lisboa|porto|braga|minho|vila real|'
                r'tras-os-montes|santarem|evora|setubal|coimbra|viseu|beja|algarve)\b'), 'PT'),
    (re.compile(r'\b(aquitaine|aquitania|gironde|pyrenees|doubs|haute-saone|bordeaux|besancon|toulouse|paris)\b'), 'FR'),
    (re.compile(r'\b(hessen|rheinland|niedersachsen|bayern|preussen|westfalen|wurttemberg|baden|sachsen)\b'), 'DE'),
    (re.compile(r'\b(buenos aires|entre rios|corrientes)\b'), 'AR'),
    (re.compile(r'\b(galicia|castilla|castela|leon|andalucia|catalunya|zamora|segovia)\b'), 'ES'),
    (re.compile(r'\b(brabant|brabante|flandres|flanders|vlaanderen)\b'), 'BE'),
    (re.compile(r'p[ei]t[e]?rs?b[o]?urg[o]?|petersburgo'), 'RU'),
]


def _norm(s):
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not unicodedata.combining(c)).strip().lower()


def place_country(place):
    """Country code for a place string, or None. Explicit country names win over region hints."""
    parts = [_norm(x) for x in re.split(r',|\s[-–]\s', place) if x.strip()]
    if not parts:
        return None
    tail = parts[-1]
    if COUNTRY_NAMES.get(tail):
        return COUNTRY_NAMES[tail]
    m = COUNTRY_TAIL.search(tail)
    if m:
        return COUNTRY_NAMES[m.group(1)]
    for part in reversed(parts):
        for rx, code in REGIONS:
            if rx.search(part):
                return code
    return None


def _place_of_birth(node):
    """Country of the recorded birthplace, or of the baptism place if no birthplace is recorded."""
    for tag in ('BIRT', 'CHR', 'BAPM'):
        for event in node.all(tag):
            place = event.val('PLAC')
            if not place:
                continue
            country = place_country(place)
            # A recorded birthplace takes precedence even when its country is unknown.
            return ({'id': country, 'event': 'nascimento' if tag == 'BIRT' else 'batismo'} if country else None), place
    return None, None


def _birth_country(node):
    """The flag shown for a person: a recorded nationality (NATI) wins over the birthplace,
    so someone born abroad to a family of another country shows that country."""
    born, place = _place_of_birth(node)
    nati = place_country(node.val('NATI') or '')
    if nati and (not born or born['id'] != nati):
        return {'id': nati, 'event': 'nacionalidade', 'born': place}
    return born


IN_COUNTRY = {'BR': 'no ', 'UY': 'no ', 'PY': 'no ', 'GB': 'no ', 'NL': 'nos ', 'PT': 'em ', 'CV': 'em ',
              'FR': 'na ', 'DE': 'na ', 'ES': 'na ', 'AR': 'na ', 'BE': 'na ', 'RU': 'na ', 'IT': 'na ', 'CH': 'na ',
              'AT': 'na ', 'AO': 'em '}
EUROPE = {'PT', 'DE', 'FR', 'ES', 'BE', 'IT', 'NL', 'GB', 'CH', 'AT', 'RU'}
OTHER_EVENTS = ('DEAT', 'BURI', 'RESI', 'MARR')


def presumed_countries(tree, recorded, path):
    """{id: {'id': code, 'event': 'presumido', 'pr': 1, 'why': reason}} for people without a recorded country.

    Judgements in research/countries/presumed.json (written after reviewing each person) win; a null
    country there means "do not presume". Everyone else gets a conservative rule, using recorded
    countries only: parents and children agree; or children born in Europe; or, from 1880 on,
    parents or children agree and nothing else in the person's life points elsewhere."""
    judged = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            judged = json.load(f)
    out = {}
    for i in tree.indi:
        if recorded.get(i):
            continue
        if i in judged:
            j = judged[i]
            if j.get('country') in COUNTRIES:
                out[i] = {'id': j['country'], 'event': 'presumido', 'pr': 1, 'why': j.get('why') or ''}
            continue
        pc = {recorded[p] for p in tree.parents(i) if p and recorded.get(p)}
        kc = {recorded[c] for c in tree.children(i) if recorded.get(c)}
        if len(pc | kc) != 1:
            continue
        x = next(iter(pc | kc))
        name = IN_COUNTRY.get(x, 'em ') + COUNTRIES[x]['name']
        own = {place_country(e.val('PLAC')) for t in OTHER_EVENTS for e in tree.indi[i].all(t) if e.val('PLAC')}
        own |= {place_country(e.val('PLAC')) for f in tree.fams(i) for e in tree.fam[f].all('MARR') if e.val('PLAC')}
        own.discard(None)
        year = tree.est_year(i)
        if pc and kc:
            why = f'pais e filhos nascidos {name}'
        elif kc and x in EUROPE:
            why = f'filhos nascidos {name}'
        elif year and year >= 1880 and own <= {x} and (kc or all(recorded.get(p) for p in tree.parents(i))):
            why = f'{"pais" if pc else "filhos"} nascidos {name}'
        else:
            continue
        out[i] = {'id': x, 'event': 'presumido', 'pr': 1, 'why': why + ' (regra automática)'}
    return out


def _person(tree, i, paths, dossiers):
    node = tree.indi[i]
    ev = []
    for tag, label in (('BIRT', 'Nascimento'), ('CHR', 'Batismo'), ('BAPM', 'Batismo'), ('DEAT', 'Óbito'),
                       ('BURI', 'Sepultamento'), ('IMMI', 'Imigração'), ('EMIG', 'Emigração'),
                       ('RESI', 'Residência'), ('OCCU', 'Ocupação')):
        for e in node.all(tag):
            d, p = e.val('DATE'), e.val('PLAC')
            if d or p or (tag == 'OCCU' and e.value):
                alternate = tag == 'BIRT' and any(n.text().startswith('Alternate disputed birth') for n in e.all('NOTE'))
                ev.append(['Alternativo' if alternate else label, d or (e.value if tag == 'OCCU' else '') or '', p or ''])
    notes = [n.text() for n in node.all('NOTE') if n.text().strip()]
    srcs = []
    for c in node.all('SOUR'):
        s = tree.sour.get((c.value or '').strip('@'))
        title = s.val('TITL') if s is not None else c.value
        url = c.val('PAGE') or (s.val('PUBL') if s is not None else None) or ''
        quote = ''
        data = c.get('DATA')
        if data is not None and data.get('TEXT') is not None:
            quote = data.get('TEXT').text()
        srcs.append({'t': title or '', 'u': url if url.startswith('http') else '', 'q': quote[:600],
                     'k': c.val('QUAY') or ''})
    conf = None
    for n in notes:
        m = CONF_RE.search(n) if n.startswith('Added by research') else None
        if m:
            conf = m.group(1)
    living = tree.possibly_living(i)
    fam = tree.famc(i)
    return {
        'id': i, 'n': tree.name(i), 's': tree.sex(i), 'l': tree.lifespan(i), 'y': tree.est_year(i),
        'f': tree.parents(i)[0], 'm': tree.parents(i)[1],
        'sp': [[f, s] for f, s in tree.spouses(i)],
        'ch': tree.children(i), 'ev': ev, 'no': notes, 'so': srcs, 'cf': conf, 'lv': living,
        'pq': max([int(c.val('QUAY') or 0) for c in tree.fam[fam].all('SOUR')] or [-1]) if fam else -1,
        'do': dossiers.get(i),
        'co': _birth_country(node),
    }


def kinship_pt(ga, gb):
    if min(ga, gb) == 0:
        return f'{max(ga, gb) - 2}º bisavô/bisneto' if max(ga, gb) > 2 else ('pai/filho' if max(ga, gb) == 1 else 'avô/neto')
    if ga == gb == 1:
        return 'irmãos'
    degree, removed = min(ga, gb) - 1, abs(ga - gb)
    if degree == 0:
        return 'tio/sobrinho' + (f' ({removed - 1}× tio-avô)' if removed > 1 else '')
    return f'primos de {degree}º grau' + (f', {removed} geração de diferença' if removed == 1 else
                                         f', {removed} gerações de diferença' if removed else '')


def _private(tree, roots):
    """People whose personal details stay out of the web copy: each root person, their parents
    and their brothers and sisters."""
    ids = set()
    for r in roots:
        ids.add(r['id'])
        for p in tree.parents(r['id']):
            if p:
                ids.add(p)
                ids.update(tree.children(p))
    return ids


PRIVATE = {'l': '', 'y': None, 'ev': [], 'no': [], 'so': [], 'pv': 1}


def build(tree, cfg, paths, root):
    dossiers = {f.split('-')[0]: 'dossiers/' + f for f in os.listdir(paths.dossiers) if f.endswith('.md')}
    people = {i: _person(tree, i, paths, dossiers) for i in tree.indi}
    recorded = {i: p['co']['id'] for i, p in people.items() if p['co']}
    for i, co in presumed_countries(tree, recorded, os.path.join(paths.research, 'countries', 'presumed.json')).items():
        people[i]['co'] = co
    rs = [r for r in cfg['roots'] if r['id'] in tree.indi]
    links = []
    for n, a in enumerate(rs):
        for b in rs[n + 1:]:
            for i, ga, gb in connect.common_ancestors(tree, a['id'], b['id'])[:4]:
                links.append({'a': a['label'], 'b': b['label'], 'id': i, 'k': kinship_pt(ga, gb)})
    research_ids = cfg.get('research_roots', [r['id'] for r in rs])
    frontier = [t['id'] for t in research.frontier(tree, research_ids, paths, True)]
    data = {'people': people, 'roots': rs, 'links': links, 'open': frontier, 'countries': COUNTRIES,
            'date': research.TODAY, 'counts': [len(tree.indi), len(tree.fam), len(tree.sour)]}
    hide = _private(tree, rs)
    web = dict(data, people={i: dict(p, do=None, **(PRIVATE if i in hide else {})) for i, p in people.items()})
    for i in hide:  # the reason for a presumed country can quote a birth year, and a birthplace is personal too
        co = web['people'][i]['co']
        if co:
            web['people'][i]['co'] = dict({k: v for k, v in co.items() if k != 'born'},
                                          **({'why': 'dados pessoais omitidos'} if co.get('pr') else {}))
    written = []
    for path, content in ((os.path.join(paths.research, 'arvore.html'), data),
                          (os.path.join(paths.root, 'web', 'index.html'), web)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(TEMPLATE.replace('/*DATA*/null', json.dumps(content, ensure_ascii=False).replace('</', '<\\/')))
        written.append(os.path.relpath(path, root))
    return '\n'.join(written)



TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#fffdf8">
<title>Árvore da família</title>
<script>try{var t=localStorage.getItem('arvore.theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}</script>
<style>
:root{color-scheme:light dark;--bg:#f7f5f0;--panel:#fffdf8;--ink:#23201b;--mute:#6f685c;--line:#cfc6b4;--m:#2f5d8a;--f:#9a3f5c;--u:#6f685c;
--hl:#d39b1f;--open:#c2410c;--weak:#a16207;--card:#ffffff;--focus:#f6ecd2}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#17150f;--panel:#1f1c16;--ink:#ece6da;--mute:#a59d8d;
--line:#4a4436;--m:#7fb0e0;--f:#e28aa6;--u:#a59d8d;--hl:#e9b949;--open:#fb923c;--weak:#facc15;--card:#26221b;--focus:#3a3222}}
:root[data-theme=dark]{color-scheme:dark;--bg:#17150f;--panel:#1f1c16;--ink:#ece6da;--mute:#a59d8d;--line:#4a4436;--m:#7fb0e0;--f:#e28aa6;
--u:#a59d8d;--hl:#e9b949;--open:#fb923c;--weak:#facc15;--card:#26221b;--focus:#3a3222}
:root[data-theme=light]{color-scheme:light}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;height:100vh;height:100dvh;display:flex;flex-direction:column;overflow:hidden}
header{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:6px 10px;padding-left:max(10px,env(safe-area-inset-left));padding-right:max(10px,env(safe-area-inset-right));border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:15px;margin:0 4px 0 0;font-weight:650}
#tools{display:flex;gap:8px;align-items:center}
select,input,button,.val{font:inherit;font-size:13px;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:6px;padding:0 8px;height:28px}
button{cursor:pointer;min-width:28px;white-space:nowrap}button:hover:not(:disabled){border-color:var(--mute)}button:disabled{opacity:.4;cursor:default}
.grp{display:inline-flex}.grp>*{border-radius:0}.grp>*+*{margin-left:-1px}
.grp>:first-child{border-radius:6px 0 0 6px}.grp>:last-child{border-radius:0 6px 6px 0}
.val{display:inline-flex;align-items:center;justify-content:center;min-width:56px;white-space:nowrap}
.on-btn{background:var(--focus)}
.meta{color:var(--mute);font-size:12px;margin-left:auto}
#crumbs{display:flex;align-items:center;gap:2px;padding:3px 10px;border-bottom:1px solid var(--line);background:var(--panel);font-size:12.5px;white-space:nowrap;overflow-x:auto;color:var(--mute);min-height:32px;scrollbar-width:none}
#crumbs a{color:var(--ink);cursor:pointer;padding:2px 6px;border-radius:4px}#crumbs a:hover{background:var(--card)}
#crumbs a.cur{font-weight:650;background:var(--focus)}
#crumbs button{height:24px;margin-right:6px;flex:none}
#origins{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:5px 10px;background:var(--panel);border-bottom:1px solid var(--line);font-size:12px;color:var(--mute)}
#origins button{height:25px;font-size:12px;border-color:color-mix(in srgb,var(--country) 45%,var(--line));background:color-mix(in srgb,var(--country) 10%,var(--card));display:inline-flex;align-items:center;gap:5px}
#origins button[aria-pressed=true]{border-color:var(--country);background:color-mix(in srgb,var(--country) 32%,var(--card));box-shadow:0 0 0 1px var(--country)}
#origins .country-flag{font-size:14px}
main{flex:1;display:flex;min-height:0}
#chart{flex:1;min-height:0;position:relative;overflow:hidden;touch-action:none;cursor:grab;-webkit-tap-highlight-color:transparent}
#chart.drag{cursor:grabbing}
#chart svg{display:block;width:100%;height:100%;user-select:none;-webkit-user-select:none}
#gens{position:absolute;top:0;left:0;right:0;height:24px;overflow:hidden;pointer-events:none;background:var(--bg);border-bottom:1px solid color-mix(in srgb,var(--line) 55%,transparent)}
.gen{position:absolute;top:0;left:0;height:24px;line-height:24px;font-size:11.5px;color:var(--mute);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-left:3px}
.gen b{color:var(--ink);font-weight:650;text-transform:uppercase;letter-spacing:.04em;font-size:10.5px}
.gen i{font-style:normal;opacity:.8}
.gen .sm{display:none}.gen.tiny .lg{display:none}.gen.tiny .sm{display:inline}
#chips{position:absolute;top:30px;left:8px;display:flex;gap:6px;flex-wrap:wrap;max-width:calc(100% - 16px)}
.chip{display:inline-flex;border:1px solid color-mix(in srgb,var(--country,var(--hl)) 60%,var(--line));background:color-mix(in srgb,var(--country,var(--hl)) 16%,var(--panel));border-radius:16px;overflow:hidden;box-shadow:0 1px 5px rgba(0,0,0,.14)}
.chip button{border:0;background:none;height:28px;border-radius:0;font-size:12px;padding:0 6px 0 10px;font-weight:600}
.chip button+button{padding:0 10px 0 4px;color:var(--mute);font-weight:400}
#hint{position:absolute;left:8px;bottom:6px;font-size:11.5px;color:var(--mute);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:3px 8px;display:flex;gap:12px;flex-wrap:wrap;max-width:calc(100% - 16px);pointer-events:none}
#hint span,.legend span{display:inline-flex;align-items:center;gap:4px}
.legend{display:flex;gap:4px 14px;flex-wrap:wrap;font-size:12.5px;color:var(--mute)}
.sw{width:18px;height:0;border-top:2px solid var(--line);display:inline-block}.sw.weak{border-top:2px dashed var(--weak)}
#side{width:340px;max-width:42vw;border-left:1px solid var(--line);background:var(--panel);overflow:auto;padding:12px 14px;font-size:13.5px;overscroll-behavior:contain}
#side[hidden]{display:none}
.x{float:right;margin:-5px -8px 0 6px;border:0;background:none;font-size:15px;color:var(--mute);width:32px;height:32px;border-radius:16px}
.x:hover{background:var(--card)}
svg text{fill:var(--ink)}
.node{cursor:pointer;transition:opacity .18s}
.node .box{fill:var(--card);stroke:var(--line);stroke-width:1}
.node.country .box{fill:color-mix(in srgb,var(--country) 10%,var(--card))}
.node:hover .box{stroke:var(--mute)}
.node.focus .box{fill:var(--focus)}
.node.weak .box{stroke:var(--weak);stroke-dasharray:3 2}
.node.hit .box{stroke:var(--country);stroke-width:2;stroke-dasharray:none;fill:color-mix(in srgb,var(--country) 26%,var(--card))}
.node.hit.pr .box{stroke-dasharray:5 3;fill:color-mix(in srgb,var(--country) 12%,var(--card))}
.node.on .box{stroke:var(--hl)}
.node.twin .box{stroke:var(--hl);stroke-dasharray:2 2}
.node.sel .box{stroke:var(--hl);stroke-width:2.4;stroke-dasharray:none}
.node.dim{opacity:.26}.node.mid{opacity:.6}
.nm{font-size:12px;font-weight:600}
.dt{font-size:10.5px;fill:var(--mute)!important}
.tg{font-size:9.5px;fill:var(--mute)!important}.tg .tw{fill:var(--weak)}
.country-flag{font:14px "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif}
.country-badge{display:inline-flex;align-items:center;gap:6px;border:1px solid color-mix(in srgb,var(--country) 45%,var(--line));background:color-mix(in srgb,var(--country) 10%,var(--card));border-radius:20px;padding:3px 9px;margin:2px 0 10px;font-size:12px}
.country-badge .country-flag{font-size:16px}
.country-flag.pr,.pr .country-flag{opacity:.5}
.node.country.pr .box{fill:color-mix(in srgb,var(--country) 4%,var(--card))}
.country-badge.pr{border-style:dashed;background:color-mix(in srgb,var(--country) 4%,var(--card))}
#origins .pr-n{font-weight:400;opacity:.7}
.edge{fill:none;stroke:var(--line);stroke-width:1.2;transition:opacity .18s}
.edge.weak{stroke:var(--weak);stroke-dasharray:4 3}
.edge.on{stroke:var(--hl);stroke-width:2.2}
.edge.dim{opacity:.3}.edge.mid{opacity:.7}
.more{cursor:pointer}.more .pill{fill:var(--card);stroke:var(--mute)}.more:hover .pill{stroke:var(--ink);fill:var(--focus)}
.more text{font-size:10.5px;font-weight:650}
.pad{fill:transparent;stroke:none}
.knob{opacity:0;cursor:pointer}.node:hover .knob{opacity:1}
.knob .dot{fill:var(--card);stroke:var(--mute)}.knob text{font-size:12px;font-weight:700;fill:var(--mute)}
.q{font-size:13px;font-weight:700;fill:var(--open)!important}
#side h2{margin:0;font-size:18px;line-height:1.25}
.sub{color:var(--mute)}
#side .sub{margin:2px 0 8px;font-size:12.5px}
#side h3,#side summary{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin:14px 0 4px;font-weight:650}
#side summary{cursor:pointer}
.acts{display:flex;gap:6px;flex-wrap:wrap}
.acts a{display:inline-flex;align-items:center;font-size:13px;color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:0 8px;height:28px;text-decoration:none;background:var(--card)}
.lnk{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:2px;cursor:pointer}
.lnk:hover{text-decoration-color:var(--ink)}
.lnk.cur{font-weight:650;text-decoration-color:var(--hl);text-decoration-thickness:2px}
.kv{display:grid;grid-template-columns:80px minmax(0,1fr);gap:3px 8px}.kv>.k{color:var(--mute)}
.note{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 8px;margin:5px 0;font-size:12.5px;white-space:pre-wrap;overflow-wrap:anywhere}
.src{border-left:3px solid var(--line);padding:1px 0 1px 8px;margin:6px 0;font-size:12.5px;overflow-wrap:anywhere}
.src q{display:block;color:var(--mute);font-style:italic;margin-top:2px}
.badge{display:inline-block;font-size:11px;padding:0 6px;border-radius:9px;border:1px solid currentColor;margin-left:5px;vertical-align:1px}
.b-open{color:var(--open)}.b-weak{color:var(--weak)}.b-live{color:var(--mute)}
.tips{margin:4px 0;padding-left:18px}.tips li{margin:3px 0}
.list div{margin:3px 0}
kbd{font:11px ui-monospace,monospace;border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 4px;background:var(--card)}
#qwrap{position:relative}
#q{width:190px}
#results{position:absolute;top:31px;left:0;z-index:5;background:var(--panel);border:1px solid var(--line);border-radius:6px;max-height:320px;overflow:auto;min-width:280px;box-shadow:0 4px 14px rgba(0,0,0,.15)}
#results div{padding:4px 10px;cursor:pointer}#results div.act,#results div:hover{background:var(--focus)}
@media (hover:none){.knob{opacity:1}}
@media (max-width:760px){
header{position:relative;gap:6px;padding-top:6px;padding-bottom:6px}
header h1,.meta,#hint,.kbd-only{display:none}
select,input,button,.val{height:36px}
select,input{font-size:16px}
button{min-width:36px}
#root,#qwrap{flex:1 1 0;min-width:0}
#qwrap{position:static}#q{width:100%}
#results{left:8px;right:8px;top:46px;min-width:0;max-height:50dvh}
#results div{padding:9px 12px}
#tools{flex:1 0 100%;gap:4px;overflow-x:auto;scrollbar-width:none}
#tools>*{flex:none}
#zo,#zi,#panel,.wide,#dc:not(.on-btn),#dd:not(.on-btn){display:none}
#fit,#dc,#dd{border-radius:6px}
#tools .val{min-width:0}
#tools::-webkit-scrollbar,#origins::-webkit-scrollbar,#crumbs::-webkit-scrollbar{display:none}
#crumbs{min-height:36px}#crumbs a{padding:6px 8px}#crumbs button{height:28px}
#origins{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}
#origins>*{flex:none}#origins .lbl{display:none}#origins button{height:30px}
main{flex-direction:column}
#side{flex:none;width:auto;max-width:none;max-height:44dvh;border-left:0;border-top:1px solid var(--line);border-radius:14px 14px 0 0;box-shadow:0 -4px 16px rgba(0,0,0,.14);padding-bottom:max(12px,env(safe-area-inset-bottom))}
.x{width:36px;height:36px;font-size:17px}
.acts a,.acts button{height:36px}
.list div{margin:8px 0}
}
</style>
</head>
<body>
<header>
  <h1>Árvore</h1>
  <select id="root" title="Pessoa raiz" aria-label="Pessoa raiz"></select>
  <span id="qwrap"><input id="q" placeholder="Buscar pessoa…" autocomplete="off" enterkeyhint="search" aria-label="Buscar pessoa"><div id="results" hidden></div></span>
  <div id="tools">
    <span class="grp"><button id="gm" title="Menos gerações" aria-label="Menos gerações">−</button><span class="val" id="gv" title="Gerações mostradas"></span><button id="gp" title="Mais gerações" aria-label="Mais gerações">+</button></span>
    <span class="grp"><button id="dc" title="Cartões compactos: nome, anos e local">Compacto</button><button id="dd" title="Cartões detalhados: nascimento, óbito, fontes, dossiê">Detalhado</button></span>
    <span class="grp"><button id="zo" title="Afastar (−)" aria-label="Afastar">−</button><button id="fit" title="Mostrar a árvore inteira (0)">Ajustar</button><button id="zi" title="Aproximar (+)" aria-label="Aproximar">+</button></span>
    <button id="panel" title="Mostrar/ocultar o painel de detalhes">Painel</button>
    <button id="theme"></button>
    <button id="help" title="Ajuda e legenda" aria-label="Ajuda e legenda">?</button>
  </div>
  <span class="meta" id="meta"></span>
</header>
<nav id="crumbs"></nav>
<nav id="origins" aria-label="Países de nascimento dos ancestrais"></nav>
<main>
  <div id="chart"><svg id="svg"><g id="vp"></g></svg>
    <div id="gens"></div>
    <div id="chips"></div>
    <div id="hint"><span><span class="sw"></span>documentada</span><span><span class="sw weak"></span>fraca</span>
    <span style="color:var(--open)"><b>?</b> pais em aberto</span><span><b>+n</b> ancestrais ocultos</span>
    <span>⚑ país do nascimento</span><span><span style="opacity:.5">⚑</span> presumido</span>
    <span>arraste = mover · rolagem = zoom · duplo clique = centralizar</span></div>
  </div>
  <aside id="side"></aside>
</main>
<script>
const D = /*DATA*/null;
const P = D.people, OPEN = new Set(D.open);
const $ = s => document.querySelector(s);
const store = {get(k, d) { try { const v = localStorage.getItem('arvore.' + k); return v === null ? d : v; } catch (e) { return d; } },
               set(k, v) { try { localStorage.setItem('arvore.' + k, v); } catch (e) {} }};
const MES = {JAN:'jan',FEB:'fev',MAR:'mar',APR:'abr',MAY:'mai',JUN:'jun',JUL:'jul',AUG:'ago',SEP:'set',OCT:'out',NOV:'nov',DEC:'dez'};
const pt = s => String(s ?? '').replace(/\b(ABT|EST|CAL)\b/g, 'c.').replace(/\bBEF\b/g, 'antes de').replace(/\bAFT\b/g, 'depois de')
  .replace(/\bBET\b/g, 'entre').replace(/\bAND\b/g, 'e').replace(/\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b/g, m => MES[m]);
const yr = s => { const m = s.match(/(\d{3,4})(?!.*\d{3,4})/); return m ? (/ABT|EST|CAL|~|\bc\./.test(s) ? 'c.' : '') + m[1] : '?'; };
const years = l => { if (!l) return ''; const a = l.split(/\s+–\s+/); return a.length > 1 ? yr(a[0]) + '–' + yr(a[1]) : yr(a[0]); };
const CF = {proven: 'comprovado', probable: 'provável', possible: 'possível', speculative: 'especulativo'};
const WEAK = new Set(['possible', 'speculative']);
for (const p of Object.values(P)) {
  p.yy = p.lv && !p.y ? '' : years(p.l);
  p.l = pt(p.l); p.ev = p.ev.map(e => [e[0], pt(e[1]), e[2]]);
  const ev = l => p.ev.find(e => e[0] === l && (e[1] || e[2]));
  p.b = ev('Nascimento') || ev('Batismo'); p.d = ev('Óbito') || ev('Sepultamento');
  const b = p.ev.find(e => (e[0] === 'Nascimento' || e[0] === 'Batismo') && e[2]);
  p.bp = b ? b[2].split(',')[0].trim() : '';
}
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const country = p => p.co && D.countries[p.co.id];
const countryLabel = p => !country(p) ? '' : p.co.pr ? `${country(p).name} · presumido (sem registro): ${p.co.why}` : p.co.event === 'nacionalidade' ? `${country(p).name} · nacionalidade${p.co.born ? ' (nascido em ' + p.co.born + ')' : ''}` : `${country(p).name} · país do ${p.co.event}`;
const narrow = () => innerWidth <= 760;

// ---- card sizes & text fitting ------------------------------------------
const PAD = 7, TOP = 30, BOT = 36;  // TOP/BOT: room kept free for the generation header and the legend
// Card and gap sizes, as tight as the text allows: H is the height of three lines (det) or two (cmp),
// GX leaves room for the elbow of a link, GY/GC are the air between cards and after a couple.
const DENS = {det: {W: 208, H: 44, GX: 16, GY: 3, GC: 4}, cmp: {W: 172, H: 31, GX: 14, GY: 2, GC: 2}};
let dens = 'det', W, H, GX, GY, GC;

// ---- text size against zoom -----------------------------------------------
// The cards follow the zoom; the text follows it at half the rate (zoom out to 1/4 and the text is 1/2),
// and stops growing at CAP times its normal size. Text that no longer fits is dropped a line at a time
// (dates, then years and place), down to the name alone; names are shortened to the width left.
const CAP = 1.3;                 // largest text, as a multiple of the normal size
const TOL = 0.82;                // a line is kept while the text need not shrink below this share of its ideal size
const NEED = [0, 17, 30, 42.5];  // height of 1, 2 and 3 lines of card text, in px at normal size
const STEPS = 8;                 // the text is refitted 8 times per halving of the zoom
const tscale = k => Math.min(Math.sqrt(k), CAP) / k;  // ideal text scale inside the zoomed drawing
const zstep = k => Math.floor(Math.log2(k) * STEPS);
function lod(k) {  // at zoom k: how many lines a card shows and the scale of its text
  const r = tscale(k);
  let L = dens === 'cmp' ? 2 : 3;
  while (L > 1 && H / NEED[L] < TOL * r) L--;
  return {L, s: Math.min(r, H / NEED[L])};
}
let TXQ = null, TXL = 3, TXS = '';  // zoom step and line count the card texts are fitted for; last transforms written
const ctx = document.createElement('canvas').getContext('2d');
const FONT = 'system-ui,-apple-system,"Segoe UI",sans-serif';
const F_NAME = '600 12px ' + FONT, F_SUB = '10.5px ' + FONT, F_TAG = '9.5px ' + FONT;
const width = (s, font) => { ctx.font = font; return ctx.measureText(s).width; };
const fits = (s, font, w) => width(s, font) <= w;
const clip = (s, font, w) => { if (fits(s, font, w)) return s; while (s.length > 1 && !fits(s + '…', font, w)) s = s.slice(0, -1); return s + '…'; };
const PART = new Set(['da', 'de', 'do', 'das', 'dos', 'e', 'di', 'van', 'von', 'der', 'du', 'la', 'le', 'y']);
const SUF = new Set(['filho', 'filha', 'neto', 'neta', 'júnior', 'junior', 'sobrinho']);
function shortName(n, w) {  // the name cut to a width: the surname is the last thing to go
  if (fits(n, F_NAME, w)) return n;
  const t = n.split(/\s+/), ab = t.map(() => false);
  let e = t.length - 1; if (e > 0 && SUF.has(t[e].toLowerCase())) e--;  // t[e] is the surname; "Filho" and the like follow it
  const build = () => t.filter((x, i) => !(PART.has(x.toLowerCase()) && ab[i + 1])).join(' ');
  for (let i = e - 1; i >= 1; i--) {  // middle names become initials, from the right: "Joaquim P. Salgado Filho"
    if (PART.has(t[i].toLowerCase())) continue;
    t[i] = t[i][0] + '.'; ab[i] = true;
    const s = build(); if (fits(s, F_NAME, w)) return s;
  }
  if (e > 0) {  // then "Joaquim Salgado Filho", "J. P. Salgado Filho", "J. Salgado Filho", "Joaquim Salgado", "J. Salgado"
    const f = t[0][0] + '.', sur = (e > 1 && PART.has(t[e - 1].toLowerCase()) ? t[e - 1] + ' ' : '') + t[e], suf = t.slice(e + 1).join(' ');
    const mid = t.slice(1, e).filter(x => !PART.has(x.toLowerCase()));
    for (const c of [[t[0], sur, suf], [f, ...mid, sur, suf], [f, sur, suf], [t[0], sur], [f, sur], [f, t[e]]]) { const s = c.filter(Boolean).join(' '); if (fits(s, F_NAME, w)) return s; }
  }
  return clip(t[e], F_NAME, w);  // and at last the surname alone
}
function sub(p, w) {  // compact card: years and, if it fits, the birthplace
  let s = p.yy;
  if (p.bp) { const t = (s ? s + ' · ' : '') + p.bp; if (fits(t, F_SUB, w)) s = t; }
  return s;
}
function fact(tag, ev, w) {  // detailed card: "n. 12 mar 1857 · Dois Irmãos, RS", with as much of the place as fits
  if (!ev) return '';
  const parts = ev[2].split(',').map(s => s.trim()).filter(Boolean);
  for (let n = Math.min(parts.length, 4); n >= 0; n--) {
    const s = [ev[1], parts.slice(0, n).join(', ')].filter(Boolean).join(' · ');
    if (s && fits(tag + ' ' + s, F_SUB, w)) return tag + ' ' + s;
  }
  return clip(tag + ' ' + (ev[1] || parts[0] || ''), F_SUB, w);
}
const brief = n => { const t = n.split(/\s+/); if (t.length < 3) return n; let l = t[t.length - 1]; if (PART.has(t[t.length - 2].toLowerCase())) l = t[t.length - 2] + ' ' + l; return t[0] + ' ' + l; };
const ancCount = (() => { const memo = {}; return id => {
  if (memo[id] != null) return memo[id];
  const seen = new Set(), st = [P[id].f, P[id].m];
  while (st.length) { const x = st.pop(); if (!x || !P[x] || seen.has(x)) continue; seen.add(x); st.push(P[x].f, P[x].m); }
  return memo[id] = seen.size; }; })();
const GEN = ['Raiz', 'Pais', 'Avós', 'Bisavós', 'Trisavós', 'Tetravós'];
const genName = g => GEN[g] || `${g - 1}ºs avós`;

// ---- state --------------------------------------------------------------
// focus: person the tree is drawn from.  selKey: selected card.  spot: card whose ancestors are spotlighted
// (set by "centralizar").  filt: country code whose ancestors are highlighted.  Keys are paths: 'r', 'rf', 'rfm'…
let focus = null, selKey = null, spot = null, filt = null, snap = null, ready = false;
let gens = Math.min(16, Math.max(2, +store.get('gens', narrow() ? 4 : 5) || 5));
const opened = new Set(), shut = new Set(), hist = [];
let N = new Map(), ext = {w: 0, h: 0}, view = {k: 1, x: 0, y: 0}, totals = [], ORG = new Map();
const chart = $('#chart'), vp = $('#vp'), side = $('#side'), gensEl = $('#gens'), chipsEl = $('#chips');

// ---- layout & render ----------------------------------------------------
function walk(fn) {  // every position in the full pedigree of the focus person: fn(key, id, generation)
  (function go(key, id, g) {
    fn(key, id, g); if (g >= 40) return;
    const p = P[id];
    if (p.f && P[p.f]) go(key + 'f', p.f, g + 1);
    if (p.m && P[p.m]) go(key + 'm', p.m, g + 1);
  })('r', focus, 0);
}
function layout() {
  N = new Map(); let cur = 0, maxG = 0, bottom = 0;
  function place(key, id, g) {
    const p = P[id], has = [p.f, p.m].filter(x => x && P[x]);
    const expand = has.length > 0 && g < 40 && !shut.has(key) && (g + 1 < gens || opened.has(key));
    const par = [];
    if (expand) { if (p.f && P[p.f]) par.push(place(key + 'f', p.f, g + 1)); if (p.m && P[p.m]) par.push(place(key + 'm', p.m, g + 1)); }
    let y;
    if (par.length) { y = (par[0].y + par[par.length - 1].y) / 2; cur += GC; }  // a little air after each couple
    else { y = cur; cur += H + GY; }
    const n = {key, id, g, y, x: g * (W + GX), par, more: has.length && !expand ? ancCount(id) : 0,
               hit: !!filt && g > 0 && !!p.co && p.co.id === filt, hasHit: par.some(q => q.hit || q.hasHit)};
    N.set(key, n); maxG = Math.max(maxG, g); bottom = Math.max(bottom, y + H);
    return n;
  }
  place('r', focus, 0);
  ext = {w: maxG * (W + GX) + W + 60, h: bottom};
}
function elbow(x1, y1, x2, y2) {
  const mx = x1 + GX / 2, dy = y2 - y1, r = Math.min(6, Math.abs(dy) / 2), s = Math.sign(dy);
  return r < 1 ? `M${x1},${y1}L${x2},${y2}` : `M${x1},${y1}H${mx - r}Q${mx},${y1} ${mx},${y1 + s * r}V${y2 - s * r}Q${mx},${y2} ${mx + r},${y2}H${x2}`;
}
function card(p, c, L, s) {  // [left, right] text of a card showing L lines at text scale s; drawn in px, the card being W / s wide
  const w = W / s;
  if (w < 120) c = null;  // far out, the flag gives its place to the name; the card keeps the country's tint
  const nameW = w - PAD - (c ? 24 : 6);
  let a = `<text class="nm" x="${PAD}" y="12.5">${esc(shortName(p.n, nameW))}</text>`;
  let b = c ? `<text class="country-flag${p.co.pr ? ' pr' : ''}" x="-21" y="13.5" role="img" aria-label="${esc(countryLabel(p))}"><title>${esc(countryLabel(p))}</title>${c.flag}</text>` : '';
  if (L === 2) a += `<text class="dt" x="${PAD}" y="25">${esc(sub(p, w - PAD - 6))}</text>`;
  if (L < 3) return [a, b];
  const tags = [];
  if (WEAK.has(p.cf)) tags.push([CF[p.cf], 'tw']);
  if (p.so.length) tags.push([p.so.length + (p.so.length > 1 ? ' fontes' : ' fonte'), '']);
  if (p.do) tags.push(['dossiê', '']);
  const tagW = tags.length ? width(tags.map(t => t[0]).join(' · '), F_TAG) + 10 : 0;
  const l1 = fact(p.b && p.b[0] === 'Batismo' ? 'bat.' : 'n.', p.b, w - PAD - 6) || p.yy || (p.d || p.pv ? '' : 'sem datas');
  const l2 = fact(p.d && p.d[0] === 'Sepultamento' ? 'sep.' : 'f.', p.d, w - PAD - 6 - tagW);
  a += `<text class="dt" x="${PAD}" y="25">${esc(l1)}</text><text class="dt" x="${PAD}" y="37.5">${esc(l2)}</text>`;
  if (tags.length) b += `<text class="tg" x="-6" y="37.5" text-anchor="end">${tags.map(t => `<tspan class="${t[1]}">${esc(t[0])}</tspan>`).join(' · ')}</text>`;
  return [a, b];
}
function retext() {  // refit the text of every card to the current zoom step
  TXQ = zstep(view.k);
  const z = lod(Math.pow(2, TXQ / STEPS)); TXL = z.L; TXS = '';
  const ng = $('#ng'); if (!ng) return;
  for (const g of ng.children) {
    const p = P[N.get(g.dataset.k).id], [a, b] = card(p, country(p), z.L, z.s);
    g.querySelector('.tl').innerHTML = a; g.querySelector('.tr').innerHTML = b;
  }
}
function render() {
  const counts = {}, vis = []; for (const n of N.values()) { counts[n.id] = (counts[n.id] || 0) + 1; vis[n.g] = (vis[n.g] || 0) + 1; }
  TXQ = zstep(view.k);
  const z = lod(Math.pow(2, TXQ / STEPS)); TXL = z.L; TXS = '';
  let e = '', s = '';
  for (const a of N.values()) for (const b of a.par) {
    b.d = elbow(a.x + W, a.y + H / 2, b.x, b.y + H / 2);
    e += `<path data-k="${b.key}"${WEAK.has(P[b.id].cf) ? ' data-w="1"' : ''} d="${b.d}"/>`;
  }
  for (const n of N.values()) {
    const p = P[n.id];
    const c = country(p);
    const col = p.s === 'M' ? 'var(--m)' : p.s === 'F' ? 'var(--f)' : 'var(--u)';
    const tip = p.n + (p.l ? ' · ' + p.l : '') + (c ? ' · ' + countryLabel(p) : '') + (p.cf ? ' · ' + CF[p.cf] : '') + (counts[n.id] > 1 ? ' · aparece ' + counts[n.id] + '× na árvore' : '');
    const [ta, tb] = card(p, c, z.L, z.s);
    // .tl and .tr hold the text, anchored to the left and right edge of the card; .mk is the marker beside it.
    // apply() scales the three with the zoom.
    s += `<g data-k="${n.key}"${c ? ` style="--country:${c.color}"` : ''} transform="translate(${n.x},${n.y})"><title>${esc(tip)}</title>
      <rect class="box" width="${W}" height="${H}" rx="4"/><rect width="3" height="${H}" rx="1.5" fill="${col}"/><g class="tl">${ta}</g><g class="tr">${tb}</g>`;
    if (n.more) {
      const t = '+' + n.more, w = 12 + t.length * 6.5;
      s += `<g class="more mk" data-h="${n.key}"><title>Mostrar mais ${n.more} ancestrais</title><rect class="pad" x="-5" y="-9" width="${w + 12}" height="18"/><rect class="pill" y="-8" width="${w}" height="16" rx="8"/><text x="${w / 2}" y="3.5" text-anchor="middle">${t}</text></g>`;
    } else if (n.par.length) {
      s += `<g class="knob" data-h="${n.key}" transform="translate(${W + GX / 2},${H / 2})"><title>Recolher este ramo</title><circle class="pad" r="11"/><circle class="dot" r="6"/><text y="4" text-anchor="middle">−</text></g>`;
    } else if (OPEN.has(n.id)) {
      s += `<g class="mk"><text class="q" x="1" y="4.5"><title>Pais em aberto</title>?</text></g>`;
    }
    s += '</g>';
  }
  vp.innerHTML = `<g id="eg">${e}</g><g id="hl"></g><g id="ng">${s}</g>`;
  gensEl.innerHTML = vis.map((v, g) => `<div class="gen" data-g="${g}"><b class="lg">${genName(g)}</b><b class="sm">G${g}</b>`
    + (g ? `<span class="lg"> · ${v}${totals[g] > v ? ` <i>(+${totals[g] - v} ocultos)</i>` : ''}</span>` : '') + '</div>').join('');
  restyle(); apply();
}
function restyle() {  // selection and highlights only: update classes in place
  const sel = selKey && N.get(selKey), selId = sel && sel.id, LIT = ['dim', 'mid', ''];
  let h = '';
  for (const g of $('#ng').children) {
    const n = N.get(g.dataset.k), p = P[n.id], on = selKey && selKey.startsWith(n.key);
    const lit = filt ? (n.hit ? 2 : n.hasHit ? 1 : 0) : spot ? (n.key.startsWith(spot) ? 2 : spot.startsWith(n.key) ? 1 : 0) : 2;
    g.setAttribute('class', ['node', country(p) ? 'country' : '', country(p) && p.co.pr ? 'pr' : '', n.key === 'r' ? 'focus' : '', WEAK.has(p.cf) ? 'weak' : '',
      n.hit ? 'hit' : '', LIT[lit], n.key === selKey ? 'sel' : on ? 'on' : n.id === selId ? 'twin' : ''].join(' '));
    if (on && n.d) h += `<path class="edge on" d="${n.d}"/>`;
  }
  for (const e of $('#eg').children) {
    const n = N.get(e.dataset.k);
    const lit = filt ? (n.hit || n.hasHit ? 1 : 0) : spot ? (n.key.length > spot.length && n.key.startsWith(spot) ? 2 : spot.startsWith(n.key) ? 1 : 0) : 2;
    e.setAttribute('class', 'edge ' + (e.dataset.w ? 'weak ' : '') + LIT[lit]);
  }
  $('#hl').innerHTML = h;
  let c = '';
  if (filt) { const o = D.countries[filt]; c += `<span class="chip" style="--country:${o.color}"><button data-chip="filt" title="Ver a lista de ancestrais deste país"><span class="country-flag">${o.flag}</span> ${esc(o.name)} · ${(ORG.get(filt) || []).length}</button><button data-x="filt" title="Remover destaque (Esc)" aria-label="Remover destaque">✕</button></span>`; }
  if (spot) c += `<span class="chip"><button data-chip="spot" title="Voltar a esta pessoa">Ancestrais de ${esc(brief(P[N.get(spot).id].n))}</button><button data-x="spot" title="Remover destaque (Esc)" aria-label="Remover destaque">✕</button></span>`;
  chipsEl.innerHTML = c;
  for (const b of $('#origins').querySelectorAll('[data-origin]')) b.setAttribute('aria-pressed', b.dataset.origin === filt);
}
function draw() {
  layout();
  const lost = selKey && !N.has(selKey);
  if (lost) selKey = 'r';
  if (spot && !N.has(spot)) spot = null;
  render();
  if (lost && ready) show(focus);
}

// ---- camera -------------------------------------------------------------
function apply() {
  vp.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
  if (zstep(view.k) !== TXQ) retext();
  // Within a zoom step the text keeps its fitted wording and only its scale follows the zoom.
  const r = tscale(view.k), s = Math.min(r, H / NEED[TXL]), y0 = (H - NEED[TXL] * s) / 2, sm = Math.min(r, H / 16);
  const sig = s.toFixed(4) + ' ' + sm.toFixed(4) + ' ' + W + ' ' + H;
  if (sig !== TXS) {
    TXS = sig;
    const a = `translate(0,${y0}) scale(${s})`, b = `translate(${W},${y0}) scale(${s})`, c = `translate(${W + 5},${H / 2}) scale(${sm})`;
    for (const el of vp.querySelectorAll('.tl')) el.setAttribute('transform', a);
    for (const el of vp.querySelectorAll('.tr')) el.setAttribute('transform', b);
    for (const el of vp.querySelectorAll('.mk')) el.setAttribute('transform', c);
  }
  const cw = W * view.k;
  for (const el of gensEl.children) {
    el.style.transform = `translateX(${view.x + el.dataset.g * (W + GX) * view.k}px)`;
    el.style.width = cw + 'px'; el.classList.toggle('tiny', cw < 104);
  }
}
const still = matchMedia('(prefers-reduced-motion: reduce)');
let anim = 0;
function moveTo(v, ms = 280) {
  cancelAnimationFrame(anim);
  if (!ms || still.matches) { view = v; apply(); return; }
  const a = view, t0 = performance.now();
  const step = t => {
    const u = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - u, 3);
    view = {k: a.k + (v.k - a.k) * e, x: a.x + (v.x - a.x) * e, y: a.y + (v.y - a.y) * e}; apply();
    if (u < 1) anim = requestAnimationFrame(step);
  };
  anim = requestAnimationFrame(step);
}
const room = () => ({vw: chart.clientWidth, vh: chart.clientHeight - TOP - (narrow() ? 8 : BOT)});
function initView(ms = 0) {
  const {vw, vh} = room();
  const k = Math.max(narrow() ? 0.8 : 0.7, Math.min(1.1, (vw - 32) / ext.w, (vh - 16) / ext.h));  // 0.7: the cards still show all their lines
  const f = N.get('r');
  moveTo({k, x: ext.w * k < vw ? (vw - ext.w * k) / 2 : 14,
          y: TOP + (ext.h * k < vh ? (vh - ext.h * k) / 2 : vh / 2 - (f.y + H / 2) * k)}, ms);
}
function frame(x0, y0, x1, y1, kMin, kMax) {  // show a rectangle of the tree
  const {vw, vh} = room(), k = Math.max(kMin, Math.min(kMax, (vw - 40) / (x1 - x0), (vh - 24) / (y1 - y0)));
  moveTo({k, x: (vw - (x0 + x1) * k) / 2, y: TOP + (vh - (y0 + y1) * k) / 2});
}
const fit = () => frame(0, 0, ext.w, ext.h, 0.05, 1.3);
function camTo(n) {  // bring one card to the middle-left, leaving room for its ancestors on the right
  const {vw, vh} = room(), k = Math.max(view.k, narrow() ? 0.85 : 0.8);
  moveTo({k, x: (narrow() ? 12 : Math.max(24, vw * 0.3)) - n.x * k, y: TOP + vh / 2 - (n.y + H / 2) * k});
}
function zoomAt(px, py, f) {
  cancelAnimationFrame(anim);
  const k = Math.max(0.12, Math.min(3, view.k * f)); f = k / view.k;
  view = {k, x: px - (px - view.x) * f, y: py - (py - view.y) * f}; apply();
}
const zoomMid = f => zoomAt(chart.clientWidth / 2, chart.clientHeight / 2, f);
function ensureVisible(n) {
  if (!n) return;
  cancelAnimationFrame(anim);
  const vw = chart.clientWidth, vh = chart.clientHeight, m = 24, k = view.k, v = {...view};
  const sx = view.x + n.x * k, sy = view.y + n.y * k, lo = TOP + 8, hi = vh - (narrow() ? 12 : BOT + 4);
  if (sx < m) v.x += m - sx; else if (sx + W * k > vw - m) v.x -= Math.min(sx - m, sx + W * k - (vw - m));
  if (sy < lo) v.y += lo - sy; else if (sy + H * k > hi) v.y -= Math.min(sy - lo, sy + H * k - hi);
  if (v.x !== view.x || v.y !== view.y) moveTo(v, 200);
}

// ---- navigation ---------------------------------------------------------
function navigate(id, push = true) {  // redraw the tree from this person
  if (!P[id]) return;
  if (push && focus && focus !== id) hist.push(focus);
  focus = id; opened.clear(); shut.clear(); selKey = 'r'; spot = null; filt = null; snap = null;
  try { history.replaceState(null, '', '#' + id); } catch (e) {}
  totals = []; walk((k, i, g) => { totals[g] = (totals[g] || 0) + 1; });
  showOrigins(); draw(); initView(); crumbs(); show(id);
}
function pick(key) {  // select a card and show its details
  const n = N.get(key); if (!n) return;
  selKey = key; restyle(); crumbs(); show(n.id); ensureVisible(n);
}
function center(key) {  // move the camera to a card and spotlight that person's ancestors; the tree stays as it is
  if (!N.has(key)) return;
  let redraw = false;
  if (filt) { filt = null; snap = null; redraw = true; }
  if (N.get(key).more) { shut.delete(key); opened.add(key); redraw = true; }
  selKey = key; spot = key === 'r' ? null : key;
  if (redraw) draw(); else restyle();
  crumbs(); show(N.get(key).id);
  if (key === 'r') initView(280); else camTo(N.get(key));
}
function keyOf(id) {  // the card of a person: next to the selection if possible, else the nearest to the root
  if (selKey) for (const k of [selKey, selKey + 'f', selKey + 'm', selKey.slice(0, -1)]) if (N.has(k) && N.get(k).id === id) return k;
  let best = null;
  for (const n of N.values()) if (n.id === id && (!best || n.key.length < best.length)) best = n.key;
  return best;
}
function openPath(key) { for (let i = 1; i < key.length; i++) { shut.delete(key.slice(0, i)); opened.add(key.slice(0, i)); } }
function reveal(id) {  // an ancestor hidden in a folded branch: unfold the shortest way to it
  let best = null;
  walk((k, i) => { if (i === id && (!best || k.length < best.length)) best = k; });
  if (best) { openPath(best); draw(); }
  return best;
}
function goPerson(id) {  // from a link: select the person in this tree, or redraw the tree from them
  const key = keyOf(id) || reveal(id);
  if (key) pick(key); else navigate(id);
}
function toggle(key) {
  const n = N.get(key), sx = view.x + n.x * view.k, sy = view.y + n.y * view.k, was = selKey;
  cancelAnimationFrame(anim);
  if (n.more) { shut.delete(key); opened.add(key); } else { shut.add(key); opened.delete(key); if (selKey && selKey.startsWith(key)) selKey = key; if (spot && spot.startsWith(key)) spot = key === 'r' ? null : key; }
  draw(); crumbs();
  if (selKey !== was) show(N.get(selKey).id);
  const m = N.get(key); view.x = sx - m.x * view.k; view.y = sy - m.y * view.k; apply();
  if (n.more) ensureVisible(N.get(key + 'f') || N.get(key + 'm'));
}
function pathUp(from, to) {
  const prev = {[from]: null}, q = [from];
  while (q.length) {
    const x = q.shift(); if (x === to) break;
    for (const y of [P[x].f, P[x].m]) if (y && P[y] && !(y in prev)) { prev[y] = x; q.push(y); }
  }
  if (!(to in prev)) return null;
  const out = []; for (let x = to; x != null; x = prev[x]) out.unshift(x); return out;
}
function crumbs() {  // root person › … › tree root › … › selected card
  let pre = pathUp($('#root').value, focus);
  if (!pre) for (const r of D.roots) if ((pre = pathUp(r.id, focus))) { $('#root').value = r.id; break; }
  const a = (attr, id, cur) => `<a ${attr} class="${cur ? 'cur' : ''}" title="${esc(P[id].n)}">${esc(brief(P[id].n))}</a>`;
  const sk = selKey || 'r', parts = (pre || [focus]).slice(0, -1).map(id => a(`data-nav="${id}"`, id));
  for (let i = 1; i <= sk.length; i++) parts.push(a(`data-key="${sk.slice(0, i)}"`, N.get(sk.slice(0, i)).id, i === sk.length));
  let h = `<button id="back" title="Voltar à árvore anterior (Alt+←)" aria-label="Voltar"${hist.length ? '' : ' disabled'}>←</button>` + parts.join('<span>›</span>');
  if (!pre) h += ` <span>&nbsp;(fora da linha das raízes)</span>`;
  const kids = P[focus].ch.filter(c => P[c]);
  if (kids.length && sk === 'r' && !(pre && pre.length > 1))
    h += `<span>&nbsp;&nbsp;filhos:</span>` + kids.map(c => a(`data-nav="${c}"`, c)).join('');
  const el = $('#crumbs');
  el.innerHTML = h;
  $('#back').onclick = back;
  el.querySelectorAll('[data-nav]').forEach(x => x.onclick = () => navigate(x.dataset.nav));
  el.querySelectorAll('[data-key]').forEach(x => x.onclick = () => center(x.dataset.key));
  el.scrollLeft = el.scrollWidth;
}
const back = () => { if (hist.length) navigate(hist.pop(), false); };

// ---- countries ----------------------------------------------------------
function showOrigins() {  // one button per birth country among the ancestors of the tree's root
  const seen = new Set([focus]), queue = [focus];
  ORG = new Map();
  while (queue.length) {
    const p = P[queue.shift()];
    for (const id of [p.f, p.m]) {
      if (!id || !P[id] || seen.has(id)) continue;
      seen.add(id); queue.push(id);
      if (country(P[id])) { const group = ORG.get(P[id].co.id) || []; group.push(id); ORG.set(P[id].co.id, group); }
    }
  }
  let h = '<span class="lbl">Países de nascimento na ascendência — clique para destacar:</span>';
  const rec = ids => ids.filter(i => !P[i].co.pr).length;
  for (const [code, all] of [...ORG].sort((a, b) => rec(b[1]) - rec(a[1]) || b[1].length - a[1].length)) {
    const n = rec(all), pr = all.length - n, c = D.countries[code];
    const title = `Destacar na árvore: ${n} ancestral(is) com local registrado${pr ? `, mais ${pr} presumido(s) sem registro` : ''}`;
    h += `<button data-origin="${code}" aria-pressed="false" class="${n ? '' : 'pr'}" style="--country:${c.color}" title="${esc(title)}"><span class="country-flag" aria-hidden="true">${c.flag}</span>${esc(c.name)} <b>${n}</b>${pr ? `<span class="pr-n">+${pr}</span>` : ''}</button>`;
  }
  if (!ORG.size) h += '<span>sem país registrado</span>';
  $('#origins').innerHTML = h;
  $('#origins').querySelectorAll('[data-origin]').forEach(b => b.onclick = () => setFilter(b.dataset.origin));
}
function setFilter(code) {  // highlight every ancestor born in a country (unfolding the branches that hide them); again = off
  const put = (to, from) => { to.clear(); for (const x of from) to.add(x); };
  if (code && code !== filt) {
    if (snap) { put(opened, snap[0]); put(shut, snap[1]); } else snap = [new Set(opened), new Set(shut)];
    filt = code; spot = null;
    walk((k, i, g) => { if (g && P[i].co && P[i].co.id === code) openPath(k); });
    draw(); crumbs(); showFilter();
    const hits = [...N.values()].filter(n => n.hit);
    if (hits.length) frame(Math.min(...hits.map(n => n.x)), Math.min(...hits.map(n => n.y)), Math.max(...hits.map(n => n.x)) + W, Math.max(...hits.map(n => n.y)) + H, 0.2, 1.1);
  } else if (filt) {
    filt = null;
    if (snap) { put(opened, snap[0]); put(shut, snap[1]); snap = null; }
    draw(); crumbs(); initView(280);
    if (selKey) show(N.get(selKey).id); else intro();
  }
}
function showFilter() {
  const c = D.countries[filt], ids = ORG.get(filt) || [], pr = ids.filter(i => P[i].co.pr).length;
  const first = new Map();  // each person once, at the place nearest to the root
  for (const n of N.values()) if (n.hit && !(first.has(n.id) && first.get(n.id).g <= n.g)) first.set(n.id, n);
  const rows = [...first.values()].sort((a, b) => a.g - b.g || a.y - b.y);
  let h = `<button class="x" id="closeSide" title="Fechar painel" aria-label="Fechar painel">✕</button><h2><span class="country-flag" style="font-size:20px">${c.flag}</span> ${esc(c.name)}</h2>
    <div class="sub">${ids.length} ancestrais de ${esc(P[focus].n)} destacados na árvore${pr ? ` · ${ids.length - pr} com local registrado, ${pr} presumidos (borda tracejada)` : ''}. Clique num nome para ir até a pessoa.</div>
    <div class="acts"><button id="unfilt">Remover destaque</button></div>`;
  let g = -1;
  for (const n of rows) {
    const p = P[n.id];
    if (n.g !== g) { h += `${g < 0 ? '' : '</div>'}<h3>${genName(n.g)} · ${rows.filter(r => r.g === n.g).length}</h3><div class="list">`; g = n.g; }
    h += `<div><a class="lnk" data-cam="${n.id}">${esc(p.n)}</a> <span class="sub">${esc([p.yy, p.bp, p.co.pr ? 'presumido' : ''].filter(Boolean).join(' · '))}</span></div>`;
  }
  side.innerHTML = h + (rows.length ? '</div>' : ''); side.scrollTop = 0; wire(); openPanel();
  $('#unfilt').onclick = () => setFilter(null);
}
function camPerson(id, el) {  // from the country list: go to the person, keep the list open
  const key = keyOf(id) || reveal(id); if (!key) return;
  selKey = key; restyle(); crumbs(); camTo(N.get(key));
  side.querySelectorAll('.lnk.cur').forEach(x => x.classList.remove('cur')); el.classList.add('cur');
}
chipsEl.addEventListener('click', e => {
  const x = e.target.closest('[data-x]'), c = e.target.closest('[data-chip]');
  if (x) { if (x.dataset.x === 'filt') setFilter(null); else { spot = null; restyle(); } }
  else if (c) { if (c.dataset.chip === 'filt') { showFilter(); setPanel(true); } else center(spot); }
});

// ---- side panel ---------------------------------------------------------
const link = id => id && P[id] ? `<a class="lnk" data-go="${id}">${esc(P[id].n)}</a> <span class="sub">${esc(P[id].yy)}</span>` : '<span class="sub">desconhecido</span>';
const linkN = id => `<a class="lnk" data-go="${id}" title="${esc(P[id].l)}">${esc(P[id].n.split(' ')[0])}</a>`;
const CLOSE = `<button class="x" id="closeSide" title="Fechar painel" aria-label="Fechar painel">✕</button>`;
function wire() {
  side.querySelectorAll('[data-go]').forEach(a => a.onclick = () => goPerson(a.dataset.go));
  side.querySelectorAll('[data-focus]').forEach(a => a.onclick = () => navigate(a.dataset.focus));
  side.querySelectorAll('[data-center]').forEach(a => a.onclick = () => center(a.dataset.center));
  side.querySelectorAll('[data-cam]').forEach(a => a.onclick = () => camPerson(a.dataset.cam, a));
  const x = $('#closeSide'); if (x) x.onclick = () => setPanel(false, !narrow());
}
function openPanel() { if (ready && side.hidden && (narrow() || panelPref === null)) setPanel(true); }
function show(id) {
  const p = P[id], key = keyOf(id);
  let h = `${CLOSE}<h2>${esc(p.n)}</h2><div class="sub">${esc(p.l || (p.pv ? 'dados pessoais omitidos' : 'datas desconhecidas'))} · ${id}`;
  if (OPEN.has(id)) h += `<span class="badge b-open">pais em aberto</span>`;
  if (p.cf) h += `<span class="badge b-weak">${CF[p.cf]}</span>`;
  if (p.lv) h += `<span class="badge b-live">vivo(a)</span>`;
  const c = country(p);
  h += `</div>${c ? `<div class="country-badge${p.co.pr ? ' pr' : ''}" style="--country:${c.color}" title="${esc(countryLabel(p))}"><span class="country-flag" aria-hidden="true">${c.flag}</span>${esc(c.name)}<span class="sub">· ${p.co.event}</span></div>${p.co.born ? `<div class="sub" style="margin:-6px 0 10px">Nascido em ${esc(p.co.born)}.</div>` : ''}${p.co.pr ? `<div class="sub" style="margin:-6px 0 10px">Sem local de nascimento registrado; ${esc(p.co.why)}.</div>` : ''}` : ''}<div class="acts">`
    + (key ? `<button data-center="${key}" title="Leva a câmera até esta pessoa e destaca os ancestrais dela (Enter ou duplo clique)">Centralizar</button>` : '')
    + (id !== focus ? `<button data-focus="${id}" title="Redesenha a árvore a partir desta pessoa">Ver como raiz</button>` : '')
    + (p.do ? `<a href="${esc(p.do)}" target="_blank">Dossiê de pesquisa ↗</a>` : '') + '</div>';
  h += `<h3>Família</h3><div class="kv"><span class="k">Pai</span><span>${link(p.f)}</span><span class="k">Mãe</span><span>${link(p.m)}</span>`;
  const spouses = p.sp.length ? p.sp : (p.ch.length ? [[null, null]] : []);
  for (const [, s] of spouses) {
    if (s) h += `<span class="k">Cônjuge</span><span>${link(s)}</span>`;
    const kids = p.ch.filter(c => P[c] && (!s || P[c].f === s || P[c].m === s));
    if (kids.length) h += `<span class="k">Filhos</span><span>${kids.map(linkN).join(', ')}</span>`;
  }
  h += '</div>';
  if (p.ev.length) h += `<h3>Fatos</h3><div class="kv">` + p.ev.map(e => `<span class="k">${esc(e[0])}</span><span>${esc(e[1])}${e[2] ? (e[1] ? ', ' : '') + esc(e[2]) : ''}</span>`).join('') + '</div>';
  if (p.no.length) h += `<details${p.no.join('').length < 300 ? ' open' : ''}><summary>Notas (${p.no.length})</summary>` + p.no.map(n => `<div class="note">${esc(n)}</div>`).join('') + '</details>';
  if (p.so.length) h += `<details${p.so.length <= 2 ? ' open' : ''}><summary>Fontes (${p.so.length})</summary>` + p.so.map(s => `<div class="src">${s.u ? `<a class="lnk" href="${esc(s.u)}" target="_blank" rel="noopener">${esc(s.t)}</a>` : esc(s.t)}${s.k !== '' ? ` <span class="sub">(${esc(s.k)}/3)</span>` : ''}${s.q ? `<q>${esc(s.q)}</q>` : ''}</div>`).join('') + '</details>';
  side.innerHTML = h; side.scrollTop = 0; wire(); openPanel();
}
function intro() {
  let h = `${CLOSE}<h2>Árvore da família</h2><div class="sub">${D.counts[0]} pessoas · ${D.counts[1]} famílias · ${D.counts[2]} fontes · gerado ${D.date}</div>
  <ul class="tips"><li><b>Clique</b> (ou toque) numa pessoa para ver os detalhes.</li>
  <li><b>Duplo clique</b>, ou o botão <b>Centralizar</b>, leva a câmera até a pessoa e destaca os ancestrais dela; o resto da árvore fica esmaecido. Clique no fundo para desfazer.</li>
  <li><b>Clique num país</b> na barra de cima para destacar todos os ancestrais nascidos lá; clique de novo para desfazer.</li>
  <li><b>+n</b> ao lado de um cartão abre aquele ramo; <b>−</b> recolhe. <b>Ver como raiz</b> redesenha a árvore a partir da pessoa.</li>
  <li>Arraste para mover; role ou faça pinça para zoom; <b>Ajustar</b> mostra tudo. <b>Compacto / Detalhado</b> muda o tamanho dos cartões. Ao afastar, o texto encolhe mais devagar que os cartões e os detalhes dão lugar ao nome, para a árvore continuar legível.</li>
  <li class="kbd-only">Teclado: <kbd>←</kbd><kbd>→</kbd><kbd>↑</kbd><kbd>↓</kbd> navegam, <kbd>Enter</kbd> centraliza, <kbd>/</kbd> busca, <kbd>Esc</kbd> limpa.</li></ul>
  <h3>Legenda</h3><div class="legend"><span><span class="sw"></span>ligação documentada</span><span><span class="sw weak"></span>ligação fraca</span>
  <span style="color:var(--open)"><b>?</b> pais em aberto</span><span><b>+n</b> ancestrais ocultos</span><span>⚑ país do nascimento ou batismo</span><span><span style="opacity:.5">⚑</span> país presumido</span>
  <span>n. nascimento · bat. batismo · f. óbito · sep. sepultamento</span></div>`;
  if (D.links.length) h += `<h3>Conexões entre as raízes</h3><div class="list">` + D.links.map(l => `<div>${esc(l.a)} e ${esc(l.b)}: <b>${esc(l.k)}</b>, por ${link(l.id)}</div>`).join('') + '</div>';
  h += `<details><summary>Pais em aberto (${D.open.length})</summary><div class="list">` + D.open.map(i => `<div>${link(i)}</div>`).join('') + '</div></details>';
  side.innerHTML = h; side.scrollTop = 0; wire();
}

// ---- pointer: click, double click, drag, pinch, wheel -------------------
const ptrs = new Map(); let drag = null, moved = false, pinch = null, tap = {k: null, t: 0};
chart.addEventListener('pointerdown', e => {
  if (e.button > 0 || e.target.closest('#chips')) return;
  cancelAnimationFrame(anim);
  ptrs.set(e.pointerId, {x: e.clientX, y: e.clientY});
  if (ptrs.size === 1) { drag = {x: e.clientX, y: e.clientY, vx: view.x, vy: view.y}; moved = false; }
  else if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; pinch = {d: Math.hypot(a.x - b.x, a.y - b.y), k: view.k}; drag = null; }
});
chart.addEventListener('pointermove', e => {
  if (!ptrs.has(e.pointerId)) return;
  ptrs.set(e.pointerId, {x: e.clientX, y: e.clientY});
  if (pinch && ptrs.size === 2) {
    const [a, b] = [...ptrs.values()], r = chart.getBoundingClientRect();
    zoomAt((a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top, pinch.k * Math.hypot(a.x - b.x, a.y - b.y) / pinch.d / view.k);
    moved = true; return;
  }
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (!moved && Math.hypot(dx, dy) < 5) return;
  if (!moved) { moved = true; chart.setPointerCapture(e.pointerId); chart.classList.add('drag'); }
  view.x = drag.vx + dx; view.y = drag.vy + dy; apply();
});
const up = e => {
  ptrs.delete(e.pointerId); if (ptrs.size < 2) pinch = null;
  if (ptrs.size === 1) { const [a] = [...ptrs.values()]; drag = {x: a.x, y: a.y, vx: view.x, vy: view.y}; }  // one finger left after a pinch: keep panning
  if (!ptrs.size) { drag = null; chart.classList.remove('drag'); setTimeout(() => { moved = false; }, 0); }
};
chart.addEventListener('pointerup', up); chart.addEventListener('pointercancel', up);
chart.addEventListener('wheel', e => {
  e.preventDefault();
  const m = e.deltaMode === 1 ? 16 : 1, r = chart.getBoundingClientRect();
  if (e.shiftKey) { cancelAnimationFrame(anim); view.x -= (e.deltaX || e.deltaY) * m; apply(); return; }  // shift+scroll pans sideways
  // scroll / pinch zooms around the mouse pointer (pinch arrives as ctrl+wheel with small deltas)
  const d = Math.max(-60, Math.min(60, e.deltaY * m));
  zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-d * (e.ctrlKey ? 0.01 : 0.003)));
}, {passive: false});
let mouse = null;  // last pointer position over the chart, for keyboard zoom
chart.addEventListener('mousemove', e => { const r = chart.getBoundingClientRect(); mouse = [e.clientX - r.left, e.clientY - r.top]; });
chart.addEventListener('mouseleave', () => { mouse = null; });
const zoomKey = f => mouse ? zoomAt(mouse[0], mouse[1], f) : zoomMid(f);
chart.addEventListener('click', e => {
  if (moved || e.target.closest('#chips')) return;
  const h = e.target.closest('[data-h]'); if (h) return toggle(h.dataset.h);
  const n = e.target.closest('.node');
  if (!n) { if (spot) { spot = null; restyle(); } return; }  // click on the background: drop the spotlight
  const k = n.dataset.k;
  if (tap.k === k && e.timeStamp - tap.t < 450) { tap.k = null; center(k); }  // double click / double tap
  else { tap = {k, t: e.timeStamp}; pick(k); }
});

// ---- keyboard -----------------------------------------------------------
document.addEventListener('keydown', e => {
  if (e.target.matches('input,select,textarea')) return;
  if (e.altKey && e.key === 'ArrowLeft') { back(); e.preventDefault(); return; }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  let n = selKey && N.get(selKey);
  const go = m => { if (m) pick(m.key); };
  switch (e.key) {
    case '/': $('#q').focus(); break;
    case 'ArrowRight':
      if (!n) { go(N.get('r')); break; }
      if (n.more) toggle(n.key);
      go(N.get(n.key + 'f') || N.get(n.key + 'm')); break;
    case 'ArrowLeft': go(n ? N.get(n.key.slice(0, -1)) : N.get('r')); break;
    case 'ArrowUp': case 'ArrowDown': {
      if (!n) { go(N.get('r')); break; }
      const col = [...N.values()].filter(m => m.g === n.g).sort((a, b) => a.y - b.y);
      go(col[col.indexOf(n) + (e.key === 'ArrowUp' ? -1 : 1)]); break;
    }
    case 'Enter': if (n) center(n.key); break;
    case 'Escape':
      if (filt) setFilter(null); else if (spot) { spot = null; restyle(); }
      else { selKey = null; restyle(); crumbs(); intro(); }
      break;
    case '+': case '=': zoomKey(1.25); break;
    case '-': case '_': zoomKey(0.8); break;
    case '0': case 'f': fit(); break;
    default: return;
  }
  e.preventDefault();
});

// ---- header controls ----------------------------------------------------
$('#meta').textContent = `${D.counts[0]} pessoas · ${D.counts[2]} fontes · ${D.date}`;
for (const r of D.roots) $('#root').insertAdjacentHTML('beforeend', `<option value="${r.id}">${esc(r.label)}</option>`);
$('#root').onchange = () => navigate($('#root').value);
function setGens(g) {
  gens = Math.max(2, Math.min(16, g)); store.set('gens', gens);
  $('#gv').textContent = gens + ' ger.'; $('#gm').disabled = gens <= 2; $('#gp').disabled = gens >= 16;
}
function regen(d) {
  setGens(gens + d); opened.clear(); shut.clear(); snap = snap && [new Set(), new Set()];
  if (filt) walk((k, i, g) => { if (g && P[i].co && P[i].co.id === filt) openPath(k); });
  if (selKey) openPath(selKey);
  draw(); crumbs(); initView();
  if (spot) camTo(N.get(spot));
}
$('#gm').onclick = () => regen(-1); $('#gp').onclick = () => regen(1);
function setDensity(d, redraw) {
  dens = DENS[d] ? d : 'det'; ({W, H, GX, GY, GC} = DENS[dens]);
  $('#dc').classList.toggle('on-btn', dens === 'cmp'); $('#dd').classList.toggle('on-btn', dens === 'det');
  if (!redraw) return;
  store.set('dens', dens); draw(); initView();
  if (selKey && selKey !== 'r') camTo(N.get(selKey));
}
$('#dc').onclick = () => setDensity(narrow() ? 'det' : 'cmp', true); $('#dd').onclick = () => setDensity(narrow() ? 'cmp' : 'det', true);
$('#zi').onclick = () => zoomMid(1.25); $('#zo').onclick = () => zoomMid(0.8); $('#fit').onclick = fit;
let panelPref = store.get('panel', null);
function setPanel(on, save) { side.hidden = !on; $('#panel').classList.toggle('on-btn', on); if (save) store.set('panel', panelPref = on ? '1' : '0'); }
$('#panel').onclick = () => setPanel(side.hidden, !narrow());
$('#help').onclick = () => { intro(); setPanel(true); };

// Theme: follows the browser / system setting unless the button picks one; the choice is remembered.
const dark = matchMedia('(prefers-color-scheme: dark)');
const tint = () => { $('meta[name=theme-color]').content = getComputedStyle(document.documentElement).getPropertyValue('--panel').trim(); };
function setTheme(t, save) {
  const r = document.documentElement, b = $('#theme');
  if (t === 'light' || t === 'dark') r.dataset.theme = t; else { delete r.dataset.theme; t = 'auto'; }
  if (save) store.set('theme', t);
  b.dataset.t = t; b.innerHTML = {auto: '◐<span class="wide"> Auto</span>', light: '☀<span class="wide"> Claro</span>', dark: '☾<span class="wide"> Escuro</span>'}[t];
  b.title = 'Tema: ' + {auto: 'automático, segue o navegador / sistema', light: 'claro', dark: 'escuro'}[t] + '. Clique para mudar.';
  tint();
}
$('#theme').onclick = () => {
  const sys = dark.matches ? 'dark' : 'light', cyc = ['auto', sys === 'dark' ? 'light' : 'dark', sys];
  setTheme(cyc[(cyc.indexOf($('#theme').dataset.t) + 1) % 3], true);
};
dark.addEventListener('change', tint);

const norm = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
let hits = [], act = 0;
function paintResults() {
  const r = $('#results');
  r.innerHTML = hits.map((p, i) => `<div data-id="${p.id}" class="${i === act ? 'act' : ''}">${esc(p.n)} <span class="sub">${esc(p.yy)}</span></div>`).join('') || '<div>nada encontrado</div>';
  r.hidden = false;
  r.querySelectorAll('[data-id]').forEach(d => d.onmousedown = ev => { ev.preventDefault(); choose(d.dataset.id); });
}
function choose(id) {  // a search result: go to the person in this tree if they are in it
  $('#results').hidden = true; $('#q').value = ''; $('#q').blur();
  const key = keyOf(id) || reveal(id);
  if (key) center(key); else navigate(id);
}
$('#q').oninput = () => {
  const q = norm($('#q').value.trim());
  if (q.length < 2) { $('#results').hidden = true; hits = []; return; }
  const words = q.split(/\s+/);
  hits = Object.values(P).filter(p => words.every(w => norm(p.n).includes(w))).slice(0, 30); act = 0; paintResults();
};
$('#q').onkeydown = e => {
  if (e.key === 'Escape') { $('#results').hidden = true; $('#q').value = ''; $('#q').blur(); }
  else if (e.key === 'Enter' && hits[act]) choose(hits[act].id);
  else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && hits.length) { act = (act + (e.key === 'ArrowDown' ? 1 : hits.length - 1)) % hits.length; paintResults(); }
  else return;
  e.preventDefault();
};
$('#q').onblur = () => setTimeout(() => { $('#results').hidden = true; }, 100);
addEventListener('resize', apply);

// ---- start --------------------------------------------------------------
if (!narrow()) $('#q').placeholder += '  /';
setTheme(store.get('theme', 'auto'));
setDensity(store.get('dens', narrow() ? 'cmp' : 'det'));
setGens(gens);
setPanel(panelPref && !narrow() ? panelPref === '1' : !narrow());
const start = decodeURIComponent(location.hash.slice(1));
navigate(P[start] ? start : D.roots[0].id, false);
if (!P[start]) { selKey = null; restyle(); crumbs(); intro(); }
ready = true;
</script>
</body>
</html>
"""
