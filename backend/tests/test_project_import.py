import io
import zipfile

import pytest

from app.services import project_import as pi


def make_zip(files: dict[str, str | bytes], root: str | None = "repo-main") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(f"{root}/{name}" if root else name, content)
    return buf.getvalue()


CODE = "def handler(event):\n    return {'ok': True, 'event': event}\n"


class TestExtraction:
    def test_indexes_code_and_docs_and_builds_overview(self):
        project = pi.extract_project_from_zip(make_zip({"README.md": "# Demo\n" + "text " * 20, "src/app.py": CODE}), "demo")
        names = [n for n, _ in project.files]
        assert names[0] == "demo/PROJECT_OVERVIEW.md"
        assert {"demo/README.md", "demo/src/app.py"} <= set(names)
        overview = dict(project.files)["demo/PROJECT_OVERVIEW.md"].decode()
        assert "src/" in overview and "app.py" in overview

    def test_skips_dependencies_build_output_lockfiles_minified_and_binaries(self):
        project = pi.extract_project_from_zip(make_zip({
            "src/app.py": CODE,
            "node_modules/lib/index.js": CODE,
            "dist/bundle.js": CODE,
            "package-lock.json": "{" + '"a":1,' * 20 + "}",
            "static/app.min.js": CODE,
            "logo.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
            "data.bin": b"\x00" * 100,
        }), "demo")
        indexed = [n for n, _ in project.files if not n.endswith("PROJECT_OVERVIEW.md")]
        assert indexed == ["demo/src/app.py"]
        assert project.skipped >= 5

    def test_path_traversal_entries_are_rejected(self):
        project = pi.extract_project_from_zip(make_zip({"src/app.py": CODE, "../evil.py": CODE}), "demo")
        assert not any("evil" in n for n, _ in project.files)

    def test_file_cap_keeps_the_most_important_files(self):
        files = {f"pkg/mod{i:03}.py": CODE for i in range(pi.MAX_PROJECT_FILES + 25)}
        files["README.md"] = "# Readme\n" + "words " * 20
        project = pi.extract_project_from_zip(make_zip(files), "big")
        assert project.truncated
        assert len(project.files) == pi.MAX_PROJECT_FILES + 1            # + overview
        assert "big/README.md" in dict(project.files)

    def test_empty_or_unsupported_archive_is_an_error(self):
        with pytest.raises(ValueError):
            pi.extract_project_from_zip(make_zip({"logo.png": b"\x89PNG" + b"\x00" * 50}), "x")

    def test_not_a_zip_is_an_error(self):
        with pytest.raises(ValueError):
            pi.extract_project_from_zip(b"definitely not a zip", "x")


class TestNaming:
    def test_project_names_never_contain_path_separators(self):
        assert pi.safe_project_name("a/b\\c") == "a-b-c"
        assert "/" not in pi.safe_project_name("../../etc")

    def test_zip_root_folder_is_stripped_and_name_sanitised(self):
        project = pi.extract_project_from_zip(make_zip({"src/app.py": CODE}), "owner/repo")
        assert all(n.startswith("owner-repo/") for n, _ in project.files)


class TestGithubUrl:
    @pytest.mark.parametrize("url,expected", [
        ("https://github.com/vercel/next.js", ("vercel", "next.js", None)),
        ("github.com/a/b.git", ("a", "b", None)),
        ("https://github.com/a/b/tree/dev", ("a", "b", "dev")),
    ])
    def test_valid(self, url, expected):
        assert pi.parse_github_url(url) == expected

    @pytest.mark.parametrize("url", [
        "https://evil.com/github.com/a/b",
        "https://gitlab.com/a/b",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        "not a url",
    ])
    def test_rejects_anything_that_is_not_a_github_repo(self, url):
        with pytest.raises(ValueError):
            pi.parse_github_url(url)
