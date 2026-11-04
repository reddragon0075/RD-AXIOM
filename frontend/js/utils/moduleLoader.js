/**
 * Axiom Mobility (Fleetline) - Dynamic ES6 Module Lazy-Loader & View Router.
 *
 * Eliminates upfront bundle bloat by dynamically loading heavy secondary components
 * (Leaflet maps, Bulk Importers, TimesFM charts, CRM) only upon user tab activation.
 * Includes AbortController tracking to cancel pending requests when switching views.
 */

export class ModuleLoader {
  constructor(options = {}) {
    this.viewContainer = options.viewContainer || null;
    this.loadedModules = new Map();
    this.activeInstances = new Map();
    this.activeAbortController = null;

    // Registry of on-demand component paths
    this.moduleRegistry = {
      OSM_MAP: "../components/AxiomOsmMap.js",
      BULK_IMPORTER: "../components/CompletedTripsImporterUI.js",
      TIMESFM_FORECAST: "../components/TimesFmForecastWidget.js",
      NATIVE_CRM: "../components/NativeCrmWorkspace.js",
      PARTNER_EXCHANGE: "../components/PartnerExchangeView.js",
      CORPORATE_ANNEXURE: "../components/CorporateAnnexurePortal.js",
      TRIP_CORRECTION_DRAWER: "../components/TripCorrectionDrawer.js",
      CORPORATE_PORTAL: "../components/CorporatePortalConsole.js",
    };
  }

  getAbortSignal() {
    if (this.activeAbortController) {
      this.activeAbortController.abort();
    }
    this.activeAbortController = new AbortController();
    return this.activeAbortController.signal;
  }

  async loadComponentModule(moduleKey) {
    const modulePath = this.moduleRegistry[moduleKey];
    if (!modulePath) {
      throw new Error(`Unknown component module key: ${moduleKey}`);
    }

    if (this.loadedModules.has(moduleKey)) {
      return this.loadedModules.get(moduleKey);
    }

    try {
      const imported = await import(modulePath);
      this.loadedModules.set(moduleKey, imported);
      return imported;
    } catch (err) {
      console.error(`[ModuleLoader] Failed to dynamically import ${moduleKey} from ${modulePath}:`, err);
      throw err;
    }
  }

  cleanupActiveView(viewKey) {
    if (this.activeInstances.has(viewKey)) {
      const instance = this.activeInstances.get(viewKey);
      if (instance && typeof instance.unmount === "function") {
        instance.unmount();
      } else if (instance && typeof instance.destroy === "function") {
        instance.destroy();
      }
      this.activeInstances.delete(viewKey);
    }
    if (this.activeAbortController) {
      this.activeAbortController.abort();
      this.activeAbortController = null;
    }
  }

  async mountLazyComponent(moduleKey, exportName, mountTarget, componentProps = {}) {
    this.cleanupActiveView(moduleKey);

    // Show lightweight loading indicator
    if (mountTarget) {
      mountTarget.innerHTML = `
        <div style="padding: 40px; text-align: center; color: #94a3b8; font-size: 13px;">
          <div style="font-size: 18px; margin-bottom: 8px;">⚡</div>
          Loading ${moduleKey} module dynamically...
        </div>
      `;
    }

    const mod = await this.loadComponentModule(moduleKey);
    const ComponentClass = mod[exportName] || mod.default;

    if (!ComponentClass) {
      throw new Error(`Export ${exportName} not found in module ${moduleKey}`);
    }

    const instance = new ComponentClass({
      ...componentProps,
      container: mountTarget,
    });

    if (typeof instance.mount === "function") {
      instance.mount(mountTarget);
    }

    this.activeInstances.set(moduleKey, instance);
    return instance;
  }
}

export const globalModuleLoader = new ModuleLoader();
