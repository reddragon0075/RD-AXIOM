/**
 * Axiom Mobility (Fleetline) - OpenStreetMap (OSM) & OSRM Interactive Map Component.
 * Zero-Build Vanilla ES6+ Leaflet Controller.
 *
 * Capabilities:
 * 1. Live Command Center Mode: Status-colored vehicle markers (Running, Idle, SOS, Escorted).
 * 2. Duty Audit Diff Mode: Planned (Dashed Slate) vs. OSRM Road-Snapped (Solid Blue) + Stoppage/Deviation Pins.
 * 3. Interactive Autocomplete Pin-Drop wired to /api/v1/osm/autocomplete.
 * 4. High-contrast CartoDB Voyager / Positron & Standard OSM tile layers switch.
 */

export class AxiomOsmMap {
  constructor(options = {}) {
    this.container = options.container || (typeof document !== "undefined" ? document.getElementById("axiom-osm-map-view") : null);
    this.apiBase = options.apiBase || "/api/v1";
    this.mode = options.mode || "COMMAND_CENTER"; // "COMMAND_CENTER" | "DUTY_AUDIT_DIFF" | "AUTOCOMPLETE_PIN_DROP" | "ETS_ROUTE"
    this.center = options.center || [12.9716, 77.5946]; // Bengaluru
    this.zoom = options.zoom || 12;
    this.onSelectLocation = options.onSelectLocation || (() => {});

    this.leafletMap = null;
    this.tileLayer = null;
    this.currentTileStyle = "voyager"; // "voyager" | "positron" | "standard_osm"

    this.markersLayer = null;
    this.routeLayers = [];

    this.state = {
      vehicles: options.vehicles || [
        { id: "v_1", plate: "KA-01-MJ-4412", status: "RUNNING", lat: 12.9716, lng: 77.6412, driver: "Ramesh K.", speed: "38 km/h" },
        { id: "v_2", plate: "KA-04-AK-9821", status: "IDLE", lat: 12.9345, lng: 77.6265, driver: "Suresh G.", speed: "0 km/h" },
        { id: "v_3", plate: "KA-05-MH-8841", status: "SOS_DELAY", lat: 12.8452, lng: 77.6602, driver: "Shivanna P.", speed: "12 km/h" },
        { id: "v_4", plate: "KA-03-AA-1102", status: "ESCORTED", lat: 12.9863, lng: 77.7381, driver: "Manjunath (Guard Attached)", speed: "42 km/h" },
      ],
      auditDiff: options.auditDiff || null,
      autocompleteResults: [],
      selectedPin: null,
      searchQuery: "",
    };
  }

  mount() {
    if (!this.container) return;
    this.injectStyles();
    this.render();
    this.initLeaflet();
    this.attachEventListeners();
  }

  unmount() {
    if (this.leafletMap && typeof this.leafletMap.remove === "function") {
      this.leafletMap.remove();
      this.leafletMap = null;
    }
    if (this.container) {
      this.container.innerHTML = "";
    }
  }

  injectStyles() {
    if (typeof document === "undefined") return;
    if (document.getElementById("axiom-osm-map-styles")) return;

    const styleEl = document.createElement("style");
    styleEl.id = "axiom-osm-map-styles";
    styleEl.textContent = `
      .axiom-map-wrapper {
        position: relative;
        width: 100%;
        height: 100%;
        min-height: 480px;
        background: #0f172a;
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid #1e293b;
        display: flex;
        flex-direction: column;
      }
      .axiom-map-toolbar {
        position: absolute;
        top: 12px;
        left: 12px;
        right: 12px;
        z-index: 500;
        display: flex;
        align-items: center;
        justify-content: space-between;
        pointer-events: none;
      }
      .axiom-search-box {
        pointer-events: auto;
        position: relative;
        width: 320px;
        background: rgba(15, 23, 42, 0.95);
        backdrop-filter: blur(8px);
        border: 1px solid #334155;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      }
      .axiom-search-input {
        width: 100%;
        background: transparent;
        border: none;
        padding: 8px 12px;
        color: #f8fafc;
        font-size: 13px;
        outline: none;
      }
      .axiom-autocomplete-menu {
        position: absolute;
        top: 100%;
        left: 0;
        right: 0;
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 0 0 8px 8px;
        max-height: 220px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
      }
      .axiom-ac-item {
        padding: 8px 12px;
        font-size: 12px;
        color: #cbd5e1;
        cursor: pointer;
        border-bottom: 1px solid #334155;
      }
      .axiom-ac-item:hover {
        background: #2563eb;
        color: #fff;
      }
      .axiom-tile-toggle {
        pointer-events: auto;
        background: rgba(15, 23, 42, 0.95);
        backdrop-filter: blur(8px);
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 4px;
        display: flex;
        gap: 4px;
      }
      .axiom-tile-btn {
        background: transparent;
        border: none;
        color: #94a3b8;
        font-size: 11px;
        font-weight: 700;
        padding: 4px 8px;
        border-radius: 6px;
        cursor: pointer;
      }
      .axiom-tile-btn.active {
        background: #2563eb;
        color: #fff;
      }
      .map-canvas-container {
        flex: 1;
        width: 100%;
        height: 100%;
      }
      .map-legend-bar {
        position: absolute;
        bottom: 12px;
        left: 12px;
        z-index: 500;
        background: rgba(15, 23, 42, 0.9);
        backdrop-filter: blur(8px);
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 6px 12px;
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 11px;
        color: #94a3b8;
      }
      .legend-pill {
        display: flex;
        align-items: center;
        gap: 4px;
      }
      .dot-running { width: 8px; height: 8px; border-radius: 50%; background: #10b981; }
      .dot-idle { width: 8px; height: 8px; border-radius: 50%; background: #f59e0b; }
      .dot-sos { width: 8px; height: 8px; border-radius: 50%; background: #ef4444; }
      .dot-escort { width: 8px; height: 8px; border-radius: 50%; background: #a855f7; }
    `;
    document.head.appendChild(styleEl);
  }

