# Solb Lexical Analyzer

A lexical analyzer (scanner) for **Solb**, a domain-specific language for secure
peer-to-peer trading, built as an improved version of Solidity. It reads a Solb
source file, splits it into tokens, reports lexical errors, and writes a symbol
table together with a character-by-character DFA trace.

## Requirements

- Python 3.7 or newer
- No third-party packages and no compile step

## Usage

```
python lexer.py program.solb
python lexer.py program_error_handling.solb
python lexer.py program_invalid.solb
```

On Windows you can use `py` instead of `python`.
Save the report under a different name with `-o`:

```
python lexer.py program.solb -o symbol_table.txt
```

The terminal shows the symbol table and any lexical errors. The full report,
including the DFA trace, is written to `symbol_table.txt`. The exit code is `0`
on success and `1` if any lexical errors were found.

## Output format

### Symbol table

Every token is listed in source order, one row per occurrence (repeats are not
merged):

```
Lexeme    | Token
----------+------------------
contract  | KEYWORD
Escrow    | IDENTIFIER
{         | LBRACE
```

### DFA trace

After the symbol table, `symbol_table.txt` lists every lexeme scanned one
character at a time:

```
SCAN | Line 3, Column 5 | Character: [u] | Class: ALPHA
DFA | Line 3, Column 5 | q1 --[u]--> q20
...
ACCEPT | [uint] | State: q23 | Token: DATA_TYPE
REJECT | [12abc] | State: q19 | No accepting token (malformed number)
```

- `SCAN` shows the character, its position and its character class.
- `DFA` shows the state transition taken for that character.
- `ACCEPT` gives the final accepting state and the token category.
- `REJECT` marks a lexeme that reached no accepting state, with the reason.
- Comments are traced too (`LINE_COMMENT`, `BLOCK_COMMENT`) but are not tokens
  and do not appear in the symbol table.

## Token categories

| Token | Examples |
| --- | --- |
| `KEYWORD` | `contract`, `def`, `if`, `else`, `for`, `while`, `return`, `require`, `emit`, `copy` |
| `DATA_TYPE` | `uint`, `uint256`, `int8`, `bool`, `address`, `string`, `asset`, `ledger`, `roster` |
| `ACCESS_SPECIFIER` | `public`, `private`, `internal`, `external` |
| `MUTABILITY` | `pure`, `view`, `payable` |
| `DATA_LOCATION` | `storage`, `memory`, `calldata` |
| `TRADINGFUNC` | `offer`, `accept`, `order`, `swap`, `batch`, `refund`, `timeout`, `cancel` |
| `CONTEXT_KEYWORD` | `partial`, `buy`, `gascontext`, `bytecodecontext` |
| `GLOBAL` | `msg`, `block`, `sender`, `value` |
| `BOOL_LITERAL` | `true`, `false` |
| `IDENTIFIER` | `price`, `serviceFee`, `offerA` |
| `INTEGER` | `42`, `10000` |
| `HEX_LITERAL` | `0x1F` |
| `DURATION` | `30s`, `5m`, `1d` |
| `ASSET_LITERAL` | `0.05 USDC`, `2261 USDC`, `100 wei` |
| `STRING_LITERAL` | `"Invalid amount"`, `'Invalid Amount'` |
| `ASSIGN_OP` | `=`, `+=`, `-=`, `*=`, `/=`, `%=`, `~=`, `&=`, `\|=`, `^=`, `<<=`, `>>=` |
| `ARITH_OP` | `+`, `-`, `*`, `/`, `%`, `**` |
| `UNARY_OP` | `++`, `--` |
| `LOGICAL_OP` | `!`, `&&`, `\|\|` |
| `BITWISE_OP` | `&`, `\|`, `^`, `~`, `<<`, `>>` |
| `RELATIONAL_OP` | `==`, `!=`, `<`, `>`, `<=`, `>=` |
| `ARROW` | `=>` |
| Delimiters | `;`, `,`, `.`, `:`, `(`, `)`, `{`, `}`, `[`, `]` |

Noise words are accepted in both forms and get the same token category:
`def`/`define`, `bool`/`boolean`, `construct`/`constructor`, `str`/`string`.

## Lexical errors

The lexer reports the error with its line and column, skips the bad text, and
keeps scanning so several errors can be found in one run.

| Error | Example |
| --- | --- |
| Identifier starting with an underscore | `_hidden` |
| Decimal without an asset symbol | `1.5` |
| Malformed number | `12abc` |
| Malformed hexadecimal literal | `0xZZ` |
| Unterminated string | `"never closed;` |
| Invalid escape sequence in a string | `"a\q"` |
| Unterminated multi-line comment | `/* never ends` |
| Invalid character | `@`, `#`, `$`, `'`, `?` |
