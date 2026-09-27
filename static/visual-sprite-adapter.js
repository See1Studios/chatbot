import { VisualAdapter } from './visual-adapter.js';

export class SpriteAdapter extends VisualAdapter {
  constructor(opts = {}) {
    super();
    this.opts = opts;
    this.character = null;
    this.spriteMap = {};
    this.currentEmotion = '';
    this.imgEl = opts.imgEl || null;
    this._transitionSeq = 0;
  }

  getSpriteElement() {
    if (this.imgEl && this.imgEl.isConnected) {
      return this.imgEl;
    }
    let el = typeof document !== 'undefined' ? document.querySelector('.character-sprite') : null;
    if (!el && typeof ensureCharacterSprite === 'function') {
      el = ensureCharacterSprite();
    } else if (!el && typeof document !== 'undefined') {
      const container = document.querySelector('.stage') ||
                        document.querySelector('.stage-shell') ||
                        (document.getElementById('log') && document.getElementById('log').parentElement) ||
                        document.body;
      el = document.createElement('img');
      el.className = 'character-sprite';
      el.alt = 'Character Sprite';
      el.style.position = 'absolute';
      el.style.bottom = '0';
      el.style.right = '1.5rem';
      el.style.maxHeight = '70%';
      el.style.maxWidth = '45%';
      el.style.objectFit = 'contain';
      el.style.pointerEvents = 'none';
      el.style.zIndex = '0';
      el.style.opacity = '0';
      el.style.transition = 'opacity 0.2s ease';
      if (container) {
        container.appendChild(el);
      }
    }
    this.imgEl = el;
    return el;
  }

  async load(character) {
    this.character = character || null;
    this.spriteMap = {};
    if (!character) return;

    let map = null;
    if (character.extensions && character.extensions.sprite_map) {
      map = character.extensions.sprite_map;
    } else if (character.card && character.card.data && character.card.data.extensions && character.card.data.extensions.sprite_map) {
      map = character.card.data.extensions.sprite_map;
    } else if (character.card && character.card.extensions && character.card.extensions.sprite_map) {
      map = character.card.extensions.sprite_map;
    } else if (character.data && character.data.extensions && character.data.extensions.sprite_map) {
      map = character.data.extensions.sprite_map;
    } else if (character.sprite_map) {
      map = character.sprite_map;
    }

    if (map && typeof map === 'object' && Object.keys(map).length > 0) {
      this.spriteMap = { ...map };
      return;
    }

    const charId = character.id || (typeof character === 'string' ? character : '');
    if (charId) {
      try {
        const basePath = typeof BASE_PATH !== 'undefined' ? BASE_PATH : '';
        const url = `${basePath}/api/characters/${encodeURIComponent(charId)}/sprites`;
        let res = null;
        if (typeof api === 'function') {
          res = await api(url);
        } else if (typeof fetch !== 'undefined') {
          const r = await fetch(url);
          if (r.ok) res = await r.json();
        }
        if (res && typeof res === 'object') {
          this.spriteMap = res.sprites || res.sprite_map || res;
        }
      } catch (_) {
        this.spriteMap = {};
      }
    }
  }

  resolveEmotionSrc(label) {
    const charId = (this.character && this.character.id) || (typeof this.character === 'string' ? this.character : '');
    const basePath = typeof BASE_PATH !== 'undefined' ? BASE_PATH : '';

    let candidate = '';
    if (this.spriteMap && typeof this.spriteMap === 'object') {
      if (this.spriteMap[label]) {
        candidate = this.spriteMap[label];
      } else if (this.spriteMap['default']) {
        candidate = this.spriteMap['default'];
      } else if (this.spriteMap['neutral']) {
        candidate = this.spriteMap['neutral'];
      }
    }

    if (!candidate) {
      const emotionFile = (label && label !== 'default') ? `${label}.webp` : 'default.webp';
      if (charId) {
        candidate = `${basePath}/api/characters/${encodeURIComponent(charId)}/sprites/${emotionFile}`;
      } else {
        candidate = emotionFile;
      }
    }

    if (!candidate) return '';
    if (candidate.startsWith('data:') || candidate.startsWith('http://') || candidate.startsWith('https://')) {
      return candidate;
    }
    if (candidate.startsWith('/')) {
      return basePath ? (basePath + candidate) : candidate;
    }
    if (charId && !candidate.startsWith(basePath + '/api/characters/')) {
      return `${basePath}/api/characters/${encodeURIComponent(charId)}/sprites/${encodeURIComponent(candidate)}`;
    }
    return candidate;
  }

  setEmotion(label) {
    const emotion = label || 'default';
    this.currentEmotion = emotion;
    const img = this.getSpriteElement();
    if (!img) return;

    const targetSrc = this.resolveEmotionSrc(emotion);
    if (!targetSrc) return;

    if (img.src === targetSrc || img.getAttribute('src') === targetSrc) {
      img.style.opacity = '1';
      return;
    }

    const transitionId = ++this._transitionSeq;
    img.style.transition = 'opacity 0.2s ease';

    const updateSrc = () => {
      if (this._transitionSeq !== transitionId) return;
      img.onload = () => {
        if (this._transitionSeq === transitionId) {
          img.style.opacity = '1';
        }
      };
      img.onerror = () => {
        if (this._transitionSeq === transitionId) {
          if (emotion !== 'default') {
            const fallbackSrc = this.resolveEmotionSrc('default');
            if (fallbackSrc && fallbackSrc !== targetSrc) {
              img.src = fallbackSrc;
              img.onload = () => {
                if (this._transitionSeq === transitionId) {
                  img.style.opacity = '1';
                }
              };
              img.onerror = () => {
                img.style.opacity = '0';
              };
              return;
            }
          }
          img.style.opacity = '0';
        }
      };
      img.src = targetSrc;
    };

    if (img.style.opacity && img.style.opacity !== '0' && img.src) {
      img.style.opacity = '0';
      setTimeout(updateSrc, 200);
    } else {
      updateSrc();
    }
  }

  speak(text, audio) {}

  destroy() {
    this._transitionSeq++;
    if (this.imgEl) {
      this.imgEl.style.opacity = '0';
      this.imgEl.removeAttribute('src');
    }
    this.character = null;
    this.spriteMap = {};
    this.currentEmotion = '';
  }
}

if (typeof window !== 'undefined') {
  window.SpriteAdapter = SpriteAdapter;
}
