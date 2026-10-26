"""Cognos expression grammar: tokenizer, recursive-descent parser, AST and SQL translation.

Covers the constructs found in FM models, report specs and security filters:
bracket references ``[ns].[qs].[item]``, dotted physical names, literals, prompts
``?p_Name?``, arithmetic, comparison, ``in``/``not in`` lists and sub-selects,
``case when``, ``extract(x from y)``, ``is [not] null``, ``between`` and function calls.

Grammar (EBNF, lowest precedence first)::

    expr      := or_expr
    or_expr   := and_expr ("or" and_expr)*
    and_expr  := not_expr ("and" not_expr)*
    not_expr  := "not" not_expr | cmp_expr
    cmp_expr  := add_expr ( cmp_op add_expr | ["not"] "in" "(" list | subquery ")"
                          | "is" ["not"] "null" | ["not"] "between" add_expr "and" add_expr
                          | ["not"] "like" add_expr )?
    add_expr  := mul_expr (("+" | "-" | "||") mul_expr)*
    mul_expr  := unary (("*" | "/") unary)*
    unary     := "-" unary | primary
    primary   := literal | prompt | ref | name ["(" args ")"] | "(" expr ")" | case | extract
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Union


class ParseError(ValueError):
    pass


# --------------------------------------------------------------------------- tokens
_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<ref>\[[^\]]*\])
  | (?P<param>\?[A-Za-z_][\w]*\?)
  | (?P<string>'(?:[^']|'')*')
  | (?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<op><>|!=|<=|>=|\|\||[=<>+\-*/(),.])
  | (?P<name>[A-Za-z_][\w$#]*)
""", re.VERBOSE)

KEYWORDS = {"and", "or", "not", "in", "case", "when", "then", "else", "end", "is", "null", "between",
            "like", "select", "from", "where", "extract", "true", "false"}


@dataclass
class Token:
    kind: str
    value: str
    pos: int


def tokenize(text: str) -> list[Token]:
    toks: list[Token] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise ParseError(f"Unexpected character {text[pos]!r} at {pos}")
        kind = m.lastgroup
        val = m.group(kind)
        if kind != "ws":
            if kind == "name" and val.lower() in KEYWORDS:
                kind = "kw"
                val = val.lower()
            toks.append(Token(kind, val, pos))
        pos = m.end()
    toks.append(Token("eof", "", len(text)))
    return toks


# --------------------------------------------------------------------------- AST
@dataclass
class Node:
    def children(self) -> list["Node"]:
        return []

    def walk(self):
        yield self
        for c in self.children():
            yield from c.walk()


@dataclass
class Ref(Node):
    parts: list[str]

    @property
    def text(self) -> str:
        return ".".join(f"[{p}]" for p in self.parts)


@dataclass
class Name(Node):
    parts: list[str]           # dotted physical identifier e.g. ENERGY_DW.METER.METER_ID


@dataclass
class Literal(Node):
    value: Union[str, float, int, bool, None]
    kind: str                  # string | number | bool | null


@dataclass
class Prompt(Node):
    name: str


@dataclass
class BinOp(Node):
    op: str
    left: Node
    right: Node

    def children(self):
        return [self.left, self.right]


@dataclass
class UnaryOp(Node):
    op: str
    operand: Node

    def children(self):
        return [self.operand]


@dataclass
class Func(Node):
    name: str
    args: list[Node] = field(default_factory=list)

    def children(self):
        return list(self.args)


@dataclass
class Case(Node):
    whens: list[tuple[Node, Node]]
    else_: Optional[Node] = None
    subject: Optional[Node] = None

    def children(self):
        out = [x for w in self.whens for x in w]
        if self.else_ is not None:
            out.append(self.else_)
        if self.subject is not None:
            out.append(self.subject)
        return out


@dataclass
class InList(Node):
    expr: Node
    items: list[Node] = field(default_factory=list)
    subquery: Optional["SubQuery"] = None
    negated: bool = False

    def children(self):
        out = [self.expr] + list(self.items)
        if self.subquery:
            out.append(self.subquery)
        return out


@dataclass
class SubQuery(Node):
    select: list[str]          # selected column names
    table: list[str]           # dotted table name
    where: Optional[Node] = None
    raw: str = ""

    def children(self):
        return [self.where] if self.where is not None else []


