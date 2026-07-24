// ui.js - CONTROL panel: lists, creates, filters, edits (inline PATCH) and deletes tasks,
// consuming ONLY api.js (never fetch directly). No innerHTML with user data: rows come
// from the <template> and are filled with textContent.
//
// Errors are VISIBLE without breaking the UI:
//  - A load failure (backend down) ⇒ a "could not connect" state DISTINCT from a genuine
//    empty (don't lie with "No tasks yet"); the real error also lives in the monitor
//    (red status 0 entry).
//  - A 422 on create ⇒ per-field detail below the form.
//  - A PATCH/DELETE failure ⇒ the control is reverted; the error stays visible in the monitor.

/**
 * @param {{ api, form, filterButtons, listEl, emptyEl, errorEl, template, composerError }} deps
 * @returns {{ refresh: () => Promise<void> }}
 */
export function initTasks({ api, form, filterButtons, listEl, emptyEl, errorEl, template, composerError }) {
  let filter = '';

  const titleInput = form.elements.title;
  const descInput = form.elements.description;
  const prioInput = form.elements.priority;

  const isNetworkError = (err) => err?.networkError === true || err?.status === 0;

  function showList(tasks) {
    listEl.replaceChildren(...tasks.map(rowFor));
    emptyEl.hidden = tasks.length > 0;
    errorEl.hidden = true;
  }

  function showLoadError(err) {
    listEl.replaceChildren();
    emptyEl.hidden = true; // NOT a genuine empty: the load failed
    errorEl.hidden = false;
    errorEl.textContent = isNetworkError(err)
      ? 'Could not reach the backend. Make sure it is running on :8000.'
      : `Could not load tasks: ${err?.message ?? 'error'}`;
  }

  async function refresh() {
    try {
      showList(await api.listTasks(filter));
    } catch (err) {
      showLoadError(err);
    }
  }

  function rowFor(task) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.dataset.id = task.id;
    node.dataset.priority = task.priority;
    node.querySelector('.task__title').textContent = task.title;
    const desc = node.querySelector('.task__desc');
    desc.textContent = task.description;
    desc.hidden = !task.description;

    const statusSel = node.querySelector('[data-field="status"]');
    const prioSel = node.querySelector('[data-field="priority"]');
    statusSel.value = task.status;
    prioSel.value = task.priority;
    statusSel.dataset.prev = task.status;
    prioSel.dataset.prev = task.priority;

    statusSel.addEventListener('change', () => patchField(task.id, 'status', statusSel, node));
    prioSel.addEventListener('change', () => patchField(task.id, 'priority', prioSel, node));
    node.querySelector('.icon-btn--danger')
      .addEventListener('click', () => removeTask(task.id, node));
    return node;
  }

  async function patchField(id, field, select, node) {
    const previous = select.dataset.prev;
    select.disabled = true;
    try {
      const updated = await api.patchTask(id, { [field]: select.value });
      select.dataset.prev = select.value;
      if (field === 'priority') node.dataset.priority = updated.priority;
    } catch {
      select.value = previous; // revert; the failure is already visible in the monitor
    } finally {
      select.disabled = false;
    }
  }

  async function removeTask(id, node) {
    try {
      await api.deleteTask(id);
      node.remove();
      if (listEl.childElementCount === 0) emptyEl.hidden = false;
    } catch {
      /* the error stays visible in the monitor; the UI does not break */
    }
  }

  function clearComposerError() {
    composerError.hidden = true;
    composerError.replaceChildren();
  }

  function showComposerError(details) {
    composerError.replaceChildren();
    const entries = details && typeof details === 'object' ? Object.entries(details) : [];
    const lines = entries.length ? entries.map(([f, p]) => `${f}: ${p}`) : ['Could not create the task.'];
    for (const text of lines) {
      const li = document.createElement('li');
      li.textContent = text;
      composerError.appendChild(li);
    }
    composerError.hidden = false;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearComposerError();
    try {
      // an empty description is omitted by api.createTask (contract's null policy).
      await api.createTask({
        title: titleInput.value,
        description: descInput.value,
        priority: prioInput.value,
      });
      form.reset();
      prioInput.value = 'medium';
      titleInput.focus();
      await refresh();
    } catch (err) {
      if (err?.status === 422) showComposerError(err.details);
      else if (isNetworkError(err)) showComposerError({ connection: 'could not reach the backend' });
      else showComposerError(null);
    }
  });

  for (const btn of filterButtons) {
    btn.addEventListener('click', () => {
      for (const b of filterButtons) {
        const active = b === btn;
        b.classList.toggle('is-active', active);
        b.setAttribute('aria-pressed', String(active));
      }
      filter = btn.dataset.status;
      refresh();
    });
  }

  return { refresh };
}
