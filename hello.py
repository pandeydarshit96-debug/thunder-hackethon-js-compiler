import os
import re
import sys

# ── Global state ──────────────────────────────────────────────────────────────
variables = {}        # global variables
functions = {}        # user-defined functions: name -> {params, body_lines}
output_header_printed = False

# Special signals for break/continue/return
class _Break(Exception):    pass
class _Continue(Exception): pass
class _Return(Exception):
    def __init__(self, value): self.value = value

# ── JS-style errors ───────────────────────────────────────────────────────────
class JSError(Exception):
    def __init__(self, error_type, message):
        self.error_type = error_type
        self.message = message
        super().__init__(f"{error_type}: {message}")

def print_js_error(error_type, message):
    print(f"\n<<error>>\n\n{error_type}: {message}\n")

# ── Value formatting ──────────────────────────────────────────────────────────
def _fmt(v):
    if isinstance(v, bool):  return "true" if v else "false"
    if v is None:            return "null"
    if isinstance(v, float) and v == int(v): return str(int(v))
    if isinstance(v, list):  return "[" + ", ".join(_fmt(x) for x in v) + "]"
    if isinstance(v, dict):
        pairs = ", ".join(f"{k}: {_fmt(val)}" for k, val in v.items())
        return "{" + pairs + "}"
    return str(v)

def _fmt_log(v):
    if isinstance(v, list):  return "[" + ", ".join(_fmt(x) for x in v) + "]"
    if isinstance(v, dict):
        pairs = ", ".join(f"{k}: {_fmt(val)}" for k, val in v.items())
        return "{" + pairs + "}"
    if isinstance(v, bool):  return "true" if v else "false"
    if v is None:            return "null"
    if isinstance(v, float) and v == int(v): return str(int(v))
    return str(v)

# ── Math / Array / Object builtins ───────────────────────────────────────────
import math as _math_mod
import random as _random_mod
import datetime as _datetime_mod

class _Math:
    floor  = staticmethod(lambda x: int(_math_mod.floor(x)))
    ceil   = staticmethod(lambda x: int(_math_mod.ceil(x)))
    round  = staticmethod(round)
    abs    = staticmethod(abs)
    sqrt   = staticmethod(_math_mod.sqrt)
    pow    = staticmethod(pow)
    max    = staticmethod(lambda *a: max(a) if len(a) > 1 else max(a[0]))
    min    = staticmethod(lambda *a: min(a) if len(a) > 1 else min(a[0]))
    PI     = _math_mod.pi
    E      = _math_mod.e
    log    = staticmethod(_math_mod.log)
    log2   = staticmethod(_math_mod.log2)
    log10  = staticmethod(_math_mod.log10)
    sin    = staticmethod(_math_mod.sin)
    cos    = staticmethod(_math_mod.cos)
    tan    = staticmethod(_math_mod.tan)
    trunc  = staticmethod(int)
    sign   = staticmethod(lambda x: (1 if x > 0 else -1) if x != 0 else 0)
    random = staticmethod(_random_mod.random)

class _JSDate:
    """Minimal JS Date object."""
    def __init__(self, *args):
        if not args:
            self._dt = _datetime_mod.datetime.now()
        elif len(args) == 1 and isinstance(args[0], str):
            try: self._dt = _datetime_mod.datetime.fromisoformat(args[0])
            except: self._dt = _datetime_mod.datetime.now()
        else:
            self._dt = _datetime_mod.datetime.now()
    def getFullYear(self):   return self._dt.year
    def getMonth(self):      return self._dt.month - 1   # JS months 0-indexed
    def getDate(self):       return self._dt.day
    def getDay(self):        return self._dt.weekday()
    def getHours(self):      return self._dt.hour
    def getMinutes(self):    return self._dt.minute
    def getSeconds(self):    return self._dt.second
    def getMilliseconds(self): return self._dt.microsecond // 1000
    def getTime(self):       return int(self._dt.timestamp() * 1000)
    def toISOString(self):   return self._dt.isoformat()
    def toString(self):      return self._dt.strftime("%a %b %d %Y %H:%M:%S")
    def toLocaleDateString(self): return self._dt.strftime("%d/%m/%Y")
    def toLocaleTimeString(self): return self._dt.strftime("%H:%M:%S")
    def __repr__(self):      return f"Date({self.toString()})"
    def __str__(self):       return self.toString()

class _JSArray:
    isArray = staticmethod(lambda x: isinstance(x, list))
    from_   = staticmethod(lambda x: list(x) if hasattr(x, '__iter__') and not isinstance(x, str) else list(str(x)))
    of      = staticmethod(lambda *a: list(a))

class _JSObject:
    keys    = staticmethod(lambda o: list(o.keys()) if isinstance(o, dict) else [])
    values  = staticmethod(lambda o: list(o.values()) if isinstance(o, dict) else [])
    entries = staticmethod(lambda o: [[k, v] for k, v in o.items()] if isinstance(o, dict) else [])
    assign  = staticmethod(lambda t, *s: (t.update(x) for x in s) and t or t)

_BUILTINS = {
    "Math": _Math, "Array": _JSArray, "Object": _JSObject,
    "parseInt":   lambda x, *a: int(float(str(x).strip())),
    "parseFloat": lambda x: float(str(x).strip()),
    "isNaN":      lambda x: x != x,
    "isFinite":   lambda x: abs(x) != float("inf"),
    "String":     str, "Number": float, "Boolean": bool,
    "abs": abs, "round": round, "len": len,
    "NaN": float("nan"), "Infinity": float("inf"),
    "True": True, "False": False, "None": None,
    "Date": _JSDate,
}

# ── Template literal processor ────────────────────────────────────────────────
def process_template_literal(s):
    """Convert `Hello ${expr} world` to evaluated string."""
    result = []
    i = 0
    while i < len(s):
        if s[i] == '$' and i + 1 < len(s) and s[i+1] == '{':
            # find matching }
            depth, j = 1, i + 2
            while j < len(s) and depth > 0:
                if s[j] == '{': depth += 1
                elif s[j] == '}': depth -= 1
                j += 1
            inner = s[i+2:j-1]
            val = evaluate(inner)
            result.append(_fmt(val))
            i = j
        else:
            result.append(s[i])
            i += 1
    return "".join(result)

# ── Nested property access helper ────────────────────────────────────────────
def _get_nested(obj, keys):
    """Get value from nested obj using list of string keys."""
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k, None)
        elif isinstance(obj, list):
            if k == "length": obj = len(obj)
            else:
                try: obj = obj[int(k)]
                except: obj = None
        elif isinstance(obj, str):
            if k == "length": obj = len(obj)
            else:
                try: obj = obj[int(k)]
                except: obj = None
        else:
            obj = None
    return obj

def _set_nested(obj, keys, val):
    """Set value in nested obj using list of string keys."""
    for k in keys[:-1]:
        if isinstance(obj, dict):
            obj = obj.setdefault(k, {})
        elif isinstance(obj, list):
            obj = obj[int(k)]
    last = keys[-1]
    if isinstance(obj, dict):
        obj[last] = val
    elif isinstance(obj, list):
        idx = int(last)
        while len(obj) <= idx: obj.append(None)
        obj[idx] = val

