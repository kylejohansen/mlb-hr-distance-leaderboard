import './styles.css';

const DATA_URL = '/data/hr-distance-latest.json';

const columns = [
  { key: 'rank', label: 'Rank', numeric: true },
  { key: 'player', label: 'Player' },
  { key: 'team', label: 'Team' },
  { key: 'hr', label: 'HR', numeric: true },
  { key: 'avgDistance', label: 'Avg HR Distance', numeric: true, unit: 'ft' },
  { key: 'longestHr', label: 'Longest HR', numeric: true, unit: 'ft' },
  { key: 'avgExitVelocity', label: 'Avg Exit Velocity', numeric: true, unit: 'mph' }
];

const state = {
  rows: [],
  query: '',
  minHr: 1,
  sortKey: 'avgDistance',
  sortDirection: 'desc',
  status: 'loading',
  error: ''
};

const app = document.querySelector('#app');

function normalizeRow(row, index) {
  return {
    player: String(row.player ?? row.player_name ?? '').trim(),
    team: String(row.team ?? '').trim(),
    hr: Number(row.hr ?? row.home_runs ?? row.homeRuns),
    avgDistance: Number(row.avgDistance ?? row.avg_hr_distance ?? row.avg_distance),
    longestHr: Number(row.longestHr ?? row.longest_hr ?? row.max_distance),
    avgExitVelocity: Number(row.avgExitVelocity ?? row.avg_exit_velocity ?? row.avg_ev),
    sourceRank: index + 1
  };
}

function getRowsFromPayload(payload) {
  const rows = Array.isArray(payload) ? payload : payload?.players;

  if (!Array.isArray(rows)) {
    throw new Error('Expected the JSON to be an array or an object with a players array.');
  }

  return rows.map(normalizeRow).filter((row) => {
    return (
      row.player &&
      row.team &&
      Number.isFinite(row.hr) &&
      Number.isFinite(row.avgDistance) &&
      Number.isFinite(row.longestHr) &&
      Number.isFinite(row.avgExitVelocity)
    );
  });
}

async function loadLeaderboard() {
  try {
    const response = await fetch(DATA_URL, { cache: 'no-store' });

    if (!response.ok) {
      throw new Error(`Could not load ${DATA_URL} (${response.status}).`);
    }

    const payload = await response.json();
    const rows = getRowsFromPayload(payload);

    if (rows.length === 0) {
      throw new Error('The data file loaded, but it did not contain any valid player rows.');
    }

    state.rows = rows;
    state.status = 'ready';
  } catch (error) {
    state.status = 'error';
    state.error = error instanceof Error ? error.message : 'The leaderboard could not be loaded.';
  }

  render();
}

function compareValues(a, b, column) {
  const aValue = column.key === 'rank' ? a.sourceRank : a[column.key];
  const bValue = column.key === 'rank' ? b.sourceRank : b[column.key];

  if (column.numeric) {
    return aValue - bValue;
  }

  return String(aValue).localeCompare(String(bValue));
}

function getVisibleRows() {
  const query = state.query.toLowerCase();

  return state.rows
    .filter((row) => row.hr >= state.minHr)
    .filter((row) => {
      return row.player.toLowerCase().includes(query) || row.team.toLowerCase().includes(query);
    })
    .sort((a, b) => {
      const column = columns.find((item) => item.key === state.sortKey);
      const direction = state.sortDirection === 'asc' ? 1 : -1;
      const primary = compareValues(a, b, column) * direction;

      if (primary !== 0) return primary;
      return b.hr - a.hr || a.player.localeCompare(b.player);
    })
    .map((row, index) => ({ ...row, rank: index + 1 }));
}

function formatNumber(value, unit = '') {
  const precision = unit === 'mph' ? 1 : 0;
  return `${value.toLocaleString(undefined, {
    maximumFractionDigits: precision,
    minimumFractionDigits: precision
  })}${unit ? ` ${unit}` : ''}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function renderSortIcon(column) {
  if (state.sortKey !== column.key) return '<span class="sort-icon">↕</span>';
  return `<span class="sort-icon active">${state.sortDirection === 'asc' ? '↑' : '↓'}</span>`;
}

function renderControls() {
  return `
    <section class="toolbar" aria-label="Leaderboard controls">
      <label class="field">
        <span>Search</span>
        <input id="search-input" type="search" placeholder="Player or team" value="${escapeHtml(state.query)}" />
      </label>
      <label class="field">
        <span>Minimum HR</span>
        <select id="min-hr-select">
          ${[1, 3, 5, 10, 15, 20].map((value) => `
            <option value="${value}" ${state.minHr === value ? 'selected' : ''}>${value}+</option>
          `).join('')}
        </select>
      </label>
    </section>
  `;
}

function renderTable(rows) {
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            ${columns.map((column) => `
              <th scope="col">
                <button class="sort-button" data-sort-key="${column.key}">
                  <span>${column.label}</span>
                  ${renderSortIcon(column)}
                </button>
              </th>
            `).join('')}
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td class="rank">${row.rank}</td>
              <td class="player">${escapeHtml(row.player)}</td>
              <td><span class="team">${escapeHtml(row.team)}</span></td>
              <td>${formatNumber(row.hr)}</td>
              <td>${formatNumber(row.avgDistance, 'ft')}</td>
              <td>${formatNumber(row.longestHr, 'ft')}</td>
              <td>${formatNumber(row.avgExitVelocity, 'mph')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderEmptyState() {
  return `
    <section class="message">
      <h2>No matching hitters</h2>
      <p>Try a broader search or lower the minimum home-run filter.</p>
    </section>
  `;
}

function renderError() {
  return `
    <section class="message error">
      <h2>Leaderboard unavailable</h2>
      <p>${escapeHtml(state.error)}</p>
      <p>Run the Python data script and confirm that <code>${DATA_URL}</code> exists.</p>
    </section>
  `;
}

function bindEvents() {
  document.querySelector('#search-input')?.addEventListener('input', (event) => {
    state.query = event.target.value;
    render();
  });

  document.querySelector('#min-hr-select')?.addEventListener('change', (event) => {
    state.minHr = Number(event.target.value);
    render();
  });

  document.querySelectorAll('[data-sort-key]').forEach((button) => {
    button.addEventListener('click', () => {
      const nextKey = button.dataset.sortKey;

      if (state.sortKey === nextKey) {
        state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
      } else {
        state.sortKey = nextKey;
        state.sortDirection = columns.find((column) => column.key === nextKey)?.numeric ? 'desc' : 'asc';
      }

      render();
    });
  });
}

function render() {
  const rows = getVisibleRows();

  app.innerHTML = `
    <section class="hero">
      <p class="eyebrow">MLB Statcast MVP</p>
      <h1>Home-Run Distance Leaderboard</h1>
      <p class="lede">Rank hitters by average home-run distance, then search, filter, and sort the static dataset.</p>
    </section>

    ${state.status === 'ready' ? renderControls() : ''}

    <section class="leaderboard" aria-live="polite">
      ${state.status === 'loading' ? '<section class="message"><h2>Loading leaderboard...</h2></section>' : ''}
      ${state.status === 'error' ? renderError() : ''}
      ${state.status === 'ready' && rows.length > 0 ? renderTable(rows) : ''}
      ${state.status === 'ready' && rows.length === 0 ? renderEmptyState() : ''}
    </section>
  `;

  bindEvents();
}

render();
loadLeaderboard();
