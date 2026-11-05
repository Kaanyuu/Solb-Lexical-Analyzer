"""
Solb lexical analyzer.

Usage:
    python lexer.py program.solb
    python lexer.py program.solb -o my_symbol_table.txt

Prints the symbol table (Lexeme | Token) and any lexical errors to the terminal.
Saves the symbol table and the character-by-character DFA transitions to
symbol_table.txt. Exits with status 1 if any lexical errors were found.
"""

import argparse
import bisect
import os
import sys
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Language definition
# --------------------------------------------------------------------------

KEYWORDS = {}


def _add(token_type, words):
    for w in words.split():
        KEYWORDS[w] = token_type


_add("DATA_TYPE",
     "uint uint8 uint16 uint32 uint64 uint128 uint256 "
     "int int8 int16 int32 int64 int128 int256 "
     "bool boolean address string str bytes asset enum struct "
     "mapping ledger roster")

_add("KEYWORD",
     "contract constructor construct def define if else for while return "
     "import new event error emit require void copy")

_add("ACCESS_SPECIFIER",
     "external internal private public")

_add("MUTABILITY", 
     "pure view payable")

_add("DATA_LOCATION", 
     "storage memory calldata")

_add("BUILTIN", 
     "offer accept order swap batch refund timeout cancel")

_add("CONTEXT_KEYWORD", 
     "partial buy gascontext bytecodecontext")

_add("GLOBAL", 
     "msg block sender value")

_add("BOOL_LITERAL", 
     "true false")


# Longest match first: 2-char operators, then 1-char operators.
OPS2 = {
    "+=": "ASSIGN_OP", "-=": "ASSIGN_OP", "*=": "ASSIGN_OP", "/=": "ASSIGN_OP",
    "%=": "ASSIGN_OP", "~=": "ASSIGN_OP", "&=": "ASSIGN_OP", "|=": "ASSIGN_OP",
    "^=": "ASSIGN_OP",
    "++": "UNARY_OP", "--": "UNARY_OP",
    "**": "ARITH_OP",
    "&&": "LOGICAL_OP", "||": "LOGICAL_OP",
    "==": "RELATIONAL_OP", "!=": "RELATIONAL_OP",
    "<=": "RELATIONAL_OP", ">=": "RELATIONAL_OP",
    "=>": "ARROW",
}

OPS1 = {
    "=": "ASSIGN_OP",
    "+": "ARITH_OP", "-": "ARITH_OP", "*": "ARITH_OP", "/": "ARITH_OP",
    "%": "ARITH_OP",
    "!": "LOGICAL_OP",
    "&": "BITWISE_OP", "|": "BITWISE_OP", "^": "BITWISE_OP", "~": "BITWISE_OP",
    "<": "RELATIONAL_OP", ">": "RELATIONAL_OP",
    ";": "SEMICOLON", ",": "COMMA", ".": "DOT", ":": "COLON",
    "(": "LPAREN", ")": "RPAREN",
    "{": "LBRACE", "}": "RBRACE",
    "[": "LBRACKET", "]": "RBRACKET",
}

ALPHA = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
DIGITS = set("0123456789")
HEXDIGITS = DIGITS | set("abcdefABCDEF")
WHITESPACE = set(" \t\r\n\f\v")


@dataclass
class Token:
    type: str
    lexeme: str
    line: int
    col: int


@dataclass
class LexError:
    lexeme: str
    line: int
    col: int
    message: str



# --------------------------------------------------------------------------
# DFA states
# --------------------------------------------------------------------------
# Fixed states for the hand-built machines. The keyword and operator machines
# are tries: every prefix of a keyword/operator gets its own state, numbered
# from FIRST_TRIE_STATE upward in the order the words appear in the tables.
START = 1
ID = 2
INT = 3
DEC_DOT = 4
DEC = 5
HEX_X = 6
HEX = 7
DUR = 8
ASSET_SP = 9
ASSET_SYM = 10
STR = 11
STR_ESC = 12
STR_END = 13
LC = 14
BC = 15
BC_STAR = 16
BC_END = 17
UNDERSCORE_ST = 18
ERR = 19
FIRST_TRIE_STATE = 20

