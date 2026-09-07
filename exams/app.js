(function () {
  "use strict";

  const PDF_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M6 2h9l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z"/><path d="M15 2v5h5"/></svg>`;
  const FILE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M6 2h9l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z"/></svg>`;

  const el = {
    search: document.getElementById("search"),
    subjectFilter: document.getElementById("subject-filter"),
    yearFilter: document.getElementById("year-filter"),
    typeFilter: document.getElementById("type-filter"),
    list: document.getElementById("file-list"),
    count: document.getElementById("result-count"),
    empty: document.getElementById("empty-state"),
    error: document.getElementById("error-state"),
  };

  let files = [];

  function uniqueSorted(values) {
    return [...new Set(values.filter(Boolean))].sort((a, b) =>
      String(a).localeCompare(String(b), undefined, { numeric: true })
    );
  }

  function populateFilters() {
    for (const subject of uniqueSorted(files.map((f) => f.subject))) {
      el.subjectFilter.appendChild(new Option(subject, subject));
    }
    for (const year of uniqueSorted(files.map((f) => f.year)).reverse()) {
      el.yearFilter.appendChild(new Option(year, year));
    }
    for (const type of uniqueSorted(files.map((f) => f.exam_type))) {
      el.typeFilter.appendChild(new Option(capitalize(type), type));
    }
  }

  function capitalize(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  }

  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  function formatSize(bytes) {
    if (!bytes && bytes !== 0) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function matchesFilters(file, query, subject, year, type) {
    if (subject && file.subject !== subject) return false;
    if (year && file.year !== year) return false;
    if (type && file.exam_type !== type) return false;
    if (query) {
      const haystack = `${file.original_filename} ${file.subject} ${file.exam_type} ${file.message_content || ""}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  }

  function renderCard(file) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.className = "file-card";
    a.href = file.stored_path;
    a.target = "_blank";
    a.rel = "noopener";

    let thumbHtml;
    if (file.file_kind === "image") {
      thumbHtml = `<img class="file-thumb" src="${encodeURI(file.stored_path)}" alt="" loading="lazy">`;
    } else {
      thumbHtml = `<span class="file-icon">${file.file_kind === "pdf" ? PDF_ICON : FILE_ICON}</span>`;
    }

    a.innerHTML = `
      ${thumbHtml}
      <span class="file-info">
        <span class="file-name">${escapeHtml(file.original_filename)}</span>
        <span class="file-meta">
          <span class="badge">${escapeHtml(file.subject)}</span>
          <span class="badge">${escapeHtml(file.year)}</span>
          <span class="badge">${escapeHtml(capitalize(file.exam_type))}</span>
          <span>${formatDate(file.timestamp)}${file.file_size_bytes ? " · " + formatSize(file.file_size_bytes) : ""}</span>
        </span>
      </span>
      <span class="download-btn">Open</span>
    `;
    li.appendChild(a);
    return li;
  }

  function escapeHtml(str) {
    return String(str ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function render() {
    const query = el.search.value.trim().toLowerCase();
    const subject = el.subjectFilter.value;
    const year = el.yearFilter.value;
    const type = el.typeFilter.value;

    const filtered = files
      .filter((f) => matchesFilters(f, query, subject, year, type))
      .sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || ""));

    el.list.innerHTML = "";
    const fragment = document.createDocumentFragment();
    for (const file of filtered) fragment.appendChild(renderCard(file));
    el.list.appendChild(fragment);

    el.count.textContent = `${filtered.length} file${filtered.length === 1 ? "" : "s"}`;
    el.empty.hidden = filtered.length !== 0;
  }

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  el.search.addEventListener("input", debounce(render, 150));
  el.subjectFilter.addEventListener("change", render);
  el.yearFilter.addEventListener("change", render);
  el.typeFilter.addEventListener("change", render);

  fetch("index.json")
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then((data) => {
      files = data.files || [];
      populateFilters();
      render();
    })
    .catch((err) => {
      console.error("Failed to load index.json", err);
      el.error.hidden = false;
    });
})();
