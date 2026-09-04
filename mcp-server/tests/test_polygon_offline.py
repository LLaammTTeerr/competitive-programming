"""Exercise the Polygon server against a fake Polygon, without network access.

Everything here runs through `httpx.MockTransport`, so the whole client — the
signature, the read/write verb split, the pacing, the one retry — is the real
code, and only the socket is fake.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

from polygon_mcp import server
from polygon_mcp.api import PLAIN_TEXT_METHODS, PolygonApi, WRITE_METHODS, sign
from polygon_mcp.config import Config, PolygonError, resolve_local_path

API_KEY = "polygon-key-11112222"
API_SECRET = "polygon-secret-33334444"

# A reply that makes the fake transport raise instead of answering.
TIMEOUT = "<<timeout>>"


# ----------------------------------------------------------------- the fake


@dataclass
class Call:
    method: str
    params: dict[str, str]
    verb: str


def ok(result: Any) -> tuple[int, Any]:
    return 200, {"status": "OK", "result": result}


def failed(comment: str) -> tuple[int, Any]:
    return 200, {"status": "FAILED", "comment": comment}


class FakePolygon:
    """Replays canned replies and records what was sent.

    Replies are consumed in order and the last one repeats, so a retry test
    reads `FakePolygon((503, "busy"), ok({}))` as "fails once, then works".
    """

    def __init__(self, *replies: tuple[int, Any]):
        self.replies = list(replies) or [ok(None)]
        self.calls: list[Call] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            params = dict(request.url.params)
        else:
            params = dict(parse_qsl(request.content.decode(), keep_blank_values=True))
        self.calls.append(
            Call(
                method=request.url.path.rsplit("/", 1)[-1],
                params=params,
                verb=request.method,
            )
        )
        status, payload = (
            self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        )
        if payload is TIMEOUT:
            raise httpx.ReadTimeout("timed out", request=request)
        if isinstance(payload, (dict, list)):
            return httpx.Response(status, json=payload)
        return httpx.Response(status, text=str(payload))

    @property
    def last(self) -> Call:
        return self.calls[-1]


def make_api(fake: FakePolygon, sleeps: list[float] | None = None, **overrides):
    overrides.setdefault("min_interval", 0.0)
    config = Config(
        api_key=API_KEY,
        api_secret=API_SECRET,
        base_url="https://polygon.test/api/",
        **overrides,
    )

    async def record_sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return config, PolygonApi(
        config, transport=httpx.MockTransport(fake), sleep=record_sleep
    )


@pytest.fixture
def polygon(monkeypatch):
    """Wire one fake Polygon into the server module for a single test."""

    def install(*replies, **overrides) -> FakePolygon:
        fake = FakePolygon(*replies)
        config, api = make_api(fake, **overrides)
        monkeypatch.setattr(server, "config", config)
        monkeypatch.setattr(server, "api", api)
        return fake

    return install


# ------------------------------------------------------------------- signing


def test_signature_has_the_documented_shape():
    signed = sign(
        "problem.info",
        {"problemId": 42},
        api_key=API_KEY,
        secret=API_SECRET,
        rand="123456",
        now=1700000000,
    )
    assert signed["apiSig"][:6] == "123456"
    assert len(signed["apiSig"]) == 6 + 128
    int(signed["apiSig"][6:], 16)  # the tail is hexadecimal
    assert signed["apiKey"] == API_KEY
    assert signed["time"] == "1700000000"


def test_signature_matches_an_independently_computed_hash():
    # The documented string: <rand>/<method>?k=v&…#<secret>, every parameter
    # including apiKey and time, sorted by name then value.
    signed = sign(
        "problem.saveTest",
        {"problemId": 42, "testset": "tests", "testIndex": 1},
        api_key="KEY",
        secret="SEC",
        rand="abcdef",
        now=1000,
    )
    query = "apiKey=KEY&problemId=42&testIndex=1&testset=tests&time=1000"
    expected = hashlib.sha512(
        f"abcdef/problem.saveTest?{query}#SEC".encode()
    ).hexdigest()
    assert signed["apiSig"] == "abcdef" + expected


def test_signature_sorts_parameters_regardless_of_insertion_order():
    forward = sign(
        "problems.list",
        {"name": "a", "owner": "b", "showDeleted": False},
        api_key="K", secret="S", rand="000000", now=1,
    )
    backward = sign(
        "problems.list",
        {"showDeleted": False, "owner": "b", "name": "a"},
        api_key="K", secret="S", rand="000000", now=1,
    )
    assert forward["apiSig"] == backward["apiSig"]


def test_signature_is_deterministic_for_a_fixed_rand_and_time():
    kwargs = dict(api_key="K", secret="S", rand="aaaaaa", now=7)
    assert sign("problem.info", {"problemId": 1}, **kwargs) == sign(
        "problem.info", {"problemId": 1}, **kwargs
    )


def test_a_different_secret_changes_the_signature():
    kwargs = dict(api_key="K", rand="aaaaaa", now=7)
    one = sign("problem.info", {"problemId": 1}, secret="S1", **kwargs)
    two = sign("problem.info", {"problemId": 1}, secret="S2", **kwargs)
    assert one["apiSig"] != two["apiSig"]


def test_booleans_are_signed_as_they_are_sent():
    signed = sign(
        "problem.enablePoints",
        {"enable": True},
        api_key="K", secret="S", rand="000000", now=1,
    )
    assert signed["enable"] == "true"
    query = "apiKey=K&enable=true&time=1"
    expected = hashlib.sha512(
        f"000000/problem.enablePoints?{query}#S".encode()
    ).hexdigest()
    assert signed["apiSig"] == "000000" + expected


async def test_the_file_content_is_signed_like_any_other_parameter():
    # Polygon takes uploads as ordinary form fields, not multipart parts, so
    # the whole source text participates in the hash.
    fake = FakePolygon(ok(None))
    _, api = make_api(fake)
    source = "int main() { return 0; }\n"
    await api.call(
        "problem.saveSolution",
        {"problemId": 1, "name": "sol.cpp", "file": source, "tag": "MA"},
    )
    sent = fake.last.params
    assert sent["file"] == source
    unsigned = {k: v for k, v in sent.items() if k != "apiSig"}
    query = "&".join(f"{k}={v}" for k, v in sorted(unsigned.items()))
    rand = sent["apiSig"][:6]
    expected = hashlib.sha512(
        f"{rand}/problem.saveSolution?{query}#{API_SECRET}".encode()
    ).hexdigest()
    assert sent["apiSig"] == rand + expected


# ---------------------------------------------------------------- transport


async def test_reads_go_as_get_and_writes_as_post():
    fake = FakePolygon(ok([]))
    _, api = make_api(fake)
    await api.call("problem.info", {"problemId": 1})
    assert fake.last.verb == "GET"
    await api.call("problem.enablePoints", {"problemId": 1, "enable": True})
    assert fake.last.verb == "POST"


def test_every_write_method_is_a_save_set_or_lifecycle_call():
    # A read wrongly listed as a write would put a statement in a query string;
    # a write wrongly left out would do the same to a solution's source.
    assert not (WRITE_METHODS & PLAIN_TEXT_METHODS)
    for method in WRITE_METHODS:
        tail = method.split(".", 1)[1]
        assert tail.startswith(("save", "set", "enable", "update", "edit")) or tail in {
            "create",
            "commitChanges",
            "discardWorkingCopy",
            "buildPackage",
        }, method


async def test_none_parameters_are_dropped_rather_than_sent_empty():
    fake = FakePolygon(ok(None))
    _, api = make_api(fake)
    await api.call(
        "problem.updateInfo",
        {"problemId": 1, "timeLimit": 2000, "interactive": None, "inputFile": None},
    )
    assert "interactive" not in fake.last.params
    assert "inputFile" not in fake.last.params
    assert fake.last.params["timeLimit"] == "2000"


async def test_a_failed_status_becomes_an_error_naming_the_method():
    fake = FakePolygon(failed("problemId: Problem not found"))
    _, api = make_api(fake)
    with pytest.raises(PolygonError) as caught:
        await api.call("problem.info", {"problemId": 9})
    assert "Problem not found" in str(caught.value)
    assert caught.value.method == "problem.info"


async def test_a_4xx_is_not_retried():
    fake = FakePolygon((403, "<html>Forbidden</html>"))
    _, api = make_api(fake)
    with pytest.raises(PolygonError, match="HTTP 403"):
        await api.call("problem.info", {"problemId": 1})
    assert len(fake.calls) == 1


async def test_a_503_is_retried_once_and_then_succeeds():
    sleeps: list[float] = []
    fake = FakePolygon((503, "<html>busy</html>"), ok({"timeLimit": 2000}))
    _, api = make_api(fake, sleeps=sleeps)
    assert await api.call("problem.info", {"problemId": 1}) == {"timeLimit": 2000}
    assert len(fake.calls) == 2
    assert sleeps == [1.0]


async def test_the_retry_is_signed_again_rather_than_replayed():
    # The signature commits to `time`, and Polygon refuses a request whose time
    # is more than five minutes off its clock, so a replay would eventually 403.
    fake = FakePolygon((503, "busy"), ok(None))
    _, api = make_api(fake)
    await api.call("problem.info", {"problemId": 1})
    first, second = fake.calls
    assert first.params["apiSig"] != second.params["apiSig"]


async def test_a_second_503_gives_up():
    fake = FakePolygon((503, "<html>busy</html>"))
    _, api = make_api(fake)
    with pytest.raises(PolygonError, match="HTTP 503"):
        await api.call("problem.info", {"problemId": 1})
    assert len(fake.calls) == 2


async def test_a_timeout_is_retried_once():
    sleeps: list[float] = []
    fake = FakePolygon((0, TIMEOUT), ok("fine"))
    _, api = make_api(fake, sleeps=sleeps)
    assert await api.call("problem.info", {"problemId": 1}) == "fine"
    assert len(fake.calls) == 2 and sleeps == [1.0]


async def test_a_persistent_timeout_reports_without_the_request_url():
    fake = FakePolygon((0, TIMEOUT))
    _, api = make_api(fake)
    with pytest.raises(PolygonError) as caught:
        await api.call("problem.info", {"problemId": 1})
    # httpx spells the request URL into its own exceptions, and a signed GET's
    # URL carries apiKey — so the message must be ours, not httpx's.
    assert API_KEY not in str(caught.value)
    assert "did not answer" in str(caught.value)


async def test_an_unreachable_host_reports_without_the_request_url():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    config = Config(
        api_key=API_KEY,
        api_secret=API_SECRET,
        base_url="https://polygon.test/api/",
        min_interval=0.0,
    )

    async def no_sleep(seconds: float) -> None:
        return None

    api = PolygonApi(
        config, transport=httpx.MockTransport(refuse), sleep=no_sleep
    )
    with pytest.raises(PolygonError) as caught:
        await api.call("problem.info", {"problemId": 1})
    assert API_KEY not in str(caught.value)
    assert "Could not reach Polygon" in str(caught.value)


async def test_requests_are_paced_by_the_minimum_interval():
    sleeps: list[float] = []
    fake = FakePolygon(ok(None))
    _, api = make_api(fake, sleeps=sleeps, min_interval=0.5)
    await api.call("problem.info", {"problemId": 1})
    await api.call("problem.info", {"problemId": 1})
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 0.5


async def test_a_plain_text_method_returns_its_body_verbatim():
    fake = FakePolygon((200, "gen_random 100 1 > $\ngen_max 200000 > $\n"))
    _, api = make_api(fake)
    script = await api.call("problem.script", {"problemId": 1, "testset": "tests"})
    assert script.startswith("gen_random 100 1")


async def test_a_plain_text_method_that_fails_still_reads_the_json_envelope():
    fake = FakePolygon(failed("testset: No such testset"))
    _, api = make_api(fake)
    with pytest.raises(PolygonError, match="No such testset"):
        await api.call("problem.script", {"problemId": 1, "testset": "nope"})


async def test_a_one_line_test_input_is_not_mistaken_for_json():
    fake = FakePolygon((200, "5"))
    _, api = make_api(fake)
    assert await api.call(
        "problem.testInput", {"problemId": 1, "testset": "tests", "testIndex": 1}
    ) == "5"


async def test_a_call_without_credentials_never_reaches_the_network():
    fake = FakePolygon(ok(None))
    config, api = make_api(fake)
    config.api_key = ""
    with pytest.raises(PolygonError, match="POLYGON_API_KEY"):
        await api.call("problem.info", {"problemId": 1})
    assert fake.calls == []


# ------------------------------------------------------------- the path guard


def test_a_path_inside_the_root_is_accepted(tmp_path: Path):
    target = tmp_path / "sol.cpp"
    target.write_text("int main(){}")
    assert resolve_local_path(str(target), tmp_path) == target.resolve()


def test_a_path_outside_the_root_is_refused(tmp_path: Path):
    root = tmp_path / "problem"
    root.mkdir()
    outside = tmp_path / "secrets.txt"
    outside.write_text("nope")
    with pytest.raises(PolygonError, match="outside POLYGON_MCP_ROOT"):
        resolve_local_path(str(outside), root)


def test_a_traversal_out_of_the_root_is_refused(tmp_path: Path):
    root = tmp_path / "problem"
    root.mkdir()
    (tmp_path / "secrets.txt").write_text("nope")
    with pytest.raises(PolygonError, match="outside POLYGON_MCP_ROOT"):
        resolve_local_path(str(root / ".." / "secrets.txt"), root)


def test_a_symlink_pointing_out_of_the_root_is_refused(tmp_path: Path):
    root = tmp_path / "problem"
    root.mkdir()
    (tmp_path / "secrets.txt").write_text("nope")
    (root / "link.txt").symlink_to(tmp_path / "secrets.txt")
    with pytest.raises(PolygonError, match="outside POLYGON_MCP_ROOT"):
        resolve_local_path(str(root / "link.txt"), root)


def test_no_root_refuses_every_path(tmp_path: Path):
    target = tmp_path / "sol.cpp"
    target.write_text("int main(){}")
    with pytest.raises(PolygonError, match="POLYGON_MCP_ROOT is not set"):
        resolve_local_path(str(target), None)


def test_a_missing_file_inside_the_root_says_so(tmp_path: Path):
    with pytest.raises(PolygonError, match="File not found"):
        resolve_local_path(str(tmp_path / "absent.cpp"), tmp_path)


async def test_a_tool_uploads_the_file_the_path_points_at(polygon, tmp_path: Path):
    source = tmp_path / "sol.cpp"
    source.write_text("int main(){ return 0; }\n")
    fake = polygon(ok(None), root=tmp_path)
    result = await server.polygon_save_solution(
        problem_id=1, name="sol.cpp", tag="MA", path=str(source)
    )
    assert result["ok"] is True
    assert fake.last.params["file"] == "int main(){ return 0; }\n"


async def test_a_tool_refuses_a_path_outside_the_root(polygon, tmp_path: Path):
    root = tmp_path / "problem"
    root.mkdir()
    outside = tmp_path / "id_rsa"
    outside.write_text("PRIVATE KEY")
    fake = polygon(ok(None), root=root)
    result = await server.polygon_save_solution(
        problem_id=1, name="sol.cpp", tag="MA", path=str(outside)
    )
    assert result["ok"] is False
    assert "outside POLYGON_MCP_ROOT" in result["error"]
    assert fake.calls == []  # nothing was sent, and nothing was read


async def test_a_tool_refuses_content_and_path_together(polygon, tmp_path: Path):
    source = tmp_path / "sol.cpp"
    source.write_text("x")
    polygon(ok(None), root=tmp_path)
    result = await server.polygon_save_solution(
        problem_id=1, name="s.cpp", tag="OK", content="y", path=str(source)
    )
    assert result["ok"] is False and "not both" in result["error"]


# ------------------------------------------------------------ tool behaviour


async def test_whoami_summarises_the_visible_problems(polygon):
    polygon(ok([{"id": 1, "name": "a-plus-b", "owner": "me"}]))
    result = await server.polygon_whoami()
    assert result["ok"] is True
    assert result["problem_count"] == 1
    assert result["first_problems"][0]["name"] == "a-plus-b"


async def test_whoami_without_credentials_explains_what_to_set(polygon):
    fake = polygon(ok([]))
    server.config.api_secret = ""
    result = await server.polygon_whoami()
    assert result["ok"] is False
    assert "POLYGON_API_SECRET" in result["error"]
    assert fake.calls == []


async def test_a_failed_reply_becomes_the_documented_failure_shape(polygon):
    polygon(failed("problemId: Problem not found"))
    result = await server.polygon_problem_info(problem_id=9)
    assert result == {
        "ok": False,
        "error": "problemId: Problem not found",
        "method": "problem.info",
    }


async def test_an_http_error_becomes_the_same_shape(polygon):
    polygon((404, "<html>nope</html>"))
    result = await server.polygon_problem_info(problem_id=9)
    assert result["ok"] is False
    assert "HTTP 404" in result["error"]
    assert result["method"] == "problem.info"


async def test_an_unknown_solution_tag_is_refused_before_a_request(polygon):
    fake = polygon(ok(None))
    result = await server.polygon_save_solution(
        problem_id=1, name="s.cpp", tag="AC", content="x"
    )
    assert result["ok"] is False and "must be one of" in result["error"]
    assert fake.calls == []


async def test_an_unknown_file_type_is_refused_before_a_request(polygon):
    fake = polygon(ok(None))
    result = await server.polygon_save_file(
        problem_id=1, file_type="binary", name="x", content="y"
    )
    assert result["ok"] is False and "must be one of" in result["error"]
    assert fake.calls == []


async def test_update_info_leaves_omitted_fields_alone(polygon):
    # Naming one limit must not silently clear `interactive` or the file names.
    fake = polygon(ok(None))
    await server.polygon_problem_update_info(problem_id=1, time_limit_ms=2000)
    sent = fake.last.params
    assert sent["timeLimit"] == "2000"
    assert not {"interactive", "wellFormed", "inputFile", "outputFile"} & sent.keys()


async def test_tags_and_dependencies_are_comma_joined(polygon):
    fake = polygon(ok(None))
    await server.polygon_save_tags(problem_id=1, tags=["dp", "graphs"])
    assert fake.last.params["tags"] == "dp,graphs"

    fake = polygon(ok(None))
    await server.polygon_save_test_group(
        problem_id=1,
        testset="tests",
        group="3",
        points_policy="COMPLETE_GROUP",
        feedback_policy="ICPC",
        dependencies=["1", "2"],
    )
    assert fake.last.params["dependencies"] == "1,2"
    assert fake.last.params["pointsPolicy"] == "COMPLETE_GROUP"


async def test_a_standard_checker_name_is_passed_through_untouched(polygon):
    fake = polygon(ok(None))
    await server.polygon_set_checker(problem_id=1, name="std::rcmp6.cpp")
    assert fake.last.params["checker"] == "std::rcmp6.cpp"


async def test_the_script_tool_returns_the_plain_text_body(polygon):
    polygon((200, "gen 1 2 > $\n"))
    result = await server.polygon_script(problem_id=1)
    assert result["ok"] is True and result["script"] == "gen 1 2 > $\n"


# One happy path per tool, so every tool is known to reach the method its
# docstring names with the parameters Polygon documents.
TOOL_CASES: list[tuple[str, dict[str, Any], Any, str, dict[str, str]]] = [
    ("polygon_whoami", {}, [], "problems.list", {}),
    (
        "polygon_problems_list",
        {"owner": "me", "show_deleted": True},
        [{"id": 1}],
        "problems.list",
        {"owner": "me", "showDeleted": "true"},
    ),
    (
        "polygon_problem_create",
        {"name": "a-plus-b"},
        {"id": 7},
        "problem.create",
        {"name": "a-plus-b"},
    ),
    (
        "polygon_problem_info",
        {"problem_id": 7},
        {"timeLimit": 2000},
        "problem.info",
        {"problemId": "7"},
    ),
    (
        "polygon_problem_update_info",
        {"problem_id": 7, "time_limit_ms": 2000, "memory_limit_mb": 256},
        None,
        "problem.updateInfo",
        {"timeLimit": "2000", "memoryLimit": "256"},
    ),
    (
        "polygon_statements",
        {"problem_id": 7},
        {"english": {"name": "A plus B"}},
        "problem.statements",
        {"problemId": "7"},
    ),
    (
        "polygon_save_statement",
        {"problem_id": 7, "lang": "english", "legend": "Add $$$a$$$ and $$$b$$$."},
        None,
        "problem.saveStatement",
        {"lang": "english", "legend": "Add $$$a$$$ and $$$b$$$."},
    ),
    (
        "polygon_save_statement_resource",
        {"problem_id": 7, "name": "fig.svg", "content": "<svg/>"},
        None,
        "problem.saveStatementResource",
        {"name": "fig.svg", "file": "<svg/>"},
    ),
    (
        "polygon_files",
        {"problem_id": 7},
        {"sourceFiles": [], "resourceFiles": [], "auxFiles": []},
        "problem.files",
        {"problemId": "7"},
    ),
    (
        "polygon_save_file",
        {"problem_id": 7, "file_type": "source", "name": "val.cpp", "content": "x"},
        None,
        "problem.saveFile",
        {"type": "source", "name": "val.cpp", "file": "x"},
    ),
    (
        "polygon_set_validator",
        {"problem_id": 7, "name": "val.cpp"},
        None,
        "problem.setValidator",
        {"validator": "val.cpp"},
    ),
    (
        "polygon_set_checker",
        {"problem_id": 7, "name": "std::wcmp.cpp"},
        None,
        "problem.setChecker",
        {"checker": "std::wcmp.cpp"},
    ),
    (
        "polygon_set_interactor",
        {"problem_id": 7, "name": "inter.cpp"},
        None,
        "problem.setInteractor",
        {"interactor": "inter.cpp"},
    ),
    (
        "polygon_solutions",
        {"problem_id": 7},
        [{"name": "sol.cpp", "tag": "MA"}],
        "problem.solutions",
        {"problemId": "7"},
    ),
    (
        "polygon_save_solution",
        {"problem_id": 7, "name": "sol.cpp", "tag": "MA", "content": "int main(){}"},
        None,
        "problem.saveSolution",
        {"name": "sol.cpp", "tag": "MA", "file": "int main(){}"},
    ),
    (
        "polygon_script",
        {"problem_id": 7, "testset": "tests"},
        "gen 1 > $\n",
        "problem.script",
        {"testset": "tests"},
    ),
    (
        "polygon_save_script",
        {"problem_id": 7, "testset": "tests", "source": "gen 1 > $\n"},
        None,
        "problem.saveScript",
        {"testset": "tests", "source": "gen 1 > $\n"},
    ),
    (
        "polygon_tests",
        {"problem_id": 7, "testset": "tests"},
        [{"index": 1, "manual": True}],
        "problem.tests",
        {"testset": "tests"},
    ),
    (
        "polygon_save_test",
        {
            "problem_id": 7,
            "testset": "tests",
            "test_index": 3,
            "test_input": "1 2\n",
            "test_group": "2",
            "test_points": 10,
            "use_in_statements": True,
        },
        None,
        "problem.saveTest",
        {
            "testIndex": "3",
            "testInput": "1 2\n",
            "testGroup": "2",
            "testPoints": "10",
            "testUseInStatements": "true",
        },
    ),
    (
        "polygon_enable_groups",
        {"problem_id": 7, "testset": "tests", "enable": True},
        None,
        "problem.enableGroups",
        {"testset": "tests", "enable": "true"},
    ),
    (
        "polygon_enable_points",
        {"problem_id": 7, "enable": True},
        None,
        "problem.enablePoints",
        {"enable": "true"},
    ),
    (
        "polygon_test_groups",
        {"problem_id": 7, "testset": "tests"},
        [{"name": "1", "pointsPolicy": "COMPLETE_GROUP"}],
        "problem.viewTestGroup",
        {"testset": "tests"},
    ),
    (
        "polygon_save_test_group",
        {
            "problem_id": 7,
            "testset": "tests",
            "group": "2",
            "points_policy": "EACH_TEST",
            "feedback_policy": "NONE",
        },
        None,
        "problem.saveTestGroup",
        {"group": "2", "pointsPolicy": "EACH_TEST", "feedbackPolicy": "NONE"},
    ),
    ("polygon_tags", {"problem_id": 7}, ["dp"], "problem.viewTags", {"problemId": "7"}),
    (
        "polygon_save_tags",
        {"problem_id": 7, "tags": ["dp", "trees"]},
        None,
        "problem.saveTags",
        {"tags": "dp,trees"},
    ),
    (
        "polygon_general_description",
        {"problem_id": 7},
        "Prepared for round 42.",
        "problem.viewGeneralDescription",
        {"problemId": "7"},
    ),
    (
        "polygon_save_general_description",
        {"problem_id": 7, "description": "Prepared for round 42."},
        None,
        "problem.saveGeneralDescription",
        {"description": "Prepared for round 42."},
    ),
    (
        "polygon_commit",
        {"problem_id": 7, "minor_changes": True, "message": "tests"},
        None,
        "problem.commitChanges",
        {"minorChanges": "true", "message": "tests"},
    ),
    (
        "polygon_build_package",
        {"problem_id": 7, "full": False, "verify": True},
        None,
        "problem.buildPackage",
        {"full": "false", "verify": "true"},
    ),
    (
        "polygon_packages",
        {"problem_id": 7},
        [{"id": 1, "state": "READY"}],
        "problem.packages",
        {"problemId": "7"},
    ),
]


@pytest.mark.parametrize(
    "tool_name,kwargs,result,method,expected",
    TOOL_CASES,
    ids=[case[0] for case in TOOL_CASES],
)
async def test_each_tool_calls_its_documented_method(
    polygon, tool_name, kwargs, result, method, expected
):
    reply = (200, result) if method in PLAIN_TEXT_METHODS else ok(result)
    fake = polygon(reply)
    answer = await getattr(server, tool_name)(**kwargs)
    assert answer["ok"] is True, answer
    assert fake.last.method == method
    for key, value in expected.items():
        assert fake.last.params[key] == value, (key, fake.last.params)


def test_every_tool_registered_on_the_server_has_a_happy_path_test():
    registered = {
        name for name in dir(server) if name.startswith("polygon_")
    }
    covered = {case[0] for case in TOOL_CASES}
    assert registered - covered == set(), sorted(registered - covered)


# ------------------------------------------------------- credentials never leak


async def test_no_result_from_any_tool_contains_the_key_or_the_secret(polygon):
    """Grep every tool's JSON, on the happy path and on each failure path.

    The happy path is the least likely leak site; the dangerous one is an error
    that stringifies an httpx exception, because a signed GET's URL carries
    `apiKey`. So each tool is run against a canned success, a FAILED envelope,
    a 4xx, an exhausted 5xx and a timeout, and every result is searched.
    """

    failures: list[tuple[int, Any]] = [
        failed("Access denied: you need WRITE access"),
        (403, "<html>Forbidden</html>"),
        (503, "<html>Service Unavailable</html>"),
        (0, TIMEOUT),
    ]

    results: list[dict[str, Any]] = []
    for tool_name, kwargs, result, method, _ in TOOL_CASES:
        success = (200, result) if method in PLAIN_TEXT_METHODS else ok(result)
        for reply in [success, *failures]:
            polygon(reply)
            results.append(await getattr(server, tool_name)(**kwargs))

    blob = json.dumps(results)
    assert API_KEY not in blob
    assert API_SECRET not in blob
    # And the sentinels really would have been found had they been there.
    assert API_KEY in json.dumps({"leak": API_KEY})
    # Every failure path did produce a failure, so the grep was not vacuous.
    assert sum(1 for r in results if r["ok"] is False) == 4 * len(TOOL_CASES)


async def test_whoami_reports_the_credentials_without_showing_them(polygon):
    """whoami is the one tool whose whole job is to talk about the credentials."""
    polygon(ok([]))
    result = await server.polygon_whoami()
    blob = json.dumps(result)
    assert result["credentials_configured"] is True
    assert API_KEY not in blob and API_SECRET not in blob