# ── typeof operator ───────────────────────────────────────────────────────────
def _js_typeof(val):
    if val is None:             return "undefined"
    if isinstance(val, bool):   return "boolean"
    if isinstance(val, (int, float)): return "number"
    if isinstance(val, str):    return "string"
    if isinstance(val, list):   return "object"
    if isinstance(val, dict):   return "object"
    if isinstance(val, _JSDate): return "object"
    if callable(val):           return "function"
    return "object"

# ── Arg splitter ──────────────────────────────────────────────────────────────
def _split_args(s):
    args, depth, in_str, current = [], 0, None, []
    for i, ch in enumerate(s):
        if in_str:
            current.append(ch)
            if ch == in_str and (i == 0 or s[i-1] != "\\"): in_str = None
        elif ch in ('"', "'", "`"): in_str = ch; current.append(ch)
        elif ch in ("(", "[", "{"): depth += 1; current.append(ch)
        elif ch in (")", "]", "}"): depth -= 1; current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current)); current = []
        else: current.append(ch)
    args.append("".join(current))
    return [a for a in args if a.strip()]

def _split_plus(expr):
    parts, depth, in_str, current = [], 0, None, []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if in_str:
            current.append(ch)
            if ch == in_str and (i == 0 or expr[i-1] != "\\"): in_str = None
        elif ch in ('"', "'", "`"): in_str = ch; current.append(ch)
        elif ch in ("(", "[", "{"): depth += 1; current.append(ch)
        elif ch in (")", "]", "}"): depth -= 1; current.append(ch)
        elif ch == "+" and depth == 0:
            nxt = expr[i+1] if i+1 < len(expr) else ""
            prv = expr[i-1] if i > 0 else ""
            if nxt in ("+", "=") or prv == "+": current.append(ch)
            else: parts.append("".join(current)); current = []
        else: current.append(ch)
        i += 1
    parts.append("".join(current))
    return [p for p in parts if p.strip()]

def js_concat_or_add(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return _fmt(a) + _fmt(b)
    if isinstance(a, list) and isinstance(b, list): return a + b
    return a + b

# ── JS expression transforms ──────────────────────────────────────────────────
def js_to_python(expr):
    expr = expr.strip()
    expr = expr.replace("===", "==")
    expr = expr.replace("!==", "!=")
    expr = expr.replace("&&",  " and ")
    expr = expr.replace("||",  " or ")
    expr = re.sub(r"\btrue\b",      "True",  expr)
    expr = re.sub(r"\bfalse\b",     "False", expr)
    expr = re.sub(r"\bnull\b",      "None",  expr)
    expr = re.sub(r"\bundefined\b", "None",  expr)
    expr = re.sub(r"\.length\b",    ".__len__()", expr)
    expr = re.sub(r"\bArray\.from\b", "Array.from_", expr)
    return expr

def substitute_variables(expr):
    """Replace variable names with repr — skip inside string literals."""
    result = []
    i = 0
    in_str = None
    str_buf = []
    while i < len(expr):
        ch = expr[i]
        if in_str:
            str_buf.append(ch)
            if ch == in_str and (i == 0 or expr[i-1] != "\\"):
                in_str = None
                result.append("".join(str_buf))
                str_buf = []
            i += 1
            continue
        if ch in ('"', "'", "`"):
            in_str = ch; str_buf = [ch]; i += 1; continue
        m = re.match(r"[a-zA-Z_$][a-zA-Z0-9_$]*", expr[i:])
        if m:
            token = m.group(0)
            if token in variables:
                val = variables[token]
                # Only substitute simple types that eval can handle
                if isinstance(val, (bool, int, float, str, list, dict, type(None))):
                    result.append(repr(val))
                else:
                    # Complex objects (Date etc) — keep token, will be resolved via variable lookup
                    result.append(token)
            else:
                result.append(token)
            i += len(token)
            continue
        result.append(ch)
        i += 1
    return "".join(result)

_IGNORE_TOKENS = {
    "true","false","null","undefined","let","var","const",
    "if","else","while","for","do","of","in","return","break","continue",
    "switch","case","default","function","console","log","typeof",
    "instanceof","new","this","delete","void",
    "None","True","False","and","or","not",
    "Math","Array","Object","Date","parseInt","parseFloat","isNaN","isFinite",
    "String","Number","Boolean","NaN","Infinity","abs","round","len",
    "push","pop","shift","unshift","splice","slice","concat","reverse","sort",
    "indexOf","lastIndexOf","includes","find","findIndex","filter","map",
    "forEach","reduce","reduceRight","some","every","flat","flatMap","fill",
    "join","toString","keys","values","entries","from","of","isArray","from_",
    "assign","freeze","create","hasOwnProperty",
    "split","trim","trimStart","trimEnd","replace","replaceAll","toUpperCase",
    "toLowerCase","startsWith","endsWith","charAt","charCodeAt","padStart",
    "padEnd","repeat","substring","substr","at","fromCharCode","valueOf",
    "floor","ceil","sqrt","pow","max","min","PI","E","log","log2","log10",
    "sin","cos","tan","trunc","sign","random",
    "getFullYear","getMonth","getDate","getDay","getHours","getMinutes",
    "getSeconds","getMilliseconds","getTime","toISOString","toLocaleDateString",
    "toLocaleTimeString",
    "length","__len__",
}

def check_undeclared(expr):
    # Skip check entirely if expression contains an arrow function
    if "=>" in expr:
        return
    clean = re.sub(r'`[^`]*`', '""', expr)
    clean = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'', '""', clean)
    tokens = re.findall(r"\b([a-zA-Z_$][a-zA-Z0-9_$]*)\b", clean)
    for token in tokens:
        if token not in _IGNORE_TOKENS and token not in variables and token not in functions:
            raise JSError("ReferenceError", f"{token} is not defined")

# ── Arrow callback parser ─────────────────────────────────────────────────────
def _parse_arrow_callback(s):
    """
    Parse an inline arrow function like:  x => x * 2  or  (x, y) => x + y
    Returns (params_list, body_expr_str) or None if not an arrow function.
    """
    s = s.strip()
    # (x, y) => expr
    m = re.match(r"^\(([^)]*)\)\s*=>\s*(.+)$", s, re.DOTALL)
    if m:
        params = [p.strip() for p in m.group(1).split(",") if p.strip()]
        return params, m.group(2).strip()
    # x => expr
    m = re.match(r"^(\w+)\s*=>\s*(.+)$", s, re.DOTALL)
    if m:
        return [m.group(1).strip()], m.group(2).strip()
    return None


def _call_arrow(params, body_expr, arg_val):
    """Call a single-arg arrow callback with one value, return result."""
    saved = dict(variables)
    if isinstance(params, list):
        for i, p in enumerate(params):
            variables[p] = arg_val[i] if isinstance(arg_val, list) and i < len(arg_val) else (arg_val if i == 0 else None)
    else:
        variables[params] = arg_val
    try:
        result = evaluate(body_expr, check_refs=False)
    finally:
        variables.clear(); variables.update(saved)
    return result


