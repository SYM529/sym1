"""新支持文档格式的解析测试。

只覆盖**不需要第三方依赖**的解析路径（CSV / HTML / 纯文本），
因此这些用例在 CI 里无需安装 Office 解析库也能跑。
Office 格式的解析走可选依赖，缺库时的错误提示另有用例覆盖。
"""

from pathlib import Path

import pytest

from agent.rag.loader import (
    SUPPORTED_SUFFIXES,
    TEXT_SUFFIXES,
    _read_csv,
    _read_html,
    load_document,
)


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestSupportedFormats:
    def test_common_formats_are_supported(self):
        """这些格式必须被支持，否则用户会误以为上传失败是系统问题。"""
        expected = {
            ".pdf", ".md", ".markdown", ".txt", ".log", ".csv",
            ".html", ".htm", ".docx", ".xlsx", ".pptx", ".json",
        }
        assert expected <= SUPPORTED_SUFFIXES

    def test_text_suffixes_read_as_plain(self):
        assert {".md", ".txt", ".json"} <= TEXT_SUFFIXES

    def test_unknown_suffix_rejected(self, tmp_path):
        path = write(tmp_path, "a.exe", "MZ\x00\x00")
        with pytest.raises(ValueError, match="不支持的文件类型"):
            load_document(path)


class TestCsv:
    def test_converts_to_markdown_table(self, tmp_path):
        path = write(tmp_path, "data.csv", "姓名,年龄\n张三,30\n李四,25\n")
        text = _read_csv(path)
        assert text.startswith("| 姓名 | 年龄 |")
        assert "| --- | --- |" in text
        assert "| 张三 | 30 |" in text

    def test_ragged_rows_are_padded(self, tmp_path):
        """列数不齐必须补齐：Markdown 表格缺列会导致后续渲染错乱。"""
        path = write(tmp_path, "r.csv", "a,b,c\n1,2\n")
        text = _read_csv(path)
        body = text.splitlines()[2]
        assert body.count("|") == 4  # 三列：首尾 + 两个分隔


class TestHtml:
    def test_strips_tags_and_scripts(self, tmp_path):
        html = (
            "<html><body><h1>标题</h1><p>正文内容</p>"
            "<script>alert('x')</script><style>.a{color:red}</style></body></html>"
        )
        path = write(tmp_path, "page.html", html)
        text = _read_html(path)
        assert "标题" in text and "正文内容" in text
        # script / style 里的东西不应进知识库
        assert "alert" not in text
        assert "color:red" not in text

    def test_collapses_blank_lines(self, tmp_path):
        path = write(tmp_path, "p.htm", "<p>a</p><br><br><br><p>b</p>")
        text = _read_html(path)
        assert "" not in text.splitlines()


class TestMissingOptionalDep:
    def test_clear_error_when_lib_missing(self, tmp_path, monkeypatch):
        """缺 Office 解析库时应给出可操作的安装提示，而不是裸 ImportError。"""
        import agent.rag.loader as loader

        def boom(_path):
            raise ImportError("No module named 'docx'")

        monkeypatch.setitem(loader._READERS, ".docx", boom)
        monkeypatch.setitem(loader.OPTIONAL_DEPS, ".docx", "python-docx")

        path = write(tmp_path, "x.docx", "whatever")
        with pytest.raises(ValueError, match="pip install python-docx"):
            loader.load_document(path)
