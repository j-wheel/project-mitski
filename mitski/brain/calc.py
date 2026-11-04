import ast
import math
import operator
import re

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_FUNCS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "floor": math.floor,
    "ceil": math.ceil,
}
_CONSTS = {"pi": math.pi, "e": math.e}


def calc(expr):
    expr = str(expr).lower().replace("^", "**").replace("×", "*").replace("÷", "/").replace("`", "")
    expr = re.sub(r"(?<=\d),(?=\d{3}\b)", "", expr)
    expr = re.sub(r"(\d|\)|\bpi|\be)\s*x\s*(?=[\d(]|pi\b|e\b)", r"\1*", expr)
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*", r"\1/100*", expr)
    expr = re.sub(r"[^0-9a-z_+\-*/().%, ]", "", expr).strip()
    if not expr or len(expr) > 120:
        return None

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
                raise ValueError("too big")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS
            and len(node.args) <= 2
        ):
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        raise ValueError("not allowed")

    try:
        value = ev(ast.parse(expr, mode="eval"))
    except Exception:
        return None
    if isinstance(value, float):
        value = int(value) if value.is_integer() and abs(value) < 1e15 else round(value, 6)
    return f"{expr.replace('**', '^')} = {value}"