def _call_arrow_two(params, body_expr, arg1, arg2):
    """Call a two-arg arrow callback."""
    saved = dict(variables)
    if len(params) > 0: variables[params[0]] = arg1
    if len(params) > 1: variables[params[1]] = arg2
    try:
        result = evaluate(body_expr, check_refs=False)
    finally:
        variables.clear(); variables.update(saved)
    return result


def _call_arrow_two(params, body_expr, arg1, arg2):
    """Call a two-arg arrow callback."""
    saved = dict(variables)
    if len(params) > 0: variables[params[0]] = arg1
    if len(params) > 1: variables[params[1]] = arg2
    try:
        result = evaluate(body_expr, check_refs=False)
    finally:
        variables.clear(); variables.update(saved)
    return result


# ── Switch statement executor ─────────────────────────────────────────────────
def _execute_switch(switch_val, body_lines):
    """Execute a switch body (list of lines already extracted from braces)."""
    # Parse case/default blocks
    cases = []   # list of (value_or_None_for_default, [lines])
    current_val = _UNRESOLVED
    current_lines = []
    i = 0
    while i < len(body_lines):
        line = body_lines[i].strip()
        # case X:
        m = re.match(r"^case\s+(.+?)\s*:\s*(.*)$", line)
        if m:
            if current_val is not _UNRESOLVED or current_lines:
                cases.append((current_val, current_lines))
            current_val = evaluate(m.group(1))
            rest = m.group(2).strip()
            current_lines = [rest] if rest else []
            i += 1; continue
        # default:
        m = re.match(r"^default\s*:\s*(.*)$", line)
        if m:
            if current_val is not _UNRESOLVED or current_lines:
                cases.append((current_val, current_lines))
            current_val = None   # None = default
            rest = m.group(1).strip()
            current_lines = [rest] if rest else []
            i += 1; continue
        current_lines.append(body_lines[i])
        i += 1
    if current_val is not _UNRESOLVED or current_lines:
        cases.append((current_val, current_lines))

    # Execute matching case with fall-through
    executing = False
    default_idx = None
    for idx, (val, lines) in enumerate(cases):
        if val is None:
            default_idx = idx
        if val == switch_val:
            executing = True
        if executing:
            try:
                execute_block(list(lines))
            except _Break:
                return
    # If no case matched, run default
    if not executing and default_idx is not None:
        for idx in range(default_idx, len(cases)):
            try:
                execute_block(list(cases[idx][1]))
            except _Break:
                return


# ── Method call on a value ────────────────────────────────────────────────────
def _call_method_on(obj, obj_name, method, args_str):
    # For callback methods, we need raw args_str — evaluate args only for non-callback methods
    cb_methods = {"map","filter","reduce","forEach","find","findIndex","some","every"}
    if method not in cb_methods:
        args = [evaluate(a.strip()) for a in _split_args(args_str)] if args_str.strip() else []
    else:
        args = []  # not used for callback methods

    # ── Static: Object.keys(), Array.isArray() etc ───────────────────────────
    if obj is _JSObject or obj_name == "Object":
        if method == "keys":    return list(args[0].keys()) if args and isinstance(args[0], dict) else []
        if method == "values":  return list(args[0].values()) if args and isinstance(args[0], dict) else []
        if method == "entries": return [[k,v] for k,v in args[0].items()] if args and isinstance(args[0], dict) else []
        if method == "assign":
            if len(args) >= 2:
                for src in args[1:]: args[0].update(src)
            return args[0] if args else {}

    if obj is _JSArray or obj_name == "Array":
        if method == "isArray":  return isinstance(args[0], list) if args else False
        if method == "from_":    return list(args[0]) if args else []
        if method == "of":       return list(args)

    if obj is _Math or obj_name == "Math":
        fn = getattr(_Math, method, None)
        if fn: return fn(*args)

    if obj_name == "String":
        if method == "fromCharCode": return chr(int(args[0])) if args else ""

    if isinstance(obj, list):
        if method == "push":
            for a in args: obj.append(a)
            return len(obj)
        if method == "pop":       return obj.pop() if obj else None
        if method == "shift":     return obj.pop(0) if obj else None
        if method == "unshift":
            for a in reversed(args): obj.insert(0, a)
            return len(obj)
        if method == "splice":
            start = int(args[0]) if args else 0
            if start < 0: start = max(0, len(obj) + start)
            dc    = int(args[1]) if len(args) > 1 else len(obj) - start
            add   = args[2:] if len(args) > 2 else []
            removed = obj[start:start+dc]
            obj[start:start+dc] = add
            return removed
        if method == "slice":
            s = int(args[0]) if len(args) > 0 else 0
            e = int(args[1]) if len(args) > 1 else len(obj)
            return obj[s:e]
        if method == "concat":
            r = list(obj)
            for a in args: r.extend(a) if isinstance(a, list) else r.append(a)
            return r
        if method == "reverse":   obj.reverse(); return obj
        if method == "sort":
            obj.sort(key=lambda x: (0, x) if isinstance(x, (int,float)) else (1, str(x)))
            return obj
        if method == "indexOf":
            try: return obj.index(args[0]) if args else -1
            except ValueError: return -1
        if method == "lastIndexOf":
            v = args[0] if args else None
            for idx in range(len(obj)-1, -1, -1):
                if obj[idx] == v: return idx
            return -1
        if method == "includes":  return (args[0] if args else None) in obj
        if method == "flat":
            d = int(args[0]) if args else 1
            def fl(lst, depth):
                r = []
                for item in lst:
                    if isinstance(item, list) and depth > 0: r.extend(fl(item, depth-1))
                    else: r.append(item)
                return r
            return fl(obj, d)
        if method == "fill":
            v = args[0] if args else None
            s = int(args[1]) if len(args) > 1 else 0
            e = int(args[2]) if len(args) > 2 else len(obj)
            for idx in range(s, e): obj[idx] = v
            return obj
        if method == "join":
            sep = str(args[0]) if args else ","
            return sep.join(_fmt(x) for x in obj)
        if method == "toString":  return ",".join(_fmt(x) for x in obj)
        if method == "keys":      return list(range(len(obj)))
        if method == "values":    return list(obj)
        if method == "entries":   return [[i, v] for i, v in enumerate(obj)]
        if method == "at":
            idx = int(args[0]) if args else 0
            if idx < 0: idx = len(obj) + idx
            return obj[idx] if 0 <= idx < len(obj) else None
        if method == "find":
            if args_str.strip():
                cb = _parse_arrow_callback(args_str)
                if cb:
                    p, body = cb
                    for item in obj:
                        if _call_arrow(p, body, item): return item
            return None
        if method == "findIndex":
            if args_str.strip():
                cb = _parse_arrow_callback(args_str)
                if cb:
                    p, body = cb
                    for idx, item in enumerate(obj):
                        if _call_arrow(p, body, item): return idx
            return -1
        if method == "filter":
            if args_str.strip():
                cb = _parse_arrow_callback(args_str)
                if cb:
                    p, body = cb
                    return [item for item in obj if _call_arrow(p, body, item)]
            return list(obj)
        if method == "map":
            if args_str.strip():
                cb = _parse_arrow_callback(args_str)
                if cb:
                    p, body = cb
                    return [_call_arrow(p, body, item) for item in obj]
            return list(obj)
        if method == "forEach":
            if args_str.strip():
                cb = _parse_arrow_callback(args_str)
                if cb:
                    p, body = cb
                    for item in obj: _call_arrow(p, body, item)
            return None
        if method == "reduce":
            if args_str.strip():
                raw_args = _split_args(args_str)
                cb_str = raw_args[0] if raw_args else ""
                cb = _parse_arrow_callback(cb_str)
                init_val = evaluate(raw_args[1].strip()) if len(raw_args) > 1 else _UNRESOLVED
                if cb:
                    p, body = cb
                    if init_val is _UNRESOLVED:
                        acc = obj[0] if obj else None
                        start = 1
                    else:
                        acc = init_val
                        start = 0
                    for item in obj[start:]:
                        acc = _call_arrow_two(p, body, acc, item)
                    return acc
            return None
        if method == "some":
            if args_str.strip():
                cb = _parse_arrow_callback(args_str)
                if cb:
                    p, body = cb
                    return any(_call_arrow(p, body, item) for item in obj)
            return False
        if method == "every":
            if args_str.strip():
                cb = _parse_arrow_callback(args_str)
                if cb:
                    p, body = cb
                    return all(_call_arrow(p, body, item) for item in obj)
            return True
    if isinstance(obj, dict):
        if method == "hasOwnProperty": return (str(args[0]) in obj) if args else False
        if method == "keys":    return list(obj.keys())
        if method == "values":  return list(obj.values())
        if method == "entries": return [[k, v] for k, v in obj.items()]
        if method == "toString": return "[object Object]"

    # ── Date methods ─────────────────────────────────────────────────────────
    if isinstance(obj, _JSDate):
        fn = getattr(obj, method, None)
        if fn: return fn()

    if isinstance(obj, str):
        if method == "toUpperCase":  return obj.upper()
        if method == "toLowerCase":  return obj.lower()
        if method == "trim":         return obj.strip()
        if method == "trimStart":    return obj.lstrip()
        if method == "trimEnd":      return obj.rstrip()
        if method == "split":
            sep   = args[0] if args else ""
            limit = int(args[1]) if len(args) > 1 else None
            r = obj.split(sep) if sep != "" else list(obj)
            return r[:limit] if limit is not None else r
        if method == "includes":     return (args[0] if args else "") in obj
        if method == "startsWith":   return obj.startswith(args[0]) if args else False
        if method == "endsWith":     return obj.endswith(args[0]) if args else False
        if method == "indexOf":      return obj.find(args[0]) if args else -1
        if method == "lastIndexOf":  return obj.rfind(args[0]) if args else -1
        if method == "slice":
            s = int(args[0]) if len(args) > 0 else 0
            e = int(args[1]) if len(args) > 1 else len(obj)
            return obj[s:e]
        if method == "substring":
            s = int(args[0]) if len(args) > 0 else 0
            e = int(args[1]) if len(args) > 1 else len(obj)
            return obj[s:e]
        if method == "substr":
            s = int(args[0]) if len(args) > 0 else 0
            l = int(args[1]) if len(args) > 1 else len(obj)
            return obj[s:s+l]
        if method == "replace":
            if len(args) >= 2: return obj.replace(str(args[0]), str(args[1]), 1)
            return obj
        if method == "replaceAll":
            if len(args) >= 2: return obj.replace(str(args[0]), str(args[1]))
            return obj
        if method == "repeat":       return obj * (int(args[0]) if args else 0)
        if method == "padStart":
            w = int(args[0]) if args else 0
            p = str(args[1])[0] if len(args) > 1 and args[1] else " "
            return obj.rjust(w, p)
        if method == "padEnd":
            w = int(args[0]) if args else 0
            p = str(args[1])[0] if len(args) > 1 and args[1] else " "
            return obj.ljust(w, p)
        if method == "charAt":
            idx = int(args[0]) if args else 0
            return obj[idx] if 0 <= idx < len(obj) else ""
        if method == "charCodeAt":
            idx = int(args[0]) if args else 0
            return ord(obj[idx]) if 0 <= idx < len(obj) else float("nan")
        if method == "at":
            idx = int(args[0]) if args else 0
            if idx < 0: idx = len(obj) + idx
            return obj[idx] if 0 <= idx < len(obj) else None
        if method == "toString":     return obj
        if method == "valueOf":      return obj

    raise JSError("TypeError", f"'{method}' is not a function")

