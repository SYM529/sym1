"""上传文件管控测试。

这组测试的核心是**路径安全**。

file_id 完全来自请求参数——而且是被模型透传的参数，属于最不可信的一类输入。
所以下面两件事必须由测试锁死，一旦有人为了"方便"直接拼路径就会被拦下：

1. 不能读到别人的文件（跨用户越权）
2. 不能读到上传目录以外的文件（路径穿越）

其余覆盖项：类型白名单、大小边界、以及"磁盘名与用户原始文件名解耦"。
"""

import pytest

from server import uploads


class TestClassify:
    @pytest.mark.parametrize("filename,kind", [
        ("photo.png", uploads.KIND_IMAGE),
        ("photo.PNG", uploads.KIND_IMAGE),
        ("a.jpg", uploads.KIND_IMAGE),
        ("a.jpeg", uploads.KIND_IMAGE),
        ("scan.webp", uploads.KIND_IMAGE),
        ("anim.gif", uploads.KIND_IMAGE),
        ("report.pdf", uploads.KIND_DOCUMENT),
        ("README.md", uploads.KIND_DOCUMENT),
        ("notes.markdown", uploads.KIND_DOCUMENT),
        ("raw.txt", uploads.KIND_DOCUMENT),
    ])
    def test_supported_types(self, filename, kind):
        assert uploads.classify_file(filename) == kind

    @pytest.mark.parametrize("filename", [
        "malware.exe",
        "script.sh",
        "no_suffix",
        "",
        "archive.zip",
    ])
    def test_unsupported_types_are_rejected(self, filename):
        with pytest.raises(uploads.UploadRejected):
            uploads.classify_file(filename)

    def test_suffix_of_handles_missing_suffix(self):
        assert uploads.suffix_of("README") == ""
        assert uploads.suffix_of("") == ""
        assert uploads.suffix_of("IMAGE.JPG") == ".jpg"


class TestSizeLimit:
    def test_accepts_zero_to_limit_inclusive(self):
        uploads.check_size(uploads.KIND_IMAGE, 1)
        uploads.check_size(uploads.KIND_IMAGE, uploads.MAX_IMAGE_BYTES)
        uploads.check_size(uploads.KIND_DOCUMENT, uploads.MAX_DOC_BYTES)

    def test_rejects_over_limit(self):
        with pytest.raises(uploads.UploadRejected):
            uploads.check_size(uploads.KIND_IMAGE, uploads.MAX_IMAGE_BYTES + 1)

    def test_rejects_empty_file(self):
        with pytest.raises(uploads.UploadRejected):
            uploads.check_size(uploads.KIND_IMAGE, 0)

    def test_document_limit_is_larger_than_image(self):
        # 图片要按 token 计费，配额必须更紧
        assert uploads.MAX_DOC_BYTES > uploads.MAX_IMAGE_BYTES


class TestSave:
    def test_disk_name_is_decoupled_from_client_filename(self, tmp_path):
        # 文件名是用户输入，绝不能直接用它拼路径
        info = uploads.save_upload(
            1, "../../../evil name.png", b"\x89PNG\r\n\x1a\n", root=tmp_path
        )

        owner, disk_name = info["file_id"].split("/")
        assert owner == "u1"
        assert "/" not in disk_name and "\\" not in disk_name
        assert "evil" not in disk_name
        assert disk_name.endswith(".png")
        assert (tmp_path / "u1" / disk_name).is_file()

    def test_original_name_kept_for_display_only(self, tmp_path):
        info = uploads.save_upload(1, "bad/name.pdf", b"%PDF-1.4", root=tmp_path)
        # 原始名中的目录部分不留档，只保留 basename 用于展示
        assert info["filename"] == "name.pdf"
        assert info["kind"] == uploads.KIND_DOCUMENT

    def test_files_are_isolated_per_user(self, tmp_path):
        first = uploads.save_upload(1, "a.png", b"data1", root=tmp_path)
        second = uploads.save_upload(2, "a.png", b"data2", root=tmp_path)

        assert first["file_id"] != second["file_id"]
        assert first["file_id"].startswith("u1/")
        assert second["file_id"].startswith("u2/")


class TestResolve:
    def test_owner_can_resolve_own_file(self, tmp_path):
        info = uploads.save_upload(5, "pic.png", b"data", root=tmp_path)
        path = uploads.resolve_user_file(5, info["file_id"], root=tmp_path)

        assert path.is_file()
        assert path.read_bytes() == b"data"

    def test_other_user_cannot_resolve(self, tmp_path):
        info = uploads.save_upload(1, "pic.png", b"secret", root=tmp_path)

        # 越权读取必须失败——这是最容易被忽略、后果也最严重的一条
        with pytest.raises(uploads.UploadRejected):
            uploads.resolve_user_file(2, info["file_id"], root=tmp_path)

    @pytest.mark.parametrize("file_id", [
        "u1/../../etc/passwd",
        "u1/..\\..\\secret.txt",
        "u1/",
        "u1/.hidden",
        "u1",
        "",
        "evil.txt",
    ])
    def test_rejects_malformed_or_traversal_ids(self, file_id, tmp_path):
        with pytest.raises(uploads.UploadRejected):
            uploads.resolve_user_file(1, file_id, root=tmp_path)

    def test_missing_file_is_rejected(self, tmp_path):
        with pytest.raises(uploads.UploadRejected):
            uploads.resolve_user_file(1, "u1/does-not-exist.png", root=tmp_path)


class TestResolveUploaded:
    def test_requires_request_identity(self):
        # 没有把当前请求的用户放进上下文时，解析必须失败，
        # 不能因为 file_id 里带了 u1 就默认归属 u1。
        with pytest.raises(uploads.UploadRejected):
            uploads.resolve_uploaded("u1/anything.png")
