"use strict";
const $ = (selector) => document.querySelector(selector);
const state = { book: null, chapters: [], index: 0, query: "", mediaSourceId: null, mediaUrl: null };
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
  const start = item.local_start_ms ?? item.start_ms;
  const end = item.local_end_ms ?? item.end_ms ?? start;
  if (start !== null && start !== undefined) return source + " · " + (start / 1000).toFixed(2) + "–" + (Number(end) / 1000).toFixed(2) + "s";
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
    if (item.alignment_status) {
      row.append(element("span", "tag", "CLOCK · " + String(item.alignment_status).replaceAll("_", " ")));
    }
    if (item.course_time_ms !== null && item.course_time_ms !== undefined) {
      row.append(element("span", "tag", "COURSE CLOCK · " + (Number(item.course_time_ms) / 1000).toFixed(2) + "s"));
    }
    if (item.local_start_ms !== null && item.local_start_ms !== undefined) {
      const seek = element("button", "seek-button", "▶ " + (Number(item.local_start_ms) / 1000).toFixed(1) + "s");
      seek.type = "button";
      seek.disabled = !state.mediaSourceId || state.mediaSourceId !== item.source_id;
      seek.title = seek.disabled ? "Attach this exact course source to enable seeking" : "Seek in attached local source";
      seek.addEventListener("click", () => {
        const media = $("#local-audio").hidden ? $("#local-media") : $("#local-audio");
        if (!media.src || state.mediaSourceId !== item.source_id) return;
        media.currentTime = Number(item.local_start_ms) / 1000;
        media.play().catch(() => {});
      });
      row.append(seek);
    }
    if (item.transcript_excerpt?.length) {
      for (const segment of item.transcript_excerpt) {
        const excerpt = element("p", "excerpt", "“" + segment.text + "”");
        row.append(excerpt);
      }
    }
    if (item.document_page?.text_content) {
      row.append(element("p", "", "Page text: " + item.document_page.text_content.slice(0, 1200)));
    }
    if (Array.isArray(item.document_elements) && item.document_elements.length) {
      const structure = element("details", "document-structure");
      structure.append(element("summary", "", "Page structure · " + item.document_elements.length + " positioned elements"));
      item.document_elements.slice(0, 20).forEach((part) => {
        const line = element("p", "document-element");
        const confidence = Number.isFinite(Number(part.confidence)) ? " · confidence " + Number(part.confidence).toFixed(2) : "";
        line.append(element("span", "tag", part.element_type || "ELEMENT"),
          document.createTextNode(" " + (part.text_content || part.content?.text || part.content?.label || "Visual element") +
            " · " + (part.review_state || "UNREVIEWED") + confidence));
        structure.append(line);
      });
      row.append(structure);
    }
    details.append(row);
  }
  return details;
}
let localDBPromise;
function openLocalDB() {
  if (localDBPromise) return localDBPromise;
  localDBPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open("omniintel-reader-local", 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("annotations")) db.createObjectStore("annotations", { keyPath: "key" });
      if (!db.objectStoreNames.contains("bookmarks")) db.createObjectStore("bookmarks", { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return localDBPromise;
}
function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
function transactionDone(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error("Local database transaction aborted"));
  });
}
function blockStorageKey(block) {
  const versionId = state.book?.version?.id || state.book?.version?.version_id || "local";
  const chapterId = state.chapters[state.index]?.chapter?.id || "chapter-" + state.index;
  return versionId + ":" + chapterId + ":" + (block.id || block.block_id || "ordinal-" + String(block.ordinal ?? "unknown"));
}
function addPersonalTools(block, host) {
  const panel = element("div", "personal-tools");
  const heading = element("p", "tag", "PERSONAL STUDY NOTES · THIS BROWSER ONLY");
  const note = document.createElement("textarea");
  note.rows = 3;
  note.maxLength = 12000;
  note.placeholder = "Add your own explanation, question or reminder…";
  note.setAttribute("aria-label", "Personal note for this textbook block");
  const actions = element("div", "personal-actions");
  const save = element("button", "quiet", "Save note");
  save.type = "button";
  const bookmark = element("button", "quiet", "☆ Bookmark");
  bookmark.type = "button";
  const status = element("span", "muted", "Stored only in this browser's local database.");
  actions.append(save, bookmark, status);
  panel.append(heading, note, actions);
  host.append(panel);
  const key = blockStorageKey(block);
  openLocalDB().then(async (db) => {
    const tx = db.transaction(["annotations", "bookmarks"], "readonly");
    const [savedNote, savedBookmark] = await Promise.all([
      requestResult(tx.objectStore("annotations").get(key)),
      requestResult(tx.objectStore("bookmarks").get(key))
    ]);
    if (savedNote) note.value = savedNote.text;
    if (savedBookmark) bookmark.textContent = "★ Bookmarked";
  }).catch(() => { status.textContent = "Local notes unavailable in this browser."; });
  save.addEventListener("click", async () => {
    try {
      const db = await openLocalDB();
      const tx = db.transaction("annotations", "readwrite");
      tx.objectStore("annotations").put({ key, text: note.value, updatedAt: new Date().toISOString() });
      await transactionDone(tx);
      status.textContent = "Saved on this device.";
    } catch { status.textContent = "Could not save note."; }
  });
  bookmark.addEventListener("click", async () => {
    try {
      const db = await openLocalDB();
      const tx = db.transaction("bookmarks", "readwrite");
      const store = tx.objectStore("bookmarks");
      const request = store.get(key);
      request.onsuccess = () => {
        if (request.result) {
          store.delete(key);
          bookmark.textContent = "☆ Bookmark";
        } else {
          store.put({ key, createdAt: new Date().toISOString() });
          bookmark.textContent = "★ Bookmarked";
        }
      };
      await transactionDone(tx);
    } catch { status.textContent = "Could not update bookmark."; }
  });
}
function renderBlock(block) {
  const wrap = element("section", "content-block");
  if (block.id || block.block_id) wrap.dataset.blockId = block.id || block.block_id;
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
  addPersonalTools(block, wrap);
  return wrap;
}
function currentKey() {
  return "omniintel-reader:" + String(state.book?.version?.id || state.book?.version?.version_id || state.book?.version?.title || "local");
}
function saveProgress() {
  if (!state.book) return;
  try { localStorage.setItem(currentKey(), JSON.stringify({ chapter: state.index, savedAt: new Date().toISOString() })); } catch {}
}
function blockMatches(block, query) {
  if (!query) return true;
  const q = query.toLocaleLowerCase();
  return JSON.stringify(block.content || {}).toLocaleLowerCase().includes(q)
    || (block.evidence || []).some((item) => evidenceLabel(item).toLocaleLowerCase().includes(q)
      || (item.transcript_excerpt || []).some((segment) => String(segment.text || "").toLocaleLowerCase().includes(q))
      || String(item.document_page?.text_content || "").toLocaleLowerCase().includes(q));
}
function visibleBlocks(chapter) {
  return (chapter?.blocks || []).filter((block) => blockMatches(block, state.query));
}
function renderSearchResults() {
  const host = $("#search-results");
  host.replaceChildren();
  if (!state.query) return;
  let count = 0;
  state.chapters.forEach((chapter, chapterIndex) => {
    const title = chapter.chapter?.title || "Chapter " + (chapterIndex + 1);
    (chapter.blocks || []).forEach((block) => {
      if (!blockMatches(block, state.query)) return;
      count++;
      const button = element("button", "search-result");
      button.type = "button";
      const heading = element("strong", "", title);
      const preview = block.content?.text || block.content?.body || block.content?.term
        || block.content?.definition || block.content?.description || block.block_type || "Matching evidence";
      button.append(heading, element("span", "", String(preview).slice(0, 110)));
      button.addEventListener("click", () => {
        state.index = chapterIndex;
        renderChapter();
        const target = block.id || block.block_id;
        if (target) document.querySelector('[data-block-id="' + CSS.escape(target) + '"]')?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      host.append(button);
    });
  });
  if (!count) host.append(element("p", "empty-search", "No matches in this book."));
  else host.prepend(element("p", "search-count", count + " result" + (count === 1 ? "" : "s") + " across the book"));
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
function configureMediaSources() {
  const select = $("#media-source");
  select.replaceChildren();
  const placeholder = element("option", "", "Select the exact course source…");
  placeholder.value = "";
  placeholder.selected = true;
  select.append(placeholder);
  for (const source of state.book?.sources || []) {
    const option = element("option", "", source.title || source.source_id);
    option.value = source.source_id;
    select.append(option);
  }
  select.disabled = !(state.book?.sources || []).length;
  $("#media-file").disabled = true;
  state.mediaSourceId = null;
  $("#media-status").textContent = select.disabled ? "This reader export has no course sources." : "Select the exact course source, then attach only the matching local media file.";
}
function resetLocalMedia() {
  const video = $("#local-media");
  const audio = $("#local-audio");
  for (const media of [video, audio]) {
    media.pause();
    media.removeAttribute("src");
    media.load();
    media.hidden = true;
  }
  if (state.mediaUrl) URL.revokeObjectURL(state.mediaUrl);
  state.mediaUrl = null;
  $("#media-status").textContent = "No media attached.";
}
function validateReaderPayload(data) {
  if (!data || typeof data !== "object" || !data.version || typeof data.version !== "object" ||
      !Array.isArray(data.chapters) || !Array.isArray(data.sources)) {
    throw new Error("This is not a valid OmniIntel reader export (expected version, sources and chapters).");
  }
  if (data.chapters.length < 1 || data.chapters.length > 500) {
    throw new Error("Reader export must contain between 1 and 500 chapters.");
  }
  let totalBlocks = 0;
  for (const chapter of data.chapters) {
    if (!chapter || typeof chapter !== "object" || !chapter.chapter || typeof chapter.chapter !== "object" ||
        !Array.isArray(chapter.blocks)) throw new Error("A chapter has an invalid structure.");
    totalBlocks += chapter.blocks.length;
    if (totalBlocks > 25000) throw new Error("Reader export exceeds the 25,000 block safety limit.");
    for (const block of chapter.blocks) {
      if (!block || typeof block !== "object" || typeof block.block_type !== "string" ||
          !block.content || typeof block.content !== "object" || Array.isArray(block.content) ||
          !Array.isArray(block.evidence)) throw new Error("A textbook block has an invalid structure.");
      if (block.evidence.length > 100) throw new Error("A textbook block exceeds the 100 evidence-reference safety limit.");
      for (const item of block.evidence) {
        if (!item || typeof item !== "object" || typeof item.source_id !== "string" ||
            typeof item.locator_kind !== "string") throw new Error("An evidence reference has an invalid structure.");
        if ((item.transcript_excerpt?.length || 0) > 40 || (item.document_elements?.length || 0) > 100) {
          throw new Error("An evidence reference exceeds the reader rendering safety limits.");
        }
      }
    }
  }
  for (const source of data.sources) {
    if (!source || typeof source !== "object" || typeof source.source_id !== "string") {
      throw new Error("A course source has an invalid structure.");
    }
  }
}
function renderBook(data, filename) {
  validateReaderPayload(data);
  state.book = data;
  state.chapters = data.chapters;
  state.index = 0;
  state.query = "";
  $("#search").value = "";
  $("#search-results").replaceChildren();
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
  configureMediaSources();
  resetLocalMedia();
  renderChapter();
}
fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  if (!file) return;
  try {
    if (file.size > 50 * 1024 * 1024) throw new Error("Reader export exceeds the 50 MB safety limit.");
    const bytes = await file.arrayBuffer();
    const raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    const parsed = JSON.parse(raw);
    renderBook(parsed, file.name);
  } catch (error) {
    alert("Could not open reader export: " + error.message);
  } finally { fileInput.value = ""; }
});
$("#clear-button").addEventListener("click", () => {
  resetLocalMedia();
  state.book = null; state.chapters = []; state.index = 0; state.mediaSourceId = null;
  $("#media-source").replaceChildren();
  $("#media-file").disabled = true;
  $("#reader").hidden = true; $("#welcome").hidden = false; $("#clear-button").disabled = true;
});
$("#media-source").addEventListener("change", (event) => {
  resetLocalMedia();
  state.mediaSourceId = event.target.value || null;
  $("#media-file").disabled = !state.mediaSourceId;
  $("#media-status").textContent = state.mediaSourceId
    ? "Source selected. Attach only the matching local media file."
    : "Select the exact course source before attaching media.";
  renderChapter();
});
$("#media-file").addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (!file || !state.mediaSourceId) return;
  if (!file.type.startsWith("video/") && !file.type.startsWith("audio/")) {
    $("#media-status").textContent = "Choose a browser-supported audio or video file.";
    event.target.value = "";
    return;
  }
  resetLocalMedia();
  state.mediaUrl = URL.createObjectURL(file);
  const media = file.type.startsWith("audio/") ? $("#local-audio") : $("#local-media");
  media.src = state.mediaUrl;
  media.hidden = false;
  media.load();
  $("#media-status").textContent = "Attached locally: " + file.name + ". Timestamps are source-local; no cross-source offset is applied.";
  event.target.value = "";
  renderChapter();
});
$("#search").addEventListener("input", (event) => {
  state.query = event.target.value.trim();
  renderSearchResults();
  renderChapter();
});
$("#previous").addEventListener("click", () => { if (state.index > 0) { state.index--; renderChapter(); } });
$("#next").addEventListener("click", () => { if (state.index < state.chapters.length - 1) { state.index++; renderChapter(); } });
if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./service-worker.js").catch(() => {}));
}