TRANSITION = {}   # (state, char) -> state, for the keyword + operator tries


def _build_tries():
    nxt = FIRST_TRIE_STATE
    words = list(KEYWORDS) + list(OPS2) + list(OPS1)
    for w in words:
        state = START
        for ch in w:
            if (state, ch) not in TRANSITION:
                TRANSITION[(state, ch)] = nxt
                nxt += 1
            state = TRANSITION[(state, ch)]


_build_tries()

# --------------------------------------------------------------------------
# Scanner
# --------------------------------------------------------------------------

def tokenize(src):
    """Return (tokens, errors) for the source text."""
    tokens, errors, segs = [], [], []
    n = len(src)

    # Precompute line starts so any offset can be turned into line/column.
    line_starts = [0] + [i + 1 for i, ch in enumerate(src) if ch == "\n"]

    def lc(i):
        ln = bisect.bisect_right(line_starts, i) - 1
        return ln + 1, i - line_starts[ln] + 1

    def emit(tok_type, start, end, kind):
        ln, col = lc(start)
        tokens.append(Token(tok_type, src[start:end], ln, col))
        segs.append((kind, start, end, tok_type, None))

    def error(start, end, message, kind, trace_end=None):
        ln, col = lc(start)
        errors.append(LexError(src[start:end], ln, col, message))
        segs.append((kind, start, trace_end or end, None, message))

    def is_word_char(ch):
        return ch in ALPHA or ch in DIGITS or ch == "_"

    def boundary(k):
        """True if position k is not the middle of a word."""
        return k >= n or not is_word_char(src[k])

    def word_end(k):
        while k < n and is_word_char(src[k]):
            k += 1
        return k

    i = 0
    while i < n:
        c = src[i]

        # ---- whitespace -------------------------------------------------
        if c in WHITESPACE:
            i += 1
            continue

        # ---- comments ---------------------------------------------------
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            segs.append(("comment", i, j, "LINE_COMMENT", None))
            i = j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j == -1:
                error(i, min(i + 2, n), "unterminated multi-line comment",
                      "comment", trace_end=n)
                i = n
            else:
                segs.append(("comment", i, j + 2, "BLOCK_COMMENT", None))
                i = j + 2
            continue

        # ---- identifiers / keywords -------------------------------------
        if c in ALPHA:
            j = word_end(i)
            word = src[i:j]
            emit(KEYWORDS.get(word, "IDENTIFIER"), i, j, "word")
            i = j
            continue

        # Identifiers must start with a letter
        if c == "_":
            j = word_end(i)
            error(i, j, "identifier cannot start with an underscore", "underscore")
            i = j
            continue

        # ---- numbers ----------------------------------------------------
        if c in DIGITS:
            # Hex literal: 0x HexDigits+
            if c == "0" and i + 1 < n and src[i + 1] == "x":
                j = i + 2
                while j < n and src[j] in HEXDIGITS:
                    j += 1
                if j == i + 2 or not boundary(j):
                    j = word_end(i)
                    error(i, j, "malformed hexadecimal literal", "number")
                else:
                    emit("HEX_LITERAL", i, j, "number")
                i = j
                continue

            j = i
            while j < n and src[j] in DIGITS:
                j += 1
            is_decimal = False
            if j + 1 < n and src[j] == "." and src[j + 1] in DIGITS:
                is_decimal = True
                j += 1
                while j < n and src[j] in DIGITS:
                    j += 1

            # Duration: Integer followed directly by s | m | h | d
            if not is_decimal and j < n and src[j] in "smhd" and boundary(j + 1):
                emit("DURATION", i, j + 1, "number")
                i = j + 1
                continue

            # AssetLiteral: (Integer | Decimal) AssetSymbol, same line,
            # separated by spaces/tabs (e.g. "0.05 USDC"); symbol is letters
            # only and not a reserved word.
            k = j
            while k < n and src[k] in " \t":
                k += 1
            m = k
            while m < n and src[m] in ALPHA:
                m += 1
            if k > j and m > k and boundary(m) and src[k:m] not in KEYWORDS:
                emit("ASSET_LITERAL", i, m, "number")
                i = m
                continue

            if is_decimal:
                error(i, j, "decimal literal is only allowed with an asset "
                            "symbol (e.g. 0.05 ETH)", "number")
                i = j
            elif j < n and is_word_char(src[j]):
                j = word_end(i)
                error(i, j, "malformed number", "number")
                i = j
            else:
                emit("INTEGER", i, j, "number")
                i = j
            continue

        # ---- string literal (double or single quoted) ---------------------
        if c == '"' or c == "'":
            q = c                      # the quote that opened this string
            j = i + 1
            bad_escape = None
            closed = False
            while j < n and src[j] != "\n":
                if src[j] == q:
                    closed = True
                    break
                if src[j] == "\\":
                    nxt = src[j + 1] if j + 1 < n else ""
                    if nxt not in (q, "\\", "n"):
                        bad_escape = j
                    j += 2
                else:
                    j += 1
            j = min(j, n)
            if not closed:
                error(i, j, "unterminated string literal", "string")
                i = j
            elif bad_escape is not None:
                error(i, j + 1, f"invalid escape sequence in string "
                                f"(allowed: \\{q} \\\\ \\n)", "string")
                i = j + 1
            else:
                emit("STRING_LITERAL", i, j + 1, "string")
                i = j + 1
            continue

        # ---- operators and delimiters (longest match) ---------------------
        two = src[i:i + 2]
        if two in OPS2:
            emit(OPS2[two], i, i + 2, "op")
            i += 2
        elif c in OPS1:
            emit(OPS1[c], i, i + 1, "op")
            i += 1
        else:
            error(i, i + 1, "invalid character", "invalid")
            i += 1

    return tokens, errors, segs, lc


