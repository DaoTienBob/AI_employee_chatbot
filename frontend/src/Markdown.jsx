// Lightweight, dependency-free Markdown renderer for chat answers.
// Builds React elements only (never injects raw HTML), so content coming from
// the model — even an attempted prompt injection — can only produce styled
// text, never executable markup/XSS.
import { createElement, Fragment } from "react";

// Inline patterns, matched in order; bold must win over italic so **x** is not
// mis-parsed as * + italic. Each needs at least one inner char (no zero-length).
const INLINE_PATTERNS = [
  { re: /\*\*(.+?)\*\*/g, tag: "strong" },
  { re: /__(.+?)__/g, tag: "strong" },
  { re: /~~(.+?)~~/g, tag: "del" },
  { re: /`([^`]+)`/g, tag: "code" },
  { re: /\[([^\]]+)\]\(([^)\s]+)\)/g, tag: "a" },
  { re: /\*([^*]+)\*/g, tag: "em" },
  { re: /_([^_]+)_/g, tag: "em" },
];

function renderInline(text) {
  const out = [];
  let rest = text;

  while (rest) {
    // Find the earliest match across all inline patterns.
    let bestIndex = -1;
    let bestPattern = null;
    let bestMatch = null;

    for (const p of INLINE_PATTERNS) {
      p.re.lastIndex = 0; // search from the start of the remaining string
      const m = p.re.exec(rest);
      if (m && (bestIndex === -1 || m.index < bestIndex)) {
        bestIndex = m.index;
        bestPattern = p;
        bestMatch = m;
      }
    }

    if (!bestMatch) {
      out.push(rest); // no more markdown → literal text (keeps stray * visible)
      break;
    }

    if (bestMatch.index > 0) {
      out.push(rest.slice(0, bestMatch.index)); // literal prefix
    }

    const { tag } = bestPattern;
    if (tag === "a") {
      out.push(
        createElement(
          "a",
          { href: bestMatch[2], target: "_blank", rel: "noopener noreferrer" },
          bestMatch[1],
        ),
      );
    } else if (tag === "code") {
      out.push(createElement("code", null, bestMatch[1])); // literal, no nesting
    } else {
      out.push(createElement(tag, null, ...renderInline(bestMatch[1]))); // nested emphasis
    }

    rest = rest.slice(bestIndex + bestMatch[0].length);
  }

  return out;
}

// Block matchers.
const UNORDERED = /^\s*([-*+])\s+(.*)$/;
const ORDERED = /^\s*(\d+)[.)]\s+(.*)$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const HR = /^\s*((?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})\s*$/;
const FENCE = /^\s*(```+|~~~+)/;

// Build a nested list tree from consecutive list-item lines
// (the bullet marker is already stripped; leading whitespace drives nesting).
function buildNestedList(itemLines) {
  const root = {
    ordered: itemLines[0].ordered,
    indent: itemLines[0].indent,
    items: [],
  };
  const stack = [root];
  let prevItem = null;

  for (const it of itemLines) {
    if (prevItem && it.indent > stack[stack.length - 1].indent) {
      // Deeper indentation → become a sub-list of the previous item.
      const nested = { ordered: it.ordered, indent: it.indent, items: [] };
      prevItem.children = nested;
      stack.push(nested);
    } else {
      // Fall back to the enclosing list at this (or a shallower) indent.
      while (stack.length > 1 && stack[stack.length - 1].indent > it.indent) {
        stack.pop();
      }
    }

    const top = stack[stack.length - 1];
    const item = { text: it.text };
    top.items.push(item);
    prevItem = item;
  }

  return { type: "list", ordered: root.ordered, items: root.items };
}

function parseBlocks(content) {
  const lines = content.split("\n");
  const blocks = [];
  let para = [];
  let listRegion = []; // list item lines collected before tree-building
  let code = null; // { fence, text[] }

  const flushPara = () => {
    if (para.length) {
      blocks.push({ type: "p", lines: para });
      para = [];
    }
  };
  const flushList = () => {
    if (listRegion.length) {
      blocks.push(buildNestedList(listRegion));
      listRegion = [];
    }
  };
  const flushCode = () => {
    if (code) {
      blocks.push({ type: "code", text: code.text.join("\n") });
      code = null;
    }
  };

  for (const line of lines) {
    // Inside a fenced code block: accumulate until the closing fence.
    if (code) {
      if (line.trimStart().startsWith(code.fence)) {
        flushCode();
      } else {
        code.text.push(line);
      }
      continue;
    }
    const fence = line.match(FENCE);
    if (fence) {
      flushPara();
      flushList();
      code = { fence: fence[1], text: [] };
      continue;
    }

    // Blank line separates blocks.
    if (!line.trim()) {
      flushPara();
      flushList();
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      flushPara();
      flushList();
      blocks.push({ type: "h", level: heading[1].length, text: heading[2] });
      continue;
    }

    if (HR.test(line)) {
      flushPara();
      flushList();
      blocks.push({ type: "hr" });
      continue;
    }

    const ul = line.match(UNORDERED);
    const ol = line.match(ORDERED);
    if (ol || ul) {
      flushPara();
      listRegion.push({
        ordered: Boolean(ol),
        indent: line.length - line.trimStart().length,
        text: ol ? ol[2] : ul[2],
      });
      continue;
    }

    // Ordinary paragraph line (consecutive lines become one <p> with <br/>).
    flushList();
    para.push(line);
  }

  flushPara();
  flushList();
  flushCode();
  return blocks;
}

// Render a (possibly nested) list with real <ul>/<ol> and <li>.
function renderListItems(items) {
  return items.map((item, i) =>
    createElement(
      "li",
      { key: i },
      ...renderInline(item.text),
      item.children ? renderList(item.children) : null,
    ),
  );
}
function renderList(list) {
  const tag = list.ordered ? "ol" : "ul";
  return createElement(tag, null, renderListItems(list.items));
}

// Exported for unit-testing the block parser.
export { parseBlocks };

export default function Markdown({ content }) {
  const blocks = parseBlocks(content ?? "");
  const nodes = [];

  for (const block of blocks) {
    switch (block.type) {
      case "p":
        nodes.push(
          createElement(
            "p",
            { key: nodes.length },
            block.lines.map((line, i) =>
              i === 0
                ? createElement(Fragment, { key: i }, ...renderInline(line))
                : createElement(
                    Fragment,
                    { key: i },
                    createElement("br", null),
                    ...renderInline(line),
                  ),
            ),
          ),
        );
        break;

      case "h":
        nodes.push(
          createElement(
            `h${block.level}`,
            { key: nodes.length },
            ...renderInline(block.text),
          ),
        );
        break;

      case "list":
        nodes.push(
          createElement(
            block.ordered ? "ol" : "ul",
            { key: nodes.length },
            renderListItems(block.items),
          ),
        );
        break;

      case "hr":
        nodes.push(createElement("hr", { key: nodes.length }));
        break;

      case "code":
        nodes.push(
          createElement(
            "pre",
            { key: nodes.length },
            createElement("code", null, block.text),
          ),
        );
        break;

      default:
        break;
    }
  }

  return createElement("div", { className: "markdown" }, nodes);
}