  render() {
    if (!this.container) return;

    this.container.innerHTML = `
      <div class="axiom-map-wrapper">
        <!-- Floating Toolbar -->
        <div class="axiom-map-toolbar">
          <div class="axiom-search-box">
            <input type="text" class="axiom-search-input" id="inp-osm-search" placeholder="🔍 Search Bangalore landmark / address (OSM)..." value="${this.state.searchQuery}" />
            <div class="axiom-autocomplete-menu" id="osm-ac-dropdown" style="display: ${this.state.autocompleteResults.length ? "flex" : "none"};">
              ${this.state.autocompleteResults
                .map(
                  (r) => `
                <div class="axiom-ac-item" data-action="pick-location" data-lat="${r.lat}" data-lng="${r.lng}" data-display="${r.display_name}">
                  <strong>${r.display_name.split(",")[0]}</strong>
                  <div style="font-size: 10px; color: #94a3b8;">${r.display_name}</div>
                </div>
              `
                )
                .join("")}
            </div>
          </div>

          <div class="axiom-tile-toggle">
            <button class="axiom-tile-btn ${this.currentTileStyle === "voyager" ? "active" : ""}" data-tile="voyager">Voyager</button>
            <button class="axiom-tile-btn ${this.currentTileStyle === "positron" ? "active" : ""}" data-tile="positron">Positron</button>
            <button class="axiom-tile-btn ${this.currentTileStyle === "standard_osm" ? "active" : ""}" data-tile="standard_osm">OSM Standard</button>
          </div>
        </div>

        <!-- Leaflet Map Container -->
        <div class="map-canvas-container" id="osm-leaflet-viewport"></div>

        <!-- Status Legend Bar -->
        <div class="map-legend-bar">
          <div class="legend-pill"><span class="dot-running"></span> Running (${this.state.vehicles.filter((v) => v.status === "RUNNING").length})</div>
          <div class="legend-pill"><span class="dot-idle"></span> Idle (${this.state.vehicles.filter((v) => v.status === "IDLE").length})</div>
          <div class="legend-pill"><span class="dot-sos"></span> SOS / Delay (${this.state.vehicles.filter((v) => v.status === "SOS_DELAY").length})</div>
          <div class="legend-pill"><span class="dot-escort"></span> POSH Night Escort (${this.state.vehicles.filter((v) => v.status === "ESCORTED").length})</div>
        </div>
      </div>
    `;
  }

  initLeaflet() {
    if (typeof window === "undefined" || !window.L) {
      // In non-browser / test environment or prior to CDN load, mock gracefully
      return;
    }

    const mapEl = this.container.querySelector("#osm-leaflet-viewport");
    if (!mapEl) return;

    this.leafletMap = window.L.map(mapEl).setView(this.center, this.zoom);

    this.applyTileLayer(this.currentTileStyle);
    this.renderMapLayers();
  }

  applyTileLayer(style) {
    if (!this.leafletMap || !window.L) return;
    if (this.tileLayer) {
      this.leafletMap.removeLayer(this.tileLayer);
    }

    let tileUrl = "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png";
    let attribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';

    if (style === "positron") {
      tileUrl = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
    } else if (style === "standard_osm") {
      tileUrl = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
      attribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
    }

    this.tileLayer = window.L.tileLayer(tileUrl, { attribution, maxZoom: 19 }).addTo(this.leafletMap);
    this.currentTileStyle = style;
  }