@dataclass
class IsNull(Node):
    expr: Node
    negated: bool = False

    def children(self):
        return [self.expr]


@dataclass
class Between(Node):
    expr: Node
    low: Node
    high: Node
    negated: bool = False

    def children(self):
        return [self.expr, self.low, self.high]


@dataclass
class Extract(Node):
    part: str
    expr: Node

    def children(self):
        return [self.expr]


# --------------------------------------------------------------------------- parser
class Parser:
    CMP_OPS = {"=", "<>", "!=", "<", ">", "<=", ">="}

    def __init__(self, text: str):
        self.text = text
        self.toks = tokenize(text)
        self.i = 0

    # token helpers
    def peek(self, k: int = 0) -> Token:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def accept(self, kind: str, value: Optional[str] = None) -> Optional[Token]:
        t = self.peek()
        if t.kind == kind and (value is None or t.value == value):
            self.i += 1
            return t
        return None

    def expect(self, kind: str, value: Optional[str] = None) -> Token:
        t = self.accept(kind, value)
        if not t:
            got = self.peek()
            raise ParseError(f"Expected {value or kind} at {got.pos}, got {got.value or got.kind!r}")
        return t

    def is_kw(self, value: str, k: int = 0) -> bool:
        t = self.peek(k)
        return t.kind == "kw" and t.value == value

    # grammar
    def parse(self) -> Node:
        node = self.or_expr()
        if self.peek().kind != "eof":
            t = self.peek()
            raise ParseError(f"Unexpected token {t.value!r} at {t.pos}")
        return node

    def or_expr(self) -> Node:
        node = self.and_expr()
        while self.accept("kw", "or"):
            node = BinOp("or", node, self.and_expr())
        return node

    def and_expr(self) -> Node:
        node = self.not_expr()
        while self.accept("kw", "and"):
            node = BinOp("and", node, self.not_expr())
        return node

    def not_expr(self) -> Node:
        if self.accept("kw", "not"):
            return UnaryOp("not", self.not_expr())
        return self.cmp_expr()

    def cmp_expr(self) -> Node:
        left = self.add_expr()
        t = self.peek()
        if t.kind == "op" and t.value in self.CMP_OPS:
            self.next()
            nxt = self.peek()
            if nxt.kind == "op" and nxt.value in self.CMP_OPS:
                raise ParseError(f"Malformed comparison '{t.value} {nxt.value}' at {t.pos}")
            return BinOp("<>" if t.value == "!=" else t.value, left, self.add_expr())
        negated = False
        if self.is_kw("not") and (self.is_kw("in", 1) or self.is_kw("between", 1) or self.is_kw("like", 1)):
            self.next()
            negated = True
        if self.accept("kw", "in"):
            self.expect("op", "(")
            if self.is_kw("select"):
                sq = self.subquery()
                self.expect("op", ")")
                return InList(left, subquery=sq, negated=negated)
            items = [self.or_expr()]
            while self.accept("op", ","):
                items.append(self.or_expr())
            self.expect("op", ")")
            return InList(left, items=items, negated=negated)
        if self.accept("kw", "between"):
            low = self.add_expr()
            self.expect("kw", "and")
            return Between(left, low, self.add_expr(), negated)
        if self.accept("kw", "like"):
            node = BinOp("like", left, self.add_expr())
            return UnaryOp("not", node) if negated else node
        if self.accept("kw", "is"):
            neg = bool(self.accept("kw", "not"))
            self.expect("kw", "null")
            return IsNull(left, neg)
        return left

    def add_expr(self) -> Node:
        node = self.mul_expr()
        while True:
            t = self.peek()
            if t.kind == "op" and t.value in ("+", "-", "||"):
                self.next()
                node = BinOp(t.value, node, self.mul_expr())
            else:
                return node

    def mul_expr(self) -> Node:
        node = self.unary()
        while True:
            t = self.peek()
            if t.kind == "op" and t.value in ("*", "/"):
                self.next()
                node = BinOp(t.value, node, self.unary())
            else:
                return node

    def unary(self) -> Node:
        if self.accept("op", "-"):
            return UnaryOp("-", self.unary())
        return self.primary()

    def primary(self) -> Node:
        t = self.peek()
        if t.kind == "string":
            self.next()
            return Literal(t.value[1:-1].replace("''", "'"), "string")
        if t.kind == "number":
            self.next()
            v = float(t.value) if any(c in t.value for c in ".eE") else int(t.value)
            return Literal(v, "number")
        if t.kind == "param":
            self.next()
            return Prompt(t.value.strip("?"))
        if t.kind == "kw" and t.value in ("true", "false"):
            self.next()
            return Literal(t.value == "true", "bool")
        if t.kind == "kw" and t.value == "null":
            self.next()
            return Literal(None, "null")
        if t.kind == "ref":
            parts = [self.next().value[1:-1]]
            while self.peek().kind == "op" and self.peek().value == "." and self.peek(1).kind == "ref":
                self.next()
                parts.append(self.next().value[1:-1])
            return Ref(parts)
        if t.kind == "kw" and t.value == "case":
            return self.case()
        if t.kind == "kw" and t.value == "extract":
            self.next()
            self.expect("op", "(")
            part = self.next().value
            self.expect("kw", "from")
            e = self.or_expr()
            self.expect("op", ")")
            return Extract(part.lower(), e)
        if t.kind == "name":
            parts = [self.next().value]
            while self.peek().kind == "op" and self.peek().value == "." and self.peek(1).kind == "name":
                self.next()
                parts.append(self.next().value)
            if self.accept("op", "("):
                args: list[Node] = []
                if not self.accept("op", ")"):
                    args.append(self.or_expr())
                    while self.accept("op", ","):
                        args.append(self.or_expr())
                    self.expect("op", ")")
                return Func(".".join(parts).lower(), args)
            return Name(parts)
        if t.kind == "op" and t.value == "(":
            self.next()
            if self.is_kw("select"):
                sq = self.subquery()
                self.expect("op", ")")
                return sq
            e = self.or_expr()
            self.expect("op", ")")
            return e
        raise ParseError(f"Unexpected token {t.value or t.kind!r} at {t.pos}")

    def case(self) -> Node:
        self.expect("kw", "case")
        subject = None
        if not self.is_kw("when"):
            subject = self.or_expr()
        whens = []
        while self.accept("kw", "when"):
            cond = self.or_expr()
            self.expect("kw", "then")
            whens.append((cond, self.or_expr()))
        else_ = None
        if self.accept("kw", "else"):
            else_ = self.or_expr()
        self.expect("kw", "end")
        if not whens:
            raise ParseError("case without when")
        return Case(whens, else_, subject)

    def subquery(self) -> SubQuery:
        start = self.peek().pos
        self.expect("kw", "select")
        cols = [self._dotted()]
        while self.accept("op", ","):
            cols.append(self._dotted())
        self.expect("kw", "from")
        table = self._dotted_parts()
        where = None
        if self.accept("kw", "where"):
            where = self.or_expr()
        end = self.peek().pos
        return SubQuery(cols, table, where, self.text[start:end].strip())

    def _dotted_parts(self) -> list[str]:
        parts = [self.expect("name").value]
        while self.accept("op", "."):
            parts.append(self.expect("name").value)
        return parts

    def _dotted(self) -> str:
        return ".".join(self._dotted_parts())


