"""Code compared as syntax: the scopes (functions, `<module>`) and the statements a change alters,
with no comments, layout or docstrings. Counter locality (counters.py), `audit` and `why`
read code only through these functions."""
import ast
import copy
import difflib
import functools
import io
import tokenize


def _strip_docstring(body):
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return body[1:]
    return body


def _hollow(node, prefix, out):
    """A copy of `node` with docstrings removed and every function inside it replaced by a
    marker; each function's own hollow dump goes into `out` under its qualified name."""
    node = copy.copy(node)
    for field, value in ast.iter_fields(node):
        if isinstance(value, list):
            if field == "body" and isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                value = _strip_docstring(value)
            new = []
            for v in value:
                if isinstance(v, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    q = prefix + v.name
                    out[q] = ast.dump(_hollow(v, q + ".", out))
                    new.append(ast.Expr(ast.Name(id=f"<def {q}>", ctx=ast.Load())))
                elif isinstance(v, ast.ClassDef):
                    new.append(_hollow(v, prefix + v.name + ".", out))
                else:
                    new.append(_hollow(v, prefix, out) if isinstance(v, ast.AST) else v)
            setattr(node, field, new)
        elif isinstance(value, ast.AST):
            setattr(node, field, _hollow(value, prefix, out))
    return node


@functools.lru_cache(maxsize=512)
def scope_dumps(src):
    """{scope: dump}: each function (qualified by its classes) and `<module>` (everything
    outside functions, classes' other statements included), as ast.dump without positions,
    comments, layout or docstrings. Raises SyntaxError if `src` does not parse."""
    out = {}
    out["<module>"] = ast.dump(_hollow(ast.parse(src), "", out))
    return out


@functools.lru_cache(maxsize=4096)
def changed_scopes(path, old, new):
    """{(path, scope)} whose AST differs between `old` and `new` (scope_dumps): a comment,
    whitespace or a docstring changes no scope. Raises SyntaxError if `new` does not parse."""
    a, b = scope_dumps(old) if old else {}, scope_dumps(new)
    return frozenset((path, k) for k in set(a) | set(b) if a.get(k) != b.get(k))


STMT_LISTS = ("body", "handlers", "orelse", "finalbody", "cases")


def _units(stmts, scope, depth, out, top=True, nodes=None):
    """Append (scope, depth, dump) for each statement of `stmts`, in source order: a simple
    statement whole, a compound one by its header (the node with its statement lists
    emptied) followed by its children; a docstring is no unit. `nodes`, when given, gets
    each unit's node, in the same order (statement_lines)."""
    for k, st in enumerate(stmts):
        if top and k == 0 and isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) \
                and isinstance(st.value.value, str):
            continue
        lists = [(f, getattr(st, f)) for f in STMT_LISTS if isinstance(getattr(st, f, None), list)]
        if nodes is not None:
            nodes.append(st)
        if not lists:
            out.append((scope, depth, ast.dump(st)))
            continue
        head = copy.copy(st)
        for f, _ in lists:
            setattr(head, f, [])
        out.append((scope, depth, ast.dump(head)))
        inner = scope + st.name + "." if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else scope
        for f, children in lists:
            _units(children, inner, depth + 1, out, top=f == "body" and inner != scope, nodes=nodes)


@functools.lru_cache(maxsize=512)
def statement_units(src):
    """[(scope, depth, dump)]: the statements of `src` at statement granularity (_units),
    without positions, comments, layout or docstrings. Raises SyntaxError."""
    out = []
    _units(ast.parse(src).body, "", 0, out)
    return out


CODELESS = frozenset({tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                      tokenize.ENCODING, tokenize.ENDMARKER})


def code_lines(src):
    """The numbers of the lines of `src` that hold a token of code: not blank, not only a
    comment. A token spanning lines (a triple-quoted string) marks each of them."""
    out = set()
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type not in CODELESS:
            out.update(range(t.start[0], t.end[0] + 1))
    return out


def _extent(st):
    """(first, last) source line of a statement node, decorators included; a match case has no
    position of its own and runs from its pattern to the end of its body."""
    if isinstance(st, ast.match_case):
        return st.pattern.lineno, st.body[-1].end_lineno
    return min([st.lineno] + [d.lineno for d in getattr(st, "decorator_list", [])]), st.end_lineno


@functools.lru_cache(maxsize=512)
def statement_lines(src):
    """[(scope, function, lines)] parallel to statement_units(src): unit i's own source lines,
    the lines of its extent outside its children's extents (a docstring child included) that
    hold code (code_lines); a compound header sharing its only line with its body keeps that
    line. `function` is the qualified name of the function the unit belongs to (a def header
    to its own function), or None at module or class level. Raises SyntaxError."""
    nodes, units = [], []
    _units(ast.parse(src).body, "", 0, units, nodes=nodes)
    code, out = code_lines(src), []
    funcs = {sc + st.name for (sc, _, _), st in zip(units, nodes) if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for (scope, _, _), st in zip(units, nodes):
        first, last = _extent(st)
        own = set(range(first, last + 1))
        for f in STMT_LISTS:
            for child in getattr(st, f, None) or []:
                a, b = _extent(child)
                own -= set(range(a, b + 1))
        own = own & code or {first}
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = scope + st.name
        else:
            parts = scope.rstrip(".").split(".") if scope else []
            fn = next((".".join(parts[:k]) for k in range(len(parts), 0, -1) if ".".join(parts[:k]) in funcs), None)
        out.append((scope, fn, frozenset(own)))
    return out


@functools.lru_cache(maxsize=4096)
def changed_statements(path, old, new):
    """{(path, key)}: the statements of `old` a change to `new` replaces or deletes, key
    ("at", i) for its i-th unit, and the places it inserts new ones, ("insert", i) before
    old unit i: both sides' units aligned (difflib), so a key names the same statement for
    any change made to the same `old`. Raises SyntaxError if `new` does not parse."""
    a, b = statement_units(old) if old else [], statement_units(new)
    out = set()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            out |= {(path, ("at", i)) for i in range(i1, i2)}
        if op == "insert" or (op == "replace" and j2 - j1 > i2 - i1):
            out.add((path, ("insert", i1)))
    return frozenset(out)