# --------------------------------------------------------------------------
# DFA trace (character-by-character scan and transitions)
# --------------------------------------------------------------------------

def _num_step(state, ch, prefix):
    if state == START and ch in DIGITS:
        return INT
    if state == INT:
        if ch in DIGITS:
            return INT
        if ch == ".":
            return DEC_DOT
        if ch == "x" and prefix == "0":
            return HEX_X
        if ch in "smhd":
            return DUR
        if ch in " \t":
            return ASSET_SP
    if state == DEC_DOT and ch in DIGITS:
        return DEC
    if state == DEC:
        if ch in DIGITS:
            return DEC
        if ch in " \t":
            return ASSET_SP
    if state in (HEX_X, HEX) and ch in HEXDIGITS:
        return HEX
    if state == ASSET_SP:
        if ch in " \t":
            return ASSET_SP
        if ch in ALPHA:
            return ASSET_SYM
    if state == ASSET_SYM and ch in ALPHA:
        return ASSET_SYM
    return ERR


def _str_step(state, ch, prefix):
    q = prefix[:1] or ch               # opening quote: " or '
    if state == START and ch in ('"', "'"):
        return STR
    if state == STR:
        if ch == "\\":
            return STR_ESC
        return STR_END if ch == q else STR
    if state == STR_ESC and ch in (q, "\\", "n"):
        return STR
    return ERR


def _comment_step(state, ch):
    slash = TRANSITION[(START, "/")]
    if state == START and ch == "/":
        return slash
    if state == slash:
        return LC if ch == "/" else BC if ch == "*" else ERR
    if state == LC:
        return LC
    if state == BC:
        return BC_STAR if ch == "*" else BC
    if state == BC_STAR:
        return BC_END if ch == "/" else BC_STAR if ch == "*" else BC
    return ERR


def _step(kind, state, ch, prefix):
    if state == ERR:
        return ERR
    if kind == "word":
        if state != ID and (state, ch) in TRANSITION:
            return TRANSITION[(state, ch)]
        return ID
    if kind == "op":
        return TRANSITION.get((state, ch), ERR)
    if kind == "number":
        return _num_step(state, ch, prefix)
    if kind == "string":
        return _str_step(state, ch, prefix)
    if kind == "comment":
        return _comment_step(state, ch)
    if kind == "underscore":
        return UNDERSCORE_ST if (state == START and ch == "_") or \
            (state == UNDERSCORE_ST and (ch in ALPHA or ch in DIGITS or ch == "_")) \
            else ERR
    return ERR  # "invalid"


