"""calculate 工具的安全性与正确性测试。

这组测试的分量高于普通单测：它锁死了"数学求值绝不使用 eval"这条底线。
历史上这个项目就是直接用 eval 的，等于把 shell 暴露给了 HTTP 接口。
任何让危险表达式重新得以执行的改动，都会在这里被拦下。
"""

import pytest

from agent.tools import calculate


def calc(expression: str) -> str:
    return calculate.invoke({"expression": expression})


class TestCorrectness:
    @pytest.mark.parametrize("expression,expected", [
        ("123 * 456", "56088"),
        ("2 ** 10", "1024"),
        ("(1 + 2) * 3.5", "10.5"),
        ("sqrt(16)", "4"),
        ("factorial(5)", "120"),
        ("sum(range(1, 101))", "5050"),
        ("sum(range(1, 10, 2))", "25"),
        ("-5 + abs(-3)", "-2"),
        ("10 / 4", "2.5"),
        ("8888 + 9999", "18887"),
        ("15 % 4", "3"),
        ("round(3.14159, 2)", "3.14"),
        ("3.14 * 5 ** 2", "78.5"),
    ])
    def test_evaluates(self, expression, expected):
        assert calc(expression) == expected

    @pytest.mark.parametrize("expression,expected", [
        ("pi * 2", 6.283185307179586),
        ("sqrt(2) + pi", 4.555806215962888),
        ("100 * 0.15", 15.0),
    ])
    def test_float_values(self, expression, expected):
        assert float(calc(expression)) == pytest.approx(expected, rel=1e-6)

    def test_integer_result_has_no_decimal(self):
        """整数结果不应输出成 4.0 这种形式。"""
        assert calc("sqrt(16)") == "4"

    def test_caret_means_power(self):
        """用户与模型习惯用 ^ 表示乘方，而 Python 中 ^ 是按位异或。

        若不转换，"7 的 3 次方"被写成 7^3 时会直接报 BitXor 不支持，
        模型只能转述失败——这是评测里真实出现过的用例（math_018）。
        """
        assert calc("7 ^ 3") == "343"
        assert calc("7 ^ 3 - 100") == "243"
        assert calc("2 ^ 10") == "1024"

    def test_empty_expression(self):
        assert "计算失败" in calc("")
        assert "计算失败" in calc("   ")


class TestSecurity:
    """所有危险输入都必须被拒绝，绝不能被执行。"""

    @pytest.mark.parametrize("expression", [
        "__import__('os').system('echo pwned')",
        "__import__('subprocess').run(['ls'])",
        "open('agent.db').read()",
        "open('/etc/passwd').read()",
        "eval('1+1')",
        "exec('x = 1')",
        "compile('1', '<s>', 'eval')",
        "().__class__.__bases__[0].__subclasses__()",
        "''.__class__.__mro__",
        "[x for x in range(10)]",
        "{k: v for k, v in []}",
        "globals()",
        "locals()",
        "vars()",
        "dir()",
        "getattr(int, 'real')",
        "int.__dict__",
        "1 if True else 2",
        "lambda: 1",
        "(lambda: 1)()",
    ])
    def test_dangerous_expressions_rejected(self, expression):
        result = calc(expression)
        assert result.startswith("计算失败"), f"危险表达式未被拒绝：{expression} -> {result}"

    def test_command_execution_does_not_happen(self):
        """即使表达式里带了命令，输出中也不能出现命令执行结果。"""
        result = calc("__import__('os').system('echo pwned')")
        assert "pwned" not in result

    def test_file_content_not_leaked(self):
        result = calc("open('agent.db').read()")
        assert "SQLite" not in result
        assert "root" not in result

    def test_no_attribute_access(self):
        """属性访问（__class__ 等）是沙箱逃逸的常见入口，必须封死。"""
        assert calc("().__class__").startswith("计算失败")

    def test_non_numeric_constant_rejected(self):
        assert calc("'abc' + 1").startswith("计算失败")
        assert calc("'abc'").startswith("计算失败")

    def test_boolean_is_not_treated_as_number(self):
        """bool 是 int 的子类，若不显式排除就会被当成 1/0 参与运算。"""
        assert calc("True + 1").startswith("计算失败")


class TestResourceLimits:
    """拒绝会耗尽 CPU 或内存的表达式。"""

    @pytest.mark.parametrize("expression", [
        "9 ** 9 ** 9",          # 算力炸弹
        "10 ** 100000",          # 超大幂
        "factorial(99999)",      # 阶乘溢出
        "sum(range(1, 10**12))", # 内存炸弹
    ])
    def test_resource_bombs_rejected(self, expression):
        assert calc(expression).startswith("计算失败")

    def test_division_by_zero(self):
        assert calc("1 / 0") == "计算失败: 除数为 0"

    def test_oversized_expression_rejected(self):
        assert "过长" in calc("1 + 1" * 100)

    def test_range_with_zero_step(self):
        assert calc("sum(range(1, 101, 0))").startswith("计算失败")
