from textwrap import dedent

from tree_sitter import Parser
from tree_sitter_language_pack import get_language

from smritikosh.indexing.extractor import extract_file
from smritikosh.indexing.graph import graph_file, resolve
from smritikosh.models import ParsedFile


def _graph(path: str, source: str, language: str = "python"):
    source = dedent(source)
    tree = Parser(get_language(language)).parse(source.encode())
    parsed = ParsedFile(path=path, language=language, content=source, tree=tree)
    return graph_file(parsed, extract_file(parsed, has_tags_scm=True))


def _edges(files: dict[str, str]) -> set[tuple[str, str]]:
    graph: list[list] = [[], [], [], [], []]
    for path, source in files.items():
        for rows, found in zip(graph, _graph(path, source), strict=True):
            rows += found
    return {(e.src, e.dst) for e in resolve(set(files), *graph)}


def test_should_name_methods_after_their_class() -> None:
    symbols, *_ = _graph(
        "a.py",
        """
        class Repo:
            def __init__(self): ...
            def save(self): ...

        def save(): ...
        """,
    )

    assert {(s.id, s.kind, s.parent) for s in symbols} == {
        ("a.py:Repo", "class", None),
        ("a.py:Repo.__init__", "method", "a.py:Repo"),
        ("a.py:Repo.save", "method", "a.py:Repo"),
        ("a.py:save", "function", None),
    }


def test_should_skip_builtins_and_module_level_calls() -> None:
    _, calls, *_ = _graph(
        "a.py",
        """
        def run():
            print(len([]))
            helper()

        run()
        """,
    )

    assert [(c.scope, c.name, c.line) for c in calls] == [("a.py:run", "helper", 4)]


def test_should_return_nothing_for_languages_without_refs_query() -> None:
    assert _graph("A.java", "class A { void f() { g(); } }", "java") == (
        [],
        [],
        [],
        [],
        [],
    )


def test_should_resolve_calls_within_a_file() -> None:
    edges = _edges(
        {
            "a.py": """
            def helper(): ...

            def run():
                helper()
            """
        }
    )

    assert edges == {("a.py:run", "a.py:helper")}


def test_should_resolve_self_calls_to_the_enclosing_class() -> None:
    edges = _edges(
        {
            "a.py": """
            class Cache:
                def update(self): ...

                def refresh(self):
                    self.update()

            class Other:
                def update(self): ...
            """
        }
    )

    assert edges == {("a.py:Cache.refresh", "a.py:Cache.update")}


def test_should_resolve_methods_called_on_a_new_instance() -> None:
    edges = _edges(
        {
            "repo.py": """
            class Repo:
                def save(self): ...
            """,
            "app.py": """
            from repo import Repo

            def run():
                Repo().save()
            """,
        }
    )

    assert edges == {
        ("app.py:run", "repo.py:Repo"),
        ("app.py:run", "repo.py:Repo.save"),
    }


def test_should_not_guess_methods_on_a_returned_value() -> None:
    edges = _edges(
        {
            "a.py": """
            class Repo:
                def save(self): ...

            def make_repo(): ...

            def run():
                make_repo().save()
            """
        }
    )

    assert edges == {("a.py:run", "a.py:make_repo")}


def test_should_record_calls_on_attributes_and_returned_values() -> None:
    _, calls, *_ = _graph(
        "a.py",
        """
        def run(self):
            self.client.send()
            Factory.get_client().send()
        """,
    )

    assert [(c.receiver, c.name) for c in calls if c.name == "send"] == [
        ("self.client", "send"),
        ("Factory.get_client", "send"),
    ]


def test_should_resolve_a_typed_parameter() -> None:
    edges = _edges(
        {
            "sms.py": "class Sms:\n    def send(self): ...",
            "app.py": """
            from sms import Sms

            def notify(channel: Sms):
                channel.send()
            """,
        }
    )

    assert edges == {("app.py:notify", "sms.py:Sms.send")}


def test_should_resolve_a_type_named_through_a_module() -> None:
    edges = _edges(
        {
            "app/__init__.py": "",
            "app/models.py": "class Account:\n    def save(self): ...",
            "svc.py": """
            from app import models

            def run(account: models.Account):
                account.save()
            """,
        }
    )

    assert edges == {("svc.py:run", "app/models.py:Account.save")}


def test_should_resolve_a_local_built_from_a_class() -> None:
    edges = _edges(
        {
            "a.py": """
            class Repo:
                def save(self): ...

            def make_repo(): ...

            def run():
                repo = Repo()
                repo.save()
                other: Repo = make_repo()
                other.save()
            """
        }
    )

    assert ("a.py:run", "a.py:Repo.save") in edges


