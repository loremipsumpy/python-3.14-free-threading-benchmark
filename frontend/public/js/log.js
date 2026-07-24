// log.js - MONITOR panel: subscribes to api.js notifications (`api.events`) and renders
// each request as an HTTP "wire" entry. It knows nothing about the network: it only
// consumes the events api.js emits. Errors are NOT hidden: every failed request
// (422, 404, network down with status 0) shows up as a red/amber entry.

import { formatMs, statusFamily, prettyBody } from './format.js';

/**
 * @param {{ events: EventTarget, listEl: HTMLElement, emptyEl: HTMLElement,
 *           clearBtn: HTMLElement, template: HTMLTemplateElement }} deps
 */
export function initLog({ events, listEl, emptyEl, clearBtn, template }) {
  function syncEmpty() {
    emptyEl.hidden = listEl.childElementCount > 0;
  }

  function addEntry(entry) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.classList.add(`wire--${statusFamily(entry.status)}`);
    node.querySelector('.wire__method').textContent = entry.method;
    node.querySelector('.wire__path').textContent = entry.path;
    node.querySelector('.wire__status').textContent = entry.status === 0 ? 'ERR' : String(entry.status);
    node.querySelector('.wire__ms').textContent = formatMs(entry.ms);

    const pres = node.querySelectorAll('.wire__pre');
    pres[0].textContent = prettyBody(entry.request);
    // On success the response is shown; on network down (response null) the error is shown.
    pres[1].textContent = prettyBody(entry.response ?? entry.error ?? null);

    listEl.prepend(node);
    syncEmpty();
  }

  events.addEventListener('http', (e) => addEntry(e.detail));
  clearBtn?.addEventListener('click', () => {
    listEl.replaceChildren();
    syncEmpty();
  });

  syncEmpty();
}
