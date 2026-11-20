"use strict";
const $ = (selector) => document.querySelector(selector);
const state = { book: null, chapters: [], index: 0, query: "", mediaSourceId: null, mediaUrl: null, studyCards: [], studyIndex: 0, studyRevealed: false };
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
    const request = indexedDB.open("omniintel-reader-local", 3);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("annotations")) db.createObjectStore("annotations", { keyPath: "key" });
      if (!db.objectStoreNames.contains("bookmarks")) db.createObjectStore("bookmarks", { keyPath: "key" });
      if (!db.objectStoreNames.contains("studyProgress")) db.createObjectStore("studyProgress", { keyPath: "key" });
      if (!db.objectStoreNames.contains("readerBooks")) db.createObjectStore("readerBooks", { keyPath: "key" });
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
  openLocalDB().then(async (db) => {
    const key = data.version.id || data.version.version_id;
    const tx = db.transaction("readerBooks", "readwrite");
    tx.objectStore("readerBooks").put({
      key,
      title: data.version.textbook_title || data.version.title || filename || "Course textbook",
      data,
      updatedAt: Date.now()
    });
    await transactionDone(tx);
  }).catch(() => {});
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

function buildStudyCards() {
  const cards = [];
  const versionId = state.book?.version?.id || state.book?.version?.version_id || "local";
  state.chapters.forEach((chapter, chapterIndex) => {
    (chapter.blocks || []).forEach((block, blockIndex) => {
      const content = block.content || {};
      const kind = String(block.block_type || "").toUpperCase();
      let front = "", back = "", label = "";
      if (kind === "DEFINITION") {
        front = content.term || content.title || "Define this concept";
        back = content.definition || content.text || content.body || "";
        label = "DEFINITION";
      } else if (kind === "EXERCISE") {
        front = content.prompt || content.question || content.text || content.body || "";
        back = content.answer || content.solution || content.expected_answer || "";
        label = "PRACTICE";
      } else if (kind === "FLASHCARD" || kind === "QUESTION") {
        front = content.front || content.question || content.prompt || content.term || "";
        back = content.back || content.answer || content.definition || content.solution || "";
        label = "SOURCE FLASHCARD";
      }
      if (!String(front).trim()) return;
      if (!String(back).trim()) back = "No answer is supplied in this block. Review its source evidence and assess your response yourself.";
      const blockId = block.id || block.block_id || "block-" + blockIndex;
      cards.push({
        key: versionId + ":study:" + blockId,
        front: String(front),
        back: String(back),
        label,
        provenance: block.provenance || "UNSPECIFIED",
        evidence: Array.isArray(block.evidence) ? block.evidence : [],
        chapterTitle: chapter.chapter?.title || "Chapter " + (chapterIndex + 1)
      });
    });
  });
  return cards;
}
async function renderStudyCard() {
  const cards = state.studyCards;
  const panel = $("#study-panel");
  if (!cards.length) {
    $("#study-count").textContent = "No definition, exercise or flashcard blocks are available in this book.";
    $("#study-position").textContent = "0 CARDS";
    $("#study-front").textContent = "Add reviewed definitions or practice questions to this textbook to create a study deck.";
    $("#study-answer").hidden = true;
    $("#study-prev").disabled = $("#study-next").disabled = $("#study-reveal").disabled = true;
    $("#study-known").disabled = $("#study-review").disabled = true;
    return;
  }
  state.studyIndex = Math.max(0, Math.min(state.studyIndex, cards.length - 1));
  const card = cards[state.studyIndex];
  const db = await openLocalDB();
  const tx = db.transaction("studyProgress", "readonly");
  const all = await requestResult(tx.objectStore("studyProgress").getAll());
  const known = all.filter(item => item.key.startsWith((state.book?.version?.id || state.book?.version?.version_id || "local") + ":study:") && item.status === "KNOWN").length;
  $("#study-count").textContent = cards.length + " cards · " + known + " marked known";
  $("#study-position").textContent = (state.studyIndex + 1) + " / " + cards.length;
  $("#study-kind").textContent = card.label + " · " + card.chapterTitle;
  $("#study-front").textContent = card.front;
  $("#study-answer").textContent = card.back;
  $("#study-answer").hidden = !state.studyRevealed;
  $("#study-provenance").textContent = "PROVENANCE · " + card.provenance + " · " + card.evidence.length + " evidence reference(s)";
  $("#study-prev").disabled = state.studyIndex === 0;
  $("#study-next").disabled = state.studyIndex === cards.length - 1;
  $("#study-reveal").disabled = state.studyRevealed;
  $("#study-reveal").textContent = state.studyRevealed ? "Answer revealed" : "Reveal answer";
  $("#study-known").disabled = !state.studyRevealed;
  $("#study-review").disabled = !state.studyRevealed;
}
function moveStudy(delta) {
  state.studyIndex = Math.max(0, Math.min(state.studyCards.length - 1, state.studyIndex + delta));
  state.studyRevealed = false;
  renderStudyCard().catch(() => { $("#study-count").textContent = "Local study progress is unavailable."; });
}
$("#study-toggle").addEventListener("click", () => {
  const panel = $("#study-panel");
  panel.hidden = !panel.hidden;
  if (!panel.hidden) {
    state.studyCards = buildStudyCards();
    state.studyIndex = 0;
    state.studyRevealed = false;
    renderStudyCard().catch(() => { $("#study-count").textContent = "Local study progress is unavailable."; });
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});
$("#study-prev").addEventListener("click", () => moveStudy(-1));
$("#study-next").addEventListener("click", () => moveStudy(1));
$("#study-reveal").addEventListener("click", () => {
  state.studyRevealed = true;
  renderStudyCard().catch(() => {});
});
async function markStudy(status) {
  const card = state.studyCards[state.studyIndex];
  if (!card) return;
  try {
    const db = await openLocalDB();
    const tx = db.transaction("studyProgress", "readwrite");
    tx.objectStore("studyProgress").put({ key: card.key, status, updatedAt: new Date().toISOString() });
    await transactionDone(tx);
    moveStudy(status === "KNOWN" ? 1 : 0);
  } catch {
    $("#study-count").textContent = "Could not save study progress in this browser.";
  }
}
$("#study-known").addEventListener("click", () => markStudy("KNOWN"));
$("#study-review").addEventListener("click", () => markStudy("REVIEW"));


const restoreFileInput = $("#restore-local-file");
function parseWebBackup(raw) {
  if (raw.length > 10 * 1024 * 1024) throw new Error("Backup exceeds the 10 MiB limit.");
  const data = JSON.parse(raw);
  if (!data || data.schema_version !== 1 || data.backup_type !== "OMNIINTEL_WEB_LOCAL_BACKUP") {
    throw new Error("Unsupported OmniIntel Web backup format.");
  }
  const arrays = ["annotations", "bookmarks", "study_progress", "reading_progress"];
  for (const name of arrays) {
    if (!Array.isArray(data[name]) || data[name].length > 100000) throw new Error("Invalid or oversized " + name + " collection.");
  }
  const seen = new Set();
  for (const row of data.annotations) {
    if (!row || typeof row.key !== "string" || row.key.length > 512 ||
        typeof row.text !== "string" || row.text.length > 12000 ||
        !Number.isFinite(Date.parse(row.updatedAt))) throw new Error("Invalid annotation record.");
    if (seen.has("a:" + row.key)) throw new Error("Duplicate annotation key.");
    seen.add("a:" + row.key);
  }
  for (const row of data.bookmarks) {
    if (!row || typeof row.key !== "string" || row.key.length > 512 ||
        !Number.isFinite(Date.parse(row.createdAt))) throw new Error("Invalid bookmark record.");
    if (seen.has("b:" + row.key)) throw new Error("Duplicate bookmark key.");
    seen.add("b:" + row.key);
  }
  for (const row of data.study_progress) {
    if (!row || typeof row.key !== "string" || row.key.length > 512 ||
        !["KNOWN", "REVIEW"].includes(row.status) ||
        !Number.isFinite(Date.parse(row.updatedAt))) throw new Error("Invalid study-progress record.");
    if (seen.has("s:" + row.key)) throw new Error("Duplicate study-progress key.");
    seen.add("s:" + row.key);
  }
  for (const row of data.reading_progress) {
    if (!row || typeof row.key !== "string" || !row.key.startsWith("omniintel-reader:") ||
        row.key.length > 512 || typeof row.value !== "string" || row.value.length > 2048) {
      throw new Error("Invalid reading-progress record.");
    }
    const progress = JSON.parse(row.value);
    if (!Number.isInteger(progress.chapter) || progress.chapter < 0 ||
        !Number.isFinite(Date.parse(progress.savedAt))) throw new Error("Invalid reading-progress value.");
  }
  return data;
}
async function exportWebBackup() {
  const db = await openLocalDB();
  const read = db.transaction(["annotations", "bookmarks", "studyProgress"], "readonly");
  const [annotations, bookmarks, studyProgress] = await Promise.all([
    requestResult(read.objectStore("annotations").getAll()),
    requestResult(read.objectStore("bookmarks").getAll()),
    requestResult(read.objectStore("studyProgress").getAll())
  ]);
  const readingProgress = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key?.startsWith("omniintel-reader:")) {
      readingProgress.push({ key, value: localStorage.getItem(key) || "" });
    }
  }
  const payload = {
    schema_version: 1,
    backup_type: "OMNIINTEL_WEB_LOCAL_BACKUP",
    exported_at: new Date().toISOString(),
    annotations, bookmarks, study_progress: studyProgress,
    reading_progress: readingProgress
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  if (blob.size > 10 * 1024 * 1024) throw new Error("Combined local backup exceeds 10 MiB.");
  const url = URL.createObjectURL(blob);
  const anchor = element("a", "", "");
  anchor.href = url;
  anchor.download = "omniintel-web-backup.json";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
async function restoreWebBackup(data) {
  const db = await openLocalDB();
  const read = db.transaction(["annotations", "bookmarks", "studyProgress"], "readonly");
  const [oldAnnotations, oldBookmarks, oldStudy] = await Promise.all([
    requestResult(read.objectStore("annotations").getAll()),
    requestResult(read.objectStore("bookmarks").getAll()),
    requestResult(read.objectStore("studyProgress").getAll())
  ]);
  const merge = (oldRows, incoming, timestamp) => {
    const map = new Map(oldRows.map(row => [row.key, row]));
    for (const row of incoming) {
      const previous = map.get(row.key);
      if (!previous || Date.parse(row[timestamp]) >= Date.parse(previous[timestamp] || 0)) map.set(row.key, row);
    }
    return [...map.values()];
  };
  const mergedAnnotations = merge(oldAnnotations, data.annotations, "updatedAt");
  const mergedBookmarks = merge(oldBookmarks, data.bookmarks, "createdAt");
  const mergedStudy = merge(oldStudy, data.study_progress, "updatedAt");
  const write = db.transaction(["annotations", "bookmarks", "studyProgress"], "readwrite");
  for (const row of mergedAnnotations) write.objectStore("annotations").put(row);
  for (const row of mergedBookmarks) write.objectStore("bookmarks").put(row);
  for (const row of mergedStudy) write.objectStore("studyProgress").put(row);
  await transactionDone(write);
  for (const row of data.reading_progress) {
    let previous = null;
    try { previous = JSON.parse(localStorage.getItem(row.key) || "null"); } catch {}
    const incoming = JSON.parse(row.value);
    if (!previous || Date.parse(incoming.savedAt) >= Date.parse(previous.savedAt || 0)) {
      localStorage.setItem(row.key, row.value);
    }
  }
  return {
    annotations: data.annotations.length,
    bookmarks: data.bookmarks.length,
    study: data.study_progress.length,
    progress: data.reading_progress.length
  };
}
$("#backup-local").addEventListener("click", () => {
  exportWebBackup().catch(error => alert("Could not back up local data: " + error.message));
});
restoreFileInput.addEventListener("change", async () => {
  const file = restoreFileInput.files?.[0];
  if (!file) return;
  try {
    const raw = await file.text();
    const data = parseWebBackup(raw);
    const counts = await restoreWebBackup(data);
    alert("Backup merged on this device. Notes: " + counts.annotations +
      ", bookmarks: " + counts.bookmarks + ", study records: " + counts.study +
      ", reading positions: " + counts.progress + ". Newer local records were preserved.");
  } catch (error) {
    alert("Could not restore backup: " + error.message);
  } finally {
    restoreFileInput.value = "";
  }
});


// Online video → notes client. The API token is held only for this browser tab.
const onlineForm = $("#online-video-form");
if (onlineForm) {
  const onlineStatus = $("#online-status");
  const onlineButton = $("#online-submit");
  const apiInput = $("#api-base-url");
  const savedApi = localStorage.getItem("omniintel-api-base-url");
  if (savedApi) apiInput.value = savedApi;
  const savedToken = sessionStorage.getItem("omniintel-api-token");
  if (savedToken) $("#api-token").value = savedToken;

  function setOnlineStatus(message, isError = false) {
    onlineStatus.textContent = message;
    onlineStatus.classList.toggle("error", isError);
  }
  function apiBase() {
    const parsed = new URL(apiInput.value.trim());
    const local = ["localhost", "127.0.0.1"].includes(parsed.hostname);
    if (parsed.protocol !== "https:" && !(local && parsed.protocol === "http:")) {
      throw new Error("Use HTTPS for a remote API. HTTP is allowed only for localhost.");
    }
    return parsed.origin;
  }
  async function apiRequest(base, token, path, options = {}) {
    const response = await fetch(base + path, {
      ...options,
      headers: {
        "Authorization": "Bearer " + token,
        ...(options.headers || {})
      }
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || ("API request failed: HTTP " + response.status));
    return body;
  }
  onlineForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!onlineForm.reportValidity()) return;
    onlineButton.disabled = true;
    try {
      const base = apiBase();
      const token = $("#api-token").value.trim();
      if (!token) throw new Error("Enter the API access token supplied by your OmniIntel server.");
      if (!$("#approve-network").checked) throw new Error("Confirm permission to retrieve public video metadata and captions.");
      if (!$("#approve-ai").checked) throw new Error("Confirm that the transcript may be sent to the configured AI provider to generate study notes.");
      localStorage.setItem("omniintel-api-base-url", base);
      sessionStorage.setItem("omniintel-api-token", token);
      setOnlineStatus("Submitting video…");
      const created = await apiRequest(base, token, "/v1/youtube/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: $("#video-url").value.trim(),
          approve_network: true,
          approve_ai: true,
          language: $("#video-language").value.trim() || null,
          chapter_minutes: 10
        })
      });
      setOnlineStatus("Video accepted · job " + created.job_id + " · fetching metadata and captions…");
      for (let attempt = 0; attempt < 1800; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        const job = await apiRequest(base, token, created.status_url);
        if (job.status === "COMPLETED") {
          if (!job.result_url || !job.result_url.startsWith("https://")) throw new Error("The server completed without a reader download URL.");
          const readerResponse = await fetch(job.result_url);
          if (!readerResponse.ok) throw new Error("Reader download failed: HTTP " + readerResponse.status);
          const reader = await readerResponse.json();
          setOnlineStatus("Notes generated · opening " + (reader.source?.title || "your video") + "…");
          renderBook(reader, (reader.source?.title || "OmniIntel video notes") + ".json");
          return;
        }
        if (job.status === "FAILED") throw new Error(job.error || "Video processing failed.");
        setOnlineStatus("Processing video · " + job.status.toLowerCase() + " · attempt " + job.attempt);
      }
      throw new Error("This job is still running. Reopen the app and check its job status with the server.");
    } catch (error) {
      setOnlineStatus(error.message || "Video processing failed.", true);
    } finally {
      onlineButton.disabled = false;
    }
  });

  const mediaUploadForm = $("#online-media-form");
  if (mediaUploadForm) {
    const uploadButton = $("#media-upload-submit");
    const uploadStatus = $("#media-upload-status");
    mediaUploadForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!mediaUploadForm.reportValidity()) return;
      uploadButton.disabled = true;
      try {
        const base = apiBase();
        const token = $("#api-token").value.trim();
        const file = $("#media-upload-file").files?.[0];
        if (!token) throw new Error("Enter the server API token above.");
        if (!file) throw new Error("Choose an audio or video file.");
        if (file.size > 250 * 1024 * 1024) throw new Error("Media upload exceeds the 250 MiB limit.");
        if (!file.type.startsWith("audio/") && !file.type.startsWith("video/")) {
          throw new Error("Choose a supported audio or video file.");
        }
        if (!$("#approve-upload-ai").checked) {
          throw new Error("Approve sending the generated transcript to the server-configured AI provider.");
        }
        sessionStorage.setItem("omniintel-api-token", token);
        localStorage.setItem("omniintel-api-base-url", base);
        uploadStatus.textContent = "Uploading media securely…";
        const created = await apiRequest(base, token, "/v1/media/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filename: file.name,
            title: file.name,
            approve_media_upload: true,
            approve_ai: true,
            language: $("#upload-language").value.trim() || null,
            chapter_minutes: 10
          })
        });
        if (!created.upload_url || !created.upload_complete_url) throw new Error("The server did not return a B2 upload URL.");
        uploadStatus.textContent = "Uploading media to private storage…";
        const uploaded = await fetch(created.upload_url, {
          method: "PUT",
          headers: { "Content-Type": file.type },
          body: file
        });
        if (!uploaded.ok) throw new Error("Backblaze upload failed: HTTP " + uploaded.status);
        await apiRequest(base, token, created.upload_complete_url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}"
        });
        uploadStatus.textContent = "Upload verified · transcription job " + created.job_id;
        for (let attempt = 0; attempt < 1800; attempt++) {
          await new Promise(resolve => setTimeout(resolve, 2000));
          const job = await apiRequest(base, token, created.status_url);
          if (job.status === "COMPLETED") {
            if (!job.result_url || !job.result_url.startsWith("https://")) throw new Error("The server completed without a reader download URL.");
            const readerResponse = await fetch(job.result_url);
            if (!readerResponse.ok) throw new Error("Reader download failed: HTTP " + readerResponse.status);
            const reader = await readerResponse.json();
            uploadStatus.textContent = "Transcription and notes complete · opening your reader…";
            renderBook(reader, (reader.source?.title || file.name) + ".json");
            return;
          }
          if (job.status === "FAILED") throw new Error(job.error || "Media processing failed.");
          uploadStatus.textContent = "Transcribing media · " + job.status.toLowerCase();
        }
        throw new Error("The job is still running. Check its status with the server later.");
      } catch (error) {
        uploadStatus.textContent = error.message || "Media processing failed.";
        uploadStatus.classList.add("error");
      } finally {
        uploadButton.disabled = false;
      }
    });
  }
}


async function restoreLatestReaderBook() {
  try {
    const db = await openLocalDB();
    const tx = db.transaction("readerBooks", "readonly");
    const books = await requestResult(tx.objectStore("readerBooks").getAll());
    books.sort((a, b) => Number(b.updatedAt || 0) - Number(a.updatedAt || 0));
    if (!state.book && books[0]?.data) renderBook(books[0].data, books[0].title);
  } catch {}
}
restoreLatestReaderBook();
