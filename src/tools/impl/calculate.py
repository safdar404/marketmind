"""Deterministic arithmetic in Python. Closed enum of operations; no expression evaluation."""
from src.schemas.tools import CalculateArgs
from src.tools.impl.base import ToolContext, ToolError


def calculate_metric(args: CalculateArgs, ctx: ToolContext) -> dict:
    v, op = args.values, args.operation.value

    def need(n):
        if len(v) < n:
            raise ToolError("invalid_arguments", f"{op} needs at least {n} values, received {len(v)}", "values")

    try:
        if op == "growth_rate":
            need(2); r = (v[-1] - v[0]) / v[0]; formula = "(last - first) / first"
        elif op == "cagr":
            need(2)
            if not args.period:
                raise ToolError("invalid_arguments", "cagr requires 'period' (number of years)", "period")
            if v[0] <= 0 or v[-1] < 0:
                raise ToolError("invalid_arguments", "cagr requires a positive start value", "values")
            r = (v[-1] / v[0]) ** (1 / args.period) - 1; formula = "(end / start) ** (1 / period) - 1"
        elif op == "share":
            need(2); r = v[0] / sum(v); formula = "values[0] / sum(values)"
        elif op == "ratio":
            need(2); r = v[0] / v[1]; formula = "values[0] / values[1]"
        elif op == "average":
            r = sum(v) / len(v); formula = "sum(values) / n"
        elif op == "sum":
            r = sum(v); formula = "sum(values)"
        elif op == "difference":
            need(2); r = v[0] - v[1]; formula = "values[0] - values[1]"
        elif op == "minimum":
            r = min(v); formula = "min(values)"
        elif op == "maximum":
            r = max(v); formula = "max(values)"
        else:  # unreachable: enum-validated
            raise ToolError("invalid_arguments", f"unsupported operation {op}", "operation")
    except ZeroDivisionError:
        raise ToolError("math_error", "division by zero for the supplied values", "values")
    pct = op in {"growth_rate", "cagr", "share"}
    return {"operation": op, "inputs": v, "period": args.period, "formula": formula,
            "result": round(r, 6), "result_display": f"{r * 100:.2f}%" if pct else f"{r:,.4g}"}
