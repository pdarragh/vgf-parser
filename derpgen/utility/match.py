from .rename import RENAME_MARKER

from inspect import findsource, getframeinfo, getmodule, signature, stack, Traceback
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, TypeVar, Union


__all__ = ['match', 'match_pred']


Val = TypeVar('Val')


class MatchError(Exception):
    def __init__(self, mdfn: str, mdln: int, msg: str):
        super().__init__(f"Error in match defined in file {mdfn}, line {mdln}:\n{msg}")


class NoMatchError(MatchError):
    def __init__(self, mdfn: str, mdln: int, cls: Type):
        super().__init__(mdfn, mdln, f"No clause to match class {cls}.")


class MatchDefinitionError(MatchError):
    pass


class ClauseSignatureError(MatchDefinitionError):
    def __init__(self, mdfn: str, mdln: int, cls: Type, src_ln: int, extra_params: List[str],
                 missing_params: List[str]):
        msg = f"{cls.__name__} clause signature mismatch on line {src_ln}."
        if extra_params:
            msg += f"\n  Unexpected arguments: {', '.join(extra_params)}"
        if missing_params:
            msg += f"\n  Missing arguments: {', '.join(missing_params)}"
        super().__init__(mdfn, mdln, msg)


class NonExhaustiveMatchError(MatchDefinitionError):
    def __init__(self, mdfn: str, mdln: int, missing_types: Set[Type]):
        super().__init__(mdfn, mdln, f"Pattern list is not exhaustive. Missing clause(s) for the following class(es):\n"
                                     f"  Missing classes: {', '.join(map(lambda t: t.__name__, missing_types))}")


class InvalidClausePatternError(MatchDefinitionError):
    def __init__(self, mdfn: str, mdln: int, base: Type, invalid_class: Type):
        super().__init__(mdfn, mdln, f"Class {invalid_class} is not a subclass of pattern-matched base class {base}.")


class DuplicatedNamesError(MatchDefinitionError):
    def __init__(self, mdfn: str, mdln: int, names: List[str]):
        super().__init__(mdfn, mdln,
                         f"Given parameters list which overlaps with at least one match clause's arguments:\n"
                         f"  Duplicated names: {', '.join(names)}")


def get_param_names(func: Callable) -> Tuple[str]:
    if not callable(func):
        return tuple()
    sig = signature(func)
    return tuple(sig.parameters.keys())


class ParamGetFunc(Callable[[Tuple[Any], Any], Any]):
    def __init__(self, pos: int):
        self.pos = pos

    def __call__(self, ps, x):
        return ps[self.pos]

    def __repr__(self) -> str:
        return f"<function match.ParamGetFunc<{self.pos}> at {id(self)}>"


class AttrGetFunc(Callable[[Tuple[Any], Any], Any]):
    def __init__(self, attr: str):
        self.attr = attr

    def __call__(self, ps, x):
        return getattr(x, self.attr)

    def __repr__(self) -> str:
        return f"<function match.AttrGetFunc<{self.attr}> at {id(self)}>"