  renderMapLayers() {
    if (!this.leafletMap || !window.L) return;

    // Clear old layers
    if (this.markersLayer) {
      this.leafletMap.removeLayer(this.markersLayer);
    }
    this.markersLayer = window.L.layerGroup().addTo(this.leafletMap);

    // 1. Plot Vehicles if Command Center Mode
    if (this.mode === "COMMAND_CENTER") {
      this.state.vehicles.forEach((v) => {
        let color = "#10b981";
        if (v.status === "IDLE") color = "#f59e0b";
        if (v.status === "SOS_DELAY") color = "#ef4444";
        if (v.status === "ESCORTED") color = "#a855f7";

        const iconHtml = `<div style="background: ${color}; width: 14px; height: 14px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 0 8px ${color};"></div>`;
        const icon = window.L.divIcon({ html: iconHtml, className: "custom-veh-marker", iconSize: [14, 14] });

        window.L.marker([v.lat, v.lng], { icon })
          .bindPopup(`<strong>${v.plate}</strong><br/>Driver: ${v.driver}<br/>Speed: ${v.speed}<br/>Status: ${v.status}`)
          .addTo(this.markersLayer);
      });
    }

    // 2. Plot Duty Audit Diff Mode (Planned vs OSRM Snapped Actual Path)
    if (this.mode === "DUTY_AUDIT_DIFF" && this.state.auditDiff) {
      const { plannedPolyline, actualPolyline, stoppages, deviations } = this.state.auditDiff;

      // Dashed Slate Line (Planned Theoretical Route)
      if (plannedPolyline && plannedPolyline.length) {
        window.L.polyline(plannedPolyline, {
          color: "#94a3b8",
          weight: 4,
          dashArray: "6, 8",
          opacity: 0.8,
        }).addTo(this.markersLayer);
      }

      // Solid Blue Line (OSRM Snapped Actual Road Path)
      if (actualPolyline && actualPolyline.length) {
        window.L.polyline(actualPolyline, {
          color: "#2563eb",
          weight: 5,
          opacity: 0.9,
        }).addTo(this.markersLayer);
      }

      // Red Stoppage / Deviation Alert Markers
      (stoppages || []).forEach((s) => {
        const stopIcon = window.L.divIcon({
          html: `<div style="background: #ef4444; color: #fff; font-size: 10px; font-weight: 800; border-radius: 50%; width: 18px; height: 18px; display: flex; align-items: center; justify-content: center; border: 2px solid #fff;">⏱️</div>`,
          iconSize: [18, 18],
        });
        window.L.marker([s.lat, s.lng], { icon: stopIcon })
          .bindPopup(`<strong>Unplanned Stoppage (>5 mins)</strong><br/>Duration: ${s.duration_seconds}s`)
          .addTo(this.markersLayer);
      });
    }
  }

  async searchAddress(query) {
    this.state.searchQuery = query;
    if (!query || query.length < 2) {
      this.state.autocompleteResults = [];
      this.render();
      return;
    }

    try {
      const res = await fetch(`${this.apiBase}/osm/autocomplete?q=${encodeURIComponent(query)}&city=Bengaluru`);
      if (res.ok) {
        const data = await res.json();
        this.state.autocompleteResults = data.items || [];
        this.render();
      }
    } catch (err) {
      // Graceful fallback
    }
  }

  selectLocation(lat, lng, displayName) {
    this.state.selectedPin = { lat, lng, displayName };
    this.state.searchQuery = displayName.split(",")[0];
    this.state.autocompleteResults = [];
    this.render();

    if (this.leafletMap) {
      this.leafletMap.flyTo([lat, lng], 14);
      if (this.markersLayer) {
        window.L.marker([lat, lng])
          .bindPopup(`<strong>${displayName}</strong>`)
          .addTo(this.markersLayer)
          .openPopup();
      }
    }
    this.onSelectLocation(this.state.selectedPin);
  }

  attachEventListeners() {
    if (!this.container) return;

    let debounceTimer = null;
    this.container.addEventListener("input", (evt) => {
      if (evt.target.id === "inp-osm-search") {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          this.searchAddress(evt.target.value);
        }, 250);
      }
    });

    this.container.addEventListener("click", (evt) => {
      // Tile switch
      const tileBtn = evt.target.closest("[data-tile]");
      if (tileBtn) {
        const style = tileBtn.dataset.tile;
        this.applyTileLayer(style);
        this.render();
        return;
      }

      // Autocomplete item pick
      const pickItem = evt.target.closest("[data-action='pick-location']");
      if (pickItem) {
        const lat = parseFloat(pickItem.dataset.lat);
        const lng = parseFloat(pickItem.dataset.lng);
        const display = pickItem.dataset.display;
        this.selectLocation(lat, lng, display);
      }
    });
  }
}
