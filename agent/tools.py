import ast
import math
import operator
import os
from datetime import datetime
from langchain_core.tools import tool
from tavily import TavilyClient

# 时区必须是显式配置，不能依赖宿主机的系统时间：
# 这个服务主要跑在 Docker 里，容器默认是 UTC，直接 datetime.now()
# 会比北京时间慢 8 小时——"现在几点"是用户最容易核验对错的答案。
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Shanghai")

try:
    from zoneinfo import ZoneInfo

    _LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)
except Exception:
    # tz 数据缺失（如精简镜像/未装 tzdata 的 Windows）时退回系统时间，
    # 宁可可能差几个小时，也不要让工具直接报错
    _LOCAL_TZ = None


# ============ 安全数学求值：基于 AST 白名单，绝不使用 eval ============

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# 只暴露无副作用的纯数学函数
_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "sqrt": math.sqrt, "pow": math.pow, "log": math.log, "log10": math.log10,
    "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "floor": math.floor, "ceil": math.ceil, "factorial": math.factorial,
}

_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

_MAX_EXPR_LEN = 200
_MAX_ABS_EXPONENT = 1000      # 拦住 9**9**9 这类算力炸弹
_MAX_FACTORIAL = 1000
_MAX_RANGE_LEN = 100_000      # 拦住 sum(range(1, 10**12)) 这类内存炸弹


def _eval_range(node: ast.Call) -> list:
    """求值 range(...)，供 sum(range(1, 101)) 这类求和表达式使用。

    只接受整数参数，并限制序列长度——否则 sum(range(1, 10**12)) 会直接打满内存。
    """
    args = [_eval_node(a) for a in node.args]
    if not 1 <= len(args) <= 3:
        raise ValueError("range 只接受 1-3 个参数")

    values = []
    for a in args:
        if not isinstance(a, int):
            raise ValueError("range 参数必须是整数")
        values.append(a)

    # len(range(...)) 是 O(1) 计算，不会因区间超大而卡死
    if len(range(*values)) > _MAX_RANGE_LEN:
        raise ValueError(f"range 序列过长（上限 {_MAX_RANGE_LEN} 项）")
    return list(range(*values))


def _eval_node(node):
    """递归求值 AST 节点，只放行白名单内的语法结构。"""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)

    if isinstance(node, ast.Constant):
        # bool 是 int 的子类，显式排除，避免 True/False 被当成数字
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError(f"不支持的常量: {node.value!r}")
        return node.value

    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        left, right = _eval_node(node.left), _eval_node(node.right)
        if op is operator.pow and (abs(right) > _MAX_ABS_EXPONENT or abs(left) > 10 ** 6):
            raise ValueError("幂运算规模过大")
        return op(left, right)

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        return op(_eval_node(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("只支持直接调用数学函数")
        if node.keywords:
            raise ValueError("不支持关键字参数")
        # range 生成的是序列而非标量，单独走一路，供 sum/求和类表达式使用
        if node.func.id == "range":
            return _eval_range(node)

        func = _FUNCS.get(node.func.id)
        if func is None:
            raise ValueError(f"不允许调用函数: {node.func.id}")
        if node.keywords:
            raise ValueError("不支持关键字参数")
        args = [_eval_node(a) for a in node.args]
        if func is sum:
            for a in args:
                if isinstance(a, list) and len(a) > _MAX_RANGE_LEN:
                    raise ValueError("求和序列过长")
        if func is math.factorial:
            for a in args:
                if not isinstance(a, int) or a < 0 or a > _MAX_FACTORIAL:
                    raise ValueError("阶乘参数非法或过大")
        return func(*args)

    if isinstance(node, ast.Name):
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise ValueError(f"不允许使用变量: {node.id}")

    raise ValueError(f"不支持的语法: {type(node).__name__}")


@tool
def calculate(expression: str) -> str:
    """执行数学计算。当用户需要精确数值计算时使用，输入是数学表达式，例如 "123 * 456" 或 "sqrt(2) + pi"。"""
    try:
        expr = expression.strip()
        if not expr:
            return "计算失败: 表达式为空"
        # 用户和模型常把 ^ 当作乘方（Excel 与数学书写习惯），
        # 而 Python 里 ^ 是按位异或。对面向自然语言的数学工具来说，
        # 按乘方解释更符合直觉，否则「7 的 3 次方」写成 7^3 会直接报 BitXor 不支持。
        expr = expr.replace("^", "**")
        if len(expr) > _MAX_EXPR_LEN:
            return f"计算失败: 表达式过长（上限 {_MAX_EXPR_LEN} 字符）"

        value = _eval_node(ast.parse(expr, mode="eval"))

        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return "计算失败: 结果不是有限数值"
            if value.is_integer():
                return str(int(value))
        return str(value)
    except ZeroDivisionError:
        return "计算失败: 除数为 0"
    except ValueError as e:
        return f"计算失败: {e}"
    except Exception as e:
        return f"计算失败: {type(e).__name__}"

@tool
def get_current_time() -> str:
    """仅当用户明确询问'现在几点''当前时间''今天几号'时使用。不要用它推断天气或新闻等实时信息。"""
    now = datetime.now(_LOCAL_TZ) if _LOCAL_TZ else datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

_tavily = None


def _tavily_client() -> TavilyClient:
    """懒加载 Tavily 客户端：缺 Key 时只在真正搜索时报错，不影响服务启动。"""
    global _tavily
    if _tavily is None:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise RuntimeError("未配置 TAVILY_API_KEY")
        _tavily = TavilyClient(api_key=api_key)
    return _tavily


@tool
def web_search(query: str) -> str:
    """联网搜索实时信息。涉及天气、新闻、股票、赛事、当前事件等必须使用此工具。"""
    try:
        result = _tavily_client().search(query, max_results=3)
        formatted = "\n".join([
            f"- {r['title']}: {r['content'][:200]}"
            for r in result.get("results", [])
        ])
        return formatted or "没有找到相关结果"
    except Exception as e:
        return f"搜索失败: {e}"