def match(table: Dict[Type, Callable[..., Val]], base: Optional[Type] = None, params: Optional[Tuple[str, ...]] = None,
          pos: int = 0, exhaustive: bool = True, omit: Optional[Set[Type]] = None, omit_recursive: bool = False,
          same_module_only: bool = True, fully_destructure: bool = True, indexed_params: bool = True,
          before_match_callback: Optional[Callable[..., Any]] = None) -> Callable[..., Val]:
    """
    Returns a function which will perform "pattern matching" on an input to perform dispatch based on that input's type.
    At module-load time, top-level calls to `match` will also perform some checks on the pattern table to ensure some
    conditions are met.

    This function is intended for use at the top level. Multiple checks are performed when the calling module is loaded
    instead of at regular runtime, which should yield improved performance. This function is not a decorator. To use it,
    do, e.g.:

        match_func = match({
            ClassB1: lambda _: True,
            ClassB2: lambda _: False,
        }, ClassA)

    :param table: the pattern table, mapping types to functions which will be executed when a value of the associated
                  type is passed in
    :param base: the base type which other types must subclass; can be left as None to skip membership checks
    :param params: the list of parameters the function expects, allowing additional parameters to be passed to the
                   matching functions at dispatch time; by default, this becomes a single variable which is passed to
                   all matched functions
    :param pos: the position of the matching object in the list of parameters; defaults to 0
    :param exhaustive: whether to guarantee exhaustiveness at module-load time; defaults to True
    :param omit: a set of classes to omit during exhaustiveness checking, which is useful if you have special classes
                 which are abstract-like that you don't ever want to match over; defaults to None
    :param omit_recursive: when omitting classes, also omit any subclasses of omitted classes; defaults to False
    :param same_module_only: only perform exhaustiveness checking over subclasses of `base` defined in the same module
                             in which `base` was defined; defaults to True
    :param fully_destructure: whether to require match clause functions to provide arguments for all the parts of each
                              matching class; defaults to True, meaning match clause functions must provide sufficient
                              arguments for full destructuring of matched instances
    :param indexed_params: whether the parameters to the match clause functions are indexed; defaults to True; a False
                           value will cause the matches to be done by name, requiring exact name matches in the classes
    :param before_match_callback: a function to execute prior to executing a match, which accepts the match function and
                                  all current parameters as arguments; can be left None to do nothing
    :return: a function which will perform the desired pattern matching
    """
    _frame = stack()[1][0]
    _caller: Traceback = getframeinfo(_frame)
    _mdfn = _caller.filename    # MDFN = Match Definition File Name.
    _mdln = _caller.lineno      # MDLN = Match Definition Line Number.
    _mdm = getmodule(_frame)    # MDM  = Match Definition Module.
    _mdmn = _mdm.__name__       # MDMN = Match Definition Module Name.

    if params is None:
        params = ('_match_obj',)
    if omit is None:
        omit = set()
    if base is None and exhaustive:
        raise MatchDefinitionError(_mdfn, _mdln, "Cannot perform exhaustive match without a given base class.")

    funcs: Dict[Type, Tuple[Callable[..., Val], Dict[str, Callable[[List[Any], Any], Any]]]] = {}
    subclasses: Dict[Type, bool] = {}  # The boolean is used for determining exhaustiveness.

    def get_all_subclasses(cls: Type):
        for subclass in cls.__subclasses__():
            if subclass not in omit:
                subclasses[subclass] = False
            if not omit_recursive:
                get_all_subclasses(subclass)

    if base is not None:
        get_all_subclasses(base)

    # Pre-process the pattern table to perform checks and prepare dispatch.
    for t, f in table.items():
        # If needed, perform membership checks.
        if base is not None:
            if t not in subclasses:
                raise InvalidClausePatternError(_mdfn, _mdln, base, t)
            subclasses[t] = True
        # Analyze the annotations of the given class. These, together with the `params`, will tell us how many arguments
        # the match clause function should have.
        func_params = list(params)
        if fully_destructure:
            annotations: Dict[str, Any] = t.__dict__.get('__annotations__', {})
            func_params.extend(annotations.keys())
        else:
            annotations = {}
        # Ensure uniqueness of names between function parameters and match clause lambda parameters.
        duped_names = {name for name in params if name in annotations}
        if duped_names:
            raise DuplicatedNamesError(_mdfn, _mdln, list(duped_names))
        # Analyze the signature of the given match clause function.
        sig_params = signature(f).parameters.keys()
        if len(sig_params) != len(func_params):
            extra_params = [param for param in sig_params if param not in func_params]
            missing_params = [param for param in func_params if param not in sig_params]
            # Remove arguments that would have been supplied but whose names didn't match.
            min_len = min(len(extra_params), len(missing_params))
            extra_params = extra_params[min_len:]
            missing_params = missing_params[min_len:]
            # Find the source line number of the offending clause.
            _, src_ln = findsource(f)
            src_ln += 1  # Line numbers from `findsource` are 0-indexed.
            raise ClauseSignatureError(_mdfn, _mdln, t, src_ln, extra_params, missing_params)
        # Build getter-function for each parameter.
        getters: Dict[str, Callable[[List[Any], Any], Any]] = {}
        indexed_annotations: Dict[int, str] = {i: name for i, name in enumerate(annotations.keys())}
        for i, name in enumerate(sig_params):
            if i < len(params):
                getters[name] = ParamGetFunc(i)
            else:
                param = name
                if indexed_params:
                    name = indexed_annotations[i - len(params)]
                getters[param] = AttrGetFunc(name)
        funcs[t] = (f, getters)

    # Check for exhaustive patterns if necessary.
    if exhaustive:
        missing_subclasses: Set[Type] = {cls for cls in subclasses if not subclasses[cls]}
        if same_module_only:
            missing_subclasses = {cls for cls in missing_subclasses if cls.__module__ == base.__module__}
        if missing_subclasses:
            raise NonExhaustiveMatchError(_mdfn, _mdln, missing_subclasses)

    # Define the actual match function.
    def do_match(*args: Any) -> Val:
        # Give the ability to perform an action prior to matching.
        if before_match_callback is not None:
            before_match_callback(do_match, *args)
        # Perform matching.
        x = args[pos]
        cls = x.__class__
        fgs = funcs.get(cls)
        if fgs is None:
            raise NoMatchError(_mdfn, _mdln, cls)
        func, gs = fgs
        call_params: Dict[str, Any] = {}
        for name in gs:
            try:
                val = gs[name](args, x)
            except Exception:
                raise MatchError(_mdfn, _mdln, f"Could not obtain param by name: {cls.__name__}.{name}")
            call_params[name] = val
        return func(**call_params)

    # Mark function for renaming and fix the module assignment.
    setattr(do_match, RENAME_MARKER, True)
    do_match.__module__ = _mdmn

    # Return the match function.
    return do_match


# TODO: Update `match_pred` to work like `match` does now.
def match_pred(table: Dict[Type, Dict[Callable[..., bool], Union[Val, Callable[..., Val]]]],
               params: Optional[Tuple[str, ...]] = None, pos: int = 0) -> Callable[..., Val]:
    if params is None:
        params = ()

    names = {t: {p: get_param_names(v) for p, v in table[t].items()} for t in table}
    pred_names = {t: {p: get_param_names(p) for p in table[t]} for t in table}

    def do_pred_match(*args: Any):
        x = args[pos]
        cls = x.__class__
        preds = table[cls]
        for pred, v in preds.items():
            param_args = {param: args[i] for (i, param) in enumerate(params)}
            pred_args = (param_args[name] if name in param_args else getattr(x, name) for name in pred_names[cls][pred])
            if not pred(*pred_args):
                continue
            if callable(v):
                call_args = (param_args[name] if name in param_args else getattr(x, name) for name in names[cls][pred])
                return v(*call_args)
            else:
                return v

    return do_pred_match
