export class VisualAdapter {
  async load(character) {
    throw new Error('not implemented');
  }

  setEmotion(label) {}

  speak(text, audio) {}

  destroy() {}
}

export class AdapterRegistry {
  constructor() {
    this._adapters = new Map();
  }

  register(name, AdapterClass) {
    if (!name || typeof AdapterClass !== 'function') return;
    this._adapters.set(name, AdapterClass);
  }

  create(name, opts) {
    const AdapterClass = this._adapters.get(name);
    if (!AdapterClass) {
      throw new Error(`Visual adapter '${name}' not registered`);
    }
    return new AdapterClass(opts);
  }

  get(name) {
    return this._adapters.get(name);
  }

  has(name) {
    return this._adapters.has(name);
  }
}

if (typeof window !== 'undefined') {
  window.VisualAdapter = VisualAdapter;
  window.AdapterRegistry = AdapterRegistry;
}
