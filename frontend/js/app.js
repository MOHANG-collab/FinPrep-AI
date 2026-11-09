const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const api = async (path, options = {}) => {
  const normalizedPath = path.startsWith('/api') ? path : '/api' + path;
  const r = await fetch(normalizedPath, { credentials: 'same-origin', ...options });
  let data;
  try {
    data = await r.json();
  } catch {
    data = { detail: 'Unexpected server response' };
  }
  if (!r.ok) {
    throw Error(typeof data.detail === 'string' ? data.detail : 'Request failed');
  }
  return data;
};

const post = (path, obj) =>
  api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(obj)
  });

const show = (message, error = false) => {
  const e = $('#message');
  if (e) {
    e.textContent = message;
    e.className = 'notice' + (error ? ' error' : '');
    e.hidden = false;
  }
};

const fmt = (n) => Number(n || 0).toLocaleString();

const safe = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[c]));

function table(rows) {
  if (!rows?.length) return '<p class="muted">No data available.</p>';
  const cols = Object.keys(rows[0]);
  return `<div class="tablewrap"><table><thead><tr>${cols
    .map((c) => `<th>${safe(c)}</th>`)
    .join('')}</tr></thead><tbody>${rows
    .map(
      (row) =>
        `<tr>${cols
          .map((c) => `<td>${safe(row[c] !== null && row[c] !== undefined ? row[c] : '')}</td>`)
          .join('')}</tr>`
    )
    .join('')}</tbody></table></div>`;
}

const page = document.body.dataset.page;
const protectedPages = [
  'dashboard',
  'upload',
  'profiling',
  'preprocessing',
  'analytics',
  'reports',
  'history',
  'settings'
];
let me = null;
let charts = [];

