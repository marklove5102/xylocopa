/** Turn an ISO / unix timestamp into a relative string like "2m ago". */
export function relativeTime(dateStr) {
  if (!dateStr) return "";
  const now = Date.now();
  // Backend returns UTC datetimes without timezone suffix — append Z so
  // JavaScript doesn't misinterpret them as local time.
  let str = String(dateStr);
  if (/^\d{4}-\d{2}-\d{2}T[\d:.]+$/.test(str)) str += "Z";
  const then = new Date(str).getTime();
  const diff = Math.max(0, now - then);
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/**
 * Extremely lightweight markdown-ish renderer.
 * Handles ## headers, fenced code blocks, tables, inline code, bold,
 * italic, and image paths that look like local file references.
 */
export function renderMarkdown(text, project) {
  if (typeof text !== "string" || !text) return null;
  project = project || "";
  try {
  // We import React implicitly via JSX transform
  const lines = text.split("\n");
  const elements = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.startsWith("```")) {
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      elements.push(
        <pre
          key={elements.length}
          className="my-2 p-3 rounded-lg bg-inset text-sm text-body overflow-x-auto font-mono"
        >
          <code>{codeLines.join("\n")}</code>
        </pre>
      );
      continue;
    }

    // Headers
    if (line.startsWith("### ")) {
      elements.push(
        <h4 key={elements.length} className="text-sm font-semibold text-heading mt-3 mb-1">
          {line.slice(4)}
        </h4>
      );
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      elements.push(
        <h3 key={elements.length} className="text-base font-semibold text-heading mt-4 mb-1">
          {line.slice(3)}
        </h3>
      );
      i++;
      continue;
    }
    if (line.startsWith("# ")) {
      elements.push(
        <h2 key={elements.length} className="text-lg font-bold text-heading mt-4 mb-2">
          {line.slice(2)}
        </h2>
      );
      i++;
      continue;
    }

    // Image reference
    const imgMatch = line.trim().match(/^!\[.*?\]\((.+?)\)$/);
    const plainImgMatch =
      !imgMatch && line.trim().match(/^(\S+\.(png|jpg|jpeg|gif|svg|webp))$/i);
    if (imgMatch || plainImgMatch) {
      const src = imgMatch ? imgMatch[1] : plainImgMatch[1];
      const cleanSrc = cleanProjectPath(src, project);
      const resolvedSrc = src.startsWith("http")
        ? src
        : `/api/files/${encodeURIComponent(project)}/${cleanSrc.split("/").map(encodeURIComponent).join("/")}`;
      elements.push(
        <img
          key={elements.length}
          src={resolvedSrc}
          alt=""
          className="my-2 max-w-full rounded-lg border border-divider"
        />
      );
      i++;
      continue;
    }

    // Markdown table
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      const tableRows = [];
      while (i < lines.length && lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|")) {
        tableRows.push(lines[i].trim());
        i++;
      }
      if (tableRows.length >= 2) {
        // Parse header, separator, and body rows
        const parseRow = (row) =>
          row.split("|").slice(1, -1).map((c) => c.trim());
        const header = parseRow(tableRows[0]);
        // Skip separator row (|---|---|)
        const isSep = (row) => /^[\s|:-]+$/.test(row);
        const bodyStart = isSep(tableRows[1]) ? 2 : 1;
        const bodyRows = tableRows.slice(bodyStart).filter((r) => !isSep(r));
        elements.push(
          <div key={elements.length} className="my-2 overflow-x-auto rounded-lg border border-divider">
            <table className="min-w-full text-xs text-body">
              <thead>
                <tr className="bg-inset">
                  {header.map((h, j) => (
                    <th key={j} className="px-3 py-1.5 text-left font-semibold text-heading whitespace-nowrap border-b border-divider">
                      {renderInline(h)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bodyRows.map((row, ri) => (
                  <tr key={ri} className={ri % 2 ? "bg-inset/50" : ""}>
                    {parseRow(row).map((cell, ci) => (
                      <td key={ci} className="px-3 py-1.5 whitespace-pre-wrap border-b border-divider last:border-b-0">
                        {renderInline(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
        continue;
      }
      // Fallback: not a real table, rewind
      i -= tableRows.length;
    }

    // Empty line
    if (line.trim() === "") {
      elements.push(<div key={elements.length} className="h-2" />);
      i++;
      continue;
    }

    // Regular paragraph — apply inline formatting
    elements.push(
      <p key={elements.length} className="text-sm text-body leading-relaxed">
        {renderInline(line)}
      </p>
    );
    i++;
  }

  return <div className="space-y-0.5">{elements}</div>;
  } catch (e) {
    console.error("renderMarkdown error:", e);
    return <pre className="text-sm text-body whitespace-pre-wrap">{text}</pre>;
  }
}

// Agent IDs are 12-char hex strings. Match them as whole tokens
// (bounded by word boundaries or common delimiters).
const AGENT_ID_RE = /\b([0-9a-f]{12})\b/g;

/** Linkify agent IDs in a plain text string, returning an array of React elements. */
function linkifyAgentIds(text, keyPrefix) {
  const parts = [];
  let last = 0;
  let m;
  AGENT_ID_RE.lastIndex = 0;
  while ((m = AGENT_ID_RE.exec(text)) !== null) {
    if (m.index > last) {
      parts.push(<span key={`${keyPrefix}-t${last}`}>{text.slice(last, m.index)}</span>);
    }
    const agentId = m[1];
    parts.push(
      <a
        key={`${keyPrefix}-a${m.index}`}
        href={`/agents/${agentId}`}
        className="text-cyan-400 hover:underline font-mono"
        onClick={(e) => { e.stopPropagation(); }}
        onDoubleClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          navigator.clipboard.writeText(agentId);
        }}
        title="Click to open, double-tap to copy"
      >
        {agentId}
      </a>
    );
    last = AGENT_ID_RE.lastIndex;
  }
  if (last === 0) return null; // no IDs found — caller uses plain text
  if (last < text.length) {
    parts.push(<span key={`${keyPrefix}-t${last}`}>{text.slice(last)}</span>);
  }
  return parts;
}

/** Inline formatting: bold, italic, inline code. Uses React elements only (no innerHTML). */
export function renderInline(text) {
  if (typeof text !== "string" || !text) return null;
  try {
  // Split on inline code first, then handle bold/italic within non-code segments
  const codeParts = text.split(/(`[^`]+`)/g);
  const elements = [];

  for (let i = 0; i < codeParts.length; i++) {
    const part = codeParts[i];
    if (part.startsWith("`") && part.endsWith("`")) {
      const inner = part.slice(1, -1);
      const linked = linkifyAgentIds(inner, `c${i}`);
      elements.push(
        <code
          key={i}
          className="px-1 py-0.5 rounded bg-input text-cyan-300 text-xs font-mono"
        >
          {linked || inner}
        </code>
      );
    } else {
      // Tokenize bold (**...**) and italic (*...*) into safe React elements
      const tokens = tokenizeBoldItalic(part);
      for (let j = 0; j < tokens.length; j++) {
        const token = tokens[j];
        const key = `${i}-${j}`;
        const linked = linkifyAgentIds(token.text, key);
        if (token.type === "bold") {
          elements.push(<strong key={key}>{linked || token.text}</strong>);
        } else if (token.type === "italic") {
          elements.push(<em key={key}>{linked || token.text}</em>);
        } else {
          elements.push(<span key={key}>{linked || token.text}</span>);
        }
      }
    }
  }

  return elements;
  } catch (e) {
    console.error("renderInline error:", e);
    return <span>{text}</span>;
  }
}

/**
 * Split text into tokens of plain text, bold (**...**), and italic (*...*).
 * Returns an array of { type: "text"|"bold"|"italic", text: string }.
 */
function tokenizeBoldItalic(text) {
  const tokens = [];
  // Match **bold** first, then *italic*
  const re = /(\*\*(.+?)\*\*|\*(.+?)\*)/g;
  let lastIndex = 0;
  let match;

  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({ type: "text", text: text.slice(lastIndex, match.index) });
    }
    if (match[2] !== undefined) {
      tokens.push({ type: "bold", text: match[2] });
    } else {
      tokens.push({ type: "italic", text: match[3] });
    }
    lastIndex = re.lastIndex;
  }

  if (lastIndex < text.length) {
    tokens.push({ type: "text", text: text.slice(lastIndex) });
  }

  return tokens;
}

/**
 * Normalise a file path relative to a project.
 * Strips common prefixes that Claude outputs:
 *  - /projects/{name}/...
 *  - {project-name}/...  (e.g. "splitvla/file.webp" when project is "splitvla")
 *  - absolute paths containing the project name
 *  - leading slashes
 */
function cleanProjectPath(raw, project) {
  let p = raw;
  // /projects/{name}/...
  p = p.replace(/^\/projects\/[^/]+\//, "");
  // absolute path: strip everything up to and including project-name dir
  if (project) {
    const absRe = new RegExp(`^.*/` + project.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + `/`);
    p = p.replace(absRe, "");
    // relative project-name prefix: "splitvla/file.webp" → "file.webp"
    if (p.startsWith(project + "/")) {
      p = p.slice(project.length + 1);
    }
  }
  p = p.replace(/^\/+/, "");
  return p;
}

// File extensions we detect for inline previews
const IMAGE_EXTS = /\.(png|jpg|jpeg|gif|svg|webp)$/i;
const VIDEO_EXTS = /\.(mp4|webm|mov)$/i;
const CSV_EXT = /\.csv$/i;
const ALL_EXTS = /\.(png|jpg|jpeg|gif|svg|webp|mp4|webm|mov|csv)$/i;

// Compiled regexes for path detection
const RE_MD_IMAGE = /!\[.*?\]\((\S+?\.(?:png|jpg|jpeg|gif|svg|webp|mp4|webm|mov|csv))\)/gi;
const RE_BACKTICK = /`([^`]*\/[^`]*\.(?:png|jpg|jpeg|gif|svg|webp|mp4|webm|mov|csv))`/gi;
const RE_BARE_PATH = /(?:^|[\s(])([^\s()\[\]!]*\/[^\s()\[\]]+\.(?:png|jpg|jpeg|gif|svg|webp|mp4|webm|mov|csv))(?=[\s),\]]|$)/gim;

/**
 * Extract file attachments (images, videos, CSVs) from message text.
 * Returns an array of { path, resolvedUrl, type, ext } objects (data, not JSX).
 * Skips images that renderMarkdown already renders inline (full-line ![](...)
 * or bare filename lines) to avoid double-rendering.
 */
export function extractFileAttachments(text, project) {
  if (!text) return [];

  // Collect paths already rendered inline by renderMarkdown
  const inlineRendered = new Set();
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    // Full-line markdown image: ![...](path.ext)
    const mdFull = trimmed.match(/^!\[.*?\]\((.+?)\)$/);
    if (mdFull) inlineRendered.add(mdFull[1]);
    // Bare filename on its own line: image.png
    const bareFull = trimmed.match(/^(\S+\.(?:png|jpg|jpeg|gif|svg|webp))$/i);
    if (bareFull) inlineRendered.add(bareFull[1]);
  }

  const seen = new Set();
  const results = [];

  const addPath = (rawPath) => {
    if (!rawPath || !ALL_EXTS.test(rawPath)) return;
    let path = cleanProjectPath(rawPath, project);
    if (seen.has(path) || inlineRendered.has(rawPath)) return;
    seen.add(path);

    const resolvedUrl = rawPath.startsWith("http")
      ? rawPath
      : `/api/files/${encodeURIComponent(project)}/${path.split("/").map(encodeURIComponent).join("/")}`;

    let type = "unknown";
    if (IMAGE_EXTS.test(path)) type = "image";
    else if (VIDEO_EXTS.test(path)) type = "video";
    else if (CSV_EXT.test(path)) type = "csv";

    const ext = path.match(/\.(\w+)$/)?.[1]?.toLowerCase() || "";
    results.push({ path, resolvedUrl, type, ext });
  };

  // Match all three patterns
  let m;
  RE_MD_IMAGE.lastIndex = 0;
  while ((m = RE_MD_IMAGE.exec(text)) !== null) addPath(m[1]);
  RE_BACKTICK.lastIndex = 0;
  while ((m = RE_BACKTICK.exec(text)) !== null) addPath(m[1]);
  RE_BARE_PATH.lastIndex = 0;
  while ((m = RE_BARE_PATH.exec(text)) !== null) addPath(m[1]);

  return results;
}
