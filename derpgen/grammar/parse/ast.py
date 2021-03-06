from dataclasses import dataclass
from enum import Enum, auto, unique
from typing import List, Union


__all__ = ['SequenceType', 'AST', 'Sequence', 'ParameterizedSequence', 'Literal', 'DeclaredToken', 'PatternMatch',
           'RuleMatch', 'Part', 'NamedProduction', 'AliasProduction', 'Production', 'Rule']


@unique
class SequenceType(Enum):
    PLAIN               = auto()
    OPTIONAL            = auto()
    REPETITION          = auto()
    NONEMPTY_REPETITION = auto()
    ALTERNATING         = auto()


@dataclass
class AST:
    pass


@dataclass
class Sequence(AST):
    type: SequenceType
    asts: List[AST]


@dataclass
class ParameterizedSequence(AST):
    sequence: Sequence
    parameter: Sequence


@dataclass
class Literal(AST):
    string: str


@dataclass
class DeclaredToken(AST):
    token: str


@dataclass
class PatternMatch(AST):
    name: str
    match: AST


@dataclass
class RuleMatch(AST):
    rule: str


Part = Union[Sequence, ParameterizedSequence, Literal, PatternMatch, RuleMatch]


@dataclass
class NamedProduction(AST):
    name: str
    parts: List[Part]


@dataclass
class AliasProduction(AST):
    alias: str


Production = Union[NamedProduction, AliasProduction]


@dataclass
class Rule(AST):
    name: str
    productions: List[Production]
