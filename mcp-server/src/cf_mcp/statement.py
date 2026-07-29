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
class Section:
    """A titled block of the statement — Input, Interaction, Scoring, Note…"""

    title: str
    body: str


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
    sections: list[Section] = field(default_factory=list)
    # Where the sample block sat among the sections, so rendering can put it back.
    samples_index: int | None = None

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

        split = (
            len(self.sections) if self.samples_index is None else self.samples_index
        )
        parts += self._section_lines(self.sections[:split])
        parts += self._sample_lines()
        parts += self._section_lines(self.sections[split:])
        return "\n".join(parts).strip() + "\n"

    def _section_lines(self, sections: list[Section]) -> list[str]:
        lines: list[str] = []
        for section in sections:
            body = section.body.strip()
            if not body:
                continue
            if section.title:
                lines += ["", f"## {section.title}", "", body]
            else:
                lines += ["", body]
        return lines

    def _sample_lines(self) -> list[str]:
        lines: list[str] = []
        for i, sample in enumerate(self.samples, 1):
            label = f"## Example {i}" if len(self.samples) > 1 else "## Example"
            lines += [
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
        return lines

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
            "sections": [
                {"title": s.title, "body": s.body} for s in self.sections
            ],
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


def _titled(node: Tag) -> str:
    """The section's heading text, or "" when the div carries no heading."""
    title = node.find("div", class_="section-title")
    return title.get_text(" ", strip=True) if title else ""


def _body(node: Tag) -> str:
    """Render a section's contents as Markdown, minus its heading."""
    clone = _soup(str(node)).find("div")
    title = clone.find("div", class_="section-title")
    if title:
        title.decompose()
    return _clean(_children_text(clone))


def _parse_samples(samples_root: Tag) -> list[Sample]:
    samples: list[Sample] = []
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
            samples.append(Sample(sample_input, outputs[i] if i < len(outputs) else ""))
    return samples


def _property(header: Tag, class_name: str, default: str = "") -> str:
    node = header.find("div", class_=class_name)
    if not node:
        return default
    clone = _soup(str(node)).find("div")
    title = clone.find("div", class_="property-title")
    if title:
        title.decompose()
    return clone.get_text(" ", strip=True) or default


# Statement divs whose class names the section; the fallback title is used when
# the page omits the heading.
_NAMED_SECTIONS = {
    "input-specification": ("input_spec", "Input"),
    "output-specification": ("output_spec", "Output"),
    "note": ("note", "Note"),
}


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
    )

    for child in root.find_all("div", recursive=False):
        if child is header:
            continue
        classes = child.get("class") or []

        if "sample-tests" in classes:
            statement.samples_index = len(statement.sections)
            statement.samples.extend(_parse_samples(child))
            continue

        named = next((c for c in classes if c in _NAMED_SECTIONS), None)
        if named:
            attribute, fallback_title = _NAMED_SECTIONS[named]
            body = _body(child)
            setattr(statement, attribute, body)
            statement.sections.append(Section(_titled(child) or fallback_title, body))
            continue

        if classes:
            continue  # A decorated div that is not statement prose.

        # Class-less divs are either the legend or a section Codeforces did not
        # give a class — Interaction, Scoring. Only the titled ones are sections.
        title = _titled(child)
        if title:
            statement.sections.append(Section(title, _body(child)))
            continue
        prose = _clean(_children_text(child))
        if not prose:
            continue
        if statement.sections:
            # A titled section already rendered above this point; keep this
            # prose at its real position instead of hoisting it to the top.
            statement.sections.append(Section("", prose))
        else:
            statement.legend = (
                f"{statement.legend}\n\n{prose}" if statement.legend else prose
            )

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