function highlightActiveNav() {
  const currentPath = location.pathname.replace(/^\//, '');
  $$('.sidebar a').forEach((a) => {
    const href = a.getAttribute('href').replace(/^\//, '');
    if (
      href === currentPath ||
      href === `${page}.html` ||
      href === page
    ) {
      a.classList.add('active');
    }
  });
}

async function init() {
  highlightActiveNav();

  if (protectedPages.includes(page)) {
    try {
      me = await api('/auth/me');
      $$('#username').forEach((el) => {
        el.textContent = me.name;
      });
      if ($('#accountName')) $('#accountName').textContent = me.name;
      if ($('#accountEmail')) $('#accountEmail').textContent = me.email;
      if ($('#accountId')) $('#accountId').textContent = `#${me.id}`;
    } catch {
      location.href = '/login.html';
      return;
    }
  }

  try {
    if (page === 'dashboard') await dashboard();
    if (['profiling', 'preprocessing', 'analytics', 'reports'].includes(page)) {
      await datasetsSelect();
    }
    if (page === 'history') await history();
    if (page === 'reports') await loadReports();
  } catch (e) {
    show(e.message, true);
  }
}

async function dashboard() {
  const d = await api('/dashboard');
  $('#metrics').innerHTML = [
    ['Datasets', d.datasets],
    ['Processed Jobs', d.processed],
    ['Rows Uploaded', fmt(d.rows_uploaded)],
    ['Rows Processed', fmt(d.rows_processed)]
  ]
    .map(
      ([label, v]) =>
        `<div class="card"><div class="muted">${label}</div><div class="kpi">${v}</div><span class="pill">FinPrep AI</span></div>`
    )
    .join('');

  if (!d.recent || !d.recent.length) {
    $('#recent').innerHTML = '<p class="muted">No datasets uploaded yet.</p>';
  } else {
    $('#recent').innerHTML = `
      <div class="tablewrap">
        <table>
          <thead>
            <tr><th>ID</th><th>Filename</th><th>Rows</th><th>Actions</th></tr>
          </thead>
          <tbody>
            ${d.recent
              .map(
                (r) => `
              <tr>
                <td>#${r.id}</td>
                <td><strong>${safe(r.filename)}</strong></td>
                <td>${fmt(r.rows)}</td>
                <td>
                  <div style="display:flex;gap:6px">
                    <a class="btn ghost small" href="/profiling.html" onclick="sessionStorage.setItem('selected_dataset','${r.id}')">Profile</a>
                    <a class="btn ghost small" href="/analytics.html" onclick="sessionStorage.setItem('selected_dataset','${r.id}')">Analytics</a>
                    <a class="btn ghost small" href="/api/datasets/${r.id}/download" title="Download original file">Original</a>
                    <button class="btn ghost small" style="color:#DC2626" onclick="deleteDataset(${r.id})">Delete</button>
                  </div>
                </td>
              </tr>
            `
              )
              .join('')}
          </tbody>
        </table>
      </div>
    `;
  }
}

async function deleteDataset(id) {
  if (!confirm(`Are you sure you want to delete dataset #${id} and all its processed jobs?`)) return;
  try {
    show('Deleting dataset...');
    await api(`/datasets/${id}`, { method: 'DELETE' });
    if (sessionStorage.getItem('selected_dataset') === String(id)) {
      sessionStorage.removeItem('selected_dataset');
    }
    show('Dataset removed successfully');
    setTimeout(() => location.reload(), 600);
  } catch (e) {
    show(e.message, true);
  }
}

async function datasetsSelect() {
  const d = await api('/datasets');
  const select = $('#dataset');
  if (!select) return;

  if (d.length === 0) {
    select.innerHTML = '<option value="">No datasets uploaded yet</option>';
    return;
  }

  select.innerHTML =
    '<option value="">Select dataset</option>' +
    d.map((x) => `<option value="${x.id}">${safe(x.filename)} (#${x.id})</option>`).join('');

  const chosen = sessionStorage.getItem('selected_dataset');
  if (chosen && d.some((x) => String(x.id) === chosen)) {
    select.value = chosen;
    await onDatasetChange(chosen);
  }

  select.onchange = async () => {
    const val = select.value;
    if (val) {
      sessionStorage.setItem('selected_dataset', val);
      await onDatasetChange(val);
    }
  };
}

async function onDatasetChange(datasetId) {
  if (!datasetId) return;

  if (page === 'profiling') {
    await profile();
  } else if (page === 'preprocessing' || page === 'analytics') {
    await populateColumns(datasetId);
    if (page === 'analytics') {
      await analytics();
    }
  } else if (page === 'reports') {
    await loadReports();
  }
}

async function populateColumns(datasetId) {
  try {
    const p = await api(`/datasets/${datasetId}/profile`);
    const datalist = $('#colDatalist');
    if (datalist && p.column_names) {
      datalist.innerHTML = p.column_names.map((col) => `<option value="${safe(col)}"></option>`).join('');
    }

    if (page === 'analytics' && p.column_names) {
      const cols = p.column_names;
      const amtInput = $('#amount');
      const dateInput = $('#date');
      const catInput = $('#category');

      if (amtInput && !amtInput.value) {
        const found = cols.find((c) => /amount|amt|value|price|total|sales/i.test(c));
        if (found) amtInput.value = found;
      }
      if (dateInput && !dateInput.value) {
        const found = cols.find((c) => /date|time|dt|period/i.test(c));
        if (found) dateInput.value = found;
      }
      if (catInput && !catInput.value) {
        const found = cols.find((c) => /category|cat|type|dept|segment/i.test(c));
        if (found) catInput.value = found;
      }
    }
  } catch (err) {
    console.warn('Could not populate columns:', err);
  }
}

async function uploadFile(ev) {
  ev.preventDefault();
  const f = $('#file').files[0];
  if (!f) return show('Choose a file', true);

  const fd = new FormData();
  fd.append('file', f);

  try {
    show('Uploading and validating file...');
    const d = await api('/datasets/upload', { method: 'POST', body: fd });
    sessionStorage.setItem('selected_dataset', d.id);
    show('Dataset uploaded successfully!');
    $('#results').innerHTML = `
      <div class="grid4" style="margin-top:16px">
        ${[
          ['Rows', d.profile.rows],
          ['Columns', d.profile.columns],
          ['Missing Values', d.profile.missing],
          ['Duplicates', d.profile.duplicates]
        ]
          .map(([k, v]) => `<div class="card"><div class="muted">${k}</div><div class="kpi">${v}</div></div>`)
          .join('')}
      </div>
      <div class="panel">
        <h2>Uploaded Data Preview</h2>
        ${table(d.profile.preview)}
      </div>
      <div style="display:flex;gap:12px;margin-top:16px">
        <a class="btn" href="/profiling.html">View Data Profile →</a>
        <a class="btn ghost" href="/preprocessing.html">Clean Dataset →</a>
        <a class="btn ghost" href="/analytics.html">Financial Analytics →</a>
      </div>
    `;
  } catch (e) {
    show(e.message, true);
  }
}

async function profile() {
  try {
    const id = $('#dataset').value;
    if (!id) return show('Select a dataset', true);
    show('Analyzing data quality...');
    const p = await api(`/datasets/${id}/profile`);
    show('');
    $('#results').innerHTML = `
      <div class="grid4">
        ${[
          ['Rows', p.rows],
          ['Columns', p.columns],
          ['Missing Cells', p.missing],
          ['Duplicates', p.duplicates],
          ['Quality Score', p.score + '%']
        ]
          .map(([k, v]) => `<div class="card"><div class="muted">${k}</div><div class="kpi">${v}</div></div>`)
          .join('')}
      </div>
      <div class="panel">
        <h2>Missing Values by Column</h2>
        ${table(Object.entries(p.missing_by_column).map(([column, count]) => ({ Column: column, 'Missing Count': count, 'Data Type': p.types[column] || 'unknown' })))}
      </div>
      <div class="panel">
        <h2>Data Preview (First 12 Rows)</h2>
        ${table(p.preview)}
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:16px">
        <a class="btn" href="/preprocessing.html">Proceed to Preprocessing & Cleaning →</a>
        <a class="btn ghost" href="/analytics.html">Financial Analytics →</a>
        <a class="btn ghost" href="/api/datasets/${id}/download">Download Raw File</a>
        <button class="btn ghost" style="color:#DC2626" onclick="deleteDataset(${id})">Delete Dataset</button>
      </div>
    `;
  } catch (e) {
    show(e.message, true);
  }
}

async function clean(preview) {
  try {
    const id = $('#dataset').value;
    if (!id) return show('Select a dataset', true);

    const config = {
      drop_duplicates: $('#duplicates').checked,
      missing: {},
      date_columns: []
    };

    const column = $('#missingColumn').value.trim();
    const method = $('#missingMethod').value;
    if (column && method !== 'keep') config.missing[column] = method;

    const date = $('#dateColumn').value.trim();
    if (date) config.date_columns = [date];

    show(preview ? 'Generating cleaning preview...' : 'Applying transformations...');
    const d = await post(`/datasets/${id}/${preview ? 'preview-cleaning' : 'process'}`, config);

    if (preview) {
      $('#results').innerHTML = `
        <div class="grid2">
          <div class="card">
            <h3>Before</h3>
            <div class="kpi">${d.before.rows} rows</div>
            <p class="muted">Missing: ${d.before.missing} | Duplicates: ${d.before.duplicates}</p>
          </div>
          <div class="card">
            <h3>After</h3>
            <div class="kpi">${d.after.rows} rows</div>
            <p class="muted">Missing: ${d.after.missing} | Duplicates: ${d.after.duplicates}</p>
          </div>
        </div>
        <div class="panel">
          <h2>Transformations Planned</h2>
          <p>${safe(d.operations.join('; ') || 'No cleaning operations selected')}</p>
        </div>
        <div class="panel">
          <h2>Preview Cleaned Data</h2>
          ${table(d.after.preview)}
        </div>
      `;
      show('Preview generated; original file is untouched.');
    } else {
      $('#results').innerHTML = `
        <div class="card" style="margin-top:20px">
          <h3>✓ Processing Complete (Job #${d.job_id})</h3>
          <p class="muted">${d.before_rows} rows → ${d.after_rows} rows</p>
          <p><strong>Transformations:</strong> ${safe(d.operations.join('; ') || 'None')}</p>
          <div style="display:flex;gap:10px;margin-top:16px">
            <a class="btn" href="/api/jobs/${d.job_id}/download?format=csv">Download CSV</a>
            <a class="btn ghost" href="/api/jobs/${d.job_id}/download?format=xlsx">Download Excel (.xlsx)</a>
            <a class="btn ghost" href="/api/jobs/${d.job_id}/download?format=pdf">Download PDF Report</a>
          </div>
          <p style="margin-top:16px"><a class="btn ghost" href="/analytics.html">Explore Analytics →</a></p>
        </div>
      `;
      show('Cleaned dataset saved successfully!');
    }
  } catch (e) {
    show(e.message, true);
  }
}

async function analytics() {
  try {
    const id = $('#dataset').value;
    if (!id) return show('Select a dataset', true);

    const q = new URLSearchParams({
      amount_column: $('#amount').value.trim(),
      date_column: $('#date').value.trim(),
      category_column: $('#category').value.trim()
    });

    const d = await api(`/datasets/${id}/analytics?${q}`);
    const isNetPositive = (d.total || 0) >= 0;
    $('#results').innerHTML = `
      <div class="grid4">
        <div class="card">
          <div class="muted">Net Cash Flow (${safe(d.amount_column || 'N/A')})</div>
          <div class="kpi" style="color:${isNetPositive ? '#16A34A' : '#DC2626'}">${d.total === null ? 'N/A' : (isNetPositive ? '+' : '') + fmt(d.total)}</div>
          <span class="small muted">${isNetPositive ? '↑ Net Positive' : '↓ Net Outflow'}</span>
        </div>
        <div class="card">
          <div class="muted">Total Inflow / Income</div>
          <div class="kpi" style="color:#16A34A">${fmt(d.income || 0)}</div>
          <span class="small muted">Positive credits</span>
        </div>
        <div class="card">
          <div class="muted">Total Outflow / Expenses</div>
          <div class="kpi" style="color:#DC2626">${fmt(d.expense || 0)}</div>
          <span class="small muted">Negative debits</span>
        </div>
        <div class="card">
          <div class="muted">Average / Count</div>
          <div class="kpi">${fmt(d.average)}</div>
          <span class="small muted">${fmt(d.count)} total transactions</span>
        </div>
      </div>
      <div class="grid2">
        <div class="panel">
          <h2>Breakdown by Category</h2>
          <canvas id="categoryChart"></canvas>
        </div>
        <div class="panel">
          <h2>Monthly Trend</h2>
          <canvas id="monthChart"></canvas>
        </div>
      </div>
    `;

    charts.forEach((c) => c.destroy());
    charts = [];

    if (d.by_category?.length) {
      charts.push(
        new Chart($('#categoryChart'), {
          type: 'doughnut',
          data: {
            labels: d.by_category.map((x) => x.label),
            datasets: [
              {
                data: d.by_category.map((x) => x.value),
                backgroundColor: [
                  '#2563EB',
                  '#1D4ED8',
                  '#0F172A',
                  '#111827',
                  '#16A34A',
                  '#D97706',
                  '#DC2626',
                  '#2563EB'
                ]
              }
            ]
          },
          options: {
            plugins: {
              legend: {
                labels: { color: '#64748B' }
              }
            }
          }
        })
      );
    }

    if (d.by_month?.length) {
      charts.push(
        new Chart($('#monthChart'), {
          type: 'line',
          data: {
            labels: d.by_month.map((x) => x.label),
            datasets: [
              {
                label: `Total (${d.amount_column || 'Value'})`,
                data: d.by_month.map((x) => x.value),
                borderColor: '#2563EB',
                backgroundColor: 'rgba(37, 99, 235, 0.15)',
                fill: true,
                tension: 0.35
              }
            ]
          },
          options: {
            scales: {
              x: { ticks: { color: '#64748B' } },
              y: { ticks: { color: '#64748B' } }
            },
            plugins: {
              legend: {
                labels: { color: '#64748B' }
              }
            }
          }
        })
      );
    }

    if (!d.by_category?.length && !d.by_month?.length) {
      show('Provide date and category column names to render charts.');
    } else {
      show('');
    }
  } catch (e) {
    show(e.message, true);
  }
}

async function loadReports() {
  try {
    const jobs = await api('/history');
    const datasetSelect = $('#dataset');
    const filterId = datasetSelect ? datasetSelect.value : '';

    const filtered = filterId
      ? jobs.filter((j) => String(j.dataset_id) === String(filterId))
      : jobs;

    const res = $('#results');
    if (!res) return;

    if (!filtered.length) {
      res.innerHTML =
        '<p class="muted">No processed reports found for this selection. Preprocess a dataset first to generate exports.</p>';
      return;
    }

    res.innerHTML =
      '<div class="stack">' +
      filtered
        .map(
          (j) => `
        <div class="card" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
          <div>
            <h3>Job #${j.id} (Dataset #${j.dataset_id})</h3>
            <p class="muted">Rows: ${j.before_rows} → ${j.after_rows} | Date: ${j.created_at.slice(0, 10)}</p>
          </div>
          <div style="display:flex;gap:8px">
            <a class="btn" href="/api/jobs/${j.id}/download?format=csv">CSV</a>
            <a class="btn ghost" href="/api/jobs/${j.id}/download?format=xlsx">Excel</a>
            <a class="btn ghost" href="/api/jobs/${j.id}/download?format=pdf">PDF Report</a>
          </div>
        </div>
      `
        )
        .join('') +
      '</div>';
  } catch (e) {
    show(e.message, true);
  }
}

async function history() {
  try {
    const d = await api('/history');
    if (!d.length) {
      $('#results').innerHTML = '<p class="muted">No processing history recorded yet.</p>';
      return;
    }
    $('#results').innerHTML =
      table(
        d.map((x) => ({
          'Job ID': `#${x.id}`,
          'Dataset ID': `#${x.dataset_id}`,
          'Before Rows': x.before_rows,
          'After Rows': x.after_rows,
          Date: x.created_at.slice(0, 10)
        }))
      ) +
      '<h3 style="margin-top:24px">Download Job Artifacts</h3><div class="stack">' +
      d
        .map(
          (x) =>
            `<div class="card" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
              <div><strong>Job #${x.id}</strong> (Dataset #${x.dataset_id}) — ${x.after_rows} cleaned rows</div>
              <div style="display:flex;gap:8px">
                <a class="btn" href="/api/jobs/${x.id}/download?format=csv">CSV</a>
                <a class="btn ghost" href="/api/jobs/${x.id}/download?format=xlsx">Excel</a>
                <a class="btn ghost" href="/api/jobs/${x.id}/download?format=pdf">PDF</a>
              </div>
            </div>`
        )
        .join('') +
      '</div>';
  } catch (e) {
    show(e.message, true);
  }
}

async function login(ev) {
  ev.preventDefault();
  try {
    show('Signing in...');
    await post('/auth/login', {
      email: $('#email').value,
      password: $('#password').value
    });
    location.href = '/dashboard.html';
  } catch (e) {
    show(e.message, true);
  }
}

async function register(ev) {
  ev.preventDefault();
  if ($('#password').value !== $('#confirm').value) {
    return show('Passwords do not match', true);
  }
  try {
    show('Creating account...');
    await post('/auth/register', {
      name: $('#name').value,
      email: $('#email').value,
      password: $('#password').value
    });
    show('Account created successfully! Redirecting to login...');
    setTimeout(() => {
      location.href = '/login.html';
    }, 1000);
  } catch (e) {
    show(e.message, true);
  }
}

async function logout() {
  try {
    await api('/auth/logout', { method: 'POST' });
  } catch {}
  location.href = '/';
}

document.addEventListener('DOMContentLoaded', init);
