from .ast import *
from .matcher import *
from ..tokenize import *

from re import compile as re_compile
from typing import Dict, List, NamedTuple, Optional, Set


__all__ = ['Parser', 'ParsedGrammar', 'RuleDict', 'TokenMatcherDict', 'StartSymbolSet']


RuleDict = Dict[str, Rule]
TokenMatcherDict = Dict[str, Matcher]
StartSymbolSet = Set[str]


ParsedGrammar = NamedTuple('ParsedGrammar', [('rules', RuleDict),
                                             ('token_matchers', TokenMatcherDict),
                                             ('start_symbols', StartSymbolSet)])


class EndOfRule(Exception):
    pass


class Parser:
    def __init__(self, tokens: List[Token]):
        # The parser ignores whitespace and comments.
        self.tokens = list(filter(lambda t: (t.type not in TokenTypeClasses.WHITESPACE and
                                             t.type not in TokenTypeClasses.COMMENTS),
                                  tokens))
        if not self.tokens:
            raise ValueError  # TODO
        self.index = 0
        self.rules: RuleDict = {}
        self.token_matchers: TokenMatcherDict = {}
        self.start_symbols: StartSymbolSet = set()
        self.SECTION_DISPATCH = {
            'rules':    self.parse_rules,
            'tokens':   self.parse_token_matchers,
            'start':    self.parse_start,
        }

    @property
    def token(self) -> Token:
        return self.tokens[self.index]

    @property
    def has_tokens(self) -> bool:
        return self.token.type not in TokenTypeClasses.EOF

    @property
    def next_token(self) -> Optional[Token]:
        if self.index + 1 >= len(self.tokens):
            return None
        return self.tokens[self.index + 1]

    def advance(self, increment: int = 1):
        self.index += increment

    def parse(self) -> ParsedGrammar:
        while self.has_tokens:
            if self.token.type not in TokenTypeClasses.SECTIONS:
                raise RuntimeError  # TODO
            raw_section = self.token.value
            section = raw_section[1:-1].strip().lower()
            self.advance()
            self.SECTION_DISPATCH[section]()
        # If there is no start symbol, use the first rule.
        if not self.start_symbols:
            self.start_symbols.add(next(iter(self.rules)))
        return ParsedGrammar(self.rules, self.token_matchers, self.start_symbols)

    def parse_rules(self):
        while (self.has_tokens and
               self.token.type not in TokenTypeClasses.SECTIONS):
            rule = self.parse_rule()
            if rule.name in self.rules:
                raise RuntimeError  # TODO
            self.rules[rule.name] = rule

    def parse_rule(self) -> Rule:
        if self.token.type not in TokenTypeClasses.LOW_CASES:
            raise RuntimeError  # TODO
        rule_name = self.token.value
        self.advance()
        productions = []
        while self.token.type in TokenTypeClasses.DIVIDERS:
            self.advance()
            production = self.parse_production()
            productions.append(production)
        if not productions:
            raise RuntimeError  # TODO
        return Rule(rule_name, productions)

    def parse_production(self) -> Production:
        if self.token.type in TokenTypeClasses.CAP_CASES:
            return self.parse_named_production()
        elif self.token.type in TokenTypeClasses.LOW_CASES:
            return self.parse_alias_production()
        else:
            raise RuntimeError  # TODO

    def parse_named_production(self) -> NamedProduction:
        name = self.token.value
        self.advance()
        parts = []
        # Keep parsing for parts until either we reach the end of the tokens or the lookahead token indicates we're done
        # with this production.
        while (self.has_tokens and
               self.token.type not in TokenTypeClasses.SECTIONS and
               self.token.type not in TokenTypeClasses.DIVIDERS and
               self.token.type not in TokenTypeClasses.OPERATORS):
            if self.next_token is not None and self.next_token.type is TokenTypes.SUBST:
                # If the next token is ::=, then this is the beginning of an entirely new rule.
                break
            part = self.parse_part()
            parts.append(part)
        if not parts:
            raise RuntimeError  # TODO
        return NamedProduction(name, parts)

    def parse_part(self) -> Part:
        if self.token.type in TokenTypeClasses.SEQUENCES:
            return self.parse_sequence()
        elif self.token.type in TokenTypeClasses.QUOTES:
            string = self.token.value
            self.advance()
            return Literal(string)
        elif self.token.type in TokenTypeClasses.LOW_CASES:
            # Snake-case words can mean any of:
            #  1. The beginning of a new rule, which shouldn't be consumed.
            #  2. The beginning of a named field match.
            #  3. A rule name match.
            if self.next_token is not None:
                if self.next_token.type is TokenTypes.SUBST:
                    # This is actually the beginning of a new rule instead of a part of this rule.
                    raise EndOfRule()
                elif self.next_token.type is TokenTypes.COLON:
                    # This is a named field match.
                    name = self.token.value
                    self.advance(2)
                    match = self.parse_part()
                    return PatternMatch(name, match)
            # Just a match against the named rule.
            name = self.token.value
            self.advance()
            return RuleMatch(name)
        elif self.token.type in TokenTypeClasses.CAP_CASES:
            string = self.token.value
            self.advance()
            return DeclaredToken(string)
        else:
            raise RuntimeError  # TODO

    def parse_sequence(self) -> Sequence:
        if self.token.type is TokenTypes.L_PAR:
            sequence_type = SequenceType.PLAIN
        elif self.token.type is TokenTypes.L_BRK:
            sequence_type = SequenceType.OPTIONAL
        elif self.token.type is TokenTypes.L_BRC:
            sequence_type = SequenceType.REPETITION
        elif self.token.type is TokenTypes.L_ABR:
            sequence_type = SequenceType.NONEMPTY_REPETITION
        else:
            raise RuntimeError  # TODO
        expected_end_token_type = BRACE_PAIRS[self.token.type]
        self.advance()
        parts = []
        alternates = []
        while self.token.type is not expected_end_token_type:
            if self.token.type is TokenTypes.STICK:
                alternates.append(parts)
                parts = []
                self.advance()
                continue
            try:
                part = self.parse_part()
            except EndOfRule:
                break
            parts.append(part)
        self.advance()
        if alternates and parts:
            alternates.append(parts)
            parts = []
        if parts:
            sequence = Sequence(sequence_type, parts)
        elif alternates:
            processed_alternates = []
            for alternate_parts in alternates:
                if len(alternate_parts) == 1:
                    processed_alternates.append(alternate_parts[0])
                else:
                    processed_alternates.append(Sequence(sequence_type, alternate_parts))
            sequence = Sequence(SequenceType.ALTERNATING, processed_alternates)
        else:
            sequence = Sequence(sequence_type, parts)
        if self.token.type is TokenTypes.SEQ_PARAM:
            self.advance()
            param = self.parse_sequence()
            return ParameterizedSequence(sequence, param)
        else:
            return sequence

    def parse_alias_production(self) -> AliasProduction:
        alias = self.token.value
        self.advance()
        return AliasProduction(alias)

    def parse_token_matchers(self):
        while (self.has_tokens and
               self.token.type not in TokenTypeClasses.SECTIONS):
            matcher = self.parse_token_matcher()
            if matcher.name in self.token_matchers:
                raise RuntimeError  # TODO
            self.token_matchers[matcher.name] = matcher

    def parse_token_matcher(self) -> Matcher:
        if self.token.type not in TokenTypeClasses.CAP_CASES:
            raise RuntimeError  # TODO
        name = self.token.value
        self.advance()
        if self.token.type is TokenTypes.EQUAL:
            self.advance()
            literal = self.token.value
            self.advance()
            return LiteralMatcher(name, literal)
        elif self.token.type is TokenTypes.RE_EQUAL:
            self.advance()
            pattern = re_compile(self.token.value)
            self.advance()
            return RegexMatcher(name, pattern)
        else:
            raise RuntimeError  # TODO

    def parse_start(self):
        while (self.has_tokens and
               self.token.type not in TokenTypeClasses.SECTIONS):
            if self.token.type not in TokenTypeClasses.LOW_CASES:
                raise RuntimeError  # TODO
            symbol = self.token.value
            if symbol in self.start_symbols:
                raise RuntimeError  # TODO
            self.start_symbols.add(symbol)
            self.advance()