def parse(text: str) -> Node:
    return Parser(text.strip()).parse()


def try_parse(text: str) -> tuple[Optional[Node], Optional[str]]:
    try:
        return parse(text), None
    except ParseError as e:
        return None, str(e)


# --------------------------------------------------------------------------- helpers
def refs(node: Node) -> list[Ref]:
    return [n for n in node.walk() if isinstance(n, Ref)]


def is_single_ref(node: Node) -> bool:
    return isinstance(node, Ref)


def literals(node: Node) -> list[Literal]:
    return [n for n in node.walk() if isinstance(n, Literal)]


def numeric_constants(node: Node) -> list[float]:
    """Hard-coded numeric factors (excluding 0/1 and literals used only in comparisons with zero)."""
    out = []
    for n in node.walk():
        if isinstance(n, BinOp) and n.op in ("*", "/"):
            for side in (n.left, n.right):
                if isinstance(side, Literal) and side.kind == "number" and side.value not in (0, 1, 10, 100, 1000):
                    out.append(side.value)
    return out


_FUNC_MAP = {
    "session_user": "CURRENT_USER()",
    "current_user": "CURRENT_USER()",
    "current_date": "CURRENT_DATE()",
    "current_timestamp": "CURRENT_TIMESTAMP()",
    "today": "CURRENT_DATE()",
}