def _find_last_method_call(expr):
    """
    Find the last top-level .method(args) call in expr.
    Returns (obj_expr, method, args_str) or None.
    Scans right to left to find the outermost closing ) then matches back.
    """
    # expr must end with )
    expr = expr.strip()
    if not expr.endswith(")"):
        return None
    # Find matching opening ( from the end
    depth = 0
    close_pos = len(expr) - 1
    open_pos = -1
    for i in range(len(expr)-1, -1, -1):
        if expr[i] == ')': depth += 1
        elif expr[i] == '(':
            depth -= 1
            if depth == 0:
                open_pos = i
                break
    if open_pos <= 0:
        return None
    args_str = expr[open_pos+1:close_pos]
    before_paren = expr[:open_pos]
    # Find .method just before (
    m = re.match(r"^(.*?)\.(\w+)$", before_paren)
    if not m:
        return None
    obj_expr = m.group(1).strip()
    method   = m.group(2)
    if not obj_expr:
        return None
    return obj_expr, method, args_str


def _balanced(s):
    """Check if parens/brackets are balanced in string."""
    depth, in_str = 0, None
    for ch in s:
        if in_str:
            if ch == in_str: in_str = None
        elif ch in ('"', "'", "`"): in_str = ch
        elif ch in ("(", "[", "{"): depth += 1
        elif ch in (")", "]", "}"): depth -= 1
        if depth < 0: return False
    return depth == 0

