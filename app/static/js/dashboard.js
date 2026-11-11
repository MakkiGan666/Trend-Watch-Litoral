(function () {
  'use strict';
  const page = document.querySelector('[data-dashboard]');
  if (!page) return;

  const form = page.querySelector('[data-dashboard-filters]');
  const search = page.querySelector('#dashboard-search');
  const editToggle = page.querySelector('[data-dashboard-edit-toggle]');
  const editHelp = page.querySelector('[data-dashboard-edit-help]');
  let editing = false;
  let searchTimer;

  function setEditing(value) {
    editing = value;
    page.querySelectorAll('[data-dashboard-actions]').forEach(cell => { cell.hidden = !editing; });
    page.querySelectorAll('[data-dashboard-empty-cell]').forEach(cell => { cell.colSpan = editing ? 7 : 6; });
    editToggle.setAttribute('aria-pressed', String(editing));
    editToggle.textContent = editing ? 'Finalizar edición' : 'Editar publicación';
    editHelp.hidden = !editing;
  }

  if (editToggle) {
    setEditing(false);
    editToggle.hidden = false;
    editToggle.addEventListener('click', () => setEditing(!editing));
  }

  function submitFilters() {
    clearTimeout(searchTimer);
    form.requestSubmit();
  }

  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(submitFilters, 450);
  });
  form.addEventListener('change', event => {
    if (event.target.matches('#dashboard-source, #dashboard-location, #dashboard-category, #dashboard-date')) submitFilters();
  });
  form.addEventListener('submit', () => clearTimeout(searchTimer));

  page.querySelectorAll('form[data-confirm]').forEach(deleteForm => {
    deleteForm.addEventListener('submit', event => {
      if (!editing) { event.preventDefault(); return; }
      if (!window.confirm(deleteForm.dataset.confirm)) event.preventDefault();
    });
  });
})();
