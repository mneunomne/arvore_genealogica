"""Lossless GEDCOM 5.5.1 reader/writer.

The file is kept as a generic tree of nodes, so every tag we do not understand
(MyHeritage's _UPD, _UID, photo tags, ...) survives a load/save round trip
byte for byte. All edits are made on this node tree.
"""
import re

LINE = re.compile(r'^(\d+) (?:(@[^@ ]+@) )?([A-Za-z0-9_]+)(?: (.*))?$', re.S)
BOM = chr(0xFEFF)
MAX_VALUE = 200  # split longer values with CONC


class Node:
    __slots__ = ('tag', 'value', 'xref', 'children', 'tail')

    def __init__(self, tag, value=None, xref=None):
        self.tag = tag
        self.value = value
        self.xref = xref
        self.children = []
        self.tail = None   # raw non-GEDCOM lines that followed this line (kept verbatim)

    # --- reading -----------------------------------------------------------
    def get(self, tag):
        for c in self.children:
            if c.tag == tag:
                return c
        return None

    def all(self, tag):
        return [c for c in self.children if c.tag == tag]

    def val(self, *path):
        """Value at a tag path, e.g. node.val('BIRT', 'DATE'); None if absent."""
        n = self
        for tag in path:
            n = n.get(tag)
            if n is None:
                return None
        return n.value

    def text(self):
        """Value joined with its CONC/CONT continuation lines."""
        out = self.value or ''
        for c in self.children:
            if c.tag == 'CONC':
                out += c.value or ''
            elif c.tag == 'CONT':
                out += '\n' + (c.value or '')
        return out

    # --- writing -----------------------------------------------------------
    def add(self, tag, value=None):
        n = Node(tag, value)
        self.children.append(n)
        return n

    def add_text(self, tag, text):
        """Add a child holding long/multi-line text, split into CONC/CONT."""
        lines = str(text).replace('\r', '').split('\n')
        node = None
        for i, line in enumerate(lines):
            chunks = [line[j:j + MAX_VALUE] for j in range(0, len(line), MAX_VALUE)] or ['']
            for k, chunk in enumerate(chunks):
                # a chunk must not start/end with a space, or it is lost on re-import
                while k + 1 < len(chunks) and chunk.endswith(' ') and len(chunk) > 1:
                    chunks[k + 1] = chunk[-1] + chunks[k + 1]
                    chunk = chunk[:-1]
                if node is None:
                    node = self.add(tag, chunk)
                elif k == 0:
                    node.add('CONT', chunk)
                else:
                    node.add('CONC', chunk)
        return node

    def remove(self, child):
        self.children.remove(child)

    def __repr__(self):
        return f'<{self.xref or ""} {self.tag} {self.value!r}>'


class Document:
    def __init__(self):
        self.records = []      # level-0 nodes, in file order
        self.bom = False
        self.eol = '\r\n'
        self.final_eol = True

    def by_xref(self):
        return {r.xref: r for r in self.records if r.xref}

    def insert_before_trailer(self, node):
        if self.records and self.records[-1].tag == 'TRLR':
            self.records.insert(len(self.records) - 1, node)
        else:
            self.records.append(node)

    def dumps(self):
        out = []

        def emit(node, level):
            parts = [str(level)]
            if node.xref:
                parts.append(node.xref)
            parts.append(node.tag)
            line = ' '.join(parts)
            if node.value is not None:
                line += ' ' + node.value
            out.append(line)
            if node.tail:
                out.extend(node.tail)
            for c in node.children:
                emit(c, level + 1)

        for r in self.records:
            emit(r, 0)
        return (BOM if self.bom else '') + self.eol.join(out) + (self.eol if self.final_eol else '')

    def save(self, path):
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.dumps())


def loads(text):
    doc = Document()
    if text.startswith(BOM):
        doc.bom = True
        text = text[1:]
    doc.eol = '\r\n' if '\r\n' in text else '\n'
    doc.final_eol = text.endswith(doc.eol)
    if doc.final_eol:
        text = text[:-len(doc.eol)]
    stack = []
    node = None
    for lineno, raw in enumerate(text.split(doc.eol), 1):
        m = LINE.match(raw)
        if not m:
            # MyHeritage sometimes writes raw multi-line text; keep it verbatim
            if node is None:
                raise ValueError(f'GEDCOM line {lineno} not understood: {raw[:80]!r}')
            if node.tail is None:
                node.tail = []
            node.tail.append(raw)
            continue
        level = int(m.group(1))
        node = Node(m.group(3), m.group(4), m.group(2))
        if level == 0:
            doc.records.append(node)
            stack = [node]
        else:
            if level > len(stack):
                raise ValueError(f'GEDCOM line {lineno} skips a level: {raw[:80]!r}')
            del stack[level:]
            stack[-1].children.append(node)
            stack.append(node)
    return doc


# MyHeritage sometimes cuts a CONC line in the middle of a multi-byte UTF-8 character;
# move the stray continuation bytes back before the line break so the file decodes.
SPLIT_CHAR = re.compile(rb'([\xc0-\xf7][\x80-\xbf]*)(\r?\n\d+ CONC )([\x80-\xbf]+)')


def load(path):
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = SPLIT_CHAR.sub(lambda m: m.group(1) + m.group(3) + m.group(2), raw).decode('utf-8')
    return loads(text)