# ── evaluate ─────────────────────────────────────────────────────────────────
def evaluate(expr, check_refs=True):
    original = expr.strip()
    if not original: return None

    # ── template literal `...${expr}...` ────────────────────────────────────
    if original.startswith("`") and original.endswith("`"):
        return process_template_literal(original[1:-1])

    # ── new Date(...) ────────────────────────────────────────────────────────
    m = re.match(r"^new\s+Date\s*\((.*)\)$", original)
    if m:
        return _JSDate()

    # ── new keyword (generic — return empty object) ──────────────────────────
    m = re.match(r"^new\s+(\w+)\s*\((.*)\)$", original)
    if m:
        cname = m.group(1)
        if cname == "Date": return _JSDate()
        return {}

    # ── spread array literal [...a, ...b, x] ────────────────────────────────
    if original.startswith("[") and original.endswith("]"):
        inner = original[1:-1].strip()
        if "..." in inner:
            result = []
            for part in _split_args(inner):
                part = part.strip()
                if part.startswith("..."):
                    val = evaluate(part[3:])
                    if isinstance(val, list): result.extend(val)
                    elif isinstance(val, str): result.extend(list(val))
                    else: result.append(val)
                else:
                    result.append(evaluate(part))
            return result

    # ── typeof expr ─────────────────────────────────────────────────────────
    m = re.match(r"^typeof\s+(.+)$", original)
    if m:
        inner = m.group(1).strip()
        # First check if it's a simple variable
        if inner in variables:
            return _js_typeof(variables[inner])
        try:
            val = evaluate(inner, check_refs=False)
        except JSError:
            val = None
        return _js_typeof(val)

    # ── ternary: cond ? a : b ────────────────────────────────────────────────
    ternary = _find_ternary(original)
    if ternary:
        cond, t_expr, f_expr = ternary
        return evaluate(t_expr) if truthy(cond) else evaluate(f_expr)

    # ── chained method calls: a.b.c or a.b().c.d() ──────────────────────────
    # Find the LAST .method(balanced_args) pattern at top level
    # Do this BEFORE substitute_variables to avoid list/dict repr breaking eval
    mc = _find_last_method_call(original)
    if mc:
        obj_expr, method, args_str = mc
        try:
            if obj_expr in variables:
                obj = variables[obj_expr]
            else:
                obj = evaluate(obj_expr, check_refs=False)
            if obj is not None:
                return _call_method_on(obj, obj_expr, method, args_str)
        except JSError: raise
        except Exception: pass

    # ── user-defined function call: funcName(args) ───────────────────────────
    m = re.match(r"^(\w+)\((.*)\)$", original, re.DOTALL)
    if m:
        fname, args_str = m.group(1), m.group(2)
        if fname in functions:
            return _call_function(fname, args_str)
    # ── property access chain: a.b.c ────────────────────────────────────────
    if "." in original and not original.startswith('"') and not original.startswith("'"):
        parts = original.split(".")
        if all(re.match(r"^\w+$", p) for p in parts) and parts[0] in variables:
            obj = variables[parts[0]]
            return _get_nested(obj, parts[1:])
        # Math.PI, Math.E etc
        if parts[0] == "Math" and len(parts) == 2:
            return getattr(_Math, parts[1], None)
        if parts[0] == "Array" and len(parts) == 2:
            return getattr(_JSArray, parts[1], None)

    # ── bracket access chain: a[expr] ───────────────────────────────────────
    m = re.match(r"^(.+?)\[(.+)\]$", original, re.DOTALL)
    if m:
        obj_expr, key_expr = m.group(1).strip(), m.group(2)
        try:
            obj = _resolve_expr(obj_expr)
            if obj is not _UNRESOLVED:
                key = evaluate(key_expr)
                if isinstance(obj, (list, str)):
                    idx = int(key)
                    return obj[idx] if 0 <= idx < len(obj) else None
                if isinstance(obj, dict):
                    return obj.get(str(key), None)
        except JSError: raise
        except Exception: pass

    if check_refs:
        check_undeclared(original)

    py_expr = js_to_python(original)
    py_expr = substitute_variables(py_expr)

    # Inject user-defined functions into eval environment
    eval_env = dict(_BUILTINS)
    for fname, fn in functions.items():
        # create a closure for each function
        def _make_caller(fn_name):
            def _caller(*args):
                args_str = ", ".join(repr(a) for a in args)
                return _call_function(fn_name, args_str) if not args_str else _call_function_vals(fn_name, list(args))
            return _caller
        eval_env[fname] = _make_caller(fname)

    try:
        return eval(py_expr, {"__builtins__": None}, eval_env)
    except TypeError as e:
        err = str(e)
        if "+" in py_expr and ("operand" in err or "str" in err):
            parts = _split_plus(py_expr)
            try:
                vals = [eval(p.strip(), {"__builtins__": None}, _BUILTINS) for p in parts]
                if any(isinstance(v, str) for v in vals):
                    return "".join(_fmt(v) for v in vals)
                return sum(vals)
            except Exception: pass
        raise JSError("TypeError", err)
    except ZeroDivisionError:
        raise JSError("RangeError", "Division by zero")
    except NameError as e:
        raise JSError("ReferenceError", str(e))
    except SyntaxError:
        raise JSError("SyntaxError", f"Unexpected token near '{original}'")
    except Exception as e:
        raise JSError("RuntimeError", str(e))


_UNRESOLVED = object()  # sentinel

def _resolve_expr(expr):
    """Try to resolve expr to a Python value. Returns _UNRESOLVED if can't."""
    expr = expr.strip()
    if expr in variables: return variables[expr]
    # dot chain
    parts = expr.split(".")
    if all(re.match(r"^\w+$", p) for p in parts) and parts[0] in variables:
        return _get_nested(variables[parts[0]], parts[1:])
    return _UNRESOLVED


def _find_ternary(expr):
    """
    Find top-level ternary ? and : in expr.
    Returns (cond, true_expr, false_expr) or None.
    """
    depth, in_str = 0, None
    q_pos = None
    for i, ch in enumerate(expr):
        if in_str:
            if ch == in_str and (i == 0 or expr[i-1] != "\\"): in_str = None
        elif ch in ('"', "'", "`"): in_str = ch
        elif ch in ("(", "[", "{"): depth += 1
        elif ch in (")", "]", "}"): depth -= 1
        elif ch == "?" and depth == 0 and q_pos is None:
            q_pos = i
        elif ch == ":" and depth == 0 and q_pos is not None:
            return expr[:q_pos].strip(), expr[q_pos+1:i].strip(), expr[i+1:].strip()
    return None


def truthy(expr):
    val = evaluate(expr)
    if val is None or val == "" or val == 0 or val is False: return False
    if isinstance(val, float) and val != val: return False  # NaN
    return True


# ── Function definition & call ────────────────────────────────────────────────
def _call_function_vals(fname, arg_vals):
    """Call a user-defined function with already-evaluated argument values."""
    if fname not in functions:
        raise JSError("ReferenceError", f"{fname} is not defined")
    fn = functions[fname]
    params = fn["params"]
    body   = fn["body"]

    saved_vars = dict(variables)
    for i, p in enumerate(params):
        variables[p] = arg_vals[i] if i < len(arg_vals) else None

    ret_val = None
    try:
        execute_block(list(body))
    except _Return as r:
        ret_val = r.value
    finally:
        variables.clear()
        variables.update(saved_vars)

    return ret_val


def _call_function(fname, args_str):
    if fname not in functions:
        raise JSError("ReferenceError", f"{fname} is not defined")
    fn = functions[fname]
    params = fn["params"]
    body   = fn["body"]

    # evaluate args BEFORE modifying scope
    arg_vals = [evaluate(a.strip()) for a in _split_args(args_str)] if args_str.strip() else []

    # save entire variable scope, set params, restore after
    saved_vars = dict(variables)
    # remove all current vars so function has clean scope
    # but keep globals that aren't params (JS-style: functions see outer scope)
    for p in params:
        variables[p] = arg_vals[params.index(p)] if params.index(p) < len(arg_vals) else None

    ret_val = None
    try:
        execute_block(list(body))
    except _Return as r:
        ret_val = r.value
    finally:
        # restore all variables to pre-call state
        variables.clear()
        variables.update(saved_vars)

    return ret_val


