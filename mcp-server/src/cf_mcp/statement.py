"""Turn a Codeforces problem page into Markdown plus structured sample tests."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag


def _soup(html: str) -> BeautifulSoup:
    # html.parser keeps this dependency-light; lxml is not required.
    return BeautifulSoup(html, "html.parser")


@dataclass
class Sample:
    input: str
    output: str


@dataclass
class Statement:
    contest_id: int
    index: str
    name: str
    url: str
    time_limit: str = ""
    memory_limit: str = ""
    input_file: str = "standard input"
    output_file: str = "standard output"
    legend: str = ""
    input_spec: str = ""
    output_spec: str = ""
    note: str = ""
    samples: list[Sample] = field(default_factory=list)

    def to_markdown(self) -> str:
        parts = [f"# {self.index}. {self.name}", ""]
        meta = []
        if self.time_limit:
            meta.append(f"- **Time limit:** {self.time_limit}")
        if self.memory_limit:
            meta.append(f"- **Memory limit:** {self.memory_limit}")
        meta.append(f"- **Input:** {self.input_file}")
        meta.append(f"- **Output:** {self.output_file}")
        meta.append(f"- **URL:** {self.url}")
        parts += meta + ["", self.legend.strip()]

        if self.input_spec:
            parts += ["", "## Input", "", self.input_spec.strip()]
        if self.output_spec:
            parts += ["", "## Output", "", self.output_spec.strip()]
        for i, sample in enumerate(self.samples, 1):
            label = f"## Example {i}" if len(self.samples) > 1 else "## Example"
            parts += [
                "",
                label,
                "",
                "Input:",
                "```",
                sample.input,
                "```",
                "",
                "Output:",
                "```",
                sample.output,
                "```",
            ]
        if self.note:
            parts += ["", "## Note", "", self.note.strip()]
        return "\n".join(parts).strip() + "\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contest_id": self.contest_id,
            "index": self.index,
            "name": self.name,
            "url": self.url,
            "time_limit": self.time_limit,
            "memory_limit": self.memory_limit,
            "input_file": self.input_file,
            "output_file": self.output_file,
            "samples": [{"input": s.input, "output": s.output} for s in self.samples],
            "markdown": self.to_markdown(),
        }


# ------------------------------------------------------------------ html → md

_INLINE_WRAPPERS = {
    "b": "**",
    "strong": "**",
    "i": "*",
    "em": "*",
}


def _text_of(node: Any) -> str:
    """Recursively render a statement node as Markdown-ish text."""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""

    name = node.name
    classes = node.get("class") or []

    if name in ("script", "style"):
        return ""
    if name == "br":
        return "\n"
    if name == "img":
        src = node.get("src", "")
        alt = node.get("alt", "figure")
        return f"\n\n![{alt}]({src})\n\n" if src else ""
    if name in _INLINE_WRAPPERS:
        marker = _INLINE_WRAPPERS[name]
        inner = _children_text(node).strip()
        return f"{marker}{inner}{marker}" if inner else ""
    if name == "sup":
        return f"^({_children_text(node).strip()})"
    if name == "sub":
        return f"_({_children_text(node).strip()})"
    if name == "pre":
        return "\n```\n" + _pre_text(node) + "\n```\n"
    if name in ("ul", "ol"):
        lines = []
        for i, item in enumerate(node.find_all("li", recursive=False), 1):
            bullet = f"{i}." if name == "ol" else "-"
            body = _children_text(item).strip()
            lines.append(f"{bullet} {body}")
        return "\n\n" + "\n".join(lines) + "\n\n"
    if name == "p":
        return "\n\n" + _children_text(node).strip() + "\n\n"
    if name == "center":
        return "\n\n" + _children_text(node).strip() + "\n\n"

    if "tex-font-style-tt" in classes:
        inner = _children_text(node)
        return f"`{inner}`" if inner.strip() else inner
    if "tex-font-style-bf" in classes:
        inner = _children_text(node).strip()
        return f"**{inner}**" if inner else ""
    if "tex-font-style-it" in classes:
        inner = _children_text(node).strip()
        return f"*{inner}*" if inner else ""
    if "section-title" in classes:
        return ""  # Headings are emitted by the caller.

    if name == "div":
        return "\n" + _children_text(node) + "\n"
    return _children_text(node)


def _children_text(node: Tag) -> str:
    return "".join(_text_of(child) for child in node.children)


def _pre_text(pre: Tag) -> str:
    """Extract sample text, handling both markup styles Codeforces uses."""
    lines = pre.find_all("div", class_="test-example-line")
    if lines:
        # Newer multi-test format: one <div> per line.
        return "\n".join(line.get_text() for line in lines).strip("\n")
    text = pre.get_text()
    return text.replace("\r\n", "\n").strip("\n")


def _clean(text: str) -> str:
    text = text.replace(" ", " ").replace("\r\n", "\n")
    text = text.replace("$$$", "$")  # MathJax delimiter → ordinary LaTeX
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _section(root: Tag, class_name: str) -> str:
    node = root.find("div", class_=class_name)
    if not node:
        return ""
    clone = _soup(str(node)).find("div")
    title = clone.find("div", class_="section-title")
    if title:
        title.decompose()
    return _clean(_children_text(clone))


def _property(header: Tag, class_name: str, default: str = "") -> str:
    node = header.find("div", class_=class_name)
    if not node:
        return default
    clone = _soup(str(node)).find("div")
    title = clone.find("div", class_="property-title")
    if title:
        title.decompose()
    return clone.get_text(" ", strip=True) or default


def parse_statement(
    html: str, contest_id: int, index: str, url: str
) -> Statement:
    soup = _soup(html)
    root = soup.find("div", class_="problem-statement")
    if root is None:
        raise ValueError(
            "No problem statement found on the page. The problem may not exist, "
            "or the contest may not have started / may require registration."
        )

    header = root.find("div", class_="header")
    name = ""
    if header:
        title = header.find("div", class_="title")
        if title:
            raw = title.get_text(strip=True)
            # Titles arrive as "A. Cover in Water"; keep only the name.
            name = re.sub(r"^[A-Za-z]\d*\.\s*", "", raw)

    statement = Statement(
        contest_id=contest_id,
        index=index,
        name=name,
        url=url,
        time_limit=_property(header, "time-limit") if header else "",
        memory_limit=_property(header, "memory-limit") if header else "",
        input_file=_property(header, "input-file", "standard input")
        if header
        else "standard input",
        output_file=_property(header, "output-file", "standard output")
        if header
        else "standard output",
        input_spec=_section(root, "input-specification"),
        output_spec=_section(root, "output-specification"),
        note=_section(root, "note"),
    )

    # The legend is the first bare <div> after the header, with no class.
    for child in root.find_all("div", recursive=False):
        if child is header:
            continue
        if child.get("class"):
            continue
        statement.legend = _clean(_children_text(child))
        break

    samples_root = root.find("div", class_="sample-tests")
    if samples_root:
        for test in samples_root.find_all("div", class_="sample-test"):
            inputs = [
                _pre_text(div.find("pre"))
                for div in test.find_all("div", class_="input")
                if div.find("pre")
            ]
            outputs = [
                _pre_text(div.find("pre"))
                for div in test.find_all("div", class_="output")
                if div.find("pre")
            ]
            for i, sample_input in enumerate(inputs):
                sample_output = outputs[i] if i < len(outputs) else ""
                statement.samples.append(Sample(sample_input, sample_output))

    return statement


def parse_contest_problem_list(html: str) -> list[dict[str, Any]]:
    """Scrape a contest page's problem table.

    Used for gyms and running contests, which the standings API will not serve.
    """
    soup = _soup(html)
    table = soup.find("table", class_="problems")
    if table is None:
        return []

    problems: list[dict[str, Any]] = []
    for row in table.find_all("tr"):
        # Codeforces emits unclosed <tr>, so html.parser nests the rows inside
        # one another; only direct <td> children belong to this row.
        cells = row.find_all("td", recursive=False)
        if len(cells) < 2:
            continue
        index = cells[0].get_text(strip=True)
        if not index:
            continue
        name_link = cells[1].find("a")
        name = name_link.get_text(strip=True) if name_link else ""
        href = name_link.get("href", "") if name_link else ""

        limits = ""
        notice = cells[1].find("div", class_="notice")
        if notice:
            limits = " ".join(notice.get_text(" ", strip=True).split())

        # The solved count sits in the cell linking to the problem's status page,
        # rendered as a non-breaking space followed by "x<count>".
        solved_count = None
        for cell in cells[2:]:
            link = cell.find("a", href=re.compile(r"/status/"))
            if link is None:
                continue
            match = re.search(r"x\s*(\d+)", link.get_text(strip=True))
            if match:
                solved_count = int(match.group(1))
                break

        problems.append(
            {
                "index": index,
                "name": name,
                "url": f"https://codeforces.com{href}" if href else "",
                "limits": limits,
                "solved_count": solved_count,
            }
        )
    return problems
