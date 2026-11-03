/**
 * Axiom Mobility (Fleetline) - Fast Client-Side 50-Row Table Pagination.
 *
 * Prevents browser DOM freezing when viewing 1,000+ duties or bulk upload staging rows.
 */

export class TablePagination {
  constructor(options = {}) {
    this.pageSize = options.pageSize || 50;
    this.currentPage = 1;
    this.rows = options.rows || [];
    this.filteredRows = [...this.rows];
    this.searchQuery = "";
    this.sortField = options.defaultSortField || null;
    this.sortDirection = options.defaultSortDir || "desc"; // "asc" | "desc"
  }

  setRows(newRows) {
    this.rows = Array.isArray(newRows) ? newRows : [];
    this.applyFilterAndSort();
  }

  setSearch(query) {
    this.searchQuery = String(query || "").trim().toLowerCase();
    this.currentPage = 1;
    this.applyFilterAndSort();
  }

  setSort(field) {
    if (this.sortField === field) {
      this.sortDirection = this.sortDirection === "asc" ? "desc" : "asc";
    } else {
      this.sortField = field;
      this.sortDirection = "desc";
    }
    this.applyFilterAndSort();
  }

  setPage(page) {
    const total = this.getTotalPages();
    this.currentPage = Math.max(1, Math.min(page, Math.max(1, total)));
  }

  nextPage() {
    this.setPage(this.currentPage + 1);
  }

  prevPage() {
    this.setPage(this.currentPage - 1);
  }

  applyFilterAndSort() {
    let result = [...this.rows];

    // Filter by search query
    if (this.searchQuery) {
      result = result.filter((row) => {
        return Object.values(row).some((val) => {
          if (val === null || val === undefined) return false;
          if (typeof val === "object") {
            return JSON.stringify(val).toLowerCase().includes(this.searchQuery);
          }
          return String(val).toLowerCase().includes(this.searchQuery);
        });
      });
    }

    // Sort
    if (this.sortField) {
      const field = this.sortField;
      const factor = this.sortDirection === "asc" ? 1 : -1;
      result.sort((a, b) => {
        const valA = a[field];
        const valB = b[field];
        if (valA === valB) return 0;
        if (valA === null || valA === undefined) return 1;
        if (valB === null || valB === undefined) return -1;
        if (typeof valA === "number" && typeof valB === "number") {
          return (valA - valB) * factor;
        }
        return String(valA).localeCompare(String(valB)) * factor;
      });
    }

    this.filteredRows = result;
    const maxPage = this.getTotalPages();
    if (this.currentPage > maxPage) {
      this.currentPage = Math.max(1, maxPage);
    }
  }

  getTotalPages() {
    return Math.ceil(this.filteredRows.length / this.pageSize) || 1;
  }

  getPageRows() {
    const start = (this.currentPage - 1) * this.pageSize;
    const end = start + this.pageSize;
    return this.filteredRows.slice(start, end);
  }

  getPaginationMeta() {
    const totalCount = this.filteredRows.length;
    const totalPages = this.getTotalPages();
    const startRow = totalCount === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1;
    const endRow = Math.min(this.currentPage * this.pageSize, totalCount);

    return {
      currentPage: this.currentPage,
      totalPages,
      pageSize: this.pageSize,
      totalCount,
      startRow,
      endRow,
      hasNext: this.currentPage < totalPages,
      hasPrev: this.currentPage > 1,
    };
  }

  renderPaginationControls(onPageChangeCallback) {
    const meta = this.getPaginationMeta();
    return `
      <div class="axiom-pagination-bar" style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: #0f172a; border-top: 1px solid #1e293b; color: #94a3b8; font-size: 12px; font-weight: 600;">
        <div>
          Showing <span style="color: #f8fafc; font-weight: 700;">${meta.startRow}–${meta.endRow}</span> of <span style="color: #f8fafc; font-weight: 700;">${meta.totalCount}</span> entries
        </div>
        <div style="display: flex; gap: 6px; align-items: center;">
          <button class="pg-btn" ${!meta.hasPrev ? "disabled style='opacity: 0.4; cursor: not-allowed;'" : ""} data-action="prev" style="padding: 4px 10px; background: #1e293b; border: 1px solid #334155; color: #f8fafc; border-radius: 4px; cursor: pointer;">
            ◀ Prev
          </button>
          <span style="padding: 0 8px; color: #38bdf8;">Page ${meta.currentPage} of ${meta.totalPages}</span>
          <button class="pg-btn" ${!meta.hasNext ? "disabled style='opacity: 0.4; cursor: not-allowed;'" : ""} data-action="next" style="padding: 4px 10px; background: #1e293b; border: 1px solid #334155; color: #f8fafc; border-radius: 4px; cursor: pointer;">
            Next ▶
          </button>
        </div>
      </div>
    `;
  }
}