# ── Statement executor ────────────────────────────────────────────────────────
def execute_statement(line):
    line = line.strip().rstrip(";")
    if not line: return

    # ── return ───────────────────────────────────────────────────────────────
    m = re.match(r"^return\b(.*)$", line)
    if m:
        val_str = m.group(1).strip()
        raise _Return(evaluate(val_str) if val_str else None)

    # ── break / continue ─────────────────────────────────────────────────────
    if line == "break":    raise _Break()
    if line == "continue": raise _Continue()

    # ── let/var/const x = expr ───────────────────────────────────────────────
    m = re.match(r"^(?:let|var|const)\s+(\w+)\s*=\s*(.+)$", line)
    if m:
        variables[m.group(1)] = evaluate(m.group(2))
        return

    # ── let/var/const x (bare) ───────────────────────────────────────────────
    m = re.match(r"^(?:let|var|const)\s+(\w+)$", line)
    if m:
        variables[m.group(1)] = None
        return

    # ── console.log(...) ─────────────────────────────────────────────────────
    m = re.match(r"^console\.log\((.*)\)$", line, re.DOTALL)
    if m:
        global output_header_printed
        if not output_header_printed:
            print("\n<<output>>\n")
            output_header_printed = True
        result = evaluate(m.group(1))
        print(_fmt_log(result))
        return

    # ── x++ / x-- ────────────────────────────────────────────────────────────
    m = re.match(r"^(\w+)\s*(\+\+|--)$", line)
    if m:
        name, op = m.group(1), m.group(2)
        if name not in variables: raise JSError("ReferenceError", f"{name} is not defined")
        variables[name] = variables[name] + (1 if op == "++" else -1)
        return

    # ── ++x / --x ────────────────────────────────────────────────────────────
    m = re.match(r"^(\+\+|--)\s*(\w+)$", line)
    if m:
        op, name = m.group(1), m.group(2)
        if name not in variables: raise JSError("ReferenceError", f"{name} is not defined")
        variables[name] = variables[name] + (1 if op == "++" else -1)
        return

    # ── x op= expr ───────────────────────────────────────────────────────────
    m = re.match(r"^(\w+)\s*(\+=|-=|\*=|/=|%=)\s*(.+)$", line)
    if m:
        name, op, expr = m.group(1), m.group(2), m.group(3)
        if name not in variables: raise JSError("ReferenceError", f"{name} is not defined")
        val, cur = evaluate(expr), variables[name]
        try:
            if op == "+=":  variables[name] = js_concat_or_add(cur, val)
            elif op == "-=": variables[name] = cur - val
            elif op == "*=": variables[name] = cur * val
            elif op == "/=":
                if val == 0: raise JSError("RangeError", "Division by zero")
                variables[name] = cur / val
            elif op == "%=": variables[name] = cur % val
        except JSError: raise
        except TypeError as e: raise JSError("TypeError", str(e))
        return

    # ── arr[i] = expr ────────────────────────────────────────────────────────
    m = re.match(r"^(\w+)\[(.+)\]\s*=\s*(.+)$", line)
    if m:
        name, key_expr, val_expr = m.group(1), m.group(2), m.group(3)
        if name not in variables: raise JSError("ReferenceError", f"{name} is not defined")
        key, val, obj = evaluate(key_expr), evaluate(val_expr), variables[name]
        if isinstance(obj, list):
            idx = int(key)
            while len(obj) <= idx: obj.append(None)
            obj[idx] = val
        elif isinstance(obj, dict):
            obj[str(key)] = val
        return

    # ── obj.prop.prop = expr (nested assignment) ──────────────────────────────
    m = re.match(r"^(\w+(?:\.\w+)+)\s*=\s*(.+)$", line)
    if m:
        chain, val_expr = m.group(1), m.group(2)
        parts = chain.split(".")
        root = parts[0]
        if root not in variables: raise JSError("ReferenceError", f"{root} is not defined")
        val = evaluate(val_expr)
        _set_nested(variables[root], parts[1:], val)
        return

    # ── obj.method(args) as statement ────────────────────────────────────────
    m = re.match(r"^(.+?)\.(\w+)\((.*)\)$", line, re.DOTALL)
    if m:
        obj_expr, method, args_str = m.group(1).strip(), m.group(2), m.group(3)
        obj = _resolve_expr(obj_expr)
        if obj is not _UNRESOLVED:
            _call_method_on(obj, obj_expr, method, args_str)
            return

    # ── user-defined function call as statement ───────────────────────────────
    m = re.match(r"^(\w+)\((.*)\)$", line, re.DOTALL)
    if m:
        fname, args_str = m.group(1), m.group(2)
        if fname in functions:
            _call_function(fname, args_str)
            return

    # ── x = expr (reassign) ──────────────────────────────────────────────────
    m = re.match(r"^(\w+)\s*=\s*(.+)$", line)
    if m:
        name, expr = m.group(1), m.group(2)
        if name not in variables: raise JSError("ReferenceError", f"{name} is not defined")
        variables[name] = evaluate(expr)
        return

    # ── fallback evaluate ─────────────────────────────────────────────────────
    try:
        evaluate(line, check_refs=False)
    except JSError: raise


# ── Block parser ──────────────────────────────────────────────────────────────
def normalize_lines(raw_lines):
    result = []
    for line in raw_lines:
        s = line.strip()
        if not s or s.startswith("//"):
            result.append(line); continue
        m = re.match(r"^\}\s*(else\b.*)", s)
        if m and not re.match(r"^\}\s*while\b", s):
            result.append("}")
            result.append(m.group(1))
            continue
        result.append(line)
    return result

def _scan_text(text, depth):
    collected, j = [], 0
    while j < len(text):
        ch = text[j]
        if ch == "{": depth += 1
        elif ch == "}":
            if depth == 1:
                seg = text[:j].strip()
                if seg: collected.append(seg)
                return collected, 0, text[j+1:]
            depth -= 1
        j += 1
    seg = text.strip()
    if seg: collected.append(seg)
    return collected, depth, ""

def parse_block(lines, index):
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines):
        return [], index
    line = lines[index]
    if "{" in line:
        block_lines, depth = [], 1
        rest = line[line.find("{") + 1:]
        seg, depth, rest_after = _scan_text(rest, depth)
        block_lines.extend(seg)
        if depth == 0:
            r = rest_after.strip()
            if r: lines[index] = r; return block_lines, index
            return block_lines, index + 1
        i = index + 1
        while i < len(lines):
            seg, depth, rest_after = _scan_text(lines[i], depth)
            block_lines.extend(seg)
            if depth == 0:
                r = rest_after.strip()
                if r: lines[i] = r; return block_lines, i
                return block_lines, i + 1
            i += 1
        return block_lines, i
    else:
        return [line.strip()], index + 1


