from commitscope.git.repository import repo_name_from_url


def test_repo_name_from_github_url() -> None:
    assert repo_name_from_url("https://github.com/example/project.git") == "project"
