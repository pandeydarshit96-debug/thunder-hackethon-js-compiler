# light weight thunder-hackethon-js-compiler
# Mini JS Compiler (V8-Inspired Interpreter)

A JavaScript interpreter written in Python that reads JS-style code from the terminal, compiles it, and produces output — similar to how a JS engine like V8 works, but built from scratch.

---

## Language Used

| Component | Technology |
|---|---|
| Implementation Language | Python 3 |
| Target Language | JavaScript (ES6+) |
| Input Mode | Interactive terminal / file pipe |
| Dependencies | None (only Python standard library) |

---

## How to Run

### Interactive Mode
```cmd
python hello.py
```
Type JS code line by line. Press **Ctrl+T** to execute.

### File Mode
```cmd
Get-Content yourfile.js | python hello.py
```

### Terminal Controls
| Key | Action |
|---|---|
| `Enter` | New line |
| `Ctrl+T` | Run buffer |
| `↑ / ↓` | History navigation |
| `← / →` | Cursor move |
| `Backspace / Delete` | Delete character |
| `Ctrl+C` | Exit |

---

## How It Works — JS to Python Pipeline

```
User types JS code
       ↓
  normalize_lines()        — splits "} else {" into separate lines
       ↓
  execute_block()          — main loop, reads line by line
       ↓
  pattern matching         — identifies: if/for/while/switch/function/etc.
       ↓
  evaluate() / execute_statement()
       ↓
  _find_last_method_call() — resolves method chains like arr.map(x => x*2)
  js_to_python()           — converts JS syntax → Python syntax
  substitute_variables()   — replaces variable names with their values
                             (skips inside string literals)
       ↓
  Python eval()            — evaluates the final expression
       ↓
  Output printed
```

---

## Core Components

### 1. `normalize_lines()`
Pre-processes raw JS lines before execution.
- Splits `} else {` into `}` and `else {` on separate lines
- Keeps `} while(...)` intact for do-while loops

### 2. `js_to_python()`
Converts JS syntax tokens to Python-compatible equivalents:

| JavaScript | Python |
|---|---|
| `===` | `==` |
| `!==` | `!=` |
| `&&` | `and` |
| `\|\|` | `or` |
| `true` | `True` |
| `false` | `False` |
| `null` | `None` |
| `undefined` | `None` |
| `.length` | `.__len__()` |

### 3. `substitute_variables()`
Before `eval()`, declared variable names are replaced with their current Python `repr()` values.
String literals are **protected** — substitution does not happen inside `"..."`, `'...'`, or backticks.
Complex objects like `Date` are kept as-is and resolved via direct variable lookup.

### 4. `_find_last_method_call()`
Scans right-to-left to find the outermost `.method(args)` call — correctly handles:
- `arr.map(x => x * 2)`
- `str.trim().toUpperCase()`
- `names.map(x => x.toUpperCase())`

### 5. `evaluate()`
The expression evaluator. Handles in order:
1. Template literals `` `Hello ${name}` ``
2. `new Date()`
3. Spread arrays `[...a, ...b]`
4. `typeof` operator
5. Ternary operator `cond ? a : b`
6. Method calls (before substitution to avoid corruption)
7. User-defined function calls
8. Property access `obj.prop`, `obj.prop.nested`
9. Bracket access `arr[i]`, `obj["key"]`
10. Final `eval()` with builtins injected

### 6. `execute_statement()`
Handles individual JS statements:
- Variable declarations: `let`, `var`, `const`
- Assignment: `x = val`, `x += val`, `x++`, `++x`
- Array/Object index assignment: `arr[i] = val`, `obj.key = val`
- Method calls as statements: `arr.push(x)`, `arr.sort()`
- `console.log()`
- `return`, `break`, `continue`

### 7. `execute_block()`
The main execution engine. Reads lines and dispatches to:

| Statement | Handler |
|---|---|
| `function foo() {}` | Stores in `functions` dict |
| `const f = () => {}` | Arrow function → `functions` dict |
| `switch / case / default` | `_execute_switch()` |
| `if / else if / else` | Conditional execution |
| `while` | Loop with condition re-evaluation |
| `do...while` | Execute-first loop |
| `for (init; cond; incr)` | Classic C-style for loop |
| `for...of` | Iterates array/string values |
| `for...in` | Iterates object keys |

---

## Supported JS Features

### Variables & Operators
- `let`, `var`, `const`
- Arithmetic: `+`, `-`, `*`, `/`, `%`
- Comparison: `==`, `!=`, `===`, `!==`, `<`, `>`, `<=`, `>=`
- Logical: `&&`, `||`, `!`
- Assignment: `=`, `+=`, `-=`, `*=`, `/=`, `%=`
- Increment/Decrement: `x++`, `x--`, `++x`, `--x`
- Ternary: `x > 0 ? "yes" : "no"`
- `typeof`
- Spread: `[...a, ...b]`

### Control Flow
- `if / else if / else`
- `switch / case / default / break`
- `for` (classic), `for...of`, `for...in`
- `while`, `do...while`
- `break`, `continue`

### Functions
- Named: `function add(a, b) { return a + b; }`
- Arrow: `const sq = (x) => x * x`
- Multi-line arrow: `const fn = (x) => { ... }`
- Recursive functions
- Return values