# ── Main executor ─────────────────────────────────────────────────────────────
def execute_block(lines, start_index=0):
    lines = normalize_lines(lines)
    i = start_index

    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("//"): i += 1; continue

        # ── function declaration ─────────────────────────────────────────────
        # function foo(a, b) { ... }
        m = re.match(r"^function\s+(\w+)\s*\((.*?)\)\s*(.*)$", line, re.DOTALL)
        if m:
            fname, params_str, after = m.group(1), m.group(2), m.group(3).strip()
            params = [p.strip() for p in params_str.split(",") if p.strip()]
            lc = list(lines)
            if after.startswith("{"):
                lc[i] = after; body, next_i = parse_block(lc, i)
            else:
                body, next_i = parse_block(lc, i + 1)
            functions[fname] = {"params": params, "body": body}
            i = next_i; continue

        # ── arrow / const fn = (params) => { } ──────────────────────────────
        m = re.match(r"^(?:let|var|const)\s+(\w+)\s*=\s*(?:function\s*)?\((.*?)\)\s*=>\s*(.+)$", line, re.DOTALL)
        if m:
            fname, params_str, after = m.group(1), m.group(2), m.group(3).strip()
            params = [p.strip() for p in params_str.split(",") if p.strip()]
            lc = list(lines)
            if after.startswith("{"):
                lc[i] = after; body, next_i = parse_block(lc, i)
            else:
                # single expression arrow: const double = x => x * 2
                body  = [f"return {after.rstrip(';')}"]
                next_i = i + 1
            functions[fname] = {"params": params, "body": body}
            i = next_i; continue

        # ── switch ───────────────────────────────────────────────────────────
        if re.match(r"^switch\s*\(", line):
            m = re.match(r"^switch\s*\((.*)\)\s*(.*)$", line, re.DOTALL)
            if not m: raise JSError("SyntaxError", f"Invalid switch: {line}")
            switch_val = evaluate(m.group(1))
            after = m.group(2).strip()
            lc = list(lines)
            if after.startswith("{"):
                lc[i] = after; body, next_i = parse_block(lc, i)
            else:
                body, next_i = parse_block(lc, i + 1)
            _execute_switch(switch_val, body)
            i = next_i; continue

        # ── if / else if / else ──────────────────────────────────────────────
        if re.match(r"^if\s*\(", line):
            m = re.match(r"^if\s*\((.*)\)\s*(.*)$", line, re.DOTALL)
            if not m: raise JSError("SyntaxError", f"Invalid if: {line}")
            condition, after = m.group(1), m.group(2).strip()
            lc = list(lines)
            if after.startswith("{"):
                lc[i] = after; body, next_i = parse_block(lc, i)
            elif after:
                body, next_i = [after.rstrip(";")], i + 1
            else:
                body, next_i = parse_block(lc, i + 1)
            cond_val = truthy(condition)
            if cond_val:
                try: execute_block(body)
                except (_Break, _Continue, _Return): raise
            i = next_i
            while i < len(lines) and not lines[i].strip(): i += 1
            if i < len(lines) and re.match(r"^else\b", lines[i].strip()):
                else_line = lines[i].strip()
                after_else = re.match(r"^else\s*(.*)", else_line, re.DOTALL).group(1).strip()
                lc2 = list(lines)
                if after_else.startswith("if"):
                    lc2[i] = after_else
                    if not cond_val: i = execute_block(lc2, i)
                    else: i = _skip_block(lc2, i)
                elif after_else.startswith("{"):
                    lc2[i] = after_else
                    else_body, next_i = parse_block(lc2, i)
                    if not cond_val:
                        try: execute_block(else_body)
                        except (_Break, _Continue, _Return): raise
                    i = next_i
                elif after_else:
                    if not cond_val:
                        try: execute_block([after_else.rstrip(";")])
                        except (_Break, _Continue, _Return): raise
                    i += 1
                else:
                    else_body, next_i = parse_block(lc2, i + 1)
                    if not cond_val:
                        try: execute_block(else_body)
                        except (_Break, _Continue, _Return): raise
                    i = next_i
            continue

        # ── while ────────────────────────────────────────────────────────────
        if re.match(r"^while\s*\(", line):
            m = re.match(r"^while\s*\((.*)\)\s*(.*)$", line, re.DOTALL)
            if not m: raise JSError("SyntaxError", f"Invalid while: {line}")
            condition, after = m.group(1), m.group(2).strip()
            lc = list(lines)
            if after.startswith("{"): lc[i] = after; body_lines, next_i = parse_block(lc, i)
            elif after: body_lines, next_i = [after.rstrip(";")], i + 1
            else: body_lines, next_i = parse_block(lc, i + 1)
            while truthy(condition):
                try: execute_block(list(body_lines))
                except _Break: break
                except _Continue: continue
            i = next_i; continue

        # ── do-while ─────────────────────────────────────────────────────────
        if re.match(r"^do\b", line):
            after = re.match(r"^do\s*(.*)", line, re.DOTALL).group(1).strip()
            lc = list(lines)
            if after.startswith("{"): lc[i] = after; body_lines, next_i = parse_block(lc, i)
            elif after: body_lines, next_i = [after.rstrip(";")], i + 1
            else: body_lines, next_i = parse_block(lc, i + 1)
            j = next_i
            while j < len(lines) and not lines[j].strip(): j += 1
            if j >= len(lines): raise JSError("SyntaxError", "do-while missing while clause")
            wl = re.sub(r"^\}\s*", "", lines[j].strip())
            wm = re.match(r"^while\s*\((.*)\)\s*;?$", wl)
            if not wm: raise JSError("SyntaxError", f"Invalid do-while ending: {wl}")
            condition = wm.group(1)
            try: execute_block(list(body_lines))
            except _Break: i = j + 1; continue
            except _Continue: pass
            while truthy(condition):
                try: execute_block(list(body_lines))
                except _Break: break
                except _Continue: continue
            i = j + 1; continue

        # ── for-of ───────────────────────────────────────────────────────────
        if re.match(r"^for\s*\(\s*(?:let|var|const)\s+\w+\s+of\b", line):
            m = re.match(r"^for\s*\(\s*(?:let|var|const)\s+(\w+)\s+of\s+(.+?)\)\s*(.*)$", line, re.DOTALL)
            if not m: raise JSError("SyntaxError", f"Invalid for-of: {line}")
            var_name, iterable_expr, after = m.group(1), m.group(2).strip(), m.group(3).strip()
            lc = list(lines)
            if after.startswith("{"): lc[i] = after; body_lines, next_i = parse_block(lc, i)
            elif after: body_lines, next_i = [after.rstrip(";")], i + 1
            else: body_lines, next_i = parse_block(lc, i + 1)
            iterable = evaluate(iterable_expr)
            items = list(iterable.values()) if isinstance(iterable, dict) else iterable
            for item in items:
                variables[var_name] = item
                try: execute_block(list(body_lines))
                except _Break: break
                except _Continue: continue
            i = next_i; continue

        # ── for-in ───────────────────────────────────────────────────────────
        if re.match(r"^for\s*\(\s*(?:let|var|const)\s+\w+\s+in\b", line):
            m = re.match(r"^for\s*\(\s*(?:let|var|const)\s+(\w+)\s+in\s+(.+?)\)\s*(.*)$", line, re.DOTALL)
            if not m: raise JSError("SyntaxError", f"Invalid for-in: {line}")
            var_name, obj_expr, after = m.group(1), m.group(2).strip(), m.group(3).strip()
            lc = list(lines)
            if after.startswith("{"): lc[i] = after; body_lines, next_i = parse_block(lc, i)
            elif after: body_lines, next_i = [after.rstrip(";")], i + 1
            else: body_lines, next_i = parse_block(lc, i + 1)
            obj = evaluate(obj_expr)
            keys = list(obj.keys()) if isinstance(obj, dict) else list(range(len(obj)))
            for key in keys:
                variables[var_name] = key
                try: execute_block(list(body_lines))
                except _Break: break
                except _Continue: continue
            i = next_i; continue

        # ── for (classic) ────────────────────────────────────────────────────
        if re.match(r"^for\s*\(", line):
            m = re.match(r"^for\s*\((.+?);\s*(.*);\s*(.+?)\)\s*(.*)$", line, re.DOTALL)
            if not m: raise JSError("SyntaxError", f"Invalid for: {line}")
            init, condition, increment, after = m.group(1).strip(), m.group(2).strip(), m.group(3).strip(), m.group(4).strip()
            lc = list(lines)
            if after.startswith("{"): lc[i] = after; body_lines, next_i = parse_block(lc, i)
            elif after: body_lines, next_i = [after.rstrip(";")], i + 1
            else: body_lines, next_i = parse_block(lc, i + 1)
            if init: execute_statement(init)
            while True:
                if condition and not truthy(condition): break
                try: execute_block(list(body_lines))
                except _Break: break
                except _Continue: pass
                if increment: execute_statement(increment)
            i = next_i; continue

        # ── standalone } ─────────────────────────────────────────────────────
        if line == "}": return i + 1

        execute_statement(line)
        i += 1

    return i


