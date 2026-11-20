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


def test_adoption_is_traced_back_through_manifest_migrations(tmp_path):
    """Flask: Click is older than the switch to pyproject.toml (#32)."""
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "setup.py").write_text('setup(install_requires=["click"])\n')
    _commit(tmp_path, "Use click for the CLI", "2014-05-01T10:00:00+00:00")
    (tmp_path / "setup.py").unlink()
    (tmp_path / "setup.cfg").write_text("[options]\ninstall_requires =\n    click>=7\n")
    _commit(tmp_path, "Move metadata to setup.cfg", "2019-03-01T10:00:00+00:00")
    (tmp_path / "setup.cfg").unlink()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["click>=8", "rich"]\n'
    )
    _commit(tmp_path, "switch to pyproject.toml", "2023-01-18T10:00:00+00:00")

    techs = {t.name: t for t in scan(Project(tmp_path, "app")).technologies}

    assert techs["Click"].adopted.subject == "Use click for the CLI"
    assert techs["Click"].adopted_from == "setup.py"
    assert techs["Click"].source == "pyproject.toml"


def test_a_dependency_new_with_its_manifest_keeps_that_date(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "requirements.txt").write_text("requests\n")
    _commit(tmp_path, "First version", "2020-01-01T10:00:00+00:00")
    (tmp_path / "requirements.txt").unlink()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["requests", "fastapi"]\n'
    )
    _commit(tmp_path, "switch to pyproject.toml and add FastAPI", "2023-01-18T10:00:00+00:00")

    fastapi = next(t for t in scan(Project(tmp_path, "app")).technologies if t.name == "FastAPI")

    assert fastapi.adopted.subject == "switch to pyproject.toml and add FastAPI"
    assert fastapi.adopted_from is None


def test_a_removed_dependency_is_not_a_manifest_migration(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("fastapi\n")
    _commit(tmp_path, "Old prototype", "2020-01-01T10:00:00+00:00")
    requirements.write_text("click\n")
    _commit(tmp_path, "Remove prototype", "2021-01-01T10:00:00+00:00")
    requirements.unlink()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["fastapi", "click"]\n'
    )
    _commit(tmp_path, "Migrate click and adopt FastAPI", "2023-01-18T10:00:00+00:00")

    techs = {t.name: t for t in scan(Project(tmp_path, "app")).technologies}

    assert techs["FastAPI"].adopted.subject == "Migrate click and adopt FastAPI"
    assert techs["FastAPI"].adopted_from is None
    assert techs["Click"].adopted.subject == "Remove prototype"


def test_a_dependency_kept_in_a_renamed_manifest_is_not_a_migration(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("fastapi\n")
    _commit(tmp_path, "Adopt FastAPI in a component", "2020-01-01T10:00:00+00:00")
    component = tmp_path / "component"
    component.mkdir()
    requirements.rename(component / requirements.name)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["fastapi"]\n'
    )
    _commit(tmp_path, "Adopt FastAPI at the root", "2023-01-18T10:00:00+00:00")

    techs = {t.name: t for t in scan(Project(tmp_path, "app")).technologies}

    assert techs["FastAPI"].source == "pyproject.toml"
    assert techs["FastAPI"].adopted.subject == "Adopt FastAPI at the root"
    assert techs["FastAPI"].adopted_from is None


def test_adoption_is_traced_when_the_old_manifest_is_archived(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("fastapi\n")
    _commit(tmp_path, "Adopt FastAPI", "2020-01-01T10:00:00+00:00")
    requirements.rename(tmp_path / "requirements.txt.bak")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["fastapi"]\n'
    )
    _commit(tmp_path, "Migrate to pyproject.toml", "2023-01-18T10:00:00+00:00")

    fastapi = next(t for t in scan(Project(tmp_path, "app")).technologies if t.name == "FastAPI")

    assert fastapi.source == "pyproject.toml"
    assert fastapi.adopted.subject == "Adopt FastAPI"
    assert fastapi.adopted_from == "requirements.txt"