### Arrays
| Method | Description |
|---|---|
| `push(x)` | Add to end |
| `pop()` | Remove from end |
| `shift()` | Remove from start |
| `unshift(x)` | Add to start |
| `splice(i, n)` | Remove/insert elements |
| `slice(s, e)` | Return portion |
| `concat(arr)` | Merge arrays |
| `reverse()` | Reverse in place |
| `sort()` | Sort elements |
| `indexOf(x)` | Find index |
| `lastIndexOf(x)` | Last index of value |
| `includes(x)` | Check existence |
| `join(sep)` | Convert to string |
| `flat(depth)` | Flatten nested arrays |
| `fill(val, s, e)` | Fill with value |
| `at(-1)` | Negative index access |
| `map(x => ...)` | Transform each element |
| `filter(x => ...)` | Filter elements |
| `reduce((acc, x) => ..., init)` | Reduce to single value |
| `find(x => ...)` | Find first match |
| `findIndex(x => ...)` | Index of first match |
| `some(x => ...)` | Any element matches |
| `every(x => ...)` | All elements match |
| `forEach(x => ...)` | Iterate with callback |
| `Array.isArray(x)` | Type check |

### Objects
| Feature | Example |
|---|---|
| Dot access | `obj.name` |
| Bracket access | `obj["key"]` |
| Property set | `obj.key = val` |
| Nested access | `student.marks.math` |
| `for...in` | Iterate keys |
| `Object.keys(obj)` | Get keys array |
| `Object.values(obj)` | Get values array |
| `Object.entries(obj)` | Get key-value pairs |
| `Object.assign(target, src)` | Merge objects |
| `hasOwnProperty(k)` | Check key exists |

### String Methods
`toUpperCase`, `toLowerCase`, `trim`, `trimStart`, `trimEnd`,
`split`, `includes`, `startsWith`, `endsWith`, `indexOf`, `lastIndexOf`,
`slice`, `substring`, `substr`, `replace`, `replaceAll`, `repeat`,
`padStart`, `padEnd`, `charAt`, `charCodeAt`, `at`

### Template Literals
```js
let name = "Rahul";
console.log(`Hello ${name}, age ${20 + 1}`);
// Output: Hello Rahul, age 21
```

### Date Object
```js
let d = new Date();
console.log(d.getFullYear());
console.log(d.getMonth());
console.log(d.getDate());
console.log(d.getHours());
console.log(d.toString());
console.log(d.toISOString());
```

### Math Object
`Math.floor`, `Math.ceil`, `Math.round`, `Math.abs`, `Math.sqrt`,
`Math.pow`, `Math.max`, `Math.min`, `Math.PI`, `Math.E`,
`Math.log`, `Math.sin`, `Math.cos`, `Math.tan`, `Math.random`

### Type Conversion
```js
Number("42")      // 42
String(100)       // "100"
Boolean(0)        // false
Boolean("hello")  // true
parseInt("10px")  // 10
parseFloat("3.14")// 3.14
```

### Error Handling
Compiler detects and reports JS-style errors:

| Error | When |
|---|---|
| `ReferenceError` | Using undeclared variable |
| `TypeError` | Wrong type operation |
| `RangeError` | Division by zero |
| `SyntaxError` | Invalid syntax |
| `RuntimeError` | Unexpected runtime issue |

Output format:
```
<<error>>

ReferenceError: x is not defined
```

---

## Project Structure

```
second/
├── hello.py       ← The entire compiler/interpreter
└── README.md      ← This file
```

---

## Example

```js
let nums = [1, 2, 3, 4, 5];
let doubled = nums.map(x => x * 2);
let evens = nums.filter(x => x % 2 === 0);
let sum = nums.reduce((acc, x) => acc + x, 0);

console.log(doubled);
console.log(evens);
console.log(`Sum = ${sum}`);
```

**Output:**
```
<<output>>

[2, 4, 6, 8, 10]
[2, 4]
Sum = 15
```
METHODS OF JS WHICH CAN EASILY RUN AND UNDERSTAND BY THIS CODE
Variables let, var, const

Operators +, -, *, /, %, ++, --, +=, -=, *=, /=, %=, ===, !==, ==, !=, <, >, <=, >=, &&, ||, !

Control Flow if, else if, else, switch, case, default, break, continue

Loops for, while, do...while, for...of, for...in

Functions function, arrow functions =>, recursive functions, return

Array Methods push(), pop(), shift(), unshift(), splice(), slice(), concat(), reverse(), sort(), indexOf(), lastIndexOf(), includes(), join(), flat(), fill(), at(), map(), filter(), reduce(), find(), findIndex(), some(), every(), forEach(), Array.isArray()

String Methods toUpperCase(), toLowerCase(), trim(), trimStart(), trimEnd(), split(), includes(), startsWith(), endsWith(), indexOf(), lastIndexOf(), slice(), substring(), substr(), replace(), replaceAll(), repeat(), padStart(), padEnd(), charAt(), charCodeAt(), at(), .length

Object Methods Object.keys(), Object.values(), Object.entries(), Object.assign(), hasOwnProperty()

Math Object Math.floor(), Math.ceil(), Math.round(), Math.abs(), Math.sqrt(), Math.pow(), Math.max(), Math.min(), Math.random(), Math.log(), Math.sin(), Math.cos(), Math.tan(), Math.trunc(), Math.sign(), Math.PI, Math.E

Date Object new Date(), getFullYear(), getMonth(), getDate(), getDay(), getHours(), getMinutes(), getSeconds(), getTime(), toString(), toISOString(), toLocaleDateString()

Other Features typeof, ternary ? :, template literals ` `, spread operator ..., parseInt(), parseFloat(), isNaN(), isFinite(), Number(), String(), Boolean(), console.log()

Error Types ReferenceError, TypeError, RangeError, SyntaxError
