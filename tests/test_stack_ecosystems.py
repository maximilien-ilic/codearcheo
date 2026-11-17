import pytest

from evals.shop import _commit, _git
from learn_it.analyzers import scan, stack
from learn_it.sources import Project

CASES = [
    ("pom.xml", '<project xmlns="http://maven.apache.org/POM/4.0.0"><dependencies><dependency>'
     '<groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId>'
     '</dependency></dependencies></project>', {"Maven", "Spring Boot"}),
    ("build.gradle", "dependencies { implementation 'org.springframework:spring-context:6' }",
     {"Gradle", "Spring"}),
    ("build.gradle.kts", 'dependencies { implementation("io.ktor:ktor-server-core:3") }',
     {"Gradle", "Ktor"}),
    ("Gemfile", 'source "https://rubygems.org"\ngem "rails", "~> 8"\n', {"Ruby", "Rails"}),
    ("composer.json", '{"require":{"laravel/framework":"^12"}}', {"PHP", "Laravel"}),
    ("web.csproj", '<Project Sdk="Microsoft.NET.Sdk.Web"><ItemGroup>'
     '<PackageReference Include="Microsoft.EntityFrameworkCore" Version="9"/>'
     '</ItemGroup></Project>', {".NET", "ASP.NET Core", "Entity Framework Core"}),
    ("providers.tf", '# provider comment\nterraform { required_providers { aws = {'
     'source = "hashicorp/aws" } } }\nprovider "aws" {}',
     {"Terraform", "Terraform provider: hashicorp/aws"}),
    ("deployment.yaml", 'apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: app\n',
     {"Kubernetes"}),
    ("Chart.yaml", 'apiVersion: v2\nname: app\nversion: 1.0.0\ndependencies:\n'
     '  - name: postgresql\n    version: "16"\n', {"Helm", "PostgreSQL"}),
]


@pytest.mark.parametrize("name,content,expected", CASES)
def test_each_ecosystem_reports_technologies_and_adoption(tmp_path, name, content, expected):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / name).write_text(content)
    _commit(tmp_path, "Introduce stack", "2024-02-01T10:00:00+00:00")
    profile = scan(Project(tmp_path, "demo"))
    technologies = {technology.name: technology for technology in profile.technologies}
    assert expected <= technologies.keys()
    assert all(technologies[key].adopted.subject == "Introduce stack" for key in expected)


@pytest.mark.parametrize("name,content", [
    ("pom.xml", '<project><dependency>'),
    ("pom.xml", '<!DOCTYPE foo [<!ENTITY x "secret">]><project>&x;</project>'),
    ("web.csproj", '<Project><PackageReference>'),
    ("composer.json", '{broken'),
    ("deployment.yaml", 'apiVersion: [unterminated'),
    ("pyproject.toml", '[invalid'),
    ("package.json", '{"dependencies":null}'),
    ("package.json", '{"dependencies":[123]}'),
    ("package.json", '[]'),
])
def test_malformed_manifests_are_ignored_without_execution(tmp_path, name, content):
    (tmp_path / name).write_text(content)
    technologies = stack.detect(tmp_path, [name])
    assert all(technology.category != "library" for technology in technologies)


def test_literal_gradle_map_and_namespaced_dotnet_are_supported(tmp_path):
    (tmp_path / "build.gradle").write_text(
        "implementation group: 'org.springframework', name: 'spring-context', version: '6'"
    )
    (tmp_path / "lib.csproj").write_text(
        '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">'
        '<ItemGroup><PackageReference Include="Npgsql" /></ItemGroup></Project>'
    )
    found = stack.detect(tmp_path, ["build.gradle", "lib.csproj"])
    assert {technology.name for technology in found} >= {"Spring", "PostgreSQL"}


def test_terraform_module_sources_are_not_reported_as_providers(tmp_path):
    (tmp_path / "modules.tf").write_text(
        'module "vpc" { source = "terraform-aws-modules/vpc/aws" }'
    )
    found = stack.detect(tmp_path, ["modules.tf"])
    assert [technology.name for technology in found] == ["Terraform"]


def test_root_manifest_wins_and_the_project_is_not_its_own_dependency(tmp_path):
    """Flask: examples/ sorts before pyproject.toml and its examples depend on flask."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "Flask"\ndependencies = ["click>=8.1"]\n'
    )
    example = tmp_path / "examples" / "celery"
    example.mkdir(parents=True)
    (example / "pyproject.toml").write_text(
        '[project]\nname = "flask-example-celery"\ndependencies = ["flask", "celery"]\n'
    )
    (example / "requirements.txt").write_text("click\nredis\n")
    files = ["examples/celery/pyproject.toml", "examples/celery/requirements.txt", "pyproject.toml"]

    sources = {t.name: t.source for t in stack.detect(tmp_path, files)}

    assert sources["Click"] == "pyproject.toml"
    assert "Flask" not in sources
    assert sources["Celery"] == "examples/celery/pyproject.toml"  # only found there: kept


def test_monorepo_members_are_not_technologies(tmp_path):
    for name, deps in [("a", '{"@acme/b": "1", "react": "19"}'), ("b", "{}")]:
        package = tmp_path / "packages" / name
        package.mkdir(parents=True)
        (package / "package.json").write_text(
            f'{{"name": "@acme/{name}", "dependencies": {deps}}}'
        )
    files = ["packages/a/package.json", "packages/b/package.json"]

    names = {t.name for t in stack.detect(tmp_path, files)}

    assert "React" in names and "@acme/b" not in names


@pytest.mark.parametrize("manifest,content,dependency,expected", [
    ("pyproject.toml", '[project]\nname = "redis"\n', "redis", "Redis"),
    ("Cargo.toml", '[package]\nname = "react"\n', "react", "React"),
    ("package.json", '{"name":"foo_bar"}', "foo-bar", "foo-bar"),
])
def test_internal_names_do_not_hide_distinct_npm_packages(
    tmp_path, manifest, content, dependency, expected,
):
    (tmp_path / manifest).write_text(content)
    app = tmp_path / "app"
    app.mkdir()
    (app / "package.json").write_text(
        '{"dependencies":{"' + dependency + '":"1"}}'
    )
    names = {t.name for t in stack.detect(tmp_path, [manifest, "app/package.json"])}
    assert expected in names


def test_python_internal_names_use_python_normalization(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "My_Package"\n')
    (tmp_path / "requirements.txt").write_text("my.package\nredis\n")
    names = {t.name for t in stack.detect(tmp_path, ["pyproject.toml", "requirements.txt"])}
    assert names == {"Redis"}


def test_fixture_package_name_does_not_hide_primary_dependency(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"react":"19"}}')
    fixture = tmp_path / "tests" / "fixtures" / "react"
    fixture.mkdir(parents=True)
    (fixture / "package.json").write_text('{"name":"react"}')
    names = {t.name for t in stack.detect(
        tmp_path, ["package.json", "tests/fixtures/react/package.json"],
    )}
    assert "React" in names


def test_technologies_only_found_in_examples_are_auxiliary(tmp_path):
    """Flask: Redis and Celery only come from examples/celery/ (#33)."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "flask"\ndependencies = ["click>=8.1"]\n'
    )
    example = tmp_path / "examples" / "celery"
    example.mkdir(parents=True)
    (example / "requirements.txt").write_text("celery\nclick\nredis\n")
    files = ["examples/celery/requirements.txt", "pyproject.toml"]

    auxiliary = {t.name: t.auxiliary for t in stack.detect(tmp_path, files)}

    assert auxiliary == {"Click": False, "Celery": True, "Redis": True}