def test_plain_php_without_manifest_reports_php_and_its_database(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "index.php").write_text("<?php include 'header.php'; ?>\n")
    _commit(tmp_path, "Start the site", "2024-02-01T10:00:00+00:00")
    (tmp_path / "ajouter.php").write_text(
        "<?php\n$pdo = new PDO('pgsql:host=localhost;dbname=f1', 'app', '');\n"
    )
    (tmp_path / "notes.php").write_text("<?php // TODO: maybe mysql: later, no connection\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "fixture.php").write_text("<?php $db = mysqli_connect('h');\n")
    _commit(tmp_path, "Connect to the database", "2024-02-03T10:00:00+00:00")

    technologies = {t.name: t for t in scan(Project(tmp_path, "demo")).technologies}

    assert technologies["PHP"].source == "index.php"
    assert technologies["PHP"].adopted.subject == "Start the site"
    assert technologies["PostgreSQL"].source == "ajouter.php"
    assert technologies["PostgreSQL"].adopted.subject == "Connect to the database"
    assert technologies["MySQL"].auxiliary  # only a test fixture connects to it
    assert {"PHP", "PostgreSQL", "MySQL"} == technologies.keys()


@pytest.mark.parametrize("code,expected", [
    ("$db = new \\PDO(\"mysql:host=db\");", {"MySQL"}),
    ("$db = new PDO( 'sqlite:/tmp/app.db' );", {"SQLite"}),
    ("$db = new mysqli('h', 'u', 'p');", {"MySQL"}),
    ("$dsn = 'mysql:host=db'; // passed to a factory", set()),
    ("// $db = new PDO('pgsql:host=db');", set()),
    ("# mysqli_connect('host');", set()),
    ("/*\n$db = new mysqli('host');\n*/", set()),
    ("$example = \"new PDO('sqlite:example.db')\";", set()),
    ("$example = \"mysqli_connect('host')\";", set()),
    ("// new PDO('pgsql:host=db');\n$db = new PDO('sqlite:app.db');", {"SQLite"}),
])
def test_php_database_signals_need_an_actual_connection(tmp_path, code, expected):
    (tmp_path / "db.php").write_text(f"<?php\n{code}\n")
    found = {t.name for t in stack.detect(tmp_path, ["db.php"]) if t.category == "data"}
    assert found == expected


@pytest.mark.parametrize("template,expected", [
    ("""<div data-db="<?php $db = new PDO('sqlite:app.db'); ?>">""", {"SQLite"}),
    ("""<?php echo '?>'; ?> <pre>new PDO('pgsql:example');</pre>""", set()),
    ("""<?php // comment ?> <?= mysqli_connect('host') ?>""", {"MySQL"}),
    ("<?php\n$x = <<<EOT\nnew PDO('pgsql:x') ?>\nEOT;\n$d = new PDO('sqlite:a');", {"SQLite"}),
    ("<?php\n$x = <<<'SQL'\nit's new PDO('pgsql:x')\nSQL;\n", set()),
])
def test_php_database_signals_in_mixed_templates(tmp_path, template, expected):
    (tmp_path / "index.php").write_text(template)

    found = {t.name for t in stack.detect(tmp_path, ["index.php"]) if t.category == "data"}

    assert found == expected


@pytest.mark.parametrize("manifest,source", [
    ("composer.json", "composer.json"),
    ("examples/composer.json", "index.php"),
])
def test_php_source_prefers_a_main_manifest_over_a_php_file(tmp_path, manifest, source):
    (tmp_path / manifest).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / manifest).write_text("{}")
    (tmp_path / "index.php").write_text("<?php\n")

    php = next(t for t in stack.detect(tmp_path, ["index.php", manifest]) if t.name == "PHP")

    assert php.source == source