def _skip_block(lines, index):
    line = lines[index].strip()
    lc = list(lines)
    if re.match(r"^if\s*\(", line):
        m = re.match(r"^if\s*\(.*\)\s*(.*)$", line)
        after = m.group(1).strip() if m else ""
        if after.startswith("{"): lc[index] = after; _, next_i = parse_block(lc, index)
        else: _, next_i = parse_block(lc, index + 1)
        j = next_i
        while j < len(lines) and not lines[j].strip(): j += 1
        if j < len(lines) and lines[j].strip().startswith("else"): return _skip_block(lines, j)
        return next_i
    if line.startswith("else"):
        after = re.match(r"^else\s*(.*)", line).group(1).strip()
        if after.startswith("if"): lc[index] = after; return _skip_block(lc, index)
        if after.startswith("{"): lc[index] = after; _, next_i = parse_block(lc, index); return next_i
        _, next_i = parse_block(lc, index + 1); return next_i
    if "{" in line: _, next_i = parse_block(lc, index); return next_i
    return index + 1


# ── Run helpers ───────────────────────────────────────────────────────────────
def run_buffer(buffer):
    global output_header_printed
    output_header_printed = False
    # Strip any accidental '> ' prompt prefix (happens when pasting)
    clean = []
    for ln in buffer:
        s = ln
        if s.startswith("> "): s = s[2:]
        elif s.startswith(">"): s = s[1:]
        clean.append(s)
    try:
        execute_block(clean)
    except JSError as e:
        print_js_error(e.error_type, e.message)
    except SyntaxError as e:
        print_js_error("SyntaxError", str(e))
    except Exception as e:
        print_js_error("RuntimeError", str(e))
    print()


def interactive_loop():
    if os.name != "nt":
        print("Type JavaScript-style code. Press Enter on blank line or type 'ctrl+t' to run.")
        buffer = []
        while True:
            try: line = input("> ")
            except EOFError: break
            if line.strip() == "" or line.strip().lower() == "ctrl+t":
                if buffer: run_buffer(buffer); buffer = []
                continue
            buffer.append(line)
        if buffer: run_buffer(buffer)
        return

    import msvcrt

    print("Type JavaScript-style code. Press Ctrl+T to run.")
    print("  Enter    = new line")
    print("  Ctrl+T   = run buffer")
    print("  Up/Down  = history navigation")
    print("  Left/Right = cursor move")
    print("-" * 40)

    buffer   = []       # multi-line buffer waiting to run
    history  = []       # list of previously entered single lines
    hist_idx = -1       # -1 means "not browsing history"

    # Current line state
    line   = ""         # content
    cursor = 0          # cursor position (0 = start)

    def _render(new_line, new_cursor):
        """Redraw current line in place using only \r and spaces (no ANSI)."""
        nonlocal line, cursor
        old_len = len(line)
        new_len = len(new_line)
        # Go to start of line, reprint "> " + full new content + erase leftover
        sys.stdout.write("\r> " + new_line + " " * max(0, old_len - new_len))
        # Move cursor back to correct position using \b
        pos_from_end = new_len - new_cursor
        if pos_from_end > 0:
            sys.stdout.write("\b" * pos_from_end)
        sys.stdout.flush()
        line   = new_line
        cursor = new_cursor

    print("> ", end="", flush=True)

    while True:
        ch = msvcrt.getwch()

        # ── Ctrl+C ────────────────────────────────────────────────────────────
        if ch == "\x03":
            raise KeyboardInterrupt

        # ── Ctrl+T — run buffer ───────────────────────────────────────────────
        if ch == "\x14":
            if line.strip():
                history.append(line)
                buffer.append(line)
                line = ""; cursor = 0
            if buffer:
                print()
                run_buffer(buffer)
                buffer = []
            hist_idx = -1
            print("> ", end="", flush=True)
            continue

        # ── Enter — add line to buffer ────────────────────────────────────────
        if ch == "\r":
            print()
            if line.strip():
                history.append(line)
                buffer.append(line)
            line = ""; cursor = 0; hist_idx = -1
            print("> ", end="", flush=True)
            continue

        # ── Backspace ─────────────────────────────────────────────────────────
        if ch == "\x08":
            if cursor > 0:
                new_line = line[:cursor-1] + line[cursor:]
                _render(new_line, cursor - 1)
            continue

        # ── Delete key (special sequence \xe0 + 'S') ─────────────────────────
        if ch in ("\x00", "\xe0"):
            # Special key — read second byte
            ch2 = msvcrt.getwch()

            # Up arrow (\xe0 H)
            if ch2 == "H":
                if history:
                    if hist_idx == -1:
                        hist_idx = len(history) - 1
                    elif hist_idx > 0:
                        hist_idx -= 1
                    _render(history[hist_idx], len(history[hist_idx]))
                continue

            # Down arrow (\xe0 P)
            if ch2 == "P":
                if hist_idx != -1:
                    if hist_idx < len(history) - 1:
                        hist_idx += 1
                        _render(history[hist_idx], len(history[hist_idx]))
                    else:
                        hist_idx = -1
                        _render("", 0)
                continue

            # Left arrow (\xe0 K)
            if ch2 == "K":
                if cursor > 0:
                    _render(line, cursor - 1)
                continue

            # Right arrow (\xe0 M)
            if ch2 == "M":
                if cursor < len(line):
                    _render(line, cursor + 1)
                continue

            # Home (\xe0 G)
            if ch2 == "G":
                _render(line, 0)
                continue

            # End (\xe0 O)
            if ch2 == "O":
                _render(line, len(line))
                continue

            # Delete (\xe0 S)
            if ch2 == "S":
                if cursor < len(line):
                    new_line = line[:cursor] + line[cursor+1:]
                    _render(new_line, cursor)
                continue

            continue  # ignore other special keys

        # ── Printable character — insert at cursor ────────────────────────────
        if ch >= " " or ch == "\t":
            new_line = line[:cursor] + ch + line[cursor:]
            _render(new_line, cursor + 1)
            continue



if __name__ == "__main__":
    if sys.stdin.isatty():
        interactive_loop()
    else:
        run_buffer([line.rstrip("\n") for line in sys.stdin])
