"use strict";
const $ = (selector) => document.querySelector(selector);
const state = { book: null, chapters: [], index: 0, query: "" };
const fileInput = $("#reader-file");
const escapeText = (value) => String(value ?? "");
const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = escapeText(text);
  return node;
};
function evidenceLabel(item) {
  const source = item.source?.title || item.source_title || item.source_id || "Source";
  if (item.locator_kind === "DOCUMENT_PAGE") return source + " · page " + (item.page_number ?? item.document_page?.page_number ?? "?");
  if (item.start_ms !== null && item.start_ms !== undefined) return source + " · " + (item.start_ms / 1000).toFixed(2) + "–" + (Number(item.end_ms ?? item.start_ms) / 1000).toFixed(2) + "s";
  return source + " · source reference";
}
function renderEvidence(items) {
  if (!Array.isArray(items) || !items.length) return null;
  const details = element("details", "evidence");
  details.append(element("summary", "", items.length + " evidence reference" + (items.length === 1 ? "" : "s")));
  for (const item of items) {
    const row = element("div", "citation");
    const tag = element("span", "tag", item.relation || "EVIDENCE");
    row.append(tag, document.createTextNode(evidenceLabel(item)));
    if (item.transcript_excerpt?.length) {
      for (const segment of item.transcript_excerpt) {
        const excerpt = element("p", "excerpt", "“" + segment.text + "”");
        row.append(excerpt);
      }
    }
    if (item.document_page?.text_content) {
      row.append(element("p", "", "Page text: " + item.document_page.text_content.slice(0, 1200)));
    }
    details.append(row);
  }
  return details;
}
function renderBlock(block) {
  const wrap = element("section", "content-block");
  const content = block.content || {};
  const kind = block.block_type || "PARAGRAPH";
  const value = content.text ?? content.body ?? content.expression ?? content.description ?? "";
  if (kind === "HEADING") wrap.append(element("h2", "", value));
  else if (kind === "DEFINITION") {
    const box = element("div", "definition");
    box.append(element("strong", "", content.term || "Definition"), element("p", "", content.definition ?? value));
    wrap.append(box);
  } else if (kind === "EQUATION" || kind === "CODE") {
    const pre = element("pre", "", kind === "CODE" ? content.code ?? value : content.latex ?? value);
    wrap.append(pre);
  } else if (kind === "TABLE" && Array.isArray(content.rows)) {
    const table = element("table");
    content.rows.forEach((cells, index) => {
      const tr = element("tr");
      (Array.isArray(cells) ? cells : []).forEach((cell) => {
        const td = element(index === 0 ? "th" : "td", "", cell);
        tr.append(td);
      });
      table.append(tr);
    });
    wrap.append(table);
  } else if (["WARNING", "MISCONCEPTION", "EXAMPLE", "WORKED_SOLUTION", "EXERCISE"].includes(kind)) {
    const quote = element("blockquote");
    quote.append(element("span", "tag", kind.replaceAll("_", " ")), document.createTextNode(escapeText(value)));
    wrap.append(quote);
  } else if (kind === "DIAGRAM" || kind === "IMAGE") {
    wrap.append(element("p", "", content.alt || content.description || value || "Visual asset description unavailable."));
  } else {
    wrap.append(element("p", "", value));
  }
  const provenance = element("p", "muted provenance", "PROVENANCE · " + (block.provenance || "UNSPECIFIED"));
  wrap.append(provenance);
  const evidence = renderEvidence(block.evidence);
  if (evidence) wrap.append(evidence);
  return wrap;
}
function currentKey() {
  return "omniintel-reader:" + String(state.book?.version?.id || state.book?.version?.version_id || state.book?.version?.title || "local");
}
function saveProgress() {
  if (!state.book) return;
  try { localStorage.setItem(currentKey(), JSON.stringify({ chapter: state.index, savedAt: new Date().toISOString() })); } catch {}
}
function visibleBlocks(chapter) {
  const blocks = chapter?.blocks || [];
  if (!state.query) return blocks;
  const q = state.query.toLocaleLowerCase();
  return blocks.filter((block) => JSON.stringify(block.content || {}).toLocaleLowerCase().includes(q)
    || (block.evidence || []).some((item) => evidenceLabel(item).toLocaleLowerCase().includes(q)));
}
function renderChapter() {
  const chapter = state.chapters[state.index];
  if (!chapter) return;
  const title = chapter.chapter?.title || "Chapter " + (state.index + 1);
  $("#chapter-count").textContent = "CHAPTER " + (state.index + 1) + " OF " + state.chapters.length;
  $("#chapter-title").textContent = title;
  $("#progress").textContent = Math.round(((state.index + 1) / Math.max(1, state.chapters.length)) * 100) + "%";
  const host = $("#blocks");
  host.replaceChildren();
  const blocks = visibleBlocks(chapter);
  if (!blocks.length) host.append(element("p", "empty-search", state.query ? "No matching blocks in this chapter." : "This chapter has no blocks yet."));
  blocks.forEach((block) => host.append(renderBlock(block)));
  $("#previous").disabled = state.index === 0;
  $("#next").disabled = state.index >= state.chapters.length - 1;
  [...$("#chapter-nav").querySelectorAll("button")].forEach((button, index) => button.classList.toggle("active", index === state.index));
  saveProgress();
}
function renderBook(data, filename) {
  if (!data || !Array.isArray(data.chapters) || !data.version) throw new Error("This is not a valid OmniIntel reader export (expected version and chapters).");
  state.book = data;
  state.chapters = data.chapters;
  state.index = 0;
  state.query = "";
  $("#search").value = "";
  $("#book-title").textContent = data.version.textbook_title || data.version.title || filename || "Course textbook";
  $("#book-subtitle").textContent = (data.sources || []).length + " source(s) · " + state.chapters.length + " chapter(s)";
  const nav = $("#chapter-nav");
  nav.replaceChildren();
  state.chapters.forEach((entry, index) => {
    const button = element("button", "", (index + 1) + ". " + (entry.chapter?.title || "Untitled chapter"));
    button.type = "button";
    button.addEventListener("click", () => { state.index = index; renderChapter(); });
    nav.append(button);
  });
  try {
    const saved = JSON.parse(localStorage.getItem(currentKey()) || "null");
    if (Number.isInteger(saved?.chapter) && saved.chapter >= 0 && saved.chapter < state.chapters.length) state.index = saved.chapter;
  } catch {}
  $("#welcome").hidden = true;
  $("#reader").hidden = false;
  $("#clear-button").disabled = false;
  renderChapter();
}
fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  if (!file) return;
  try {
    if (file.size > 50 * 1024 * 1024) throw new Error("Reader export exceeds the 50 MB safety limit.");
    const parsed = JSON.parse(await file.text());
    renderBook(parsed, file.name);
  } catch (error) {
    alert("Could not open reader export: " + error.message);
  } finally { fileInput.value = ""; }
});
$("#clear-button").addEventListener("click", () => {
  state.book = null; state.chapters = []; state.index = 0;
  $("#reader").hidden = true; $("#welcome").hidden = false; $("#clear-button").disabled = true;
});
$("#search").addEventListener("input", (event) => { state.query = event.target.value.trim(); renderChapter(); });
$("#previous").addEventListener("click", () => { if (state.index > 0) { state.index--; renderChapter(); } });
$("#next").addEventListener("click", () => { if (state.index < state.chapters.length - 1) { state.index++; renderChapter(); } });
if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./service-worker.js").catch(() => {}));
}