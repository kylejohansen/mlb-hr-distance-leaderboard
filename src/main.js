import './styles.css';

const DATA_URL = '/data/hr-distance-latest.json';

const columns = [
  { key: 'rank', label: 'Rank', numeric: true },
  { key: 'player', label: 'Player' },
  { key: 'team', label: 'Team' },
  { key: 'longballIndex', label: 'LBI', numeric: true },
  { key: 'hr', label: 'HR', numeric: true },
  { key: 'avgDistance', label: 'Avg Distance', numeric: true, unit: 'ft' },
  { key: 'longestHr', label: 'Longest', numeric: true, unit: 'ft' },
  { key: 'avgExitVelocity', label: 'Avg EV', numeric: true, unit: 'mph' },
  { key: 'barrelRate', label: 'Barrel%', numeric: true, unit: 'percent' },
  { key: 'sweetSpotRate', label: 'Sweet Spot%', numeric: true, unit: 'percent' },
  { key: 'sampleBadge', label: 'Badge' }
];

const state = {
  rows: [],
  query: '',
  minHr: 1,
  sortKey: 'longballIndex',
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
    barrelRate: Number(row.barrelRate ?? 0),
    sweetSpotRate: Number(row.sweetSpotRate ?? 0),
    longballIndex: Number(row.longballIndex ?? 0),
    sampleBadge: String(row.sampleBadge ?? 'Building Sample'),
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
      Number.isFinite(row.avgExitVelocity) &&
      Number.isFinite(row.longballIndex)
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
  if (unit === 'percent') {
    return `${Math.round(value * 100)}%`;
  }

  const precision = unit === 'mph' || unit === 'lbi' ? 1 : 0;
  return `${value.toLocaleString(undefined, {
    maximumFractionDigits: precision,
    minimumFractionDigits: precision
  })}${unit && unit !== 'lbi' ? ` ${unit}` : ''}`;
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

function renderBombBoard(rows) {
  const bombs = [...rows].sort((a, b) => b.longestHr - a.longestHr).slice(0, 3);

  return `
    <section class="bomb-board">
      <div>
        <p class="eyebrow">Daily Bomb Board</p>
        <h2>Season-to-date fallback</h2>
      </div>
      <div class="bomb-grid">
        ${bombs.map((row) => `
          <article class="bomb-card">
            <span class="team">${escapeHtml(row.team)}</span>
            <h3>${escapeHtml(row.player)}</h3>
            <strong>${formatNumber(row.longestHr, 'ft')}</strong>
            <p>${formatNumber(row.avgExitVelocity, 'mph')} avg EV · LBI ${formatNumber(row.longballIndex, 'lbi')}</p>
          </article>
        `).join('')}
      </div>
    </section>
  `;
}

function renderBadges() {
  return `
    <section class="badge-strip" aria-label="Long Ball badges">
      ${['Reliable Sample', 'Small Sample Monster', 'No-Doubter Candidate', 'Wall-Scraper Watch'].map((badge) => `
        <span class="badge">${badge}</span>
      `).join('')}
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
              <td class="lbi">${formatNumber(row.longballIndex, 'lbi')}</td>
              <td>${formatNumber(row.hr)}</td>
              <td>${formatNumber(row.avgDistance, 'ft')}</td>
              <td>${formatNumber(row.longestHr, 'ft')}</td>
              <td>${formatNumber(row.avgExitVelocity, 'mph')}</td>
              <td>${formatNumber(row.barrelRate, 'percent')}</td>
              <td>${formatNumber(row.sweetSpotRate, 'percent')}</td>
              <td><span class="badge small">${escapeHtml(row.sampleBadge)}</span></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderFutureFeatures() {
  return `
    <section class="future">
      <h2>On deck</h2>
      <div class="future-grid">
        <span>Stadium-neutral LBI / All Stadiums Neutral toggle</span>
        <span>No-Doubter Meter</span>
        <span>Wall-Scraper Wall</span>
        <span>Meatball Tracker / Meatball Hall of Fame</span>
        <span>CSS launch-angle visualizer</span>
      </div>
    </section>
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
      <p>Run the Python data script and confirm that <code>${DATA_URL}</code> contains player rows.</p>
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
      <p class="eyebrow">The Long Ball</p>
      <h1>MLB Longball Index</h1>
      <p class="tagline">Digging the data behind the distance.</p>
      <p class="lede">A daily Statcast-powered look at baseball's biggest bombs, no-doubters, wall-scrapers, and almost-homers.</p>
    </section>

    ${state.status === 'ready' ? renderBombBoard(state.rows) : ''}
    ${state.status === 'ready' ? renderBadges() : ''}
    ${state.status === 'ready' ? renderControls() : ''}

    <section class="leaderboard" aria-live="polite">
      <div class="section-heading">
        <p class="eyebrow">Core Feature</p>
        <h2>MLB Longball Index leaderboard</h2>
      </div>
      ${state.status === 'loading' ? '<section class="message"><h2>Loading leaderboard...</h2></section>' : ''}
      ${state.status === 'error' ? renderError() : ''}
      ${state.status === 'ready' && rows.length > 0 ? renderTable(rows) : ''}
      ${state.status === 'ready' && rows.length === 0 ? renderEmptyState() : ''}
    </section>

    ${renderFutureFeatures()}
  `;

  bindEvents();
}

render();
loadLeaderboard();