def _char_class(ch):
    if ch in ALPHA:
        return "ALPHA"
    if ch in DIGITS:
        return "DIGIT"
    if ch == "_":
        return "UNDERSCORE"
    if ch in " \t":
        return "SPACE"
    if ch in "\r\n":
        return "NEWLINE"
    if ch in ('"', "'"):
        return "QUOTE"
    if ch == "\\":
        return "BACKSLASH"
    if ch in ";,.:(){}[]":
        return "DELIMITER"
    if ch in OPS1:
        return "OPERATOR"
    return "INVALID"


def _show(text, limit=60):
    text = text.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return text if len(text) <= limit else text[:limit] + "..."


def build_trace(src, segs, lc):
    """Character-by-character SCAN / DFA lines for every lexeme."""
    out = []
    for kind, start, end, tok_type, msg in segs:
        state = START
        for idx in range(start, end):
            ch = src[idx]
            nxt = _step(kind, state, ch, src[start:idx])
            if kind == "comment" and idx - start < 2 and nxt != ERR:
                cls = "COMMENT_MARKER"
            elif kind == "comment" and nxt != ERR:
                cls = "COMMENT"
            else:
                cls = _char_class(ch)
            ln, col = lc(idx)
            shown = _show(ch)
            out.append(f"SCAN | Line {ln}, Column {col} | Character: "
                       f"[{shown}] | Class: {cls}")
            out.append(f"DFA | Line {ln}, Column {col} | "
                       f"q{state} --[{shown}]--> q{nxt}")
            state = nxt
        lexeme = _show(src[start:end])
        if msg is None:
            out.append(f"ACCEPT | [{lexeme}] | State: q{state} | "
                       f"Token: {tok_type}")
        else:
            out.append(f"REJECT | [{lexeme}] | State: q{state} | "
                       f"No accepting token ({msg})")
    return out


# --------------------------------------------------------------------------
# Symbol table insertions and rendering
# --------------------------------------------------------------------------

def build_symbol_table(tokens):
    """Unique (lexeme, token) rows in order of first appearance."""
    seen = {}
    for t in tokens:
        seen.setdefault((t.lexeme, t.type), None)
    return list(seen)


def render_symbol_table(tokens):
    # Every occurrence is listed, in source order.
    rows = [(t.lexeme, t.type) for t in tokens]
    width = max([len("Lexeme")] + [len(lex) for lex, _ in rows])
    out = [f"{'Lexeme':<{width}} | Token",
           f"{'-' * width}-+-{'-' * 18}"]
    out += [f"{lex:<{width}} | {tok}" for lex, tok in rows]
    return out, len(rows)


def main():
    ap = argparse.ArgumentParser(description="Solb lexical analyzer")
    ap.add_argument("source", help="Solb source file (.solb)")
    ap.add_argument("-o", "--output", default="SYMBOL TABLE.txt",
                    help="where to save the report (default: SYMBOL TABLE.txt)")
    args = ap.parse_args()

    if not args.source.lower().endswith(".solb"):
        print("Warning: input does not use the .solb extension.",
              file=sys.stderr)
    if not os.path.isfile(args.source):
        print(f"Cannot open input file '{args.source}'.", file=sys.stderr)
        return 1

    with open(args.source, encoding="utf-8") as f:
        src = f.read()

    tokens, errors, segs, lc = tokenize(src)
    table, unique = render_symbol_table(tokens)

    # Output Terminal - symbol table + errors.
    print("\n".join(table))
    if errors:
        print("\nLEXICAL ERRORS")
        for e in errors:
            print(f"Line {e.line}, Column {e.col}: {e.message} -> [{e.lexeme}]")

    # File - symbol table, then the DFA trace.
    lines = table + [
        "",
        "CHARACTER-BY-CHARACTER SCAN AND DFA TRANSITIONS",
        "ACCEPT rows show the final accepting state and token category.",
        "REJECT rows show lexemes that reached no accepting token state.",
    ] + build_trace(src, segs, lc)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n{len(tokens)} token(s), {len(errors)} error(s).")
    if errors:
        print(f"Lexical analysis completed with {len(errors)} error(s). "
              f"See {args.output}.", file=sys.stderr)
        return 1
    print(f"Lexical analysis completed successfully. "
          f"Symbol table written to {args.output}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())