def test_should_resolve_an_attribute_set_in_another_method() -> None:
    edges = _edges(
        {
            "a.py": """
            class Client:
                def get(self): ...

            class Service:
                def __init__(self):
                    self.client = Client()

                def run(self):
                    self.client.get()
            """
        }
    )

    assert ("a.py:Service.run", "a.py:Client.get") in edges


def test_should_not_guess_when_a_name_holds_two_classes() -> None:
    edges = _edges(
        {
            "a.py": """
            class A:
                def go(self): ...

            class B:
                def go(self): ...

            def run():
                x = A()
                x = B()
                x.go()
            """
        }
    )

    assert edges == {("a.py:run", "a.py:A"), ("a.py:run", "a.py:B")}


def test_should_find_inherited_methods_on_self() -> None:
    edges = _edges(
        {
            "base.py": "class Base:\n    def helper(self): ...",
            "a.py": """
            from base import Base

            class Child(Base):
                def run(self):
                    self.helper()
            """,
        }
    )

    assert edges == {("a.py:Child.run", "base.py:Base.helper")}


def test_should_find_inherited_methods_on_a_class() -> None:
    edges = _edges(
        {
            "a.py": """
            class Singleton:
                @classmethod
                def instance(cls): ...

            class Client(Singleton):
                pass

            def run():
                Client.instance()
            """
        }
    )

    assert edges == {("a.py:run", "a.py:Singleton.instance")}


def test_should_stop_at_a_base_class_from_a_library() -> None:
    edges = _edges(
        {
            "test_a.py": """
            from unittest import TestCase

            class TestA(TestCase):
                def test_it(self):
                    self.assertEqual(1, 1)
            """
        }
    )

    assert edges == set()


def test_should_stop_when_base_classes_loop() -> None:
    edges = _edges(
        {
            "a.py": """
            class A(B):
                def run(self):
                    self.missing()

            class B(A):
                pass
            """
        }
    )

    assert edges == set()


def test_should_not_guess_the_target_of_an_untyped_receiver() -> None:
    edges = _edges(
        {
            "a.py": """
            class Client:
                def send(self): ...

            def run(client):
                client.send()
            """
        }
    )

    assert edges == set()


def test_should_follow_from_imports() -> None:
    edges = _edges(
        {
            "pkg/__init__.py": "",
            "pkg/models.py": """
            class User:
                def load(self): ...

            def make(): ...
            """,
            "app.py": """
            from pkg.models import User, make as build

            def run():
                User()
                User.load()
                build()
            """,
        }
    )

    assert edges == {
        ("app.py:run", "pkg/models.py:User"),
        ("app.py:run", "pkg/models.py:User.load"),
        ("app.py:run", "pkg/models.py:make"),
    }


def test_should_follow_module_aliases() -> None:
    edges = _edges(
        {
            "pkg/__init__.py": "",
            "pkg/util.py": "def slugify(): ...",
            "a.py": """
            import pkg.util as u

            def run():
                u.slugify()
            """,
            "b.py": """
            from pkg import util

            def run():
                util.slugify()
            """,
        }
    )

    assert edges == {
        ("a.py:run", "pkg/util.py:slugify"),
        ("b.py:run", "pkg/util.py:slugify"),
    }


def test_should_follow_relative_imports_under_a_source_root() -> None:
    edges = _edges(
        {
            "src/pkg/__init__.py": "",
            "src/pkg/util.py": "def slugify(): ...",
            "src/pkg/api/__init__.py": "",
            "src/pkg/api/views.py": """
            from ..util import slugify
            from .. import util

            def index():
                slugify()

            def detail():
                util.slugify()
            """,
        }
    )

    assert edges == {
        ("src/pkg/api/views.py:index", "src/pkg/util.py:slugify"),
        ("src/pkg/api/views.py:detail", "src/pkg/util.py:slugify"),
    }


def test_should_not_resolve_a_name_that_is_not_imported() -> None:
    edges = _edges(
        {
            "a.py": """
            def run(callback):
                callback()
            """,
            "b.py": "def callback(): ...",
        }
    )

    assert edges == set()


def test_should_not_fall_back_when_the_import_is_external() -> None:
    edges = _edges(
        {
            "client.py": "def get(): ...",
            "app.py": """
            from requests import get

            def run():
                get()
            """,
        }
    )

    assert edges == set()
