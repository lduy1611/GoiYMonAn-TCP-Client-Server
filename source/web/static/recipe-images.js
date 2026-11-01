/* Local presentation metadata only. This module never changes recipe/API data. */
(() => {
  'use strict';
  const placeholder = '/static/images/recipes/placeholder.svg';
  const catalogUrl = '/static/recipe-images.json?v=ui-1.2.3';
  const mounted = new WeakSet();
  let catalogPromise;

  function localImagePath(value) {
    return typeof value === 'string' && /^\/static\/images\/recipes\/[a-z0-9][a-z0-9._-]*\.(?:webp|jpe?g|png|svg)$/.test(value);
  }

  function sourceLink(value) {
    try {
      const url = new URL(value);
      return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
    } catch { return null; }
  }

  function load() {
    if (!catalogPromise) {
      catalogPromise = fetch(catalogUrl).then(response => {
        if (!response.ok) throw Error('Image catalog unavailable');
        return response.json();
      }).then(catalog => catalog && typeof catalog.recipes === 'object' && catalog.recipes !== null ? catalog : {recipes: {}})
        .catch(() => ({recipes: {}}));
    }
    return catalogPromise;
  }

  function mount(root = document) {
    for (const figure of root.querySelectorAll('[data-recipe-media]')) {
      if (mounted.has(figure)) continue;
      mounted.add(figure);
      const id = Number(figure.dataset.recipeId);
      const title = figure.dataset.recipeTitle || 'món ăn';
      const image = document.createElement('img');
      const caption = document.createElement('figcaption');
      image.className = 'recipe-photo';
      image.width = 960;
      image.height = 600;
      image.loading = figure.classList.contains('detail-media') ? 'eager' : 'lazy';
      image.decoding = 'async';
      image.dataset.recipeId = String(id);
      caption.className = 'photo-credit';
      const showPlaceholder = () => {
        image.dataset.placeholder = 'true';
        delete image.dataset.sourceType;
        image.removeAttribute('srcset');
        image.removeAttribute('sizes');
        image.alt = 'Chưa có ảnh cho món ' + title;
        caption.textContent = 'Chưa có ảnh phù hợp';
        if (image.getAttribute('src') !== placeholder) image.src = placeholder;
      };
      image.addEventListener('error', () => {
        if (image.dataset.placeholder !== 'true') showPlaceholder();
      });
      showPlaceholder();
      figure.replaceChildren(image, caption);
      load().then(catalog => {
        const entry = catalog.recipes[String(id)];
        if (!entry || entry.recipe_id !== id || entry.is_placeholder !== false || entry.image_path === placeholder || !localImagePath(entry.image_path)) return;
        const url = sourceLink(entry.source_url);
        const projectAI = entry.source_type === 'project_ai' && entry.generated_ai === true;
        if ((!projectAI && !url) || typeof entry.source_name !== 'string' || !entry.source_name.trim()) return;
        image.dataset.placeholder = 'false';
        image.dataset.sourceType = projectAI ? 'project_ai' : 'external';
        image.alt = typeof entry.alt === 'string' && entry.alt.trim() ? entry.alt : 'Ảnh minh họa món ' + title;
        const variants = entry.variants && typeof entry.variants === 'object'
          ? Object.entries(entry.variants).filter(([width, path]) => /^\d+$/.test(width) && Number(width) > 0 && Number(width) <= 2400 && localImagePath(path)) : [];
        if (variants.length) {
          image.srcset = variants.map(([width, path]) => path + ' ' + width + 'w').join(', ');
          image.sizes = figure.classList.contains('detail-media')
            ? '(max-width: 760px) calc(100vw - 36px), 1032px'
            : '(max-width: 540px) calc(100vw - 36px), (max-width: 1020px) 50vw, 400px';
        }
        if (projectAI) {
          caption.textContent = entry.source_name;
        } else {
          const link = document.createElement('a');
          link.href = url;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.textContent = entry.source_name;
          caption.replaceChildren(document.createTextNode(entry.generated_ai === true ? 'Minh họa AI · ' : 'Ảnh minh họa · '), link);
        }
        image.src = entry.image_path;
      });
    }
  }

  window.RecipeImages = Object.freeze({mount, ready: load});
})();
