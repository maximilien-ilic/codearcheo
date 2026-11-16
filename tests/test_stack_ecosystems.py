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
