from .grammar import *
from .tree import *

from derpgen.utility.fixed_points import *
from derpgen.utility.lazy import *
from derpgen.utility.match import *
from derpgen.utility.memoize import *

from typing import Callable, List, TypeVar


__all__ = ['is_empty', 'is_nullable', 'parse_null', 'derive', 'make_compact', 'parse', 'parse_compact']


Value = TypeVar('Value')


is_empty: Callable[[Grammar], bool] = fix(lambda: False, EqType.Eq)(match({
    Nil: lambda _:          True,
    Eps: lambda _, ts:      False,
    Tok: lambda _, t:       False,
    Rep: lambda _, g:       False,
    Alt: lambda _, g1, g2:  is_empty(g1) and is_empty(g2),
    Seq: lambda _, g1, g2:  is_empty(g1) or is_empty(g2),
    Red: lambda _, g, f:    is_empty(g),
}, Grammar))


is_nullable: Callable[[Grammar], bool] = fix(lambda: True, EqType.Eq)(match({
    Nil: lambda _:          False,
    Eps: lambda _, ts:      True,
    Tok: lambda _, t:       False,
    Rep: lambda _, g:       is_nullable(g) or is_empty(g),
    Alt: lambda _, g1, g2:  is_nullable(g1) or is_nullable(g2),
    Seq: lambda _, g1, g2:  is_nullable(g1) and is_nullable(g2),
    Red: lambda _, g, f:    is_nullable(g),
}, Grammar))


parse_null: Callable[[Grammar], List[Tree[Value]]] = fix(list, EqType.Eq)(match({
    Nil: lambda _:          [],
    Eps: lambda _, ts:      ts,
    Tok: lambda _, t:       [],
    Rep: lambda _, g:       [Empty()],
    Alt: lambda _, g1, g2:  parse_null(g1) + parse_null(g2),
    Seq: lambda _, g1, g2:  [Branch(t1, t2) for t1 in parse_null(g1) for t2 in parse_null(g2)],
    Red: lambda _, g, f:    [f(t) for t in parse_null(g)],
}, Grammar))


def derive_seq(c: Value, g1: Grammar, g2: Grammar) -> Grammar:
    dcl_r = delay(lambda: seq(derive(g1, c), g2))
    if is_nullable(g1):
        return alt(force(dcl_r), seq(eps(parse_null(g1)), derive(g2, c)))
    else:
        return force(dcl_r)


derive: Callable[[Grammar, Value], Grammar] = memoize(EqType.Equal, EqType.Eq)(match({
    Nil: lambda _, c:          nil(),
    Eps: lambda _, c, ts:      nil(),
    Tok: lambda _, c, t:       eps([Leaf(c)]) if c == t else nil(),
    Rep: lambda g_, c, g:      seq(derive(g, c), g_),
    Alt: lambda _, c, g1, g2:  alt(derive(g1, c), derive(g2, c)),
    Seq: lambda _, c, g1, g2:  derive_seq(c, g1, g2),
    Red: lambda _, c, g, f:    red(derive(g, c), f),
}, Grammar, ('g_', 'c')))


nullp_t: Tree[Value]


def nullp(g: Grammar) -> bool:
    global nullp_t
    if is_nullable(g):
        ts = parse_null(g)
        if len(ts) == 1:
            nullp_t = ts[0]
            return True
    return False


make_compact: Callable[[Grammar], Grammar] = memoize(EqType.Eq)(match_pred({
    Nil: {lambda:           True:                               lambda g_:      g_},
    Eps: {lambda:           True:                               lambda g_:      g_},
    Tok: {lambda g_:        is_empty(g_):                       lambda:         nil(),
          lambda:           True:                               lambda g_:      g_},
    Rep: {lambda g:         is_empty(g):                        lambda:         eps([Empty()]),
          lambda:           True:                               lambda g:       Rep(make_compact(g))},
    Alt: {lambda g1:        is_empty(g1):                       lambda g2:      make_compact(g2),
          lambda g2:        is_empty(g2):                       lambda g1:      make_compact(g1),
          lambda:           True:                               lambda g1, g2:  alt(make_compact(g1),
                                                                                    make_compact(g2))},
    Seq: {lambda g1, g2:    is_empty(g1) or is_empty(g2):       lambda:         nil(),
          lambda g1:        nullp(g1):                          lambda g2:      red(make_compact(g2),
                                                                                    lambda w2: Branch(nullp_t, w2)),
          lambda g2:        nullp(g2):                          lambda g1:      red(make_compact(g1),
                                                                                    lambda w1: Branch(w1, nullp_t)),
          lambda:           True:                               lambda g1, g2:  seq(make_compact(g1),
                                                                                    make_compact(g2))},
    Red: {lambda g:         g.__class__ is Eps:                 lambda g, f:    eps([f(t) for t in g.ts]),
          lambda g:         g.__class__ is Seq and nullp(g.g1): lambda f, g:    red(make_compact(g.g2),
                                                                                    lambda t: f(Branch(nullp_t, t))),
          lambda g:         g.__class__ is Red:                 lambda g, f:    red(make_compact(g.g),
                                                                                    lambda t: g.f(t)),
          lambda:           True:                               lambda g, f:    red(make_compact(g), f)},
}, ('g_',)))


def parse(values: List[Value], g: Grammar) -> List[Tree[Value]]:
    if not values:
        return parse_null(g)
    else:
        c, *cs = values
        return parse(cs, derive(g, c))


def parse_compact(values: List[Value], g: Grammar) -> List[Tree[Value]]:
    if not values:
        return parse_null(g)
    else:
        c, *cs = values
        return parse_compact(cs, make_compact(derive(g, c)))