_RENAME_FUNCS = {"substring": "SUBSTR", "char_length": "LENGTH", "nvl": "COALESCE", "trim": "TRIM",
                 "upper": "UPPER", "lower": "LOWER", "coalesce": "COALESCE", "abs": "ABS",
                 "round": "ROUND", "floor": "FLOOR", "ceiling": "CEIL", "mod": "MOD"}


def to_sql(node: Node, resolve: Callable[[Node], str], *, prompt: Callable[[str], str] | None = None,
           prefer_iff: bool = True) -> str:
    """Translate an AST into Snowflake SQL. ``resolve`` maps Ref/Name nodes to column SQL."""

    def r(n: Node, parent_prec: int = 0) -> str:
        if isinstance(n, Name) and len(n.parts) == 1 and n.parts[0].lower() in _FUNC_MAP:
            return _FUNC_MAP[n.parts[0].lower()]
        if isinstance(n, (Ref, Name)):
            return resolve(n)
        if isinstance(n, Literal):
            if n.kind == "string":
                return "'" + str(n.value).replace("'", "''") + "'"
            if n.kind == "bool":
                return "TRUE" if n.value else "FALSE"
            if n.kind == "null":
                return "NULL"
            return repr(n.value) if isinstance(n.value, float) else str(n.value)
        if isinstance(n, Prompt):
            return prompt(n.name) if prompt else f"${n.name.upper()}"
        if isinstance(n, UnaryOp):
            if n.op == "not":
                return f"NOT ({r(n.operand)})"
            return f"-{r(n.operand, 9)}"
        if isinstance(n, BinOp):
            prec = {"or": 1, "and": 2, "=": 4, "<>": 4, "<": 4, ">": 4, "<=": 4, ">=": 4, "like": 4,
                    "+": 5, "-": 5, "||": 5, "*": 6, "/": 6}[n.op]
            op = n.op.upper() if n.op in ("and", "or", "like") else n.op
            s = f"{r(n.left, prec)} {op} {r(n.right, prec + 1)}"
            return f"({s})" if prec < parent_prec else s
        if isinstance(n, Func):
            if n.name in _FUNC_MAP and not n.args:
                return _FUNC_MAP[n.name]
            fname = _RENAME_FUNCS.get(n.name, n.name.upper())
            return f"{fname}({', '.join(r(a) for a in n.args)})"
        if isinstance(n, Extract):
            inner = r(n.expr)
            return f"EXTRACT({n.part.upper()} FROM {inner})"
        if isinstance(n, Case):
            if prefer_iff and n.subject is None and len(n.whens) == 1 and n.else_ is not None:
                c, v = n.whens[0]
                return f"IFF({r(c)}, {r(v)}, {r(n.else_)})"
            parts = ["CASE"]
            if n.subject is not None:
                parts.append(r(n.subject))
            for c, v in n.whens:
                parts.append(f"WHEN {r(c)} THEN {r(v)}")
            if n.else_ is not None:
                parts.append(f"ELSE {r(n.else_)}")
            parts.append("END")
            return " ".join(parts)
        if isinstance(n, InList):
            neg = "NOT " if n.negated else ""
            if n.subquery is not None:
                return f"{r(n.expr)} {neg}IN ({r(n.subquery)})"
            return f"{r(n.expr)} {neg}IN ({', '.join(r(i) for i in n.items)})"
        if isinstance(n, SubQuery):
            where = f" WHERE {r(n.where)}" if n.where is not None else ""
            return f"SELECT {', '.join(n.select)} FROM {'.'.join(n.table)}{where}"
        if isinstance(n, IsNull):
            return f"{r(n.expr)} IS {'NOT ' if n.negated else ''}NULL"
        if isinstance(n, Between):
            return f"{r(n.expr)} {'NOT ' if n.negated else ''}BETWEEN {r(n.low)} AND {r(n.high)}"
        raise ParseError(f"Cannot translate {type(n).__name__}")

    return r(node)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())
